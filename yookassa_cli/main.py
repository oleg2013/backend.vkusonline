#!/usr/bin/env python3
"""YooKassa CLI — интерактивная утилита для создания платежей с чеком."""

import io
import json
import logging
import re
import sys
import time
import uuid
import threading
import webbrowser
from decimal import Decimal, ROUND_HALF_UP
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import yaml
from yookassa import Configuration, Payment

# ─── Исправление кодировки для Windows ───────────────────────────────────────

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

# ─── Настройка логгирования ──────────────────────────────────────────────────

LOG_FILE = Path(__file__).parent / "yookassa_cli.log"

log = logging.getLogger("yookassa_cli")
log.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))

log.addHandler(file_handler)
log.addHandler(console_handler)


# ─── Загрузка конфигурации ───────────────────────────────────────────────────

def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    log.info("Загрузка конфигурации из %s", config_path)
    if not config_path.exists():
        log.error("Файл конфигурации не найден: %s", config_path)
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    log.debug("Конфигурация загружена: shop_id=%s, callback=%s:%s",
              config["yookassa"]["shop_id"],
              config["callback"]["host"],
              config["callback"]["port"])
    return config


# ─── Валидация ввода ─────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "", validator=None, error_msg: str = "") -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default:
            value = default
        if not value:
            print("  Поле обязательно для заполнения.")
            continue
        if validator and not validator(value):
            print(f"  {error_msg}" if error_msg else "  Некорректное значение.")
            continue
        log.debug("Ввод: '%s' -> '%s'", prompt, value)
        return value


def validate_phone(phone: str) -> bool:
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    return bool(re.match(r"^\+?[78]\d{10}$", cleaned))


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if cleaned.startswith("8"):
        cleaned = "+7" + cleaned[1:]
    elif cleaned.startswith("7"):
        cleaned = "+" + cleaned
    elif not cleaned.startswith("+"):
        cleaned = "+7" + cleaned
    return cleaned


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_price(price: str) -> bool:
    try:
        val = Decimal(price)
        return val > 0
    except Exception:
        return False


def validate_quantity(qty: str) -> bool:
    try:
        val = int(qty)
        return val > 0
    except Exception:
        return False


# ─── Ввод данных покупателя ──────────────────────────────────────────────────

def input_customer() -> dict:
    print("\n═══ Данные покупателя ═══")
    full_name = ask("ФИО покупателя")
    phone = ask(
        "Телефон (например, +79001234567)",
        validator=validate_phone,
        error_msg="Введите корректный российский номер телефона.",
    )
    email = ask(
        "Email",
        validator=validate_email,
        error_msg="Введите корректный email.",
    )
    customer = {
        "full_name": full_name,
        "phone": normalize_phone(phone),
        "email": email,
    }
    log.info("Покупатель: %s, тел: %s, email: %s",
             customer["full_name"], customer["phone"], customer["email"])
    return customer


# ─── Ввод товаров ───────────────────────────────────────────────────────────

def input_items(config: dict) -> list[dict]:
    print("\n═══ Товары ═══")
    items = []
    while True:
        idx = len(items) + 1
        print(f"\n--- Товар #{idx} ---")
        name = ask("Название товара")
        price = ask(
            "Цена за единицу (руб.)",
            validator=validate_price,
            error_msg="Цена должна быть положительным числом.",
        )
        quantity = ask(
            "Количество",
            default="1",
            validator=validate_quantity,
            error_msg="Количество должно быть целым положительным числом.",
        )

        price_dec = Decimal(price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        qty_int = int(quantity)
        line_total = (price_dec * qty_int).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        receipt_cfg = config["receipt"]
        item = {
            "description": name,
            "quantity": str(qty_int),
            "amount": {
                "value": str(price_dec),
                "currency": "RUB",
            },
            "vat_code": receipt_cfg["vat_code"],
            "payment_mode": receipt_cfg["payment_mode"],
            "payment_subject": receipt_cfg["payment_subject"],
        }
        items.append(item)
        log.info("Товар добавлен: %s x%d @ %s = %s руб. (НДС код: %d)",
                 name, qty_int, price_dec, line_total, receipt_cfg["vat_code"])
        print(f"  Добавлено: {name} x{qty_int} @ {price_dec} = {line_total} руб.")

        more = input("\nДобавить ещё товар? (д/н) [н]: ").strip().lower()
        if more not in ("д", "y", "да", "yes"):
            break

    log.info("Всего товаров: %d", len(items))
    return items


# ─── Ввод данных карты ───────────────────────────────────────────────────────

def input_card(config: dict) -> dict:
    print("\n═══ Данные карты ═══")
    card_cfg = config["default_card"]
    print(f"  Карта по умолчанию: {card_cfg['number']}")
    print(f"  Срок: {card_cfg['expiry']}, CVC: {card_cfg['cvc']}")
    use_default = input("Использовать карту по умолчанию? (д/н) [д]: ").strip().lower()
    if use_default in ("н", "n", "нет", "no"):
        number = ask("Номер карты (16 цифр)", validator=lambda v: len(re.sub(r"\s", "", v)) == 16)
        expiry = ask("Срок действия (MM/YY)", validator=lambda v: bool(re.match(r"^\d{2}/\d{2}$", v)))
        cvc = ask("CVC (3 цифры)", validator=lambda v: bool(re.match(r"^\d{3}$", v)))
        card = {"number": re.sub(r"\s", "", number), "expiry": expiry, "cvc": cvc}
    else:
        card = card_cfg
    log.info("Карта: ****%s, срок: %s", card["number"][-4:], card["expiry"])
    return card


# ─── Callback-сервер ─────────────────────────────────────────────────────────

class CallbackHandler(BaseHTTPRequestHandler):
    """Обрабатывает редирект браузера после оплаты."""

    callback_received = threading.Event()
    payment_result = None  # будет заполнено после поллинга
    payment_id = None

    def do_GET(self, *_args):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        log.info("Callback получен: path=%s, params=%s, от %s",
                 self.path, params, self.client_address)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        # Формируем HTML с результатом платежа
        result = CallbackHandler.payment_result
        if result and result.status == "succeeded":
            status_text = "ПЛАТЁЖ УСПЕШНО ПРОВЕДЁН"
            status_color = "#28a745"
            status_icon = "&#10004;"
            details = f"""
            <p><b>ID платежа:</b> {result.id}</p>
            <p><b>Сумма:</b> {result.amount.value} {result.amount.currency}</p>
            <p><b>Способ оплаты:</b> Банковская карта</p>
            <p>Чек будет отправлен на email покупателя.</p>"""
        elif result and result.status == "canceled":
            status_text = "ПЛАТЁЖ ОТМЕНЁН"
            status_color = "#dc3545"
            status_icon = "&#10008;"
            reason = ""
            if result.cancellation_details:
                reason = f"<p><b>Причина:</b> {result.cancellation_details.reason}</p>"
            details = f"""
            <p><b>ID платежа:</b> {result.id}</p>
            {reason}"""
        else:
            # Результат ещё не получен — покажем статус ожидания
            pid = CallbackHandler.payment_id or "—"
            status_text = "ОБРАБОТКА ПЛАТЕЖА..."
            status_color = "#ffc107"
            status_icon = "&#9203;"
            details = f"""
            <p><b>ID платежа:</b> {pid}</p>
            <p>Платёж обрабатывается. Проверьте статус в терминале.</p>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>YooKassa CLI — Результат</title></head>
<body style="font-family:sans-serif;text-align:center;margin:60px auto;max-width:500px;">
<div style="border:2px solid {status_color};border-radius:12px;padding:30px;">
  <div style="font-size:48px;color:{status_color};">{status_icon}</div>
  <h1 style="color:{status_color};">{status_text}</h1>
  <div style="text-align:left;padding:10px 20px;">{details}</div>
</div>
<p style="margin-top:20px;color:#666;">Можете закрыть эту вкладку и вернуться в терминал.</p>
</body></html>"""
        self.wfile.write(html.encode("utf-8"))
        CallbackHandler.callback_received.set()

    def log_message(self, format, *args):
        log.debug("HTTP: %s", format % args)


def start_callback_server(host: str, port: int) -> HTTPServer:
    log.info("Запуск callback-сервера на %s:%d", host, port)
    server = HTTPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Callback-сервер запущен")
    return server


# ─── Создание платежа ────────────────────────────────────────────────────────

def create_payment(
    config: dict,
    customer: dict,
    items: list[dict],
    total_amount: str,
) -> dict:
    cb_cfg = config["callback"]
    return_url = f"http://{cb_cfg['host']}:{cb_cfg['port']}/callback"

    payment_data = {
        "amount": {
            "value": total_amount,
            "currency": "RUB",
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "receipt": {
            "customer": customer,
            "items": items,
            "tax_system_code": config["receipt"]["tax_system_code"],
        },
        "description": f"Оплата для {customer['full_name']}",
    }

    idempotence_key = str(uuid.uuid4())
    log.info("Создание платежа: сумма=%s RUB, idempotence_key=%s", total_amount, idempotence_key)
    log.debug("Данные платежа:\n%s", json.dumps(payment_data, ensure_ascii=False, indent=2))

    try:
        payment = Payment.create(payment_data, idempotence_key)
        log.info("Платёж создан: id=%s, status=%s", payment.id, payment.status)
        if payment.confirmation:
            log.info("Confirmation URL: %s", payment.confirmation.confirmation_url)
        log.debug("Полный ответ: %s", payment.json())
        return payment
    except Exception as e:
        log.error("Ошибка создания платежа: %s", e, exc_info=True)
        raise


# ─── Ожидание завершения платежа ─────────────────────────────────────────────

def wait_for_payment(payment_id: str, timeout: int = 300) -> dict:
    """Поллит статус платежа до финального состояния или таймаута."""
    log.info("Ожидание завершения платежа %s (таймаут: %d сек)", payment_id, timeout)
    start = time.time()
    final_statuses = ("succeeded", "canceled")
    poll_count = 0

    while time.time() - start < timeout:
        poll_count += 1
        try:
            payment = Payment.find_one(payment_id)
            status = payment.status
            elapsed = int(time.time() - start)
            log.debug("Поллинг #%d (%d сек): статус=%s", poll_count, elapsed, status)

            if status in final_statuses:
                log.info("Финальный статус: %s (после %d сек, %d запросов)",
                         status, elapsed, poll_count)
                return payment
        except Exception as e:
            log.warning("Ошибка поллинга #%d: %s", poll_count, e)

        if CallbackHandler.callback_received.is_set():
            log.debug("Callback получен, ускоренный поллинг (1 сек)")
            time.sleep(1)
        else:
            time.sleep(3)

    log.warning("Таймаут ожидания платежа (%d сек, %d запросов)", timeout, poll_count)
    return Payment.find_one(payment_id)


# ─── Отображение итогов ──────────────────────────────────────────────────────

def print_summary(customer: dict, items: list[dict], total: Decimal, card: dict):
    print("\n" + "═" * 50)
    print("  СВОДКА ЗАКАЗА")
    print("═" * 50)
    print(f"  Покупатель: {customer['full_name']}")
    print(f"  Телефон:    {customer['phone']}")
    print(f"  Email:      {customer['email']}")
    print("─" * 50)
    for i, item in enumerate(items, 1):
        desc = item["description"]
        qty = int(item["quantity"])
        unit_price = Decimal(item["amount"]["value"])
        line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        print(f"  {i}. {desc} x{qty} @ {unit_price} = {line_total} руб.")
    print("─" * 50)
    print(f"  ИТОГО: {total} руб. (вкл. НДС 22%)")
    print(f"  Карта: **** **** **** {card['number'][-4:]}")
    print("═" * 50)


def print_result(payment):
    status = payment.status
    print("\n" + "═" * 50)
    if status == "succeeded":
        print("  ПЛАТЁЖ УСПЕШНО ПРОВЕДЁН")
        print(f"  ID платежа: {payment.id}")
        print(f"  Сумма: {payment.amount.value} {payment.amount.currency}")
        if payment.payment_method:
            pm = payment.payment_method
            if hasattr(pm, "card") and pm.card:
                print(f"  Карта: *{pm.card.last4} ({pm.card.card_type})")
        print("  Чек будет отправлен на email покупателя.")
        log.info("УСПЕХ: платёж %s, сумма %s %s",
                 payment.id, payment.amount.value, payment.amount.currency)
    elif status == "canceled":
        print("  ПЛАТЁЖ ОТМЕНЁН")
        print(f"  ID платежа: {payment.id}")
        reason = ""
        party = ""
        if payment.cancellation_details:
            cd = payment.cancellation_details
            reason = cd.reason
            party = cd.party
            print(f"  Причина: {reason}")
            print(f"  Инициатор: {party}")
        log.warning("ОТМЕНА: платёж %s, причина=%s, инициатор=%s",
                    payment.id, reason, party)
    else:
        print(f"  СТАТУС ПЛАТЕЖА: {status}")
        print(f"  ID платежа: {payment.id}")
        print("  Платёж не завершён в отведённое время.")
        print("  Проверьте статус позже в личном кабинете YooKassa.")
        log.warning("НЕЗАВЕРШЁН: платёж %s, статус=%s", payment.id, status)
    print("═" * 50)


# ─── Главная функция ─────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("YooKassa CLI запущен")
    log.info("=" * 60)

    print("╔══════════════════════════════════════╗")
    print("║     YooKassa CLI — Создание платежа  ║")
    print("╚══════════════════════════════════════╝")

    config = load_config()

    # Настройка SDK
    Configuration.account_id = config["yookassa"]["shop_id"]
    Configuration.secret_key = config["yookassa"]["api_key"]
    log.info("SDK настроен: shop_id=%s", config["yookassa"]["shop_id"])

    # Сбор данных
    customer = input_customer()
    items = input_items(config)
    card = input_card(config)

    # Подсчёт итога (amount в items = цена за единицу, quantity = кол-во)
    total = sum(
        Decimal(item["amount"]["value"]) * Decimal(item["quantity"])
        for item in items
    )
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    log.info("Итого к оплате: %s руб.", total)

    # Сводка
    print_summary(customer, items, total, card)

    confirm = input("\nПровести платёж? (д/н) [д]: ").strip().lower()
    if confirm in ("н", "n", "нет", "no"):
        log.info("Платёж отменён пользователем")
        print("Платёж отменён пользователем.")
        sys.exit(0)

    # Запуск callback-сервера
    cb_cfg = config["callback"]
    server = start_callback_server(cb_cfg["host"], cb_cfg["port"])
    print(f"\nCallback-сервер запущен на http://{cb_cfg['host']}:{cb_cfg['port']}")

    # Создание платежа
    print("Создание платежа в YooKassa...")
    try:
        payment = create_payment(config, customer, items, str(total))
    except Exception as e:
        print(f"\nОшибка создания платежа: {e}")
        server.shutdown()
        sys.exit(1)

    print(f"Платёж создан: {payment.id}")
    print(f"Статус: {payment.status}")

    # Открываем страницу оплаты в браузере
    confirmation_url = payment.confirmation.confirmation_url
    print(f"\nОткрываю страницу оплаты в браузере...")
    print(f"URL: {confirmation_url}")

    # Подсказка по карте
    print(f"\n  Данные для ввода на странице оплаты:")
    print(f"  Номер карты: {card['number']}")
    print(f"  Срок:        {card['expiry']}")
    print(f"  CVC:         {card['cvc']}")

    webbrowser.open(confirmation_url)
    log.info("Браузер открыт с URL: %s", confirmation_url)

    # Ожидание результата
    print("\nОжидание завершения оплаты (до 5 минут)...")
    print("  После оплаты браузер вернётся на callback-страницу.")

    # Сохраняем ID для callback-страницы (пока результат ещё не известен)
    CallbackHandler.payment_id = payment.id

    result = wait_for_payment(payment.id, timeout=300)

    # Передаём результат в callback-сервер (для отображения на странице)
    CallbackHandler.payment_result = result
    print_result(result)

    # Ждём callback (когда пользователь нажмёт "Вернуться на сайт")
    if not CallbackHandler.callback_received.is_set():
        print("\nОжидание возврата из браузера (нажмите 'Вернуться на сайт')...")
        log.info("Ожидание callback от браузера (до 60 сек)...")
        CallbackHandler.callback_received.wait(timeout=60)
        if CallbackHandler.callback_received.is_set():
            log.info("Callback получен — браузер вернулся на callback-страницу")
            print("  Callback получен. Результат отображён в браузере.")
        else:
            log.info("Таймаут ожидания callback (60 сек) — завершаем без него")
            print("  Таймаут ожидания callback. Завершаем.")
    else:
        log.info("Callback уже был получен ранее")

    # Остановка сервера
    server.shutdown()
    log.info("Callback-сервер остановлен")
    log.info("Сессия завершена")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Прервано пользователем (Ctrl+C)")
        print("\n\nПрервано пользователем.")
        sys.exit(0)
    except Exception as e:
        log.critical("Необработанное исключение: %s", e, exc_info=True)
        print(f"\nКритическая ошибка: {e}")
        sys.exit(1)
