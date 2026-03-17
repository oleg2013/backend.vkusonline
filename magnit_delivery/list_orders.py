#!/usr/bin/env python3
"""
Magnit Post — Просмотр списка заказов.

Выводит в консоль все существующие заказы с основной информацией:
статус, дата, получатель, ПВЗ, трекинг-номер.

Поддерживает фильтрацию по статусу и дате.

Использование:
    python list_orders.py                        # все заказы
    python list_orders.py --status CREATED       # только со статусом CREATED
    python list_orders.py --days 7               # за последние 7 дней
    python list_orders.py --status ISSUED --days 30
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone

from magnit_api import MagnitAPI, MagnitAPIError

# ── Константы ────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")

# Все возможные статусы заказов Magnit
ALL_STATUSES = [
    "NEW", "CREATED", "DELIVERING_STARTED", "ACCEPTED_AT_POINT",
    "IN_COURIER_DELIVERY", "ISSUED", "DESTROYED", "ACCEPTED_AT_WAREHOUSE",
    "REMOVED", "WAITING_RETURN", "RETURN_INITIATED", "RETURN_SEND_TO_WAREHOUSE",
    "POSSIBLY_DEFECTED", "DEFECTED", "RETURN_ACCEPTED_AT_WAREHOUSE",
    "RETURNED_TO_PROVIDER", "CANCELED_BY_PROVIDER", "ACCEPTED_AT_CUSTOMS",
]

# Цвета для статусов (ANSI, работает в Windows Terminal / PowerShell 7+)
STATUS_COLORS = {
    "NEW":                       "\033[96m",    # голубой
    "CREATED":                   "\033[94m",    # синий
    "DELIVERING_STARTED":        "\033[93m",    # жёлтый
    "ACCEPTED_AT_POINT":         "\033[92m",    # зелёный
    "IN_COURIER_DELIVERY":       "\033[93m",    # жёлтый
    "ISSUED":                    "\033[92m",    # зелёный
    "DESTROYED":                 "\033[91m",    # красный
    "REMOVED":                   "\033[91m",    # красный
    "WAITING_RETURN":            "\033[95m",    # пурпурный
    "RETURN_INITIATED":          "\033[95m",    # пурпурный
    "RETURN_SEND_TO_WAREHOUSE":  "\033[95m",    # пурпурный
    "RETURN_ACCEPTED_AT_WAREHOUSE": "\033[95m", # пурпурный
    "RETURNED_TO_PROVIDER":      "\033[95m",    # пурпурный
    "CANCELED_BY_PROVIDER":      "\033[91m",    # красный
    "POSSIBLY_DEFECTED":         "\033[91m",    # красный
    "DEFECTED":                  "\033[91m",    # красный
}
RESET = "\033[0m"

# Русские названия статусов
STATUS_RU = {
    "NEW":                          "Новый",
    "CREATED":                      "Создан",
    "DELIVERING_STARTED":           "В пути",
    "ACCEPTED_AT_POINT":            "Принят в ПВЗ",
    "IN_COURIER_DELIVERY":          "У курьера",
    "ISSUED":                       "Выдан",
    "DESTROYED":                    "Уничтожен",
    "ACCEPTED_AT_WAREHOUSE":        "На складе",
    "REMOVED":                      "Удалён",
    "WAITING_RETURN":               "Ожидает возврата",
    "RETURN_INITIATED":             "Возврат начат",
    "RETURN_SEND_TO_WAREHOUSE":     "Возврат в пути",
    "POSSIBLY_DEFECTED":            "Возможен брак",
    "DEFECTED":                     "Брак",
    "RETURN_ACCEPTED_AT_WAREHOUSE": "Возврат принят на складе",
    "RETURNED_TO_PROVIDER":         "Возвращён поставщику",
    "CANCELED_BY_PROVIDER":         "Отменён",
    "ACCEPTED_AT_CUSTOMS":          "На таможне",
}


# ── Настройка логирования ────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = os.path.join(LOGS_DIR, f"list_orders_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    file_fmt = logging.Formatter(
        "%(asctime)s | %(name)-12s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)
    root_logger.addHandler(fh)

    if verbose:
        console_fmt = logging.Formatter("%(levelname)-7s | %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(console_fmt)
        root_logger.addHandler(ch)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    return logging.getLogger("list_orders")


# ── Загрузка конфигурации ────────────────────────────────────────────

def load_config(path: str) -> dict:
    if not os.path.exists(path):
        print(f"ОШИБКА: Файл конфигурации не найден: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Форматирование даты ─────────────────────────────────────────────

def format_dt(raw: str) -> str:
    """Форматирует ISO/RFC3339 дату в читаемый вид."""
    if not raw:
        return "—"
    try:
        # Обрабатываем разные форматы
        raw_clean = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw_clean)
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return raw[:19] if len(raw) > 19 else raw


# ── Извлечение данных заказа ─────────────────────────────────────────

def extract_order_fields(order: dict) -> dict:
    """Извлекает ключевые поля из объекта заказа (V1 и V2 совместимо)."""

    # ID
    order_id = order.get("id") or order.get("order_id") or "—"

    # Статус
    status = order.get("status") or "—"

    # Трекинг
    tracking = (order.get("tracking_number") or
                order.get("trackingNumber") or "—")

    # Номер заказа клиента
    customer_oid = (order.get("customer_order_id") or
                    order.get("customerOrderId") or "—")

    # Дата создания
    created = (order.get("created_at") or
               order.get("createdAt") or
               order.get("created") or "")

    # Получатель
    recipient = order.get("recipient") or order.get("delivery", {}).get("recipient", {})
    first_name = recipient.get("first_name") or recipient.get("firstName") or ""
    family_name = recipient.get("family_name") or recipient.get("familyName") or ""
    phone = recipient.get("phone_number") or recipient.get("phoneNumber") or ""
    recipient_str = f"{family_name} {first_name}".strip() or "—"

    # ПВЗ
    pp_key = (order.get("pickup_point") or
              order.get("pickupPointKey") or
              order.get("delivery", {}).get("pickupPointKey") or "—")

    # Объявленная ценность
    declared_value = None
    parcels = order.get("parcels", [])
    if parcels:
        declared_value = parcels[0].get("declared_value") or parcels[0].get("declaredValue")
    if declared_value is None:
        declared_value = order.get("payment", {}).get("declaredValue")

    # Стоимость доставки
    cost = order.get("cost") or order.get("delivery_cost") or ""

    return {
        "id": order_id,
        "status": status,
        "tracking": tracking,
        "customer_order_id": customer_oid,
        "created": format_dt(created),
        "recipient": recipient_str,
        "phone": phone,
        "pickup_point": pp_key,
        "declared_value": declared_value,
        "cost": cost,
    }


# ── Вывод таблицы ───────────────────────────────────────────────────

def colorize_status(status: str) -> str:
    """Добавляет ANSI-цвет к статусу."""
    color = STATUS_COLORS.get(status, "")
    ru = STATUS_RU.get(status, status)
    if color:
        return f"{color}{ru}{RESET}"
    return ru


def print_orders_table(orders: list):
    """Красиво выводит таблицу заказов в консоль."""
    if not orders:
        print("\n  Заказов не найдено.")
        return

    fields = [extract_order_fields(o) for o in orders]

    # Шапка
    print()
    print(f"{'№':>3}  {'Дата':^16}  {'Статус':<26}  {'Трекинг':<20}  "
          f"{'Номер заказа':<24}  {'Получатель':<25}  {'Телефон':<16}  "
          f"{'ПВЗ':<15}  {'Ценность':>10}")
    print("─" * 170)

    for i, f in enumerate(fields, 1):
        status_display = colorize_status(f["status"])
        value_str = f"{f['declared_value']:.2f}₽" if f['declared_value'] else "—"

        print(f"{i:>3}  {f['created']:^16}  {status_display:<35}  {f['tracking']:<20}  "
              f"{f['customer_order_id']:<24}  {f['recipient']:<25}  {f['phone']:<16}  "
              f"{f['pickup_point']:<15}  {value_str:>10}")

    print("─" * 170)


def print_order_detail(order: dict):
    """Выводит подробную информацию об одном заказе."""
    f = extract_order_fields(order)

    print(f"\n{'=' * 60}")
    print(f"  ЗАКАЗ: {f['customer_order_id']}")
    print(f"{'=' * 60}")
    print(f"  UUID:              {f['id']}")
    print(f"  Трекинг:           {f['tracking']}")
    print(f"  Статус:            {colorize_status(f['status'])}")
    print(f"  Дата создания:     {f['created']}")
    print(f"  Получатель:        {f['recipient']}")
    print(f"  Телефон:           {f['phone']}")
    print(f"  ПВЗ:               {f['pickup_point']}")

    if f['declared_value']:
        print(f"  Объявл. ценность:  {f['declared_value']:.2f} руб")
    if f['cost']:
        print(f"  Стоимость:         {f['cost']}")

    # Полный JSON
    print(f"\n  Полные данные API:")
    print(f"  {json.dumps(order, ensure_ascii=False, indent=2)}")
    print(f"{'=' * 60}")


# ── Основная логика ──────────────────────────────────────────────────

def fetch_all_orders(magnit: MagnitAPI, status: str = None,
                     created_from: str = None, created_to: str = None,
                     max_pages: int = 50, page_size: int = 100) -> list:
    """
    Загружает все заказы с пагинацией.
    """
    all_orders = []
    page = 1

    while page <= max_pages:
        data = magnit.get_orders(
            status=status,
            created_from=created_from,
            created_to=created_to,
            page=page,
            size=page_size,
            sort_direction="desc",
        )

        # API может вернуть разные структуры
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (data.get("items") or
                     data.get("orders") or
                     data.get("content") or [])
            # Если это единственный заказ
            if not items and "id" in data:
                items = [data]
        else:
            items = []

        all_orders.extend(items)

        # Информация о пагинации
        if isinstance(data, dict):
            total = data.get("totalCount") or data.get("total") or data.get("totalElements")
            if total is not None:
                print(f"  Загружено: {len(all_orders)} / {total}")

        # Если получили меньше чем page_size — последняя страница
        if len(items) < page_size:
            break

        page += 1

    return all_orders


def main():
    # ── Аргументы командной строки ───────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Magnit Post — Просмотр списка заказов",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Доступные статусы:\n  " + "\n  ".join(
            f"{s:<35} {STATUS_RU.get(s, '')}" for s in ALL_STATUSES
        ),
    )
    parser.add_argument(
        "--status", "-s",
        help="Фильтр по статусу (напр. CREATED, ISSUED, DELIVERING_STARTED)",
        choices=ALL_STATUSES,
        default=None,
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        help="Показать заказы за последние N дней",
        default=None,
    )
    parser.add_argument(
        "--order-id", "-o",
        help="Показать один конкретный заказ по UUID",
        default=None,
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Подробный вывод (DEBUG-логи в консоль)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результат в формате JSON",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Размер страницы при запросе (по умолчанию 100, макс 1000)",
    )

    args = parser.parse_args()

    # ── Инициализация ────────────────────────────────────────────────
    print("=" * 60)
    print("  MAGNIT POST — Список заказов")
    print("=" * 60)

    logger = setup_logging(verbose=args.verbose)
    config = load_config(CONFIG_PATH)
    magnit = MagnitAPI(config["magnit"])

    # Авторизация
    print("\n▸ Авторизация...")
    try:
        magnit.authenticate()
        print("  ✓ Авторизация успешна")
    except MagnitAPIError as e:
        print(f"  ✗ Ошибка авторизации: {e}")
        if e.response_body:
            logger.error("Ответ: %s", e.response_body)
        sys.exit(1)

    # ── Один конкретный заказ ─────────────────────────────────────────
    if args.order_id:
        print(f"\n▸ Загрузка заказа {args.order_id}...")
        try:
            order = magnit.get_order(args.order_id)
            if args.json:
                print(json.dumps(order, ensure_ascii=False, indent=2))
            else:
                print_order_detail(order)
        except MagnitAPIError as e:
            print(f"  ✗ Ошибка: {e}")
            if e.response_body:
                print(f"    {e.response_body[:300]}")
        return

    # ── Список заказов ───────────────────────────────────────────────
    created_from = None
    created_to = None

    if args.days:
        created_from = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        print(f"\n▸ Загрузка заказов за последние {args.days} дн.", end="")
    else:
        print(f"\n▸ Загрузка всех заказов", end="")

    if args.status:
        print(f" (статус: {args.status})...", end="")
    print("...")

    try:
        orders = fetch_all_orders(
            magnit,
            status=args.status,
            created_from=created_from,
            created_to=created_to,
            page_size=min(args.page_size, 1000),
        )
    except MagnitAPIError as e:
        print(f"  ✗ Ошибка загрузки: {e}")
        if e.response_body:
            print(f"    {e.response_body[:300]}")
        sys.exit(1)

    print(f"  ✓ Найдено заказов: {len(orders)}")

    if not orders:
        print("\n  Заказов не найдено.")
        return

    # Вывод
    if args.json:
        print(json.dumps(orders, ensure_ascii=False, indent=2))
    else:
        print_orders_table(orders)

        # Статистика по статусам
        status_counts = {}
        for o in orders:
            s = o.get("status", "UNKNOWN")
            status_counts[s] = status_counts.get(s, 0) + 1

        if len(status_counts) > 1:
            print(f"\n  Статистика по статусам:")
            for s, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
                ru = STATUS_RU.get(s, s)
                bar = "█" * min(cnt, 50)
                print(f"    {colorize_status(s):<35}  {cnt:>5}  {bar}")
            print()

    logger.info("Готово: загружено %d заказов", len(orders))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logging.getLogger("list_orders").exception("Необработанная ошибка")
        print(f"\n✗ Ошибка: {e}")
        sys.exit(1)
