# Magnit Post - Спецификация интеграции службы доставки

> Этот документ содержит полную техническую спецификацию для интеграции с Magnit Post (доставка в ПВЗ сети "Магнит") в интернет-магазине. Используй его как единственный источник истины при разработке фронтенда и бэкенда.

---

## 1. Общее описание

**Magnit Post** - служба доставки товаров из интернет-магазинов в пункты выдачи заказов (ПВЗ), расположенные в магазинах сети "Магнит" по всей России. Покупатель выбирает ПВЗ при оформлении заказа, товар доставляется туда, покупатель забирает.

### Ключевые характеристики

| Параметр                   | Значение                                                            |
| -------------------------- | ------------------------------------------------------------------- |
| Тип доставки               | Только в ПВЗ (не курьерская)                                        |
| Сеть ПВЗ                   | Магазины "Магнит Косметик" и аналогичные                            |
| География                  | ~350 городов РФ, ~5000 ПВЗ                                          |
| Оплата при получении (COD) | **НЕ поддерживается** (планируется). Только предоплата              |
| Размеры посылок            | S (25x15x10 см), M (35x25x15 см), L (45x30x20 см)                   |
| Стоимость для покупателя   | 150 руб без НДС, НДС 22% = **183 руб** с НДС                        |
| Возврат невостребованных   | На склад отправителя                                                |
| API                        | REST JSON, OAuth2 client_credentials                                |
| Среда                      | UAT: `b2b-api-gateway.uat.ya.magnit.ru` / Prod: `b2b-api.magnit.ru` |

---

## 2. Аутентификация (OAuth2)

### Получение токена

```
POST {base_url}/api/v2/oauth/token
Content-Type: application/x-www-form-urlencoded

client_id=<CLIENT_ID>
client_secret=<CLIENT_SECRET>
scope=openid magnit-post:orders magnit-post:pickup-points
grant_type=client_credentials
```

### Ответ

```json
{
  "access_token": "eyJhbGciOi...",
  "expires_in": 3600,
  "token_type": "Bearer",
  "scope": "openid magnit-post:orders magnit-post:pickup-points"
}
```

### Правила работы с токеном

- Токен живёт ~3600 секунд (1 час)
- **ОБЯЗАТЕЛЬНО кэшировать** токен и обновлять за 60 сек до истечения
- Все запросы к API — с заголовком `Authorization: Bearer <token>`
- При 401 — перезапросить токен

### Учётные данные

```
base_url:      https://b2b-api-gateway.uat.ya.magnit.ru
client_id:     a3fc5459-781c-47e8-b9c9-b9d6622053ae
client_secret: a6psDoI7cukJRCIG0vHx
scope:         openid magnit-post:orders magnit-post:pickup-points
```

---

## 3. API Endpoints - Полная спецификация

### 3.1. Склады (Warehouses)

Склады — это точки отправки товаров. Создаются заранее через API или ЛК.

#### Список складов

```
GET /api/v1/magnit-post/warehouses
Authorization: Bearer <token>
```

**Ответ:**
```json
[
  {
    "warehouse_id": "uuid-string",
    "warehouse_name": "Основной склад Москва",
    "address": "г. Москва, ул. Складская, д. 1",
    "coordinates": {
      "latitude": 55.7558,
      "longitude": 37.6173
    }
  }
]
```

#### Создание склада

```
POST /api/v1/magnit-post/warehouses
Content-Type: application/json

{
  "warehouse_name": "Склад Москва",           // 1-256 символов
  "address": "г. Москва, ул. Складская, д. 1", // 1-512 символов
  "coordinates": {
    "latitude": 55.7558,    // -90 до 90
    "longitude": 37.6173    // -180 до 180
  }
}
```

---

### 3.2. Пункты выдачи заказов (ПВЗ)

#### Список ПВЗ

```
GET /api/v1/magnit-post/pickup-points?city=Москва&page=1&size=1000
Authorization: Bearer <token>
```

**Query-параметры:**

| Параметр | Тип    | Описание                           |
| -------- | ------ | ---------------------------------- |
| `key`    | string | Фильтр по ключу конкретного ПВЗ    |
| `region` | string | Фильтр по региону                  |
| `city`   | string | Фильтр по городу (точное название) |
| `page`   | int    | Номер страницы (с 1)               |
| `size`   | int    | Размер страницы (макс 1000)        |

**Ответ — объект ПВЗ:**
```json
{
  "key": "64553",
  "name": "Магнит Косметик",
  "type": "MAGNIT_COSMETICS",
  "address": "г. Москва, ул. Паустовского, д. 5к1",
  "region": "Москва",
  "city": "Москва",
  "index": "117216",
  "coordinates": {
    "latitude": 55.6357,
    "longitude": 37.5198
  },
  "workHours": [
    {"day": "MON", "from": "09:00", "till": "21:00"},
    {"day": "TUE", "from": "09:00", "till": "21:00"},
    {"day": "WED", "from": "09:00", "till": "21:00"},
    {"day": "THU", "from": "09:00", "till": "21:00"},
    {"day": "FRI", "from": "09:00", "till": "21:00"},
    {"day": "SAT", "from": "09:00", "till": "21:00"},
    {"day": "SUN", "from": "09:00", "till": "21:00"}
  ]
}
```

#### Важные замечания по ПВЗ

- `type` — тип магазина: `MAGNIT_COSMETICS`, `MAGNIT_FAMILY` и т.д.
- `workHours` — массив до 7 элементов (MON-SUN)
- Координаты есть у всех ПВЗ — используются для отображения на карте и расчёта расстояний
- Город в ответе — точное название, не всегда совпадает с написанием в DaData (регистр, склонение)
- **НЕТ поля** для поддержки наложенного платежа (COD) — сейчас не актуально, все ПВЗ работают одинаково
- ~5000 ПВЗ по всей РФ, **рекомендуется кэшировать** (TTL 24 часа) — список меняется редко

---

### 3.3. Создание заказа (V2 API)

**Это основной эндпоинт для интернет-магазина.**

```
POST /api/v2/magnit-post/orders
Content-Type: application/json
Authorization: Bearer <token>
```

#### Тело запроса — КРИТИЧЕСКИ ВАЖНО:

```json
{
  "pickup_point": {"key": "64553"},
  "warehouse_id": "uuid-склада",
  "customer_order_id": "ORD-A7K3-20260304-M9X2",
  "return_type": "return",
  "return_warehouse_id": "uuid-склада",
  "recipient": {
    "phone_number": "+79991234567",
    "first_name": "Олег",
    "family_name": "Иванов"
  },
  "parcels": [
    {
      "declared_value": 2500.00,
      "characteristic": {
        "weight": 500,
        "length": 250,
        "width": 150,
        "height": 100
      },
      "parcel_payment": {
        "billing_type": "already_paid"
      }
    }
  ]
}
```

#### ВНИМАНИЕ: Подводные камни (выявлены при интеграции)

1. **`pickup_point` — это ОБЪЕКТ, не строка!**
   ```json
   // ПРАВИЛЬНО:
   "pickup_point": {"key": "64553"}

   // НЕПРАВИЛЬНО (ошибка 400):
   "pickup_point": "64553"
   ```

2. **`billing_type`** — только `"already_paid"` (предоплата). Значение `"not_paid"` (COD) пока не работает.

3. **`characteristic`** — единицы измерения:
   - `weight` — граммы (integer, min 1)
   - `length`, `width`, `height` — миллиметры (integer, min 1)

4. **`declared_value`** — в рублях (число с плавающей точкой, min 1)

5. **`return_type`**:
   - `"return"` — вернуть невостребованный заказ на склад
   - `"utilization"` — уничтожить

6. **`customer_order_id`** — ваш внутренний номер заказа (строка). Генерируется вашей системой.

7. Данные отправителя **НЕ передаются** — определяются автоматически по `client_id`.

#### Ответ при успехе:

```json
{
  "id": "uuid-заказа-в-magnit",
  "tracking_number": "MPOST-XXXXXXXX",
  "status": "NEW",
  "cost": {...}
}
```

#### Поля для COD (на будущее, когда заработает):

```json
"parcel_payment": {
  "billing_type": "not_paid",
  "items": [
    {
      "good_id": "ART-001",
      "name": "Товар",
      "unit": "piece",
      "quantity": 1,
      "unit_price": 250000,
      "total_sum_for_item": 250000,
      "vat_rate": 22
    },
    {
      "good_id": "DELIVERY",
      "name": "Доставка",
      "unit": "piece",
      "quantity": 1,
      "unit_price": 18300,
      "total_sum_for_item": 18300,
      "vat_rate": 22
    }
  ],
  "total_sum_for_parcel": 268300
}
```

- `unit_price` и `total_sum_for_item` — в **копейках**
- `vat_rate` — целое число: 0, 5, 7, 10, 20, 22

---

### 3.4. Список заказов

```
GET /api/v1/magnit-post/orders?page=1&size=100&sortDirection=desc
```

**Query-параметры:**

| Параметр          | Тип    | Описание                        |
| ----------------- | ------ | ------------------------------- |
| `customerOrderId` | string | Фильтр по номеру заказа клиента |
| `externalOrderId` | string | Фильтр по внешнему ID           |
| `status`          | string | Фильтр по статусу               |
| `createdFrom`     | string | Дата от (RFC3339)               |
| `createdTo`       | string | Дата до (RFC3339)               |
| `page`            | int    | Номер страницы (с 1)            |
| `size`            | int    | Размер (макс 1000)              |
| `sortDirection`   | string | `asc` / `desc`                  |

---

### 3.5. Получение заказа по ID

```
GET /api/v2/magnit-post/orders/{order_id}
```

`order_id` — UUID заказа из ответа при создании.

---

### 3.6. Отмена заказа

```
DELETE /api/v1/magnit-post/orders/{order_id}
```

Возвращает `204 No Content` при успехе.

---

### 3.7. История статусов заказа

```
GET /api/v1/magnit-post/orders/{order_id}/status-history
```

---

### 3.8. Этикетка (PDF)

```
GET /api/v1/magnit-post/orders/{order_id}/labels
Accept: application/pdf
```

Возвращает PDF-файл для печати.

---

### 3.9. Оценка стоимости доставки

```
POST /api/v2/magnit-post/orders/estimate
Content-Type: application/json

{
  "city_from": "Москва",
  "pickup_point_key": "64553",
  "parcels_count": 1
}
```

**Допустимые значения `city_from`:** Казань, Москва, Екатеринбург, Ижевск, Магнитогорск, Оренбург, Саратов, или `"Regions"` (прочие).

**Ответ:**
```json
{
  "from": 3,
  "to": 7,
  "cost": 12000,
  "cost_with_vat": 14640
}
```

- `from`, `to` — сроки доставки в днях
- `cost` — стоимость в копейках без НДС
- `cost_with_vat` — стоимость в копейках с НДС

---

## 4. Статусы заказов

| Статус                         | Описание                          | Финальный? |
| ------------------------------ | --------------------------------- | ---------- |
| `NEW`                          | Создан в системе                  | Нет        |
| `CREATED`                      | Подтверждён                       | Нет        |
| `DELIVERING_STARTED`           | Передан в доставку                | Нет        |
| `ACCEPTED_AT_POINT`            | Принят в ПВЗ, ждёт покупателя     | Нет        |
| `IN_COURIER_DELIVERY`          | Передан курьеру                   | Нет        |
| `ISSUED`                       | Выдан покупателю                  | **Да**     |
| `DESTROYED`                    | Уничтожен                         | **Да**     |
| `ACCEPTED_AT_WAREHOUSE`        | Принят на складе (после возврата) | Нет        |
| `REMOVED`                      | Удалён                            | **Да**     |
| `WAITING_RETURN`               | Ожидает возврата                  | Нет        |
| `RETURN_INITIATED`             | Возврат начат                     | Нет        |
| `RETURN_SEND_TO_WAREHOUSE`     | Возврат в пути на склад           | Нет        |
| `POSSIBLY_DEFECTED`            | Возможен брак                     | Нет        |
| `DEFECTED`                     | Брак подтверждён                  | **Да**     |
| `RETURN_ACCEPTED_AT_WAREHOUSE` | Возврат принят на складе          | Нет        |
| `RETURNED_TO_PROVIDER`         | Возвращён поставщику              | **Да**     |
| `CANCELED_BY_PROVIDER`         | Отменён поставщиком               | **Да**     |
| `ACCEPTED_AT_CUSTOMS`          | На таможне                        | Нет        |

---

## 5. Внешние сервисы

### 5.1. DaData (автокомплит адресов)

Используется для поиска города, улицы и дома покупателя. Возвращает координаты.

**URL:** `https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address`
**Метод:** POST
**Заголовки:**
```
Authorization: Token <DADATA_API_KEY>
X-Secret: <DADATA_SECRET_KEY>
Content-Type: application/json
```

#### Поиск города

```json
{
  "query": "Мос",
  "count": 10,
  "from_bound": {"value": "city"},
  "to_bound": {"value": "city"}
}
```

#### Поиск улицы (в контексте города)

```json
{
  "query": "Паус",
  "count": 10,
  "from_bound": {"value": "street"},
  "to_bound": {"value": "street"},
  "locations": [{"city_fias_id": "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"}]
}
```

#### Поиск дома (в контексте улицы)

```json
{
  "query": "5",
  "count": 10,
  "from_bound": {"value": "house"},
  "to_bound": {"value": "house"},
  "locations": [{"street_fias_id": "..."}]
}
```

#### Структура ответа (suggestion)

```json
{
  "value": "г Москва, ул Паустовского, д 5к1",
  "data": {
    "city": "Москва",
    "city_fias_id": "0c5b2444-70a0-4932-980c-b4dc0d3f02b5",
    "region_with_type": "г Москва",
    "street": "Паустовского",
    "street_fias_id": "...",
    "street_type": "ул",
    "house": "5к1",
    "geo_lat": "55.642380",
    "geo_lon": "37.519743"
  }
}
```

**Ключевые поля для интеграции:**
- `data.city_fias_id` — для ограничения поиска улицы
- `data.street_fias_id` — для ограничения поиска дома
- `data.geo_lat`, `data.geo_lon` — координаты для расчёта расстояний до ПВЗ

**API-ключи DaData:**
```
api_key:    6edbb2bc2316e22f8c6813515d87a39ae06da954
secret_key: 41bd3221e238a152db623360c0a4ab6a06d466b1
```

---

### 5.2. Yandex Maps JavaScript API

Для отображения ПВЗ на карте на фронтенде.

**API-ключ:** `ca05fe00-c79a-4fe2-812a-11758ed257ba`

---

## 6. Бизнес-логика

### 6.1. Конфигурируемые параметры

```json
{
  "delivery": {
    "cost_without_vat_rub": 150,
    "vat_rate_percent": 22
  },
  "parcel_sizes": {
    "S": {"label": "25x15x10 cm", "length_mm": 250, "width_mm": 150, "height_mm": 100},
    "M": {"label": "35x25x15 cm", "length_mm": 350, "width_mm": 250, "height_mm": 150},
    "L": {"label": "45x30x20 cm", "length_mm": 450, "width_mm": 300, "height_mm": 200}
  }
}
```

### 6.2. Расчёт стоимости доставки для покупателя

```
cost_with_vat = cost_without_vat * (1 + vat_rate / 100)
150 * 1.22 = 183 руб
```

Это фиксированная стоимость для покупателя, показывается при оформлении заказа.

### 6.3. Если в городе нет ПВЗ

Не все города имеют ПВЗ Magnit. Алгоритм:

1. Проверить наличие ПВЗ в городе покупателя
2. Если нет — рассчитать расстояние (Haversine) от координат города до центроидов всех городов с ПВЗ
3. Показать покупателю список ближайших городов с ПВЗ, отсортированных по расстоянию
4. Покупатель выбирает город — далее показываем ПВЗ из этого города

### 6.4. Выбор ПВЗ

1. Получить координаты адреса покупателя (из DaData)
2. Загрузить все ПВЗ в выбранном городе (из кэша)
3. Рассчитать расстояние от адреса до каждого ПВЗ (Haversine)
4. Отсортировать по расстоянию
5. Показать ближайшие 10

### 6.5. Формула Haversine (расчёт расстояния)

```python
import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0  # км
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
```

### 6.6. Кэширование ПВЗ

- Загружаем ВСЕ ПВЗ (~5000) одним запросом (с пагинацией по 1000)
- Сохраняем в файл/БД с таймстампом
- TTL: 24 часа
- Строим индекс по городу для быстрого поиска
- При TTL expired — перезагружаем из API

### 6.7. Генерация номера заказа

Формат: `ORD-XXXX-YYYYMMDD-XXXX` (латинские буквы + цифры + тире).
Пример: `ORD-A7K3-20260304-M9X2`

---

## 7. Frontend - Рекомендации по реализации

### 7.1. Виджет выбора ПВЗ на Yandex Maps

На странице оформления заказа показать карту с маркерами ПВЗ.

**Данные для фронтенда (получать с бэкенда):**

```typescript
interface PickupPoint {
  key: string;           // "64553" — ID для передачи в API
  name: string;          // "Магнит Косметик"
  type: string;          // "MAGNIT_COSMETICS"
  address: string;       // Полный адрес
  city: string;
  latitude: number;
  longitude: number;
  distance_km: number;   // Расстояние от адреса покупателя
  work_hours: WorkHour[];
}

interface WorkHour {
  day: string;    // "MON" | "TUE" | ... | "SUN"
  from: string;   // "09:00"
  till: string;   // "21:00"
}
```

**Подключение Yandex Maps:**

```html
<script src="https://api-maps.yandex.ru/v3/?apikey=ca05fe00-c79a-4fe2-812a-11758ed257ba&lang=ru_RU"></script>
```

**Логика виджета:**

1. Покупатель вводит адрес (DaData-автокомплит для фронтенда)
2. Бэкенд возвращает список ПВЗ с расстояниями
3. Фронтенд отображает маркеры на карте
4. Слева — список ПВЗ (отсортирован по расстоянию), справа — карта
5. Клик по маркеру/элементу списка → выбор ПВЗ
6. В balloon маркера: название, адрес, режим работы
7. Выбранный ПВЗ подсвечивается, его `key` сохраняется для заказа

**Состояние «нет ПВЗ в городе»:**

- Показать баннер: "В вашем городе пока нет пунктов выдачи Magnit"
- Предложить ближайшие города с ПВЗ (с расстояниями)
- При выборе другого города — перецентрировать карту и загрузить ПВЗ

### 7.2. Форма оформления заказа

```
Адрес доставки:
  [город]  ← DaData autocomplete, from_bound=city, to_bound=city
  [улица]  ← DaData autocomplete, привязка к city_fias_id
  [дом]    ← DaData autocomplete, привязка к street_fias_id

Пункт выдачи:
  [Карта с ПВЗ]  ← Yandex Maps
  [Список ПВЗ]   ← Сортировка по расстоянию

Размер посылки:
  ○ S (25x15x10 см)
  ○ M (35x25x15 см)
  ○ L (45x30x20 см)

Стоимость доставки: 183 ₽

Получатель:
  [Фамилия]
  [Имя]
  [Телефон]  ← формат +7XXXXXXXXXX
```

---

## 8. Backend - Рекомендации по реализации

### 8.1. Эндпоинты бэкенда для фронтенда

```
GET  /api/delivery/magnit/cities
     → Список городов где есть ПВЗ (из кэша)

GET  /api/delivery/magnit/pickup-points?city=Москва&lat=55.64&lon=37.52&limit=10
     → Ближайшие ПВЗ с расстояниями

GET  /api/delivery/magnit/nearest-cities?lat=59.56&lon=150.80&limit=5
     → Ближайшие города с ПВЗ (если в текущем городе нет)

POST /api/delivery/magnit/estimate
     → Оценка стоимости и сроков

POST /api/delivery/magnit/create-order
     → Создание заказа (проксирует в Magnit API)

GET  /api/delivery/magnit/order/{id}
     → Статус заказа

DELETE /api/delivery/magnit/order/{id}
     → Отмена заказа
```

### 8.2. Модель данных (DB)

```sql
CREATE TABLE magnit_orders (
    id                  SERIAL PRIMARY KEY,
    magnit_order_id     UUID,               -- UUID из ответа Magnit
    tracking_number     VARCHAR(50),         -- Трекинг Magnit
    customer_order_id   VARCHAR(50),         -- Наш внутренний номер
    shop_order_id       INTEGER REFERENCES orders(id), -- Связь с заказом магазина
    warehouse_id        UUID,
    pickup_point_key    VARCHAR(20),
    pickup_point_name   VARCHAR(255),
    pickup_point_address VARCHAR(512),
    status              VARCHAR(50) DEFAULT 'NEW',
    billing_type        VARCHAR(20) DEFAULT 'already_paid',
    declared_value      DECIMAL(10,2),
    weight_grams        INTEGER,
    size_code           VARCHAR(1),         -- S, M, L
    recipient_name      VARCHAR(255),
    recipient_phone     VARCHAR(20),
    delivery_address    VARCHAR(512),       -- Адрес покупателя (для справки)
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE magnit_pvz_cache (
    id          SERIAL PRIMARY KEY,
    key         VARCHAR(20) UNIQUE,
    name        VARCHAR(255),
    type        VARCHAR(50),
    address     VARCHAR(512),
    city        VARCHAR(100),
    region      VARCHAR(100),
    latitude    DECIMAL(9,6),
    longitude   DECIMAL(9,6),
    work_hours  JSONB,
    cached_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_pvz_city ON magnit_pvz_cache(city);
CREATE INDEX idx_pvz_coords ON magnit_pvz_cache(latitude, longitude);
```

### 8.3. Сервис интеграции (примерная архитектура)

```
MagnitDeliveryService
├── authenticate()              → OAuth2, кэш токена
├── sync_pickup_points()        → Обновление кэша ПВЗ (cron, раз в сутки)
├── get_pickup_points(city, lat, lon, limit) → Поиск ПВЗ
├── get_nearest_cities(lat, lon) → Города с ПВЗ
├── estimate(city_from, pp_key) → Стоимость и сроки
├── create_order(order_data)    → Создание заказа
├── get_order(magnit_id)        → Статус
├── cancel_order(magnit_id)     → Отмена
└── process_webhook(event)      → Обработка вебхуков (если появятся)
```

### 8.4. Webhook / Polling статусов

На момент интеграции Magnit **не предоставляет webhook** для push-уведомлений о смене статуса. Варианты:

1. **Polling** — периодически (раз в час) опрашивать `GET /api/v1/magnit-post/orders` с фильтром по статусу
2. **По запросу** — проверять статус при обращении покупателя к странице заказа

---

## 9. Коды ошибок API

| HTTP | Код                     | Описание                                      |
| ---- | ----------------------- | --------------------------------------------- |
| 400  | `BAD_REQUEST`           | Ошибка валидации (неправильный формат данных) |
| 400  | `VALIDATION_ERROR`      | Ошибка валидации полей                        |
| 401  | —                       | Токен невалидный / истёк                      |
| 404  | `NOT_FOUND`             | Ресурс не найден                              |
| 409  | `CONFLICT`              | Конфликт (напр. дублирующий customerOrderId)  |
| 422  | `UNPROCESSABLE_ENTITY`  | Данные валидны, но не могут быть обработаны   |
| 500  | `INTERNAL_SERVER_ERROR` | Ошибка сервера                                |
| 503  | —                       | Сервис недоступен                             |

---

## 10. Полный пример создания заказа (бэкенд)

```python
# 1. Авторизация
token = magnit.authenticate()

# 2. Данные от фронтенда
pickup_point_key = "64553"
warehouse_id = "550e8400-e29b-41d4-a716-446655440000"

# 3. Формируем заказ
order = {
    "pickup_point": {"key": pickup_point_key},   # ОБЪЕКТ, не строка!
    "warehouse_id": warehouse_id,
    "customer_order_id": "ORD-A7K3-20260304-M9X2",
    "return_type": "return",
    "return_warehouse_id": warehouse_id,
    "recipient": {
        "phone_number": "+79991234567",
        "first_name": "Олег",
        "family_name": "Иванов"
    },
    "parcels": [{
        "declared_value": 2500.00,
        "characteristic": {
            "weight": 500,       # граммы
            "length": 250,       # мм
            "width": 150,        # мм
            "height": 100        # мм
        },
        "parcel_payment": {
            "billing_type": "already_paid"
        }
    }]
}

# 4. Отправляем
response = requests.post(
    f"{BASE_URL}/api/v2/magnit-post/orders",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json=order,
)

# 5. Сохраняем результат
result = response.json()
magnit_order_id = result["id"]
tracking_number = result["tracking_number"]
```

---

## 11. Известные особенности и баги

1. **`pickup_point` должен быть объектом** `{"key": "..."}`, а не строкой. Иначе 400 BAD_REQUEST с ошибкой "Unmarshal type error: expected=serverhttp.PickupPointShort, got=string".

2. **COD (`not_paid`) не работает** — API принимает, но функционал не реализован на стороне Magnit. Использовать только `already_paid`.

3. **Город в фильтре ПВЗ** — точное совпадение. "москва" ≠ "Москва". Используйте точное название из ответа API.

4. **Пагинация ПВЗ** — максимум 1000 за запрос. Если в городе > 1000 ПВЗ, нужно запрашивать следующие страницы.

5. **API документация** — https://magnit-tech.github.io/mpost-api/ (Swagger/OpenAPI).

6. **Не все города имеют ПВЗ** — обязательно проверять наличие и предлагать альтернативы.

---

## 12. Ссылки

- API документация: https://magnit-tech.github.io/mpost-api/
- DaData Suggestions API: https://dadata.ru/api/suggest/address/
- Yandex Maps JS API v3: https://yandex.ru/dev/jsapi30/
- Yandex HTTP Geocoder: https://yandex.ru/dev/geocode/
