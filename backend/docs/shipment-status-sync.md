# Синхронизация статусов заказов с провайдерами доставки

## Обзор

Система автоматически отслеживает статусы заказов в 5Post и Magnit через периодический опрос их API (polling). При изменении статуса у провайдера — обновляет Shipment и Order в нашей БД, отправляет уведомления клиенту по email.

## Архитектура

```
                    ┌──────────────┐
                    │   Worker     │
                    │  (scheduler) │
                    └──────┬───────┘
                           │ каждые N минут
                           ▼
              ┌────────────────────────┐
              │  poll_shipment_statuses │
              │  (Redis lock защита)    │
              └─────┬──────────┬───────┘
                    │          │
          ┌─────────▼──┐  ┌───▼──────────┐
          │  5Post API  │  │  Magnit API   │
          │  GET status │  │  GET status   │
          └─────────┬──┘  └───┬──────────┘
                    │          │
                    ▼          ▼
         ┌──────────────────────────┐
         │  Shipment (обновление)   │
         │  ShipmentStatusHistory   │
         └────────────┬─────────────┘
                      │ если ключевой статус
                      ▼
         ┌──────────────────────────┐
         │  Order (state machine)   │
         │  → event dispatch        │
         │  → email клиенту         │
         └──────────────────────────┘
```

## Конфигурация (.env)

```env
# Интервал опроса в минутах (по умолчанию 30)
FIVEPOST_POLL_INTERVAL_MINUTES=30
MAGNIT_POLL_INTERVAL_MINUTES=30
```

## Таблицы БД

### Shipment

Таблица `shipments`. Создаётся автоматически когда заказ переходит в статус `shipped` (через очередь `shipment:pending` в Redis). Связь с Order — один к одному.

| Поле                    | Тип                | Описание                                                                  |
|-------------------------|--------------------|---------------------------------------------------------------------------|
| `id`                    | UUID               | Первичный ключ                                                            |
| `order_id`              | UUID (FK → orders) | Ссылка на заказ                                                           |
| `provider`              | string             | `"5post"` или `"magnit"`                                                  |
| `provider_shipment_id`  | string             | ID заказа в системе провайдера (UUID от 5Post, tracking_number от Magnit) |
| `provider_order_number` | string             | Номер заказа у провайдера                                                 |
| `status`                | string             | Текущий ShipmentStatus (см. enum ниже)                                    |
| `tracking_number`       | string             | Трекинг-номер для отслеживания                                            |
| `parcel_size`           | string             | Размер посылки: `S`, `M`, `L`                                             |
| `weight_grams`          | int                | Вес посылки в граммах                                                     |
| `label_url`             | string             | URL PDF-этикетки                                                          |
| `created_at`            | timestamp          | Дата создания записи                                                      |
| `updated_at`            | timestamp          | Дата последнего обновления                                                |

**Жизненный цикл Shipment:**
1. Order переходит в `shipped` → event handler ставит задачу в Redis-очередь `shipment:pending`
2. Worker (каждые 10 сек) берёт задачу → вызывает API провайдера → создаёт запись Shipment
3. Поллер (каждые 30 мин) проверяет статус у провайдера → обновляет `status`
4. При достижении терминального статуса (`issued`, `returned`, `cancelled`, `lost`) — больше не опрашивается

### ShipmentStatusHistory

Таблица `shipment_status_history`. Аудит-лог: каждое изменение статуса отправления записывается отдельной строкой. Используется для отладки, отчётности и разрешения споров.

| Поле              | Тип                   | Описание                                                                             |
|-------------------|-----------------------|--------------------------------------------------------------------------------------|
| `id`              | UUID                  | Первичный ключ                                                                       |
| `shipment_id`     | UUID (FK → shipments) | Ссылка на отправление                                                                |
| `status`          | string                | Наш внутренний ShipmentStatus                                                        |
| `provider_status` | string                | Оригинальный статус от провайдера (например `ACCEPTED_AT_POINT`, `READY_FOR_PICKUP`) |
| `provider_data`   | JSONB                 | Полный сырой ответ API провайдера (для отладки)                                      |
| `occurred_at`     | timestamp             | Когда произошло изменение                                                            |

**Пример записей для одного заказа:**
```
shipment_id=abc123  status=created          provider_status=NEW                occurred_at=2026-03-17 10:00
shipment_id=abc123  status=in_transit       provider_status=DELIVERING_STARTED occurred_at=2026-03-17 14:30
shipment_id=abc123  status=ready_for_pickup provider_status=ACCEPTED_AT_POINT  occurred_at=2026-03-19 09:15
shipment_id=abc123  status=issued           provider_status=ISSUED             occurred_at=2026-03-20 16:42
```

### Enum: ShipmentStatus

```python
class ShipmentStatus(StrEnum):
    CREATED = "created"            # Создан у провайдера
    ACCEPTED = "accepted"          # Принят на обработку
    IN_TRANSIT = "in_transit"      # В пути
    ARRIVED = "arrived"            # Прибыл в ПВЗ (приёмка)
    READY_FOR_PICKUP = "ready_for_pickup"  # Готов к выдаче клиенту
    ISSUED = "issued"              # Выдан клиенту (терминальный)
    RETURNING = "returning"        # Возвращается отправителю
    RETURNED = "returned"          # Возвращён (терминальный)
    CANCELLED = "cancelled"        # Отменён (терминальный)
    LOST = "lost"                  # Утерян (терминальный)
```

### Enum: OrderStatus

```python
class OrderStatus(StrEnum):
    DRAFT = "draft"                                          # Черновик (не используется)
    PENDING_PAYMENT = "pending_payment"                      # Ожидает оплаты (PREPAID заказы)
    PAID = "paid"                                            # Оплачен картой на сайте
    PENDING_CONFIRMATION = "pending_confirmation"            # Ожидает подтверждения клиентом (COD заказы)
    CONFIRMED_BY_CLIENT = "confirmed_by_client"              # Клиент подтвердил COD, ждёт подтверждения магазина
    CONFIRMED = "confirmed"                                  # Подтверждён магазином, готов к отправке
    SHIPPED = "shipped"                                      # Отправлен в службу доставки
    READY_FOR_PICKUP = "ready_for_pickup"                    # Прибыл в ПВЗ, ждёт клиента
    DELIVERED = "delivered"                                  # Доставлен, клиент забрал (финальный)
    CANCELLED = "cancelled"                                  # Отменён (финальный)
    CLIENT_DONT_PICKUP = "client_dont_pickup"                # Клиент не забрал, возвращается
    RETURNED_TO_SUPPLIER = "returned_to_supplier"            # Возвращён нам (финальный)
    REFUNDED = "refunded"                                    # Деньги возвращены клиенту (финальный)
```

**Жизненный цикл Order (PREPAID — оплата картой):**
```
PENDING_PAYMENT → PAID → CONFIRMED → SHIPPED → READY_FOR_PICKUP → DELIVERED
                                        │
                                        └→ CLIENT_DONT_PICKUP → RETURNED_TO_SUPPLIER
```

**Жизненный цикл Order (CODFLOW — наложенный платёж):**
```
PENDING_CONFIRMATION → CONFIRMED_BY_CLIENT → CONFIRMED → SHIPPED → READY_FOR_PICKUP → DELIVERED
                                                            │
                                                            └→ CLIENT_DONT_PICKUP → RETURNED_TO_SUPPLIER
```

**Что меняется автоматически, что вручную:**
- `PENDING_PAYMENT → PAID` — автоматически (webhook YooKassa или check-payment)
- `PENDING_CONFIRMATION → CONFIRMED_BY_CLIENT` — клиент подтверждает через сайт
- `CONFIRMED_BY_CLIENT → CONFIRMED` — магазин подтверждает (админ)
- `CONFIRMED → SHIPPED` — админ вручную
- `SHIPPED → READY_FOR_PICKUP` — **автоматически (поллер)** при получении статуса от провайдера
- `READY_FOR_PICKUP → DELIVERED` — **автоматически (поллер)** при выдаче клиенту
- `→ CLIENT_DONT_PICKUP` — **автоматически (поллер)** если клиент не забрал
- `→ RETURNED_TO_SUPPLIER` — **автоматически (поллер)** при возврате
- `→ CANCELLED` — админ или автоотмена (неоплаченные PREPAID через 30 мин)

### Связь таблиц

```
orders (1) ──── (1) shipments (1) ──── (N) shipment_status_history
  │                    │
  │ order_id           │ shipment_id
  │                    │
  └─ status            └─ status (текущий)
     (OrderStatus)        (ShipmentStatus)

```

### Сейчас клиентам на странице статуса заказа отображаются статусы из таблицы orders поле status. Текуще сопоставление систеного статуса и лейбла для клинета:

```
"draft":                 "Черновик",
"pending_payment":       "Ожидает оплаты",
"paid":                  "Оплачен",
"pending_confirmation":  "Ожидает подтверждения клиента",
"confirmed_by_client":   "Подтверждён клиентом, ожидает подтверждения магазина",
"confirmed":             "Подтвержден",
"shipped":               "Отправлен",
"ready_for_pickup":      "Ожидает в пункте выдачи",
"delivered":             "Доставлен",
"cancelled":             "Отменён",
"client_dont_pickup":    "Клиент не забрал посылку",
"returned_to_supplier":  "Возвращен в магазин",
"refunded":              "Возврат средств",
```


Модели определены в:
- `packages/models/shipment.py` — Shipment, ShipmentStatusHistory
- `packages/models/order.py` — Order

## Файлы

| Файл                                         | Назначение                                               |
|----------------------------------------------|----------------------------------------------------------|
| `apps/worker/jobs/poll_shipment_statuses.py` | Основной поллер (5Post + Magnit)                         |
| `apps/worker/scheduler.py`                   | Расписание (IntervalTrigger)                             |
| `packages/integrations/fivepost/utils.py`    | Маппинг статусов 5Post → ShipmentStatus                  |
| `packages/integrations/magnit/utils.py`      | Маппинг статусов Magnit → ShipmentStatus                 |
| `packages/services/checkout/__init__.py`     | `update_order_status()` — state machine + event dispatch |

## Как работает поллинг

1. **Scheduler** запускает `poll_fivepost_statuses()` / `poll_magnit_statuses()` каждые N минут
2. **Redis lock** (`poll_lock:{provider}`, TTL 1 час) предотвращает наложение циклов — если предыдущий ещё работает, новый пропускается
3. **Загрузка активных shipments** — все записи Shipment, где `status` не в терминальных (`issued`, `returned`, `cancelled`, `lost`)
4. **Rate limiting** — между каждым запросом к API провайдера пауза 2 секунды (max 30 запросов/минуту)
5. **Запрос статуса** у провайдера:
   - 5Post: `GET /api/v1/orders/{order_id}/status`
   - Magnit: `GET /api/v1/magnit-post/orders/{order_id}`
6. **Маппинг** провайдерского статуса на внутренний `ShipmentStatus`
7. **Обновление Shipment** + запись в `ShipmentStatusHistory`
8. **Обновление Order** через state machine (если применимо) → триггер email

## Маппинг статусов: провайдер → Shipment → Order

### 5Post

**Примечание:** 5Post возвращает `execution_status` как `statusCode`. Наш поллер маппит именно его.

| 5Post execution_status                    | Описание                  | → ShipmentStatus   | → OrderStatus              |
|-------------------------------------------|---------------------------|--------------------|-----------------------------|
| `CREATED`                                 | Заказ создан              | `created`          | — (остаётся `shipped`)      |
| `APPROVED`                                | Подтверждён               | `created`          | —                           |
| `RECEIVED_IN_WAREHOUSE_IN_DETAILS`        | Принят на складе          | `accepted`         | —                           |
| `SORTED_IN_WAREHOUSE`                     | Отсортирован              | `in_transit`       | —                           |
| `COMPLECTED_IN_WAREHOUSE`                 | Скомплектован             | `in_transit`       | —                           |
| `READY_TO_BE_SHIPPED_FROM_WAREHOUSE`      | Готов к отправке          | `in_transit`       | —                           |
| `SHIPPED`                                 | Отправлен                 | `in_transit`       | —                           |
| `RECEIVED_IN_STORE`                       | Принят в магазине         | `arrived`          | —                           |
| `PLACED_IN_POSTAMAT`                      | Помещён в постамат        | `ready_for_pickup` | **`ready_for_pickup`**      |
| `PICKED_UP`                               | Клиент забрал             | `issued`           | **`delivered`**             |
| `READY_FOR_WITHDRAW_FROM_PICKUP_POINT`    | Клиент не забрал, возврат | `returning`        | **`client_dont_pickup`**    |
| `WITHDRAWN_FROM_PICKUP_POINT`             | Изъят из ПВЗ              | `returning`        | **`client_dont_pickup`**    |
| `RETURNED_TO_PARTNER`                     | Возвращён нам             | `returned`         | **`returned_to_supplier`**  |
| `CANCELLED`                               | Отменён                   | `cancelled`        | — (ручное решение)          |
| `LOST`                                    | Утерян                    | `lost`             | — (ручное решение)          |

### 5Post Happy Path
```
NEW/CREATED → APPROVED → RECEIVED_IN_WAREHOUSE → SORTED → COMPLECTED →
→ READY_TO_BE_SHIPPED → SHIPPED → RECEIVED_IN_STORE → PLACED_IN_POSTAMAT → PICKED_UP
     (created)              (accepted)         (in_transit)          (ready_for_pickup)  (issued/delivered)
```

### 5Post Unclaimed Path (клиент не забрал)
```
PLACED_IN_POSTAMAT → READY_FOR_WITHDRAW → WITHDRAWN_FROM_PICKUP_POINT → RETURNED_TO_PARTNER
  (ready_for_pickup)    (returning/client_dont_pickup)                      (returned/returned_to_supplier)
```





### Magnit

| Magnit статус                  | Описание           | → ShipmentStatus   | → OrderStatus              | Email                       |
|--------------------------------|--------------------|--------------------|----------------------------|-----------------------------|
| `NEW`                          | Заказ создан       | `created`          | — (остаётся `shipped`)     | —                           |
| `CREATED`                      | Принят системой    | `created`          | —                          | —                           |
| `DELIVERING_STARTED`           | Доставка начата    | `in_transit`       | —                          | —                           |
| `ACCEPTED_AT_POINT`            | Принят в магазине  | `ready_for_pickup` | **`ready_for_pickup`**     | "Ожидает в магазине Магнит" |
| `IN_COURIER_DELIVERY`          | Курьер в пути      | `in_transit`       | —                          | —                           |
| `ISSUED`                       | Выдан клиенту      | `issued`           | **`delivered`**            | "Заказ получен"             |
| `WAITING_RETURN`               | Ожидает возврата   | `returning`        | **`client_dont_pickup`**   | Уведомление админу          |
| `RETURN_INITIATED`             | Возврат запущен    | `returning`        | **`client_dont_pickup`**   | Уведомление админу          |
| `RETURN_SEND_TO_WAREHOUSE`     | Возврат в пути     | `returning`        | **`client_dont_pickup`**   | Уведомление админу          |
| `RETURN_ACCEPTED_AT_WAREHOUSE` | Возврат на складе  | `returned`         | **`returned_to_supplier`** | Уведомление админу          |
| `RETURNED_TO_PROVIDER`         | Возвращён нам      | `returned`         | **`returned_to_supplier`** | Уведомление админу          |
| `CANCELED_BY_PROVIDER`         | Отменён нами       | `cancelled`        | — (ручное решение)         | —                           |
| `DESTROYED`                    | Уничтожен          | `returned`         | — (ручное решение)         | —                           |
| `ACCEPTED_AT_WAREHOUSE`        | На складе          | `accepted`         | —                          | —                           |
| `ACCEPTED_AT_CUSTOMS`          | На таможне         | `in_transit`       | —                          | —                           |
| `POSSIBLY_DEFECTED`            | Возможно повреждён | — (не маппится)    | — (ручное решение)         | —                           |
| `DEFECTED`                     | Повреждён          | — (не маппится)    | — (ручное решение)         | —                           |
| `REMOVED`                      | Удалён             | `cancelled`        | — (ручное решение)         | —                           |

### Magnit Нормальная доставка (5-10 дней)
```
NEW → CREATED → DELIVERING_STARTED → ACCEPTED_AT_POINT → ISSUED
 │       │              │                    │               │
 │       │              │                    │               └─ Клиент забрал в магазине - delivered
 │       │              │                    └─ Привезли в магазин Магнит, лежит на кассе - ready_for_pickup
 │       │              └─ Посылка едет со склада в магазин - (остаётся shipped)
 │       └─ Система приняла заказ - (остаётся shipped)
 └─ Мы создали через API - (остаётся shipped)
```
### Magnit Возврат (клиент не забрал)
```
ACCEPTED_AT_POINT - (остаётся shipped) → WAITING_RETURN - client_dont_pickup → RETURN_INITIATED - client_dont_pickup → 
RETURN_SEND_TO_WAREHOUSE - client_dont_pickup → RETURN_ACCEPTED_AT_WAREHOUSE - returned_to_supplier → 
RETURNED_TO_PROVIDER - returned_to_supplier
```




### Автоматическое обновление Order (сводка)

| ShipmentStatus     | → OrderStatus          | Письмо клиенту                                       |
|--------------------|------------------------|------------------------------------------------------|
| `ready_for_pickup` | `ready_for_pickup`     | "Ожидает вас в пункте выдачи"                        |
| `issued`           | `delivered`            | "Заказ получен"                                      |
| `returning`        | `client_dont_pickup`   | "Заказ не забран, возвращается" + уведомление админу |
| `returned`         | `returned_to_supplier` | Уведомление админу                                   |

### Статусы, при которых Order НЕ обновляется автоматически

Если Order уже в одном из этих статусов, автообновление пропускается:
- `delivered` — уже финальный
- `cancelled` — отменён
- `returned_to_supplier` — уже возвращён
- `refunded` — деньги возвращены

## Auto-advance: обработка пропущенных промежуточных статусов

Поллер проверяет статус у провайдера только текущий (не историю). Если между двумя циклами поллера провайдер прошёл несколько статусов (например: `PLACED_IN_POSTAMAT` → `PICKED_UP` за 5 минут), поллер увидит сразу финальный статус.

**Проблема:** State machine запрещает прямой переход `shipped → delivered` (требуется промежуточный `ready_for_pickup`).

**Решение:** Функция `_auto_advance_order()` автоматически проходит через промежуточные статусы:

### Цепочка доставки (happy path):
```
shipped → ready_for_pickup → delivered
```
Если поллер видит `PICKED_UP` (→ `delivered`), а заказ в `shipped`, он автоматически пройдёт:
1. `shipped → ready_for_pickup` (промежуточный)
2. `ready_for_pickup → delivered` (целевой)

### Цепочка возврата (unclaimed path):
```
shipped → ready_for_pickup → client_dont_pickup → returned_to_supplier
```
Если поллер видит `RETURNING` (→ `client_dont_pickup`), а заказ в `shipped`, он пройдёт:
1. `shipped → ready_for_pickup` (промежуточный)
2. `ready_for_pickup → client_dont_pickup` (целевой)

Каждый промежуточный шаг:
- Проходит через state machine (валидация)
- Создаёт запись в `order_events`
- Триггерит email (event dispatch)

**Файл:** `apps/worker/jobs/poll_shipment_statuses.py` → `_auto_advance_order()`

## Защита от проблем

### Наложение циклов
Redis lock `poll_lock:{provider}` с TTL 1 час. Если предыдущий цикл ещё работает — новый пропускается с логом `poll_skipped_lock_held`.

### Rate limiting
Пауза 2 секунды между запросами. При 1000 заказов = ~33 минуты. Следующий цикл подождёт (lock).

### Ошибки API провайдера
Ошибка при проверке одного заказа не останавливает проверку остальных. Логируется `poll_shipment_error`.

### State machine rejection
Если state machine не позволяет переход (например Order уже в `cancelled`), логируется `order_status_auto_update_rejected`, но shipment всё равно обновляется.

### Пропуск промежуточных статусов
Обрабатывается `_auto_advance_order()` — автоматически проходит через все нужные промежуточные статусы. Если текущий статус заказа не в цепочке — логируется warning и transition пропускается.

## Терминальные статусы Shipment (не опрашиваются)

- `issued` — выдан клиенту
- `returned` — возвращён отправителю
- `cancelled` — отменён
- `lost` — утерян

## Масштабирование

При росте до 1000+ активных заказов:
1. **Magnit** — использовать батчевый `POST /api/v1/magnit-post/order-statuses` (массив ID за один запрос)
2. **5Post** — приоритизация: сначала свежие заказы, потом старые
3. **5Post webhooks** — эндпоинт `/api/v3/webhooks` существует, но требует подключения через менеджера (сейчас 403). При наличии — push вместо polling

## Логи

Логи поллера маршрутизируются по имени logger `worker.poll_statuses`:
- `poll_fivepost_started` / `poll_fivepost_completed`
- `poll_magnit_started` / `poll_magnit_completed`
- `shipment_status_changed` — при обнаружении изменения
- `order_status_auto_updated` — при обновлении Order (включая промежуточные шаги, поле `intermediate=True/False`)
- `order_status_auto_update_rejected` — state machine отклонил переход
- `poll_skipped_lock_held` — пропуск из-за lock
- `poll_shipment_error` — ошибка при проверке конкретного заказа
