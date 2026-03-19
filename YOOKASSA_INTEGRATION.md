# YooKassa Integration Guide

Техническое описание интеграции с платежной системой YooKassa (yookassa.ru) для интернет-магазина.
Основано на **реально протестированной** рабочей интеграции (тестовый магазин, март 2026).

---

## 1. Учётные данные

| Параметр       | Значение                                            | Описание                   |
| -------------- | --------------------------------------------------- | -------------------------- |
| ShopID         | `1290955`                                           | Идентификатор магазина     |
| API Key        | `test_Veshzf2S4ksgtkRdq7y_534YDVI47b5IqhzQ-xRXuDs`  | Секретный ключ (тестовый)  |
| Mobile SDK Key | `test_MTI5MDk1NY6tkXWrnIkRQ1WvOxv2t5jyP9xgr3A39Wk`  | Ключ для мобильного SDK    |
| API Base URL   | `https://api.yookassa.ru/v3/`                       | Базовый URL API            |
| Checkout URL   | `https://yoomoney.ru/checkout/payments/v2/contract` | Страница оплаты (redirect) |

**Аутентификация:** HTTP Basic Auth — `shop_id:api_key` (base64).

---

## 2. Архитектура платежного процесса

### 2.1 Общая схема (redirect flow)

```
[Корзина] --> [Бэкенд: создание платежа] --> [YooKassa API]
                                                    |
                                              confirmation_url
                                                    |
                                              [Браузер: checkout-страница YooKassa]
                                                    |
                                              [Ввод карты + 3D Secure]
                                                    |
                                              [YooKassa redirect на return_url]
                                                    |
                                              [Бэкенд: проверка статуса + отображение результата]
```

### 2.2 Жизненный цикл платежа

```
pending --> waiting_for_capture --> succeeded
   |                |
   v                v
canceled        canceled
```

Для одноэтапной оплаты (`capture: true`): `pending --> succeeded | canceled`.

### 2.3 Статусы платежа

| Статус                | Описание                                    | Финальный |
| --------------------- | ------------------------------------------- | --------- |
| `pending`             | Создан, ожидает подтверждения пользователем | Нет       |
| `waiting_for_capture` | Авторизован, ожидает capture (двухэтапная)  | Нет       |
| `succeeded`           | Успешно проведён                            | Да        |
| `canceled`            | Отменён                                     | Да        |

---

## 3. Backend: Создание платежа

### 3.1 Python SDK

```bash
pip install yookassa pyyaml
```

```python
from yookassa import Configuration, Payment
import uuid

# Инициализация (один раз при старте приложения)
Configuration.account_id = "1290955"
Configuration.secret_key = "test_Veshzf2S4ksgtkRdq7y_534YDVI47b5IqhzQ-xRXuDs"
```

### 3.2 Создание платежа с чеком (54-ФЗ)

```python
payment_data = {
    "amount": {
        "value": "5450.00",       # СТРОКА, не число!
        "currency": "RUB"
    },
    "capture": True,               # Одноэтапная оплата
    "confirmation": {
        "type": "redirect",
        "return_url": "https://your-shop.ru/payment/callback"
    },
    "receipt": {
        "customer": {
            "full_name": "Шубин ОМ",
            "phone": "+79165640299",
            "email": "olegshubin@gmail.com"
        },
        "items": [
            {
                "description": "RIO GRANDE 707",
                "quantity": "1",           # СТРОКА
                "amount": {
                    "value": "3000.00",    # Цена за ЕДИНИЦУ, не итого!
                    "currency": "RUB"
                },
                "vat_code": 11,            # НДС 22%
                "payment_mode": "full_payment",
                "payment_subject": "commodity"
            },
            {
                "description": "Молочный Улун 550096",
                "quantity": "1",
                "amount": {
                    "value": "1200.00",
                    "currency": "RUB"
                },
                "vat_code": 11,
                "payment_mode": "full_payment",
                "payment_subject": "commodity"
            },
            {
                "description": "Английский завтрак 550090",
                "quantity": "1",
                "amount": {
                    "value": "1250.00",
                    "currency": "RUB"
                },
                "vat_code": 11,
                "payment_mode": "full_payment",
                "payment_subject": "commodity"
            }
        ],
        "tax_system_code": 1       # ОСН (общая система налогообложения)
    },
    "description": "Заказ #12345"
}

# ОБЯЗАТЕЛЬНО: уникальный ключ идемпотентности для каждого платежа
idempotence_key = str(uuid.uuid4())
payment = Payment.create(payment_data, idempotence_key)

# Результат:
# payment.id = "313bd040-000f-5000-8000-1671ab4ed7d7"
# payment.status = "pending"
# payment.confirmation.confirmation_url = "https://yoomoney.ru/checkout/payments/v2/contract?orderId=..."
```

### 3.3 Реальный JSON-запрос к API (проверенный)

Ниже — точная копия запроса, который был **успешно** отправлен в YooKassa API и вернул платёж:

```json
{
  "amount": {
    "value": "5450.00",
    "currency": "RUB"
  },
  "capture": true,
  "confirmation": {
    "type": "redirect",
    "return_url": "http://localhost:8765/callback"
  },
  "receipt": {
    "customer": {
      "full_name": "Шубин ОМ",
      "phone": "+79165640299",
      "email": "olegshubin@gmail.com"
    },
    "items": [
      {
        "description": "RIO GRANDE 707",
        "quantity": "1",
        "amount": {
          "value": "3000.00",
          "currency": "RUB"
        },
        "vat_code": 11,
        "payment_mode": "full_payment",
        "payment_subject": "commodity"
      },
      {
        "description": "Молочный Улун 550096",
        "quantity": "1",
        "amount": {
          "value": "1200.00",
          "currency": "RUB"
        },
        "vat_code": 11,
        "payment_mode": "full_payment",
        "payment_subject": "commodity"
      },
      {
        "description": "Английский завтрак 550090",
        "quantity": "1",
        "amount": {
          "value": "1250.00",
          "currency": "RUB"
        },
        "vat_code": 11,
        "payment_mode": "full_payment",
        "payment_subject": "commodity"
      }
    ],
    "tax_system_code": 1
  },
  "description": "Оплата для Шубин ОМ"
}
```

### 3.4 Реальный JSON-ответ от API

```json
{
  "id": "313bd040-000f-5000-8000-1671ab4ed7d7",
  "status": "pending",
  "amount": {
    "value": "5450.00",
    "currency": "RUB"
  },
  "confirmation": {
    "type": "redirect",
    "confirmation_url": "https://yoomoney.ru/checkout/payments/v2/contract?orderId=313bd040-000f-5000-8000-1671ab4ed7d7"
  },
  "created_at": "2026-03-05T17:25:20.285Z",
  "description": "Оплата для Шубин ОМ",
  "metadata": {
    "cms_name": "yookassa_sdk_python"
  },
  "paid": false,
  "recipient": {
    "account_id": "1290955",
    "gateway_id": "2665921"
  },
  "refundable": false,
  "test": true
}
```

---

## 4. Frontend: Варианты интеграции оплаты

### 4.1 Вариант A: Redirect (рекомендуемый, проверен)

Самый простой и надёжный. Пользователь уходит на страницу YooKassa, вводит карту там.

**Бэкенд:**
```python
# После создания платежа — отдать URL фронтенду
confirmation_url = payment.confirmation.confirmation_url
# "https://yoomoney.ru/checkout/payments/v2/contract?orderId=..."
```

**Фронтенд (JavaScript):**
```javascript
// После получения confirmation_url от бэкенда
window.location.href = confirmationUrl;
```

**Что видит пользователь на checkout-странице YooKassa:**
1. Сумма платежа и описание
2. Выбор способа оплаты: YooMoney кошелёк или "New card"
3. При выборе карты — поля: Card number, Expiration date (MM/YY), CVC
4. Кнопка "Pay {сумма}₽"
5. 3D Secure (если требуется): страница банка с полем "Any number" + "Confirm"
6. Страница успеха с кнопкой "Back to the website" (ведёт на return_url)

### 4.2 Вариант B: Embedded виджет (checkout.js)

Платёжная форма встраивается прямо в страницу магазина.

**HTML:**
```html
<div id="payment-form"></div>
<script src="https://yookassa.ru/checkout-widget/v1/checkout-widget.js"></script>
<script>
const checkout = new window.YooMoneyCheckoutWidget({
    confirmation_token: '<confirmation_token>', // получить от бэкенда
    return_url: 'https://your-shop.ru/payment/result',
    error_callback: function(error) {
        console.error('Payment error:', error);
    }
});
checkout.render('payment-form');
</script>
```

**Бэкенд для embedded:**
```python
payment_data = {
    "amount": {"value": "5450.00", "currency": "RUB"},
    "capture": True,
    "confirmation": {
        "type": "embedded"  # вместо "redirect"
    },
    "receipt": { ... }
}
payment = Payment.create(payment_data, idempotence_key)
# payment.confirmation.confirmation_token — передать на фронтенд
```

### 4.3 Вариант C: Собственная платёжная форма (требует PCI DSS)

Только для компаний с сертификатом PCI DSS. Карточные данные собираются на вашей стороне. **Не рекомендуется** для большинства магазинов.

---

## 5. Backend: Отслеживание статуса платежа

### 5.1 Поллинг (проверен, работает)

```python
import time
from yookassa import Payment

def wait_for_payment(payment_id: str, timeout: int = 300):
    """Поллит статус каждые 3 секунды."""
    start = time.time()
    while time.time() - start < timeout:
        payment = Payment.find_one(payment_id)
        if payment.status in ("succeeded", "canceled"):
            return payment
        time.sleep(3)
    return Payment.find_one(payment_id)
```

**Из реальных тестов:** платёж переходит в `succeeded` через 40-80 секунд после оплаты.

### 5.2 Webhooks (рекомендуется для продакшена)

Для веб-приложения с публичным URL webhook'и — правильный подход:

1. В личном кабинете YooKassa настроить URL для уведомлений
2. YooKassa отправит POST-запрос на ваш URL при изменении статуса

**Flask-пример обработки webhook:**
```python
from flask import Flask, request, jsonify
import hmac
import hashlib

app = Flask(__name__)

@app.route('/yookassa/webhook', methods=['POST'])
def yookassa_webhook():
    data = request.json
    event = data.get('event')          # "payment.succeeded", "payment.canceled", etc.
    payment = data.get('object')

    if event == 'payment.succeeded':
        payment_id = payment['id']
        amount = payment['amount']['value']
        # Обновить статус заказа в БД
        order = Order.query.filter_by(payment_id=payment_id).first()
        if order:
            order.status = 'paid'
            order.paid_at = datetime.utcnow()
            db.session.commit()

    elif event == 'payment.canceled':
        payment_id = payment['id']
        reason = payment.get('cancellation_details', {}).get('reason', 'unknown')
        # Отменить заказ
        ...

    return jsonify({"status": "ok"}), 200
```

**Типы событий:**
- `payment.waiting_for_capture` — авторизован (двухэтапная)
- `payment.succeeded` — оплачен
- `payment.canceled` — отменён
- `refund.succeeded` — возврат выполнен

### 5.3 Return URL (callback из браузера)

После оплаты браузер пользователя перенаправляется на `return_url`. Это НЕ подтверждение оплаты, а просто редирект. **Всегда проверяйте статус через API или webhook.**

```python
@app.route('/payment/callback')
def payment_callback():
    # Не доверяйте параметрам URL — проверяйте через API
    order_id = request.args.get('order_id')
    order = Order.query.get(order_id)

    payment = Payment.find_one(order.payment_id)

    if payment.status == 'succeeded':
        return render_template('payment_success.html', order=order)
    elif payment.status == 'canceled':
        return render_template('payment_failed.html', order=order,
                             reason=payment.cancellation_details.reason)
    else:
        return render_template('payment_pending.html', order=order)
```

---

## 6. Параметры чека (54-ФЗ)

### 6.1 Обязательные поля

| Поле                                  | Тип            | Описание                    |
| ------------------------------------- | -------------- | --------------------------- |
| `receipt.customer.email` или `.phone` | string         | Хотя бы одно обязательно    |
| `receipt.items[].description`         | string (1-128) | Название товара             |
| `receipt.items[].quantity`            | string         | Количество                  |
| `receipt.items[].amount.value`        | string         | Цена за ЕДИНИЦУ (не итого!) |
| `receipt.items[].amount.currency`     | string         | `"RUB"`                     |
| `receipt.items[].vat_code`            | int            | Код НДС                     |

### 6.2 Коды НДС (vat_code)

| Код | Ставка  | Примечание                    |
| --- | ------- | ----------------------------- |
| 1   | Без НДС |                               |
| 2   | 0%      |                               |
| 3   | 10%     |                               |
| 4   | 20%     |                               |
| 5   | 10/110  | Расчётная                     |
| 6   | 20/120  | Расчётная                     |
| 7   | 5%      | С 01.01.2025                  |
| 8   | 7%      | С 01.01.2025                  |
| 11  | **22%** | **С 01.01.2026 (используем)** |
| 12  | 22/122  | Расчётная, с 01.01.2026       |

### 6.3 Системы налогообложения (tax_system_code)

| Код | Система                      |
| --- | ---------------------------- |
| 1   | **ОСН (общая) — используем** |
| 2   | УСН (доходы)                 |
| 3   | УСН (доходы - расходы)       |
| 5   | ЕСХН                         |
| 6   | Патент                       |

### 6.4 Предметы расчёта (payment_subject)

| Значение    | Описание               |
| ----------- | ---------------------- |
| `commodity` | **Товар (используем)** |
| `excise`    | Подакцизный товар      |
| `job`       | Работа                 |
| `service`   | Услуга                 |
| `payment`   | Платёж                 |
| `another`   | Иное                   |

### 6.5 Способы расчёта (payment_mode)

| Значение             | Описание                       |
| -------------------- | ------------------------------ |
| `full_prepayment`    | Полная предоплата              |
| `partial_prepayment` | Частичная предоплата           |
| `advance`            | Аванс                          |
| `full_payment`       | **Полный расчёт (используем)** |
| `partial_payment`    | Частичный расчёт               |
| `credit`             | Кредит                         |
| `credit_payment`     | Оплата кредита                 |

---

## 7. Критичные нюансы (подводные камни из реального опыта)

### 7.1 amount в items — это цена за ЕДИНИЦУ

```python
# НЕПРАВИЛЬНО — вернёт 400 Bad Request:
"quantity": "2",
"amount": {"value": "9000.00"}   # 4500 * 2 = итого

# ПРАВИЛЬНО:
"quantity": "2",
"amount": {"value": "4500.00"}   # цена за штуку
```

API сам умножает `amount.value * quantity` и проверяет, что сумма всех позиций = общей сумме платежа.

### 7.2 Все числовые значения — строки

```python
# НЕПРАВИЛЬНО:
"value": 5450.00
"quantity": 2

# ПРАВИЛЬНО:
"value": "5450.00"
"quantity": "2"
```

### 7.3 Idempotence-Key обязателен

Каждый POST-запрос **должен** содержать уникальный `Idempotence-Key`. Без него API вернёт ошибку. UUID v4 — идеальный вариант.

```python
import uuid
idempotence_key = str(uuid.uuid4())
```

Если повторить запрос с тем же ключом в течение 24 часов — вернётся тот же результат (защита от дублей).

### 7.4 Сумма items должна совпадать с amount платежа

```
sum(item.amount.value * item.quantity for item in items) == payment.amount.value
```

Если не совпадает — API вернёт ошибку.

### 7.5 Windows и кодировка

На Windows при работе с русским текстом через Python нужно явно выставлять UTF-8:

```python
import io, sys
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
```

### 7.6 3D Secure обрабатывается автоматически

При использовании `confirmation.type: "redirect"` — YooKassa сама перенаправит пользователя на 3D Secure, если карта этого требует. Бэкенд ничего дополнительно не делает.

---

## 8. Тестовые карты

| Номер                 | Поведение                        | 3D Secure |
| --------------------- | -------------------------------- | --------- |
| `5555 5555 5555 4444` | Успешная оплата                  | Нет       |
| `5555 5555 5555 4477` | **Успешная оплата (используем)** | **Да**    |
| `5555 5555 5555 4002` | Отказ оплаты                     | Нет       |
| `5555 5555 5555 4010` | Отказ оплаты                     | Да        |

- Любой будущий срок действия (например, `05/30`)
- Любой CVC (например, `111`)
- На странице 3D Secure — любой код (например, `123456`)

---

## 9. Полезные API-эндпоинты

### 9.1 Получение платежа

```python
payment = Payment.find_one("313bd040-000f-5000-8000-1671ab4ed7d7")
# payment.status, payment.amount, payment.payment_method, etc.
```

**cURL:**
```bash
curl https://api.yookassa.ru/v3/payments/{payment_id} \
  -u 1290955:test_Veshzf2S4ksgtkRdq7y_534YDVI47b5IqhzQ-xRXuDs
```

### 9.2 Список платежей

```python
from yookassa import Payment

payments = Payment.list({
    "created_at.gte": "2026-03-01T00:00:00.000Z",
    "status": "succeeded",
    "limit": 10
})
```

### 9.3 Возврат платежа

```python
from yookassa import Refund
import uuid

refund = Refund.create({
    "payment_id": "313bd040-000f-5000-8000-1671ab4ed7d7",
    "amount": {
        "value": "1200.00",
        "currency": "RUB"
    },
    "receipt": {
        "customer": {
            "full_name": "Шубин ОМ",
            "email": "olegshubin@gmail.com"
        },
        "items": [
            {
                "description": "Молочный Улун 550096",
                "quantity": "1",
                "amount": {
                    "value": "1200.00",
                    "currency": "RUB"
                },
                "vat_code": 11,
                "payment_mode": "full_payment",
                "payment_subject": "commodity"
            }
        ],
        "tax_system_code": 1
    }
}, str(uuid.uuid4()))
```

### 9.4 Capture (для двухэтапной оплаты)

```python
payment = Payment.capture("payment_id", {
    "amount": {"value": "5450.00", "currency": "RUB"}
}, str(uuid.uuid4()))
```

### 9.5 Отмена платежа

```python
payment = Payment.cancel("payment_id", str(uuid.uuid4()))
```

---

## 10. Рекомендуемая архитектура для интернет-магазина

### 10.1 Модели данных (Django/SQLAlchemy)

```python
class Order:
    id: int
    customer_name: str
    customer_phone: str
    customer_email: str
    total_amount: Decimal
    status: str           # "draft", "pending_payment", "paid", "canceled", "refunded"
    payment_id: str       # YooKassa payment ID
    payment_url: str      # confirmation_url (для повторного перехода)
    created_at: datetime
    paid_at: datetime

class OrderItem:
    id: int
    order_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    vat_code: int         # 11 для НДС 22%
```

### 10.2 Бэкенд-флоу

```python
# 1. Создать заказ в БД со статусом "draft"
order = Order.create(cart_items, customer)

# 2. Собрать items для чека
receipt_items = []
for item in order.items:
    receipt_items.append({
        "description": item.product_name[:128],  # макс 128 символов!
        "quantity": str(item.quantity),
        "amount": {
            "value": f"{item.unit_price:.2f}",
            "currency": "RUB"
        },
        "vat_code": 11,
        "payment_mode": "full_payment",
        "payment_subject": "commodity"
    })

# 3. Создать платёж
payment = Payment.create({
    "amount": {"value": f"{order.total_amount:.2f}", "currency": "RUB"},
    "capture": True,
    "confirmation": {
        "type": "redirect",
        "return_url": f"https://your-shop.ru/orders/{order.id}/payment-result"
    },
    "receipt": {
        "customer": {
            "full_name": order.customer_name,
            "phone": order.customer_phone,
            "email": order.customer_email,
        },
        "items": receipt_items,
        "tax_system_code": 1,
    },
    "description": f"Заказ #{order.id}",
    "metadata": {"order_id": str(order.id)},  # для обратной связи в webhook
}, str(uuid.uuid4()))

# 4. Сохранить payment_id, обновить статус
order.payment_id = payment.id
order.payment_url = payment.confirmation.confirmation_url
order.status = "pending_payment"
db.commit()

# 5. Отдать URL фронтенду
return {"redirect_url": payment.confirmation.confirmation_url}
```

### 10.3 Фронтенд-флоу

```javascript
// Страница корзины / оформления заказа
async function checkout() {
    // 1. Отправить заказ на бэкенд
    const response = await fetch('/api/orders', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            customer: { name, phone, email },
            items: cartItems
        })
    });
    const { redirect_url } = await response.json();

    // 2. Перенаправить на YooKassa
    window.location.href = redirect_url;
}

// Страница результата (return_url)
// /orders/{order_id}/payment-result
async function checkPaymentResult() {
    const response = await fetch(`/api/orders/${orderId}/status`);
    const { status, payment } = await response.json();

    if (status === 'paid') {
        showSuccess(payment);
    } else if (status === 'canceled') {
        showError(payment.cancellation_reason);
    } else {
        // Ещё обрабатывается — поллить
        setTimeout(checkPaymentResult, 3000);
    }
}
```

---

## 11. Ссылки

- API документация: https://yookassa.ru/developers/api
- Python SDK: https://github.com/yoomoney/yookassa-sdk-python
- Тестирование: https://yookassa.ru/developers/payment-acceptance/testing-and-going-live/testing
- OpenAPI спецификация: https://yookassa.ru/developers/using-api/openapi-specification
- Чеки 54-ФЗ: https://yookassa.ru/developers/payment-acceptance/receipts/54fz
- Checkout виджет: https://yookassa.ru/developers/payment-acceptance/integration-scenarios/widget

---

## 12. Чеклист перед запуском в продакшен

- [ ] Заменить тестовые `shop_id` и `api_key` на боевые
- [ ] Настроить webhook URL в личном кабинете YooKassa
- [ ] Заменить `return_url` с localhost на реальный домен
- [ ] Убедиться, что `description` в items не превышает 128 символов
- [ ] Проверить, что сумма items совпадает с общей суммой платежа
- [ ] Настроить HTTPS для webhook-эндпоинта (обязательно для продакшена)
- [ ] Добавить обработку ошибок и повторных попыток
- [ ] Логировать все платёжные операции
- [ ] Тестировать с картами: успех (4477), отказ (4002), 3DS отказ (4010)
- [ ] Настроить правильный `tax_system_code` и `vat_code` для вашей организации
