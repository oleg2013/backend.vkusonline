#!/usr/bin/env python3
"""
Magnit Post Delivery CLI — интерактивная утилита для создания заявок
на доставку в ПВЗ через API Magnit Post.

Python 3.13+ | Windows

Использование:
    python main.py                    # обычный запуск
    python main.py --refresh-cache    # принудительно обновить кэш ПВЗ
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Optional

from magnit_api import MagnitAPI, MagnitAPIError
from dadata_api import DaDataAPI, DaDataAPIError
from pvz_cache import PVZCache
from geo_utils import (
    haversine,
    generate_order_id,
    calculate_delivery_cost_kopecks,
    delivery_cost_rub,
    format_phone,
)

# ── Константы ────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")


# ── Настройка логирования ────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Настраивает логирование: консоль (INFO) + файл (DEBUG)."""
    os.makedirs(LOGS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = os.path.join(LOGS_DIR, f"magnit_{timestamp}.log")

    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Формат
    file_fmt = logging.Formatter(
        "%(asctime)s | %(name)-12s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_fmt = logging.Formatter("%(levelname)-7s | %(message)s")

    # Хэндлер файла
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)
    root_logger.addHandler(fh)

    # Хэндлер консоли
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(console_fmt)
    root_logger.addHandler(ch)

    # Уменьшаем шум от requests/urllib3
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    logger = logging.getLogger("main")
    logger.info("Лог-файл: %s", log_file)
    return logger


# ── Загрузка конфигурации ────────────────────────────────────────────

def load_config(path: str) -> dict:
    """Загружает конфигурацию из JSON-файла."""
    if not os.path.exists(path):
        print(f"ОШИБКА: Файл конфигурации не найден: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config


# ── Вспомогательные функции CLI ──────────────────────────────────────

def prompt_choice(prompt_text: str, options: list, display_fn=None,
                  allow_search: bool = False) -> tuple:
    """
    Показывает пронумерованный список вариантов и запрашивает выбор.

    Args:
        prompt_text: Текст-приглашение
        options: Список элементов для выбора
        display_fn: Функция для отображения элемента (по умолчанию str)
        allow_search: Разрешить уточнение поиска вводом текста

    Returns:
        (index, selected_item)
    """
    if display_fn is None:
        display_fn = str

    print(f"\n{prompt_text}")
    print("-" * 60)

    for i, opt in enumerate(options, 1):
        print(f"  {i}. {display_fn(opt)}")

    if allow_search:
        print(f"  0. Уточнить поиск (ввести другой запрос)")

    print("-" * 60)

    while True:
        raw = input("Ваш выбор: ").strip()
        if not raw:
            continue

        if allow_search and raw == "0":
            return -1, None

        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return idx - 1, options[idx - 1]
            else:
                print(f"  Введите число от 1 до {len(options)}")
        except ValueError:
            if allow_search:
                return -1, None
            print("  Введите число.")


def prompt_input(text: str, required: bool = True, default: str = None) -> str:
    """Запрашивает ввод строки."""
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{text}{suffix}: ").strip()
        if not value and default:
            return default
        if value or not required:
            return value
        print("  Это поле обязательно. Введите значение.")


def prompt_int(text: str, min_val: int = None, max_val: int = None) -> int:
    """Запрашивает целое число."""
    while True:
        raw = input(f"{text}: ").strip()
        try:
            val = int(raw)
            if min_val is not None and val < min_val:
                print(f"  Минимум: {min_val}")
                continue
            if max_val is not None and val > max_val:
                print(f"  Максимум: {max_val}")
                continue
            return val
        except ValueError:
            print("  Введите целое число.")


def prompt_float(text: str, min_val: float = None) -> float:
    """Запрашивает число с плавающей точкой."""
    while True:
        raw = input(f"{text}: ").strip()
        try:
            val = float(raw)
            if min_val is not None and val < min_val:
                print(f"  Минимум: {min_val}")
                continue
            return val
        except ValueError:
            print("  Введите число.")


# ══════════════════════════════════════════════════════════════════════
#  ОСНОВНОЙ СЦЕНАРИЙ CLI
# ══════════════════════════════════════════════════════════════════════

def parse_args():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Magnit Post — Создание заявки на доставку в ПВЗ",
    )
    parser.add_argument(
        "--refresh-cache", action="store_true",
        help="Принудительно обновить кэш ПВЗ (игнорировать TTL)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("  MAGNIT POST — Создание заявки на доставку в ПВЗ")
    print("=" * 60)

    # ── Шаг 1: Инициализация ─────────────────────────────────────────
    logger = setup_logging()
    config = load_config(CONFIG_PATH)
    logger.info("Конфигурация загружена из %s", CONFIG_PATH)

    magnit = MagnitAPI(config["magnit"])
    dadata = DaDataAPI(config["dadata"]["api_key"], config["dadata"]["secret_key"])

    delivery_cfg = config["delivery"]
    parcel_sizes = config["parcel_sizes"]

    cost_rub = delivery_cost_rub(
        delivery_cfg["cost_without_vat_rub"],
        delivery_cfg["vat_rate_percent"],
    )

    # ── Шаг 2: Авторизация ───────────────────────────────────────────
    print("\n▸ Авторизация в Magnit API...")
    try:
        magnit.authenticate()
        print("  ✓ Авторизация успешна")
    except MagnitAPIError as e:
        print(f"  ✗ Ошибка авторизации: {e}")
        logger.exception("Критическая ошибка авторизации")
        sys.exit(1)

    # ── Шаг 3: Выбор склада ──────────────────────────────────────────
    print("\n▸ Загрузка списка складов...")
    try:
        warehouses = magnit.get_warehouses()
    except MagnitAPIError as e:
        print(f"  ✗ Ошибка загрузки складов: {e}")
        logger.exception("Ошибка загрузки складов")
        sys.exit(1)

    if not warehouses:
        print("  ✗ Нет доступных складов. Сначала создайте склад в ЛК Magnit.")
        sys.exit(1)

    def display_warehouse(wh):
        name = wh.get("warehouse_name", "Без имени")
        addr = wh.get("address", "адрес не указан")
        return f"{name} — {addr}"

    _, selected_warehouse = prompt_choice(
        "Выберите склад отправки:",
        warehouses,
        display_fn=display_warehouse,
    )

    warehouse_id = selected_warehouse.get("warehouse_id")
    warehouse_name = selected_warehouse.get("warehouse_name", "")
    warehouse_address = selected_warehouse.get("address", "")

    logger.info("Выбран склад: %s (%s) — %s", warehouse_id, warehouse_name, warehouse_address)
    print(f"  ✓ Склад: {warehouse_name}")

    # Определяем город отправки из адреса склада (используем DaData для разбора)
    city_from = extract_city_from_warehouse(dadata, warehouse_address, warehouse_name, logger)

    # ── Шаг 4: Выбор города доставки ─────────────────────────────────
    selected_city = interactive_city_search(dadata, logger)
    city_name = DaDataAPI.get_city_name(selected_city)
    city_fias_id = DaDataAPI.get_city_fias_id(selected_city)
    city_region = DaDataAPI.get_region(selected_city)

    logger.info("Выбран город доставки: %s (ФИАС: %s, регион: %s)",
                city_name, city_fias_id, city_region)

    # ── Шаг 5: Ввод улицы ───────────────────────────────────────────
    selected_street = interactive_street_search(dadata, city_fias_id, city_name, logger)
    street_name = DaDataAPI.get_street_name(selected_street)
    street_fias_id = DaDataAPI.get_street_fias_id(selected_street)

    logger.info("Выбрана улица: %s (ФИАС: %s)", street_name, street_fias_id)

    # ── Шаг 6: Ввод номера дома ──────────────────────────────────────
    selected_house = interactive_house_search(dadata, street_fias_id, street_name, city_name, logger)
    full_address = DaDataAPI.get_full_address(selected_house)
    client_lat, client_lon = DaDataAPI.get_coordinates(selected_house)

    if client_lat is None or client_lon is None:
        print("  ⚠ Не удалось получить координаты адреса. Расстояния до ПВЗ будут приблизительными.")
        # Пробуем получить координаты из улицы
        client_lat, client_lon = DaDataAPI.get_coordinates(selected_street)
        if client_lat is None:
            # Используем координаты города
            client_lat, client_lon = DaDataAPI.get_coordinates(selected_city)

    logger.info("Адрес клиента: %s (lat=%s, lon=%s)", full_address, client_lat, client_lon)
    print(f"\n  ✓ Адрес доставки: {full_address}")

    # ── Шаг 7: Способ оплаты ─────────────────────────────────────────
    print("\n▸ Способ оплаты:")
    payment_options = [
        {"label": "Предоплата (клиент уже оплатил)", "billing_type": "already_paid"},
        {"label": "Наложенный платёж (оплата при получении) [скоро]", "billing_type": "not_paid"},
    ]

    _, selected_payment = prompt_choice(
        "Как клиент оплачивает заказ?",
        payment_options,
        display_fn=lambda x: x["label"],
    )

    billing_type = selected_payment["billing_type"]

    if billing_type == "not_paid":
        print("\n  ⚠ ВНИМАНИЕ: Наложенный платёж пока не поддерживается Магнитом.")
        print("    Заказ будет создан с типом 'not_paid', но может быть отклонён API.")
        confirm = input("    Продолжить? (д/н): ").strip().lower()
        if confirm not in ("д", "y", "да", "yes"):
            print("    Переключаемся на предоплату.")
            billing_type = "already_paid"

    logger.info("Способ оплаты: %s", billing_type)

    # ── Шаг 8: Поиск ближайших ПВЗ (с кэшем) ─────────────────────────
    cache_cfg = config.get("cache", {})
    pvz_cache = PVZCache(magnit, ttl_hours=cache_cfg.get("pvz_ttl_hours", 24))

    force_refresh = args.refresh_cache
    if force_refresh:
        print("\n▸ Принудительное обновление кэша ПВЗ...")
    else:
        print("\n▸ Загрузка базы ПВЗ Magnit...")
    try:
        total = pvz_cache.load(force_refresh=force_refresh)
        stats = pvz_cache.get_stats()
        print(f"  ✓ Загружено ПВЗ: {stats['total_points']} в {stats['total_cities']} городах")
    except MagnitAPIError as e:
        print(f"  ✗ Ошибка загрузки ПВЗ: {e}")
        logger.exception("Ошибка загрузки ПВЗ")
        sys.exit(1)

    # Проверяем — есть ли ПВЗ в выбранном городе
    delivery_city = city_name  # город для финального заказа

    if not pvz_cache.has_city(city_name):
        print(f"\n  ⚠ В городе «{city_name}» нет ПВЗ Magnit.")
        logger.warning("В городе '%s' нет ПВЗ", city_name)

        # Ищем ближайшие города с ПВЗ
        if client_lat and client_lon:
            nearest = pvz_cache.find_nearest_cities(
                client_lat, client_lon, limit=10, exclude_city=city_name,
            )

            if nearest:
                print(f"\n  Ближайшие города с ПВЗ Magnit:")

                def display_nearby_city(c):
                    return (f"{c['city']} — {c['count']} ПВЗ, "
                            f"~{c['distance_km']} км от адреса клиента")

                _, chosen_city = prompt_choice(
                    "Выберите город для доставки в ПВЗ:",
                    nearest,
                    display_fn=display_nearby_city,
                )

                delivery_city = chosen_city["city"]
                logger.info("Выбран альтернативный город: %s (%.1f км)",
                            delivery_city, chosen_city["distance_km"])
                print(f"  ✓ Доставка в город: {delivery_city}")
            else:
                print("  ✗ Не найдено городов с ПВЗ поблизости.")
                sys.exit(1)
        else:
            print("  ✗ Координаты адреса недоступны, не удалось найти ближайшие города.")
            sys.exit(1)

    # Находим ближайшие ПВЗ к адресу клиента
    if client_lat and client_lon:
        top_points = pvz_cache.find_nearest_points(
            client_lat, client_lon, city_name=delivery_city, limit=10,
        )
    else:
        top_points = pvz_cache.get_points_in_city(delivery_city)[:10]
        logger.warning("Координаты недоступны — показываем первые 10 ПВЗ без сортировки")

    total_in_city = len(pvz_cache.get_points_in_city(delivery_city))
    print(f"\n  ПВЗ в г. {delivery_city}: {total_in_city}")

    def display_pickup_point(pp):
        name = pp.get("name", "")
        addr = pp.get("address", "")
        pp_type = pp.get("type", "")
        dist = pp.get("_distance_km")
        dist_str = f"{dist} км" if dist and dist < 99999 else "n/a"
        return f"{name} | {addr} | {pp_type} | ~{dist_str}"

    _, selected_pp = prompt_choice(
        f"Ближайшие 10 ПВЗ (из {total_in_city}). Выберите:",
        top_points,
        display_fn=display_pickup_point,
    )

    pp_key = selected_pp.get("key")
    pp_name = selected_pp.get("name", "")
    pp_address = selected_pp.get("address", "")

    logger.info("Выбран ПВЗ: key=%s, name=%s, address=%s", pp_key, pp_name, pp_address)
    print(f"  ✓ ПВЗ: {pp_name} — {pp_address}")

    # ── Шаг 9: Детали посылки ────────────────────────────────────────
    print("\n▸ Детали посылки:")

    weight_grams = prompt_int("  Вес посылки (граммы)", min_val=1)

    size_options = []
    for code, info in parcel_sizes.items():
        size_options.append({
            "code": code,
            "label": f"{code}: {info['label']}",
            "length": info["length_mm"],
            "width": info["width_mm"],
            "height": info["height_mm"],
        })

    _, selected_size = prompt_choice(
        "Выберите размер посылки:",
        size_options,
        display_fn=lambda x: x["label"],
    )

    declared_value_rub = prompt_float("  Объявленная ценность (руб)", min_val=1)

    logger.info("Посылка: вес=%d г, размер=%s, ценность=%.2f руб",
                weight_grams, selected_size["code"], declared_value_rub)

    # ── Шаг 10: Данные получателя ────────────────────────────────────
    print("\n▸ Данные получателя:")

    recipient_last_name = prompt_input("  Фамилия")
    recipient_first_name = prompt_input("  Имя")
    recipient_middle_name = prompt_input("  Отчество (необязательно)", required=False)
    recipient_phone_raw = prompt_input("  Телефон (напр. +79991234567)")
    recipient_phone = format_phone(recipient_phone_raw)

    logger.info("Получатель: %s %s %s, тел: %s",
                recipient_last_name, recipient_first_name,
                recipient_middle_name or "", recipient_phone)

    # ── Шаг 11: Формируем и отправляем заказ ─────────────────────────
    customer_order_id = generate_order_id()

    # Данные получателя
    recipient = {
        "phone_number": recipient_phone,
        "first_name": recipient_first_name,
        "family_name": recipient_last_name,
    }

    if recipient_middle_name:
        # API может не поддерживать отчество — добавляем к имени
        recipient["first_name"] = f"{recipient_first_name} {recipient_middle_name}"

    # Данные посылки
    parcel = {
        "declared_value": declared_value_rub,
        "characteristic": {
            "weight": weight_grams,
            "length": selected_size["length"],
            "width": selected_size["width"],
            "height": selected_size["height"],
        },
    }

    # Платёжная информация
    parcel["parcel_payment"] = {
        "billing_type": billing_type,
    }

    # Если наложенный платёж — добавляем информацию о сумме к оплате
    if billing_type == "not_paid":
        delivery_cost_kop = calculate_delivery_cost_kopecks(
            delivery_cfg["cost_without_vat_rub"],
            delivery_cfg["vat_rate_percent"],
        )
        goods_kop = round(declared_value_rub * 100)
        total_kop = goods_kop + delivery_cost_kop

        parcel["parcel_payment"]["items"] = [
            {
                "good_id": customer_order_id,
                "name": "Товар",
                "unit": "piece",
                "quantity": 1,
                "unit_price": goods_kop,
                "total_sum_for_item": goods_kop,
                "vat_rate": delivery_cfg["vat_rate_percent"],
            },
            {
                "good_id": "DELIVERY",
                "name": "Доставка",
                "unit": "piece",
                "quantity": 1,
                "unit_price": delivery_cost_kop,
                "total_sum_for_item": delivery_cost_kop,
                "vat_rate": delivery_cfg["vat_rate_percent"],
            },
        ]
        parcel["parcel_payment"]["total_sum_for_parcel"] = total_kop

    # Сводка перед отправкой
    print("\n" + "=" * 60)
    print("  СВОДКА ЗАКАЗА")
    print("=" * 60)
    print(f"  Номер заказа:      {customer_order_id}")
    print(f"  Склад отправки:    {warehouse_name}")
    print(f"  ПВЗ доставки:      {pp_name}")
    print(f"  Адрес ПВЗ:         {pp_address}")
    print(f"  Адрес клиента:     {full_address}")
    print(f"  Получатель:        {recipient_last_name} {recipient_first_name} {recipient_middle_name or ''}")
    print(f"  Телефон:           {recipient_phone}")
    print(f"  Вес:               {weight_grams} г")
    print(f"  Размер:            {selected_size['label']}")
    print(f"  Объявл. ценность:  {declared_value_rub:.2f} руб")
    print(f"  Оплата:            {'Предоплата' if billing_type == 'already_paid' else 'Наложенный платёж'}")
    print(f"  Стоим. доставки:   {cost_rub:.2f} руб (с НДС {delivery_cfg['vat_rate_percent']}%)")
    print(f"  Тип возврата:      Возврат на склад")
    print("=" * 60)

    confirm = input("\n  Отправить заказ? (д/н): ").strip().lower()
    if confirm not in ("д", "y", "да", "yes"):
        print("  Заказ отменён.")
        logger.info("Пользователь отменил отправку заказа")
        sys.exit(0)

    # Отправляем
    print("\n▸ Отправка заказа в Magnit...")
    try:
        result = magnit.create_order_v2(
            pickup_point_key=pp_key,
            warehouse_id=warehouse_id,
            customer_order_id=customer_order_id,
            recipient=recipient,
            parcels=[parcel],
            return_type="return",
            return_warehouse_id=warehouse_id,
        )
    except MagnitAPIError as e:
        print(f"\n  ✗ Ошибка создания заказа: {e}")
        if e.response_body:
            print(f"    Ответ API: {e.response_body[:500]}")
        logger.exception("Ошибка создания заказа")
        sys.exit(1)

    # ── Шаг 12: Результат ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ✓ ЗАКАЗ УСПЕШНО СОЗДАН!")
    print("=" * 60)

    # Извлекаем данные из ответа (структура может варьироваться)
    if isinstance(result, dict):
        order_uuid = result.get("id", result.get("order_id", ""))
        tracking = result.get("tracking_number", result.get("trackingNumber", ""))
        status = result.get("status", "")
        cost_info = result.get("cost", result.get("delivery_cost", ""))

        print(f"  UUID заказа:       {order_uuid}")
        print(f"  Трекинг-номер:     {tracking}")
        print(f"  Статус:            {status}")
        if cost_info:
            print(f"  Стоимость:         {cost_info}")

        print(f"\n  Полный ответ API:")
        print(f"  {json.dumps(result, ensure_ascii=False, indent=2)}")
    else:
        print(f"  Ответ: {result}")

    print("=" * 60)
    logger.info("Заказ успешно создан: %s", json.dumps(result, ensure_ascii=False))
    print("\nГотово! Подробности в лог-файле.")


# ══════════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ CLI-СЦЕНАРИЯ
# ══════════════════════════════════════════════════════════════════════

def extract_city_from_warehouse(dadata: DaDataAPI, address: str,
                                name: str, logger: logging.Logger) -> str:
    """
    Определяет город отправки из адреса склада.
    Используется для оценки доставки.
    """
    logger.info("Определяем город отправки из адреса склада: %s", address)

    try:
        suggestions = dadata.suggest_address(address or name, count=1)
        if suggestions:
            city = DaDataAPI.get_city_name(suggestions[0])
            if city:
                logger.info("Город отправки определён: %s", city)
                print(f"  Город отправки: {city}")
                return city
    except DaDataAPIError as e:
        logger.warning("Не удалось определить город через DaData: %s", e)

    # Fallback — спрашиваем пользователя
    city = prompt_input("  Не удалось определить город склада. Введите город отправки")
    logger.info("Город отправки введён вручную: %s", city)
    return city


def interactive_city_search(dadata: DaDataAPI, logger: logging.Logger) -> dict:
    """
    Интерактивный поиск города через DaData.
    Пользователь вводит текст → показываем варианты → выбор или уточнение.
    """
    while True:
        query = prompt_input("\n▸ Введите город доставки (или часть названия)")

        try:
            suggestions = dadata.suggest_city(query, count=15)
        except DaDataAPIError as e:
            print(f"  ✗ Ошибка DaData: {e}")
            logger.exception("Ошибка поиска города")
            continue

        if not suggestions:
            print(f"  Город «{query}» не найден. Попробуйте другой запрос.")
            continue

        # Если один точный результат — предлагаем сразу
        if len(suggestions) == 1:
            city_name = DaDataAPI.get_city_name(suggestions[0])
            confirm = input(f"  Найден город: {suggestions[0]['value']}. Верно? (д/н): ").strip().lower()
            if confirm in ("д", "y", "да", "yes", ""):
                return suggestions[0]
            continue

        def display_city(s):
            data = s.get("data", {})
            region = data.get("region_with_type", "")
            city = s.get("value", "")
            return f"{city}" + (f" ({region})" if region else "")

        idx, selected = prompt_choice(
            f"Найдено городов: {len(suggestions)}. Выберите:",
            suggestions,
            display_fn=display_city,
            allow_search=True,
        )

        if idx == -1:
            # Уточнить поиск
            continue

        return selected


def interactive_street_search(dadata: DaDataAPI, city_fias_id: str,
                              city_name: str, logger: logging.Logger) -> dict:
    """
    Интерактивный поиск улицы через DaData.
    """
    while True:
        query = prompt_input(f"\n▸ Введите улицу в г. {city_name} (или часть названия)")

        try:
            suggestions = dadata.suggest_street(query, city_fias_id, count=15)
        except DaDataAPIError as e:
            print(f"  ✗ Ошибка DaData: {e}")
            logger.exception("Ошибка поиска улицы")
            continue

        if not suggestions:
            print(f"  Улица «{query}» не найдена в г. {city_name}. Попробуйте другой запрос.")
            continue

        if len(suggestions) == 1:
            street = DaDataAPI.get_street_name(suggestions[0])
            confirm = input(f"  Найдена улица: {street}. Верно? (д/н): ").strip().lower()
            if confirm in ("д", "y", "да", "yes", ""):
                return suggestions[0]
            continue

        def display_street(s):
            return DaDataAPI.get_street_name(s)

        idx, selected = prompt_choice(
            f"Найдено улиц: {len(suggestions)}. Выберите:",
            suggestions,
            display_fn=display_street,
            allow_search=True,
        )

        if idx == -1:
            continue

        return selected


def interactive_house_search(dadata: DaDataAPI, street_fias_id: str,
                             street_name: str, city_name: str,
                             logger: logging.Logger) -> dict:
    """
    Интерактивный поиск номера дома через DaData.
    """
    while True:
        query = prompt_input(f"\n▸ Введите номер дома на {street_name}, г. {city_name}")

        try:
            suggestions = dadata.suggest_house(query, street_fias_id, count=15)
        except DaDataAPIError as e:
            print(f"  ✗ Ошибка DaData: {e}")
            logger.exception("Ошибка поиска дома")
            continue

        if not suggestions:
            print(f"  Дом «{query}» не найден. Попробуйте другой номер.")
            continue

        if len(suggestions) == 1:
            full_addr = DaDataAPI.get_full_address(suggestions[0])
            confirm = input(f"  Найден адрес: {full_addr}. Верно? (д/н): ").strip().lower()
            if confirm in ("д", "y", "да", "yes", ""):
                return suggestions[0]
            continue

        def display_house(s):
            data = s.get("data", {})
            house = data.get("house", "")
            block_type = data.get("block_type", "")
            block = data.get("block", "")
            result = f"д. {house}"
            if block_type and block:
                result += f" {block_type} {block}"
            return result

        idx, selected = prompt_choice(
            f"Найдено адресов: {len(suggestions)}. Выберите:",
            suggestions,
            display_fn=display_house,
            allow_search=True,
        )

        if idx == -1:
            continue

        return selected


# ── Точка входа ──────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logging.getLogger("main").exception("Необработанная ошибка")
        print(f"\n✗ Критическая ошибка: {e}")
        print("  Подробности в лог-файле.")
        sys.exit(1)
