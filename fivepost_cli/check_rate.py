"""
Утилита проверки стоимости доставки до конкретного ПВЗ.

Загружает данные ПВЗ из кэша (тарифы получены через API 5Post)
и записывает подробный расчёт стоимости доставки в лог-файл.

Использование:
    python check_rate.py

Результат сохраняется в папку logs/
"""

import json
import math
import os
import sys
from datetime import datetime

# ===================== Параметры запроса =====================

PICKUP_POINT_ID = "2820c063-d69d-4a3c-95bd-428bc5391677"  # ПВЗ в Магадане
WAREHOUSE_ID = "f6389674-af2c-4f0f-aa49-4966fcc19cda"     # Склад в Москве
WEIGHT_KG = 1.0                                            # Вес груза (кг)
DECLARED_VALUE = 3000.0                                    # Объявленная стоимость (руб.)
PAYMENT_TYPE = "PREPAYMENT"                                # Предоплата
OVERWEIGHT_THRESHOLD_KG = 3.0                              # Порог перевеса (кг)

# ===================== Пути =====================

BASE_DIR = os.path.dirname(__file__)
CACHE_FILE = os.path.join(BASE_DIR, "cache", "pickup_points.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")


def main():
    # --- Подготовка лог-файла ---
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"check_rate_{timestamp}.log")

    lines: list[str] = []

    def log(text: str = ""):
        """Добавить строку в буфер и вывести в консоль."""
        lines.append(text)
        print(text)

    log("=" * 65)
    log("  Проверка стоимости доставки 5Post (из данных API)")
    log("=" * 65)

    # --- Загрузка кэша ---
    if not os.path.exists(CACHE_FILE):
        log(f"\nОШИБКА: Кэш не найден: {CACHE_FILE}")
        log("Сначала выполните: python update_cache.py")
        _save_log(log_file, lines)
        sys.exit(1)

    log(f"\nЗагрузка кэша: {CACHE_FILE}")
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache_data = json.load(f)

    cached_at = cache_data.get("cached_at", "?")
    points = cache_data.get("points", [])
    log(f"Кэш от: {cached_at}")
    log(f"Всего точек в кэше: {len(points)}")

    # --- Поиск ПВЗ по ID ---
    target = None
    for p in points:
        if p.get("id") == PICKUP_POINT_ID:
            target = p
            break

    if not target:
        log(f"\nОШИБКА: ПВЗ с ID {PICKUP_POINT_ID} не найден в кэше!")
        _save_log(log_file, lines)
        sys.exit(1)

    # --- Информация о ПВЗ ---
    address = target.get("address", {})
    log(f"\n{'─' * 65}")
    log(f"  ПУНКТ ВЫДАЧИ")
    log(f"{'─' * 65}")
    log(f"  Название:    {target.get('name', '?')}")
    log(f"  Тип:         {target.get('type', '?')}")
    log(f"  Адрес:       {target.get('fullAddress', '?')}")
    log(f"  Город:       {address.get('city', '?')}")
    log(f"  ID:          {target.get('id', '?')}")
    log(f"  MDM-код:     {target.get('mdmCode', '?')}")
    log(f"  Партнёр:     {target.get('partnerName', '?')}")
    log(f"  Наличные:    {'Да' if target.get('cashAllowed') else 'Нет'}")
    log(f"  Карта:       {'Да' if target.get('cardAllowed') else 'Нет'}")
    log(f"  Статус:      {target.get('extStatus', '?')}")

    # --- Ограничения ячейки ---
    cell = target.get("cellLimits", {})
    if cell:
        max_w = cell.get("maxCellWidth", 0)
        max_h = cell.get("maxCellHeight", 0)
        max_l = cell.get("maxCellLength", 0)
        max_weight_mg = cell.get("maxWeight", 0)
        log(f"\n  Ячейка:      {max_w}×{max_h}×{max_l} мм, макс. вес {max_weight_mg / 1000:.0f} г")

    # --- Рабочие часы ---
    work_hours = target.get("workHours", [])
    if work_hours:
        day_names = {
            "MON": "Пн", "TUE": "Вт", "WED": "Ср", "THU": "Чт",
            "FRI": "Пт", "SAT": "Сб", "SUN": "Вс",
        }
        day_order = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        sorted_hours = sorted(work_hours, key=lambda wh: day_order.index(wh.get("day", "MON"))
                              if wh.get("day") in day_order else 99)
        hours_str = ", ".join(
            f"{day_names.get(wh['day'], wh['day'])} {wh.get('opensAt', '?')}-{wh.get('closesAt', '?')}"
            for wh in sorted_hours
        )
        log(f"  Режим:       {hours_str}")

    # --- Все тарифы ---
    rates = target.get("rate", [])
    log(f"\n{'─' * 65}")
    log(f"  ТАРИФЫ (из API 5Post)")
    log(f"{'─' * 65}")

    if not rates:
        log("  Тарифы отсутствуют!")
        _save_log(log_file, lines)
        sys.exit(1)

    for i, r in enumerate(rates, 1):
        rate_type = r.get("rateType", "?")
        zone = r.get("zone", "?")
        rate_val = r.get("rateValue", 0)
        rate_vat = r.get("rateValueWithVat", 0)
        extra_val = r.get("rateExtraValue", 0)
        extra_vat = r.get("rateExtraValueWithVat", 0)
        vat_pct = r.get("vat", 0)
        currency = r.get("rateCurrency", "RUB")
        rate_code = r.get("rateTypeCode", "—")

        log(f"\n  Тариф #{i}:")
        log(f"    Тип:                   {rate_type}")
        log(f"    Код типа:              {rate_code}")
        log(f"    Зона:                  {zone}")
        log(f"    НДС:                   {vat_pct}%")
        log(f"    Базовая (без НДС):     {rate_val:.2f} {currency}")
        log(f"    Базовая (с НДС):       {rate_vat:.2f} {currency}")
        log(f"    Надбавка/кг (без НДС): {extra_val:.2f} {currency}")
        log(f"    Надбавка/кг (с НДС):   {extra_vat:.2f} {currency}")

    # --- Расчёт стоимости доставки ---
    valid_rates = [r for r in rates if r.get("rateValueWithVat", 0) > 0]
    if not valid_rates:
        log("\n  ОШИБКА: Все тарифы имеют нулевую стоимость (не прогружены)!")
        _save_log(log_file, lines)
        sys.exit(1)

    best = min(valid_rates, key=lambda r: r.get("rateValueWithVat", 0))

    base_cost = best.get("rateValueWithVat", 0)
    extra_per_kg = best.get("rateExtraValueWithVat", 0)

    log(f"\n{'─' * 65}")
    log(f"  РАСЧЁТ СТОИМОСТИ ДОСТАВКИ")
    log(f"{'─' * 65}")
    log(f"  Используемый тариф:    {best.get('rateType', '?')} (зона {best.get('zone', '?')})")
    log(f"  Вес груза:             {WEIGHT_KG:.1f} кг")
    log(f"  Объявленная стоимость: {DECLARED_VALUE:.2f} руб.")
    log(f"  Способ оплаты:        {PAYMENT_TYPE}")
    log(f"  Склад отправки:       {WAREHOUSE_ID}")
    log()
    log(f"  Базовая стоимость (с НДС):  {base_cost:.2f} руб.")

    if WEIGHT_KG > OVERWEIGHT_THRESHOLD_KG:
        overweight_kg = math.ceil(WEIGHT_KG - OVERWEIGHT_THRESHOLD_KG)
        overweight_cost = extra_per_kg * overweight_kg
        total = base_cost + overweight_cost
        log(f"  Перевес:                    {WEIGHT_KG - OVERWEIGHT_THRESHOLD_KG:.1f} кг → округлено до {overweight_kg} кг")
        log(f"  Надбавка за перевес:        {extra_per_kg:.2f} × {overweight_kg} = {overweight_cost:.2f} руб.")
        log(f"  ─────────────────────────────────")
        log(f"  ИТОГО доставка:             {total:.2f} руб.")
    else:
        log(f"  Перевес:                    нет (≤ {OVERWEIGHT_THRESHOLD_KG:.0f} кг)")
        log(f"  ─────────────────────────────────")
        log(f"  ИТОГО доставка:             {base_cost:.2f} руб.")

    # --- Сроки доставки ---
    delivery_sl = target.get("deliverySL", [])
    if delivery_sl:
        log(f"\n{'─' * 65}")
        log(f"  СРОКИ ДОСТАВКИ (SL)")
        log(f"{'─' * 65}")
        for sl_item in delivery_sl:
            sl_code = sl_item.get("slCode", "?")
            sl_days = sl_item.get("sl", "?")
            sl_min = sl_item.get("minimalSl", "?")
            log(f"  slCode={sl_code}: {sl_min}-{sl_days} дн.")

    # --- Сырой JSON (для отладки) ---
    log(f"\n{'─' * 65}")
    log(f"  СЫРЫЕ ДАННЫЕ rate[] ИЗ API")
    log(f"{'─' * 65}")
    log(json.dumps(rates, ensure_ascii=False, indent=2))

    log(f"\n{'=' * 65}")
    log(f"  Источник: кэш API 5Post от {cached_at}")
    log(f"  Примечание: API 5Post не имеет отдельного endpoint'а для")
    log(f"  расчёта B2B-тарифов. Тарифы получены из POST pickupPoints.")
    log(f"{'=' * 65}")

    # --- Сохранение лог-файла ---
    _save_log(log_file, lines)
    print(f"\nЛог сохранён: {os.path.abspath(log_file)}")


def _save_log(log_file: str, lines: list[str]):
    """Записать накопленные строки в лог-файл."""
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
