"""
5Post CLI-утилита для создания заказов на доставку.
Интерактивный скрипт: выбор склада → ввод адреса → выбор постамата → товары → заказ.
Python 3.11.2 для Windows.
"""

import logging
import os
import sys
import json
import re
from datetime import datetime
from typing import Optional

import config
from fivepost_api import FivePostAPI
from dadata_api import DaDataAPI
from models import (
    Product, Warehouse, PickupPoint, Cargo, OrderCost, Order
)
from utils import (
    haversine_distance, calculate_cargo_weight_mg, calculate_cargo_weight_display,
    calculate_delivery_cost, calculate_total_products_price, calculate_total_order_cost,
    generate_order_id, generate_cargo_id, format_weight, get_best_rate,
)


# ======================== Настройка логирования ========================

def setup_logging():
    """Настройка логирования в файл и консоль."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(config.LOG_DIR, f"fivepost_{timestamp}.log")

    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Файловый обработчик — всё, включая DEBUG
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(config.LOG_FORMAT, config.LOG_DATE_FORMAT))

    # Консольный обработчик — только INFO и выше
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info(f"Лог-файл: {os.path.abspath(log_file)}")
    return log_file


# ======================== Вспомогательные функции CLI ========================

def print_header(text: str):
    """Напечатать заголовок раздела."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_separator():
    """Напечатать разделитель."""
    print("-" * 60)


def input_int(prompt: str, min_val: int = 1, max_val: int = 999999) -> int:
    """Запросить целое число в заданном диапазоне."""
    while True:
        try:
            value = int(input(prompt).strip())
            if min_val <= value <= max_val:
                return value
            print(f"  Введите число от {min_val} до {max_val}.")
        except ValueError:
            print("  Ошибка: введите целое число.")


def input_float(prompt: str, min_val: float = 0.01) -> float:
    """Запросить число с плавающей точкой."""
    while True:
        try:
            value = float(input(prompt).strip().replace(",", "."))
            if value >= min_val:
                return round(value, 2)
            print(f"  Значение должно быть не менее {min_val}.")
        except ValueError:
            print("  Ошибка: введите число.")


def input_non_empty(prompt: str) -> str:
    """Запросить непустую строку."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("  Поле не может быть пустым.")


def input_phone(prompt: str) -> str:
    """Запросить номер телефона в формате +7XXXXXXXXXX."""
    while True:
        phone = input(prompt).strip()
        # Нормализация: удаляем всё кроме цифр и +
        cleaned = re.sub(r'[^\d+]', '', phone)

        # Приведение к формату +7XXXXXXXXXX
        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "+7" + cleaned[1:]
        elif cleaned.startswith("7") and len(cleaned) == 11:
            cleaned = "+" + cleaned
        elif cleaned.startswith("+7") and len(cleaned) == 12:
            pass  # уже правильный формат
        elif cleaned.startswith("9") and len(cleaned) == 10:
            cleaned = "+7" + cleaned
        else:
            print("  Формат: +7XXXXXXXXXX, 89XXXXXXXXX или 9XXXXXXXXX")
            continue

        if re.match(r'^\+7\d{10}$', cleaned):
            return cleaned
        print("  Некорректный номер. Формат: +7XXXXXXXXXX")


def input_email(prompt: str) -> str:
    """Запросить email (необязательный)."""
    email = input(prompt).strip()
    if not email:
        return ""
    # Простая валидация
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return email
    print("  Предупреждение: email выглядит некорректно, но будет использован.")
    return email


def confirm(prompt: str) -> bool:
    """Запросить подтверждение (д/н)."""
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("д", "да", "y", "yes"):
            return True
        if answer in ("н", "нет", "n", "no"):
            return False
        print("  Введите 'д' (да) или 'н' (нет).")


# ======================== Шаги CLI ========================

def step_select_warehouse(api: FivePostAPI) -> Warehouse:
    """Шаг 1: Выбор склада отправки."""
    print_header("ШАГ 1: Выбор склада отправки")
    print("Загрузка складов...")

    warehouses = api.get_warehouses()
    if not warehouses:
        print("ОШИБКА: Нет доступных складов! Создайте склад в личном кабинете 5Post.")
        sys.exit(1)

    print(f"\nДоступные склады ({len(warehouses)}):")
    for i, wh in enumerate(warehouses, 1):
        print(f"  {i}. [{wh.name}] — {wh.full_address}")

    idx = input_int(f"Выберите склад (1-{len(warehouses)}): ", 1, len(warehouses))
    selected = warehouses[idx - 1]
    print(f"\n  Выбран: {selected.name} ({selected.full_address})")
    logging.info(f"Выбран склад: {selected.name} (partnerLocationId: {selected.partner_location_id})")
    return selected


def step_enter_address(dadata: DaDataAPI) -> tuple[str, float, float]:
    """
    Шаг 2: Ввод адреса клиента через DaData подсказки.
    Возвращает: (полный_адрес, lat, lon)
    """
    print_header("ШАГ 2: Адрес получателя")

    # --- Город ---
    city_fias_id = None
    city_name = ""
    while not city_fias_id:
        query = input_non_empty("Введите город (или начало названия): ")
        suggestions = dadata.suggest_city(query)

        if not suggestions:
            print("  Ничего не найдено. Попробуйте другой запрос.")
            continue

        print(f"\nНайдены города ({len(suggestions)}):")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. {dadata.get_display_city(s)}")

        choice = input(f"Выберите город (1-{len(suggestions)}) или введите новый запрос: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(suggestions):
                selected = suggestions[idx - 1]
                city_fias_id = dadata.get_city_fias_id(selected)
                city_name = selected.get("data", {}).get("city", "")
                print(f"  Выбран город: {city_name}")
            else:
                print("  Номер вне диапазона.")
        except ValueError:
            # Пользователь ввёл новый текст для поиска — повторяем
            suggestions = dadata.suggest_city(choice)
            if not suggestions:
                print("  Ничего не найдено. Попробуйте ещё раз.")
                continue
            print(f"\nНайдены города ({len(suggestions)}):")
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {dadata.get_display_city(s)}")

    # --- Улица ---
    street_fias_id = None
    while not street_fias_id:
        query = input_non_empty("Введите улицу (или начало названия): ")
        suggestions = dadata.suggest_street(query, city_fias_id)

        if not suggestions:
            print("  Улица не найдена. Попробуйте другой запрос.")
            continue

        print(f"\nНайдены улицы ({len(suggestions)}):")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. {dadata.get_display_street(s)}")

        choice = input(f"Выберите улицу (1-{len(suggestions)}) или введите новый запрос: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(suggestions):
                selected = suggestions[idx - 1]
                street_fias_id = dadata.get_street_fias_id(selected)
                street_name = dadata.get_display_street(selected)
                print(f"  Выбрана улица: {street_name}")
            else:
                print("  Номер вне диапазона.")
        except ValueError:
            suggestions = dadata.suggest_street(choice, city_fias_id)
            if not suggestions:
                print("  Ничего не найдено.")
                continue
            print(f"\nНайдены улицы ({len(suggestions)}):")
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {dadata.get_display_street(s)}")

    # --- Дом ---
    full_address = ""
    lat, lon = 0.0, 0.0
    while not full_address:
        query = input_non_empty("Введите номер дома: ")
        suggestions = dadata.suggest_house(query, street_fias_id)

        if not suggestions:
            print("  Дом не найден. Попробуйте другой номер.")
            continue

        print(f"\nНайдены адреса ({len(suggestions)}):")
        for i, s in enumerate(suggestions, 1):
            coords = dadata.get_coordinates(s)
            coord_str = f" (координаты: {coords[0]}, {coords[1]})" if coords else ""
            print(f"  {i}. {dadata.get_display_house(s)}{coord_str}")

        choice = input(f"Выберите адрес (1-{len(suggestions)}) или введите другой номер: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(suggestions):
                selected = suggestions[idx - 1]
                full_address = dadata.get_full_address(selected)
                coords = dadata.get_coordinates(selected)
                if coords:
                    lat, lon = coords
                else:
                    print("  ПРЕДУПРЕЖДЕНИЕ: Координаты не найдены для этого адреса.")
                    print("  Поиск ближайших постаматов может быть неточным.")
                    lat, lon = 0.0, 0.0
            else:
                print("  Номер вне диапазона.")
        except ValueError:
            suggestions = dadata.suggest_house(choice, street_fias_id)
            if not suggestions:
                print("  Ничего не найдено.")
                continue
            print(f"\nНайдены адреса ({len(suggestions)}):")
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {dadata.get_display_house(s)}")

    print(f"\n  Адрес: {full_address}")
    print(f"  Координаты: {lat}, {lon}")
    logging.info(f"Адрес получателя: {full_address} ({lat}, {lon})")
    return full_address, lat, lon


def step_select_payment() -> tuple[str, Optional[str]]:
    """
    Шаг 3: Выбор способа оплаты.
    Возвращает: (payment_type, payment_method)
      payment_type: 'cod' или 'prepaid'
      payment_method: 'cash', 'card' или None (для предоплаты)
    """
    print_header("ШАГ 3: Способ оплаты")
    print("  1. Наложенный платёж (оплата при получении)")
    print("  2. Предоплата (уже оплачено)")

    choice = input_int("Выберите способ оплаты (1-2): ", 1, 2)

    if choice == 1:
        payment_type = "cod"
        print("\n  Как клиент будет платить при получении?")
        print("  1. Наличными")
        print("  2. Банковской картой")
        method_choice = input_int("  Выберите (1-2): ", 1, 2)
        payment_method = "cash" if method_choice == 1 else "card"
        method_display = "наличными" if payment_method == "cash" else "картой"
        print(f"\n  Выбрано: Наложенный платёж ({method_display})")
        logging.info(f"Способ оплаты: Наложенный платёж ({method_display})")
    else:
        payment_type = "prepaid"
        payment_method = None
        print(f"\n  Выбрано: Предоплата")
        logging.info(f"Способ оплаты: Предоплата")

    return payment_type, payment_method


def step_select_pickup_point(
    api: FivePostAPI, customer_lat: float, customer_lon: float,
    payment_type: str, payment_method: Optional[str] = None,
) -> PickupPoint:
    """
    Шаг 4: Выбор ближайшего постамата/ПВЗ.
    Работает ТОЛЬКО с файловым кэшем (cache/pickup_points.json).
    Для обновления кэша запустите: python update_cache.py
    """
    print_header("ШАГ 4: Выбор пункта выдачи")

    all_points = api.load_pickup_points_from_cache()
    if not all_points:
        print("ОШИБКА: Кэш пунктов выдачи не найден или пуст!")
        print("Сначала выполните: python update_cache.py")
        sys.exit(1)

    # Предупреждение об устаревшем кэше
    cache_info = api.get_cache_info()
    if cache_info.get("is_expired"):
        cached_at = cache_info.get("cached_at")
        if cached_at:
            print(f"  ВНИМАНИЕ: кэш устарел (создан {cached_at.strftime('%Y-%m-%d %H:%M:%S')})")
            print(f"  Рекомендуется обновить: python update_cache.py")

    print(f"Загружено из кэша: {len(all_points)} точек")

    # Фильтрация по способу оплаты
    if payment_type == "cod":
        if payment_method == "card":
            filtered = [p for p in all_points if p.card_allowed]
            print(f"С поддержкой оплаты картой: {len(filtered)}")
        elif payment_method == "cash":
            filtered = [p for p in all_points if p.cash_allowed]
            print(f"С поддержкой оплаты наличными: {len(filtered)}")
        else:
            filtered = [p for p in all_points if p.accepts_cod]
            print(f"С поддержкой наложенного платежа: {len(filtered)}")
    else:
        filtered = all_points
        print(f"Все точки доступны для предоплаты: {len(filtered)}")

    # Фильтрация точек без координат или с нулевыми координатами
    filtered = [p for p in filtered if p.lat != 0 and p.lng != 0]

    # Фильтрация точек с нулевыми тарифами
    filtered = [p for p in filtered if get_best_rate(p) is not None]

    if not filtered:
        print("ОШИБКА: Нет доступных точек выдачи!")
        sys.exit(1)

    # Расчёт расстояния
    if customer_lat != 0 and customer_lon != 0:
        for point in filtered:
            point.distance_km = haversine_distance(
                customer_lat, customer_lon, point.lat, point.lng
            )
        # Сортировка по расстоянию
        filtered.sort(key=lambda p: p.distance_km)
    else:
        print("  Координаты клиента не определены — сортировка по алфавиту.")
        filtered.sort(key=lambda p: p.full_address)

    # Показываем топ-N ближайших
    top_n = min(config.NEAREST_POINTS_COUNT, len(filtered))
    nearest = filtered[:top_n]

    print(f"\n{top_n} ближайших пунктов выдачи:")
    print_separator()

    for i, p in enumerate(nearest, 1):
        dist_str = f"{p.distance_km:.1f} км" if customer_lat != 0 else "—"
        payment_str = ""
        if p.card_allowed:
            payment_str += "карта"
        if p.cash_allowed:
            payment_str += (", " if payment_str else "") + "нал."
        if not payment_str:
            payment_str = "предоплата"

        # Доп. информация о расположении (если есть)
        location_info = ""
        if p.additional:
            if "Пятёрочка" in p.additional or "Пятерочка" in p.additional:
                location_info = " [Пятёрочка]"
            elif "Перекрёсток" in p.additional or "Перекресток" in p.additional:
                location_info = " [Перекрёсток]"

        addr = p.full_address
        if len(addr) > 60:
            addr = addr[:57] + "..."

        print(f"  {i}. [{p.name}] {p.type_display} — {addr}{location_info}")
        print(f"     {dist_str} | Оплата: {payment_str} | Режим: {p.work_hours_display}")

    idx = input_int(f"\nВыберите пункт выдачи (1-{top_n}): ", 1, top_n)
    selected = nearest[idx - 1]

    rate = get_best_rate(selected)

    # Подробная информация о выбранной точке
    print(f"\n  Выбран: [{selected.name}] {selected.type_display}")
    print(f"  Адрес:   {selected.full_address}")
    print(f"  ID:      {selected.id}")
    print(f"  Режим:   {selected.work_hours_display}")
    if selected.phone:
        print(f"  Тел.:    {selected.phone_display}")
    if rate:
        print(f"  Тариф:   {rate.rate_value_with_vat:.2f} руб. (зона {rate.zone})")
    if selected.additional:
        # Обрезаем слишком длинные доп. описания
        add_info = selected.additional
        if len(add_info) > 80:
            add_info = add_info[:77] + "..."
        print(f"  Доп.:    {add_info}")

    logging.info(
        f"Выбрана точка выдачи: [{selected.name}] {selected.full_address} "
        f"(id: {selected.id}, тип: {selected.type}, расстояние: {selected.distance_km:.1f} км, "
        f"режим: {selected.work_hours_display})"
    )
    return selected


def step_add_products() -> list[Product]:
    """Шаг 5: Добавление товаров в заказ."""
    print_header("ШАГ 5: Состав заказа")
    products = []
    product_num = 1

    while True:
        print(f"\n--- Товар #{product_num} ---")

        name = input_non_empty("  Название: ")
        quantity = input_int("  Количество: ", 1, 10000)
        price = input_float("  Цена за единицу (руб.): ", 0.01)

        # НДС
        vat_input = input(f"  НДС (%) [по умолчанию {config.DEFAULT_VAT}]: ").strip()
        if vat_input:
            try:
                vat = int(vat_input)
                if vat not in (-1, 0, 5, 7, 10, 20, 22):
                    print(f"  Допустимые значения НДС: -1 (без НДС), 0, 5, 7, 10, 20, 22")
                    print(f"  Установлено значение по умолчанию: {config.DEFAULT_VAT}%")
                    vat = config.DEFAULT_VAT
            except ValueError:
                vat = config.DEFAULT_VAT
        else:
            vat = config.DEFAULT_VAT

        vendor_code = input("  Артикул: ").strip()
        weight = input_float("  Вес единицы товара (грамм): ", 0.1)

        product = Product(
            name=name,
            quantity=quantity,
            price_per_unit=price,
            weight_grams=weight,
            vat=vat,
            vendor_code=vendor_code,
        )
        products.append(product)

        print(f"\n  Добавлено: {name} x{quantity} = {product.total_price:.2f} руб. "
              f"(НДС {vat}%, вес {product.total_weight_grams:.0f}г)")

        product_num += 1
        if not confirm("\nДобавить ещё товар? (д/н): "):
            break

    print(f"\nВсего товаров: {len(products)}, "
          f"на сумму: {calculate_total_products_price(products):.2f} руб.")
    return products


def step_enter_recipient() -> tuple[str, str, str]:
    """
    Шаг 6: Ввод данных получателя.
    Возвращает: (ФИО, телефон, email)
    """
    print_header("ШАГ 6: Данные получателя")

    name = input_non_empty("  ФИО: ")
    phone = input_phone("  Телефон (+7XXXXXXXXXX): ")
    email = input_email("  Email (необязательно): ")

    print(f"\n  Получатель: {name}")
    print(f"  Телефон: {phone}")
    if email:
        print(f"  Email: {email}")

    logging.info(f"Получатель: {name}, {phone}, {email}")
    return name, phone, email


def step_confirm_and_create(
    api: FivePostAPI,
    warehouse: Warehouse,
    pickup_point: PickupPoint,
    products: list[Product],
    payment_type: str,
    payment_method: Optional[str],
    client_name: str,
    client_phone: str,
    client_email: str,
) -> Optional[dict]:
    """Шаг 7-8: Сводка, подтверждение и создание заказа."""

    # --- Расчёты ---
    order_id = generate_order_id()
    cargo_id = generate_cargo_id()

    # Вес грузоместа
    weight_mg = calculate_cargo_weight_mg(products)
    products_weight_g, packaging_weight_g = calculate_cargo_weight_display(products)
    total_weight_g = products_weight_g + packaging_weight_g

    # Стоимость доставки 5Post (из тарифа точки выдачи)
    delivery_cost_5post = calculate_delivery_cost(pickup_point, weight_mg)

    # Стоимости
    total_products_price = calculate_total_products_price(products)

    # Оценочная стоимость = сумма товаров (требование API: price == sum(cargoes.price))
    estimated_price = total_products_price

    # Полный расчёт стоимости с комиссиями и страховкой
    insurance_fee, cod_commission, total_to_pay = calculate_total_order_cost(
        total_products_price, delivery_cost_5post, payment_type, payment_method
    )

    # Сумма к оплате при выдаче (paymentValue для API)
    if payment_type == "cod":
        payment_value = total_to_pay  # Наложный = товары + доставка + комиссия + страховка
        api_payment_type = "CASH" if payment_method == "cash" else "CASHLESS"
    else:
        payment_value = 0.0  # Предоплата — уже оплачено
        api_payment_type = "PREPAYMENT"

    # Тариф
    rate = get_best_rate(pickup_point)
    rate_info = f"{rate.rate_value_with_vat:.2f} руб. (зона {rate.zone})" if rate else "нет данных"

    # --- Сводка ---
    print_header("СВОДКА ЗАКАЗА")

    print(f"  Номер заказа:       {order_id}")
    print(f"  Склад отправки:     {warehouse.name} ({warehouse.full_address})")
    print(f"  Получатель:         {client_name}, {client_phone}")
    if client_email:
        print(f"  Email:              {client_email}")
    print(f"  Пункт выдачи:       [{pickup_point.name}] {pickup_point.type_display} — {pickup_point.full_address}")
    print(f"  ID точки:           {pickup_point.id}")
    print(f"  Режим работы:       {pickup_point.work_hours_display}")
    if pickup_point.phone:
        print(f"  Телефон ПВЗ:        {pickup_point.phone_display}")

    print(f"\n  Товары:")
    for i, p in enumerate(products, 1):
        print(f"    {i}. {p.name} x{p.quantity} — {p.total_price:.2f} руб. "
              f"(НДС {p.vat}%, артикул: {p.vendor_code or '—'})")

    print(f"\n  Расчёт стоимости:")
    print(f"    Сумма товаров:               {total_products_price:.2f} руб.")
    print(f"    Доставка до ПВЗ (5Post):     {delivery_cost_5post:.2f} руб. ({rate_info})")
    print(f"    Страховка ({config.INSURANCE_PERCENT}%):            {insurance_fee:.2f} руб.")
    if payment_type == "cod":
        method_display = "картой" if payment_method == "card" else "наличными"
        commission_pct = config.COD_CARD_COMMISSION_PERCENT if payment_method == "card" else config.COD_CASH_COMMISSION_PERCENT
        print(f"    Комиссия НП {method_display} ({commission_pct}%):  {cod_commission:.2f} руб.")
    print(f"    ─────────────────────────────────────")
    print(f"    ИТОГО для клиента:           {total_to_pay:.2f} руб.")

    print(f"\n  Грузоместо:")
    print(f"    Габариты:  {config.CARGO_WIDTH_MM}x{config.CARGO_HEIGHT_MM}x{config.CARGO_LENGTH_MM} мм")
    print(f"    Вес:       {total_weight_g:.0f} г "
          f"(товары {products_weight_g:.0f}г + упаковка {packaging_weight_g:.0f}г)")
    print(f"    ID:        {cargo_id}")

    if payment_type == "cod":
        method_display = "наличными" if payment_method == "cash" else "картой"
        print(f"\n  Оплата:                        Наложенный платёж ({method_display})")
        print(f"  Сумма к оплате при выдаче:     {payment_value:.2f} руб.")
        print(f"  Тип оплаты (API):              {api_payment_type}")
    else:
        print(f"\n  Оплата:                        Предоплата")
        print(f"  Сумма к оплате при выдаче:     {total_to_pay:.2f} руб. (клиент оплачивает заранее)")
    print(f"  Оценочная стоимость:           {estimated_price:.2f} руб.")
    print(f"  Невостребованный заказ:         Возврат на склад")

    print_separator()

    if not confirm("\nСоздать заказ? (д/н): "):
        print("Заказ отменён.")
        return None

    # --- Формирование и отправка заказа ---
    print("\nОтправка заказа в 5Post...")

    cargo = Cargo(
        sender_cargo_id=cargo_id,
        height_mm=config.CARGO_HEIGHT_MM,
        length_mm=config.CARGO_LENGTH_MM,
        width_mm=config.CARGO_WIDTH_MM,
        weight_mg=weight_mg,
        price=estimated_price,
        currency=config.DEFAULT_CURRENCY,
        vat=config.DEFAULT_VAT,
        products=products,
    )

    # deliveryCost для API = всё сверх товаров (доставка + комиссия + страховка)
    # Формула API: paymentValue = sum(productValues.price) + deliveryCost
    delivery_cost_for_api = round(total_to_pay - total_products_price, 2) if payment_type == "cod" else 0.0

    cost = OrderCost(
        delivery_cost=delivery_cost_for_api,
        payment_value=payment_value,
        payment_currency=config.DEFAULT_CURRENCY,
        payment_type=api_payment_type,
        price=estimated_price,
        price_currency=config.DEFAULT_CURRENCY,
    )

    order = Order(
        sender_order_id=order_id,
        client_order_id=order_id,  # Синхронизация номеров
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        sender_location=warehouse.partner_location_id,
        receiver_location=pickup_point.id,
        undeliverable_option="RETURN",
        cost=cost,
        cargoes=[cargo],
    )

    # Логирование полного тела запроса
    logging.info(f"Полное тело запроса: {json.dumps(order.to_api_dict(), ensure_ascii=False, indent=2)}")

    try:
        result = api.create_order(order)

        if result.get("created"):
            print_header("ЗАКАЗ УСПЕШНО СОЗДАН!")
            print(f"  Order ID (5Post):       {result.get('orderId', '—')}")
            print(f"  Sender Order ID:        {result.get('senderOrderId', '—')}")
            cargoes_result = result.get("cargoes", [])
            for c in cargoes_result:
                print(f"  Cargo ID (5Post):       {c.get('cargoId', '—')}")
                print(f"  Штрих-код:              {c.get('barcode', '—')}")
            print(f"\n  Сохраните эти данные для отслеживания заказа!")
        else:
            print_header("ОШИБКА СОЗДАНИЯ ЗАКАЗА")
            errors = result.get("errors", [])
            if errors:
                for err in errors:
                    print(f"  Код: {err.get('code', '?')}")
                    print(f"  Описание: {err.get('message') or err.get('text', 'нет описания')}")
            else:
                print(f"  Ответ сервера: {json.dumps(result, ensure_ascii=False, indent=2)}")

        return result

    except Exception as e:
        print(f"\nОШИБКА: {e}")
        logging.exception("Ошибка при создании заказа")
        return None


# ======================== Главная функция ========================

def main():
    """Главная точка входа CLI-утилиты."""
    log_file = setup_logging()

    print_header("5Post CLI — Создание заказа на доставку")
    print(f"  Среда: Продуктивная ({config.FIVEPOST_BASE_URL})")
    print(f"  Лог-файл: {log_file}")
    print()

    # Инициализация API-клиентов
    fivepost = FivePostAPI()
    dadata = DaDataAPI()

    # Проверка кэша ПВЗ
    cache_info = fivepost.get_cache_info()
    if not cache_info.get("exists"):
        print("  ОШИБКА: Кэш пунктов выдачи не найден!")
        print("  Сначала выполните: python update_cache.py")
        sys.exit(1)

    cached_at = cache_info.get("cached_at")
    points_count = cache_info.get("points_count", 0)
    expired_marker = " (УСТАРЕЛ!)" if cache_info.get("is_expired") else ""
    if cached_at:
        print(f"  Кэш ПВЗ: {points_count} точек, "
              f"обновлён {cached_at.strftime('%Y-%m-%d %H:%M:%S')}{expired_marker}")
    print()

    # Подключение к API (получение JWT)
    print("Подключение к API 5Post...")
    try:
        fivepost._ensure_token()
        print("  Подключение успешно!\n")
    except RuntimeError as e:
        print(f"\nОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
        print("Проверьте API-ключ и подключение к интернету.")
        sys.exit(1)

    # Шаг 1: Выбор склада
    warehouse = step_select_warehouse(fivepost)

    # Шаг 2: Ввод адреса клиента
    full_address, customer_lat, customer_lon = step_enter_address(dadata)

    # Шаг 3: Способ оплаты
    payment_type, payment_method = step_select_payment()

    # Шаг 4: Выбор пункта выдачи
    pickup_point = step_select_pickup_point(fivepost, customer_lat, customer_lon, payment_type, payment_method)

    # Шаг 5: Добавление товаров
    products = step_add_products()

    # Шаг 6: Данные получателя
    client_name, client_phone, client_email = step_enter_recipient()

    # Шаг 7-8: Сводка и создание заказа
    result = step_confirm_and_create(
        api=fivepost,
        warehouse=warehouse,
        pickup_point=pickup_point,
        products=products,
        payment_type=payment_type,
        payment_method=payment_method,
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
    )

    print_separator()
    if result and result.get("created"):
        print("Программа завершена успешно.")
    else:
        print("Программа завершена. Заказ не был создан.")

    print(f"Подробный лог: {log_file}")


if __name__ == "__main__":
    main()
