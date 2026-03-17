"""
Модели данных для 5Post CLI-утилиты.
Dataclass-модели для товаров, складов, точек выдачи, заказов.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Product:
    """Товар в заказе."""
    name: str                           # Наименование товара
    quantity: int                       # Количество
    price_per_unit: float               # Цена за единицу (руб., с НДС)
    weight_grams: float                 # Вес единицы товара (граммы)
    vat: int = 22                       # Ставка НДС (%)
    vendor_code: str = ""               # Артикул товара

    @property
    def total_price(self) -> float:
        """Общая стоимость позиции."""
        return round(self.price_per_unit * self.quantity, 2)

    @property
    def total_weight_grams(self) -> float:
        """Общий вес позиции (граммы)."""
        return self.weight_grams * self.quantity


@dataclass
class Rate:
    """Тарифный план точки выдачи."""
    rate_type: str                      # Тип тарифного плана
    rate_value_with_vat: float          # Базовая стоимость доставки с НДС
    rate_extra_value_with_vat: float    # Надбавка за перевес с НДС (за 1 кг)
    zone: str = ""                      # Тарифная зона
    currency: str = "RUB"              # Валюта


@dataclass
class CellLimits:
    """Ограничения ячейки точки выдачи."""
    max_width_mm: int = 0               # Макс. ширина (мм)
    max_height_mm: int = 0              # Макс. высота (мм)
    max_length_mm: int = 0              # Макс. длина (мм)
    max_weight_mg: int = 0              # Макс. вес (мг)


@dataclass
class WorkHours:
    """Рабочие часы точки выдачи за один день."""
    day: str                            # День недели: MON, TUE, WED, THU, FRI, SAT, SUN
    opens_at: str                       # Время открытия (HH:MM)
    closes_at: str                      # Время закрытия (HH:MM)

    @property
    def day_display(self) -> str:
        """Короткое русское название дня недели."""
        day_names = {
            "MON": "Пн", "TUE": "Вт", "WED": "Ср", "THU": "Чт",
            "FRI": "Пт", "SAT": "Сб", "SUN": "Вс",
        }
        return day_names.get(self.day, self.day)

    @property
    def is_24h(self) -> bool:
        """Круглосуточная работа."""
        return self.opens_at == "00:00" and self.closes_at == "23:59"

    @property
    def is_closed(self) -> bool:
        """Выходной день."""
        return self.opens_at == self.closes_at


@dataclass
class PickupPoint:
    """Точка выдачи (постамат/ПВЗ)."""
    id: str                             # UUID точки выдачи
    name: str                           # Название (код ПВЗ, напр. "5POST-00513")
    type: str                           # Тип: POSTAMAT, TOBACCO, ISSUE_POINT
    full_address: str                   # Полный адрес
    city: str                           # Город
    lat: float                          # Широта
    lng: float                          # Долгота
    cash_allowed: bool                  # Оплата наличными
    card_allowed: bool                  # Оплата картой
    rates: list[Rate] = field(default_factory=list)           # Тарифы
    cell_limits: Optional[CellLimits] = None                  # Ограничения ячейки
    additional: str = ""                # Доп. информация (расположение)
    distance_km: float = 0.0           # Расстояние от адреса клиента (рассчитывается)
    work_hours: list["WorkHours"] = field(default_factory=list)  # Расписание работы
    phone: str = ""                     # Телефон
    short_address: str = ""             # Короткий адрес
    partner_name: str = ""              # Название партнёра (Fivebox и т.п.)
    mdm_code: str = ""                  # MDM-код точки

    @property
    def type_display(self) -> str:
        """Отображаемый тип точки."""
        type_names = {
            "POSTAMAT": "Постамат",
            "TOBACCO": "Касса",
            "ISSUE_POINT": "ПВЗ",
        }
        return type_names.get(self.type, self.type)

    @property
    def accepts_cod(self) -> bool:
        """Принимает ли наложенный платёж (наличные или карта)."""
        return self.cash_allowed or self.card_allowed

    @property
    def work_hours_display(self) -> str:
        """Компактное отображение расписания работы."""
        if not self.work_hours:
            return "нет данных"

        # Проверяем: все ли дни круглосуточные
        if all(wh.is_24h for wh in self.work_hours):
            return "Круглосуточно"

        # Группируем дни с одинаковым расписанием
        groups: list[tuple[list[str], str]] = []
        for wh in self.work_hours:
            if wh.is_closed:
                schedule = "выходной"
            elif wh.is_24h:
                schedule = "круглосуточно"
            else:
                schedule = f"{wh.opens_at}-{wh.closes_at}"

            if groups and groups[-1][1] == schedule:
                groups[-1][0].append(wh.day_display)
            else:
                groups.append(([wh.day_display], schedule))

        parts = []
        for days, schedule in groups:
            if len(days) == 1:
                parts.append(f"{days[0]}: {schedule}")
            else:
                parts.append(f"{days[0]}-{days[-1]}: {schedule}")
        return ", ".join(parts)

    @property
    def phone_display(self) -> str:
        """Форматированный телефон."""
        if not self.phone:
            return ""
        # 88005118800 → 8-800-511-88-00
        p = self.phone
        if len(p) == 11 and p.startswith("8"):
            return f"{p[0]}-{p[1:4]}-{p[4:7]}-{p[7:9]}-{p[9:11]}"
        return p


@dataclass
class Warehouse:
    """Склад партнёра."""
    id: str                             # UUID склада в системе 5Post
    name: str                           # Наименование
    full_address: str                   # Полный адрес
    partner_location_id: str            # ID склада в системе партнёра
    city: str = ""                      # Город
    status: str = "ACTIVE"             # Статус


@dataclass
class Cargo:
    """Грузоместо в заказе."""
    sender_cargo_id: str                # ID грузоместа в системе партнёра
    height_mm: int                      # Высота (мм)
    length_mm: int                      # Длина (мм)
    width_mm: int                       # Ширина (мм)
    weight_mg: int                      # Вес (мг)
    price: float                        # Оценочная стоимость груза (руб.)
    currency: str = "RUB"              # Валюта
    vat: int = 22                       # НДС (%)
    products: list[Product] = field(default_factory=list)     # Товары в грузоместе


@dataclass
class OrderCost:
    """Стоимостные параметры заказа."""
    delivery_cost: float                # Стоимость доставки для получателя
    payment_value: float                # Сумма к оплате при выдаче
    payment_currency: str               # Валюта оплаты
    payment_type: str                   # Способ: CASH, CASHLESS, PREPAYMENT
    price: float                        # Оценочная стоимость заказа
    price_currency: str                 # Валюта оценочной стоимости


@dataclass
class Order:
    """Заказ для отправки в 5Post."""
    sender_order_id: str                # ID заказа (генерируется)
    client_order_id: str                # Трек-номер для клиента (= sender_order_id)
    client_name: str                    # ФИО получателя
    client_phone: str                   # Телефон получателя
    client_email: str                   # Email получателя
    sender_location: str                # partnerLocationId выбранного склада
    receiver_location: str              # UUID точки выдачи
    undeliverable_option: str           # RETURN или UTILIZATION
    cost: OrderCost                     # Стоимостные параметры
    cargoes: list[Cargo] = field(default_factory=list)        # Грузоместа

    def to_api_dict(self) -> dict:
        """Преобразование в формат API v3 5Post."""
        cargoes_list = []
        for cargo in self.cargoes:
            product_values = []
            for p in cargo.products:
                pv = {
                    "name": p.name,
                    "value": p.quantity,
                    "price": p.price_per_unit,
                    "vat": p.vat,
                    "currency": cargo.currency,
                }
                if p.vendor_code:
                    pv["vendorCode"] = p.vendor_code
                product_values.append(pv)

            cargo_dict = {
                "senderCargoId": cargo.sender_cargo_id,
                "height": cargo.height_mm,
                "length": cargo.length_mm,
                "width": cargo.width_mm,
                "weight": cargo.weight_mg,
                "price": cargo.price,
                "currency": cargo.currency,
                "vat": cargo.vat,
                "productValues": product_values,
            }
            cargoes_list.append(cargo_dict)

        order_dict = {
            "partnerOrders": [
                {
                    "senderOrderId": self.sender_order_id,
                    "clientOrderId": self.client_order_id,
                    "clientName": self.client_name,
                    "clientPhone": self.client_phone,
                    "clientEmail": self.client_email,
                    "senderLocation": self.sender_location,
                    "receiverLocation": self.receiver_location,
                    "undeliverableOption": self.undeliverable_option,
                    "cost": {
                        "deliveryCost": self.cost.delivery_cost,
                        "deliveryCostCurrency": self.cost.payment_currency,
                        "paymentValue": self.cost.payment_value,
                        "paymentCurrency": self.cost.payment_currency,
                        "paymentType": self.cost.payment_type,
                        "price": self.cost.price,
                        "priceCurrency": self.cost.price_currency,
                    },
                    "cargoes": cargoes_list,
                }
            ]
        }
        return order_dict
