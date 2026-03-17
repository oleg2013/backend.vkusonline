# 5Post API Integration Guide

Техническое описание интеграции со службой доставки 5Post (X5 Retail Group).
Документ основан на API v7.25 и практическом опыте интеграции.

---

## 1. Общее описание

**5Post** — служба доставки X5 Retail Group. Доставка B2B осуществляется в постаматы (5BOX/Fivebox) и ПВЗ,
расположенные в магазинах «Пятёрочка», «Перекрёсток» и отдельно стоящих точках.

- Продуктивный API: `https://api-omni.x5.ru`
- Тестовый API: `https://api-preprod-omni.x5.ru`
- Виджет выбора ПВЗ: `https://fivepost.ru/widget`
- Всего ~25 000 активных точек выдачи по России

---

## 1.1. Ключи доступа и учётные данные

### API 5Post

| Параметр | Значение |
|----------|----------|
| Base URL (продуктивный) | `https://api-omni.x5.ru` |
| Base URL (тестовый) | `https://api-preprod-omni.x5.ru` |
| API Key | `f6c7fc81-9d6f-485c-b5c6-72175dfeaeb9` |

### DaData (подсказки адресов + геокодирование)

| Параметр | Значение |
|----------|----------|
| API Key | `6edbb2bc2316e22f8c6813515d87a39ae06da954` |
| Secret Key | `41bd3221e238a152db623360c0a4ab6a06d466b1` |
| Suggest URL | `https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address` |

### Yandex Geocoder (резервный)

| Параметр | Значение |
|----------|----------|
| API Key | `ca05fe00-c79a-4fe2-812a-11758ed257ba` |
| Geocoder URL | `https://geocode-maps.yandex.ru/1.x/` |

### Склады партнёра

| Склад | UUID / partnerLocationId |
|-------|--------------------------|
| Склад Москва (Витебский пр-т, д. 11) | `f6389674-af2c-4f0f-aa49-4966fcc19cda` |

> **Примечание:** Полный список складов можно получить через `GET /api/v3/warehouses`. UUID и `partnerLocationId` каждого склада используются в поле `senderLocation` при создании заказа.

---

## 2. Аутентификация

### Получение JWT-токена

```
POST /jwt-generate-claims/rs256/1?apikey={API_KEY}
Content-Type: application/json
```

**Тело запроса:** пустое `{}`

**Ответ:**
```json
{
  "jwt": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9..."
}
```

- Время жизни токена: **1 час**
- Использование: `Authorization: Bearer {jwt}` во всех последующих запросах
- Токен нужно обновлять по истечении срока

---

## 3. Точки выдачи (Pickup Points)

### 3.1. Получение списка

```
POST /api/v1/pickuppoints/query
Authorization: Bearer {jwt}
Content-Type: application/json
```

**Тело запроса:**
```json
{
  "pageSize": 1000,
  "pageNumber": 0
}
```

**ВАЖНО:**
- Единственные параметры — пагинация. Фильтрация по ID, городу, зоне и т.д. **невозможна**
- Для получения всех точек нужно перебрать все страницы (поле `totalPages` в ответе)
- ~25 000 точек = ~26 страниц по 1000
- **Rate limit:** 3 полные выгрузки в сутки (скользящее окно: 3000 точек/сек, 50000/час, 150000/сутки)
- Рекомендуется запрашивать 1-2 раза в сутки после 6 утра (массовое обновление данных 02:00-05:00 МСК)

### 3.2. Структура ответа — одна точка выдачи

```json
{
  "content": [
    {
      "id": "001c8a44-dac3-4651-8a9e-caa8cdbd860e",
      "mdmCode": "OM120349",
      "name": "OM120349",
      "partnerName": "Fivebox",
      "type": "POSTAMAT",
      "multiplaceDeliveryAllowed": true,
      "fullAddress": "Магаданская обл., г. Магадан, Якутская ул., 14",
      "shortAddress": "Якутская ул., 14",
      "extStatus": "ACTIVE",
      "phone": "88005118800",
      "cashAllowed": false,
      "cardAllowed": true,
      "loyaltyAllowed": false,
      "returnAllowed": false,
      "timezoneOffset": "+11:00",
      "timezone": "Asia/Magadan",
      "outsideX5": false,
      "localityFiasCode": "uuid-...",
      "createDate": "2020-03-20T12:40:12Z",
      "openDate": "2018-11-22T15:07:35Z",

      "address": {
        "country": "RU",
        "zipCode": "685000",
        "region": "Магаданская область",
        "regionType": "обл",
        "city": "Магадан",
        "cityType": "г",
        "street": "Якутская",
        "house": "14",
        "building": null,
        "metroStation": null,
        "lat": 59.5667,
        "lng": 150.8000
      },

      "additional": "Пункт выдачи 5Post расположен в ПВЗ Ozon...",

      "workHours": [
        { "day": "MON", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "TUE", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "WED", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "THU", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "FRI", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "SAT", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" },
        { "day": "SUN", "opensAt": "09:00", "closesAt": "21:00", "timezone": "Asia/Magadan", "timezoneOffset": "+11:00" }
      ],

      "cellLimits": {
        "maxCellWidth": 450,
        "maxCellHeight": 600,
        "maxCellLength": 450,
        "maxWeight": 25000000
      },

      "rate": [
        {
          "rateType": "HUB_SPB",
          "rateTypeCode": "20",
          "zone": "D18",
          "rateValue": 381.25,
          "vat": 20,
          "rateValueWithVat": 457.50,
          "rateExtraValue": 91.50,
          "rateExtraValueWithVat": 109.80,
          "rateCurrency": "RUB"
        }
      ],

      "deliverySL": [
        { "sl": 10, "minimalSl": 7, "slCode": "20" }
      ],

      "lastMileWarehouse": {
        "id": "uuid-...",
        "name": "Склад Магадан"
      }
    }
  ],
  "totalPages": 26,
  "totalElements": 25038,
  "numberOfElements": 1000
}
```

### 3.3. Типы точек выдачи

| type | Описание | Приоритет |
|------|----------|-----------|
| `ISSUE_POINT` | ПВЗ (пункт выдачи заказов) | Высший |
| `POSTAMAT` | Постамат (5BOX/Fivebox) | Средний |
| `TOBACCO` | Касса (выдача на кассе магазина) | Низший |

При наличии нескольких типов в одном магазине действует приоритет: ПВЗ > Постамат > Касса.

### 3.4. Способы оплаты

| Поле | Описание |
|------|----------|
| `cashAllowed` | Точка принимает наличные |
| `cardAllowed` | Точка принимает банковские карты |

Если оба `false` — точка работает **только по предоплате**.

### 3.5. Ограничения ячейки (cellLimits)

| Поле | Единицы | Описание |
|------|---------|----------|
| `maxCellWidth` | мм | Максимальная ширина |
| `maxCellHeight` | мм | Максимальная высота |
| `maxCellLength` | мм | Максимальная длина |
| `maxWeight` | **мг** (миллиграммы) | Максимальный вес |

**Обязательно проверять:** габариты и вес посылки не должны превышать ограничения ячейки выбранной точки.

---

## 4. Тарифы и расчёт стоимости доставки

### 4.1. Данные тарифов

Тарифы приходят в массиве `rate[]` каждой точки выдачи. Отдельного endpoint'а для расчёта B2B-тарифов **не существует**.

| Поле | Описание |
|------|----------|
| `rateType` | Тип тарифного плана (напр. `HUB_SPB`, `HUB_MOSCOW`) |
| `rateTypeCode` | Код типа (10=HubMoscow, 20=HubSPB, 30=HubEKB и т.д.) |
| `zone` | Тарифная зона (1-13, D1-D18 и т.д.) |
| `rateValue` | Базовая стоимость без НДС |
| `rateValueWithVat` | Базовая стоимость **с НДС** |
| `rateExtraValue` | Надбавка за кг перевеса без НДС |
| `rateExtraValueWithVat` | Надбавка за кг перевеса **с НДС** |
| `rateCurrency` | Валюта (`RUB`) |
| `vat` | Ставка НДС (%) |

### 4.2. Формула расчёта стоимости доставки (из документации API)

```
Если вес ≤ 3 кг:
    стоимость_доставки = rateValueWithVat

Если вес > 3 кг:
    перевес_кг = ceil(фактический_вес_кг - 3)    // округление ВВЕРХ до целого кг
    стоимость_доставки = rateValueWithVat + rateExtraValueWithVat × перевес_кг
```

**Пример:** вес 4.5 кг, rateValueWithVat=457.50, rateExtraValueWithVat=109.80
```
перевес = ceil(4.5 - 3) = ceil(1.5) = 2 кг
стоимость = 457.50 + 109.80 × 2 = 677.10 руб.
```

### 4.3. КРИТИЧЕСКОЕ ЗАМЕЧАНИЕ О ТАРИФАХ

> **Тарифы из `rate[]` могут НЕ соответствовать реальной стоимости доставки, которую 5Post выставит партнёру.**
>
> Пример из практики: для маршрута СПб→Магадан (1 кг, предоплата) API возвращает `rateValueWithVat = 457.50 руб.`,
> а калькулятор в личном кабинете 5Post показывает **1 464 руб.** — расхождение в 3.2 раза.
>
> Фактическую стоимость партнёр узнаёт только **после доставки** через callback (раздел 8).
> Поле `deliveryCost` в заказе — это то, сколько партнёр **берёт с клиента**, а не то, сколько спишет 5Post.
>
> **Рекомендация:** уточнить у менеджера 5Post актуальные тарифы и правильную интерпретацию `rate[]`.

### 4.4. Выбор тарифа при наличии нескольких rate

Точка может иметь несколько тарифов (от разных хабов). В текущей реализации у большинства партнёров
все точки имеют только один тариф (например, `HUB_SPB`).

Если тарифов несколько — нужно выбирать тот, который соответствует хабу склада отправки.

---

## 5. Склады партнёра (Warehouses)

### 5.1. Получение списка складов

```
GET /api/v3/warehouses
Authorization: Bearer {jwt}
```

**Ответ:**
```json
[
  {
    "id": "uuid-...",
    "name": "Основной склад",
    "city": "Санкт-Петербург",
    "region": "г. Санкт-Петербург",
    "fullAddress": "г. Санкт-Петербург, Витебский пр-т, д. 11",
    "partnerLocationId": "warehouse-001",
    "status": "ACTIVE",
    "phone": "+79001234567",
    "workingTime": "09:00-18:00",
    "lat": 59.8614,
    "lng": 30.3190
  }
]
```

Поле `partnerLocationId` — идентификатор склада в системе партнёра, используется при создании заказа (`senderLocation`).

### 5.2. Создание склада

```
POST /api/v3/warehouses
Authorization: Bearer {jwt}
Content-Type: application/json
```

Тело запроса — объект с данными склада (name, address, partnerLocationId и т.д.).

---

## 6. Создание заказа

### 6.1. Endpoint

```
POST /api/v3/orders
Authorization: Bearer {jwt}
Content-Type: application/json
```

### 6.2. Структура запроса

```json
{
  "partnerOrders": [
    {
      "senderOrderId": "ORDER-2025-001",
      "clientOrderId": "ORDER-2025-001",
      "clientName": "Иванов Иван Иванович",
      "clientPhone": "+79001234567",
      "clientEmail": "ivan@example.com",
      "senderLocation": "warehouse-001",
      "receiverLocation": "001c8a44-dac3-4651-8a9e-caa8cdbd860e",
      "undeliverableOption": "RETURN",
      "cost": {
        "deliveryCost": 345.43,
        "deliveryCostCurrency": "RUB",
        "paymentValue": 5845.43,
        "paymentCurrency": "RUB",
        "paymentType": "CASHLESS",
        "price": 5500.00,
        "priceCurrency": "RUB"
      },
      "cargoes": [
        {
          "senderCargoId": "CARGO-001",
          "height": 100,
          "length": 200,
          "width": 150,
          "weight": 1340000,
          "price": 5500.00,
          "currency": "RUB",
          "vat": 22,
          "productValues": [
            {
              "name": "Чай зелёный Sencha 100г",
              "value": 2,
              "price": 2750.00,
              "vat": 22,
              "currency": "RUB"
            }
          ]
        }
      ]
    }
  ]
}
```

### 6.3. Описание ключевых полей cost

| Поле | Описание |
|------|----------|
| `deliveryCost` | Стоимость доставки **для клиента** (сколько клиент платит за доставку) |
| `paymentValue` | **Общая сумма к оплате клиентом** при получении. Для предоплаты = `0` |
| `paymentType` | `CASH` / `CASHLESS` / `PREPAYMENT` |
| `price` | Оценочная стоимость заказа (для расчёта страховки) |
| `prepaymentSum` | Сумма предоплаты/бонусов/скидки (опционально) |

### 6.4. Формула валидации paymentValue

API проверяет:

```
paymentValue = SUM(cargoes.productValues.price × value) + deliveryCost - prepaymentSum
```

Если формула не сходится — **ошибка 70**.

**Пример:**
```
Товары: 2 × 2750 = 5500 руб.
deliveryCost: 345.43 руб. (включает доставку + комиссию + страховку)
paymentValue: 5500 + 345.43 = 5845.43 руб. ✓
```

### 6.5. Единицы измерения

| Параметр | Единицы |
|----------|---------|
| `height`, `length`, `width` | **мм** (миллиметры) |
| `weight` | **мг** (миллиграммы). 1 кг = 1 000 000 мг |
| `price`, `deliveryCost`, `paymentValue` | **руб.** (не более 2 знаков после запятой) |

### 6.6. Способы оплаты

| paymentType | Описание | paymentValue |
|-------------|----------|--------------|
| `PREPAYMENT` | Клиент уже оплатил | `0` |
| `CASH` | Наличными при получении | `> 0` |
| `CASHLESS` | Картой при получении | `> 0` |

### 6.7. Успешный ответ

```json
{
  "created": true,
  "orderId": "uuid-...",
  "senderOrderId": "ORDER-2025-001",
  "cargoes": [
    {
      "cargoId": "uuid-...",
      "barcode": "10000XXXXXXXXX"
    }
  ]
}
```

### 6.8. Ответ с ошибкой

```json
{
  "created": false,
  "errors": [
    {
      "code": 70,
      "message": "The sum of partnerOrders.cargoes.productValues.price and partnerOrders.cost.deliveryCost is not equal to partnerOrders.cost.paymentValue"
    }
  ]
}
```

---

## 7. Комиссии и дополнительные сборы

### 7.1. Страховка (Приём отправления с объявленной ценностью)

```
страховка = объявленная_стоимость / 100 × 0.5
```

Пример: объявленная стоимость 3000 руб. → страховка = 15.00 руб.
Совпадает с калькулятором ЛК 5Post.

### 7.2. Комиссия за наложенный платёж

**Оплата картой (2.5%):**
```
комиссия_карта = сумма_товаров / (100 - 2.5) × 100 - сумма_товаров
```

**Оплата наличными (1.5%):**
```
комиссия_наличные = сумма_товаров / (100 - 1.5) × 100 - сумма_товаров
```

**Пример:** сумма товаров 5500 руб.
- Комиссия картой: 5500 / 97.5 × 100 - 5500 = 141.03 руб.
- Комиссия наличными: 5500 / 98.5 × 100 - 5500 = 83.76 руб.

### 7.3. Итоговые формулы для клиента

**Предоплата:**
```
итого = сумма_товаров + стоимость_доставки + страховка
```

**Наложенный платёж (наличные):**
```
итого = сумма_товаров + стоимость_доставки + комиссия_наличные + страховка
```

**Наложенный платёж (карта):**
```
итого = сумма_товаров + стоимость_доставки + комиссия_карта + страховка
```

### 7.4. Передача в API при наложенном платеже

При наложенном платеже все сборы (доставка + комиссия + страховка) включаются в поле `deliveryCost`:

```
deliveryCost = итого - сумма_товаров
paymentValue = итого
```

Это обеспечивает выполнение формулы API: `paymentValue = SUM(products.price) + deliveryCost`.

---

## 8. Callback — фактическая стоимость доставки (Раздел 15 API)

### 8.1. Описание

5Post отправляет webhook на сервер партнёра через **23 часа** после терминального статуса заказа.
Содержит **реальную стоимость**, которую 5Post выставит партнёру (может отличаться от `rate[]`).

### 8.2. Терминальные статусы

| status | executionStatus | Описание |
|--------|----------------|----------|
| `DONE` | `PICKED_UP` | Клиент забрал заказ |
| `CANCELLED` | `RETURNED_TO_PARTNER` | Отменён, возврат партнёру |
| `CANCELLED` | `READY_FOR_UTILIZE` | Отменён, утилизация |
| `UNCLAIMED` | `RETURNED_TO_PARTNER` | Не востребован, возврат |
| `UNCLAIMED` | `READY_FOR_UTILIZE` | Не востребован, утилизация |

### 8.3. Структура callback

```json
{
  "type": "SERVICE_DELIVERY_REPORT",
  "data": {
    "order": {
      "contractNumber": "KK12345",
      "trackingNumber": "uuid-5post",
      "orderCode": "ORDER-2025-001",
      "shipmentDate": "2025-03-01T10:00:00+03:00",
      "paymentInfo": {
        "tariff": "HUB Moscow",
        "assessedValue": 5500,
        "cod": 5845.43,
        "paymentType": "CASHLESS"
      },
      "orderStatus": "DONE",
      "orderExecutionStatus": "PICKED_UP",
      "statusTime": "2025-03-05T14:00:00+03:00",
      "shippingAddress": {
        "region": "г Санкт-Петербург",
        "city": "Санкт-Петербург",
        "addressLine": "Витебский пр-т, д. 11"
      },
      "consigneeAddress": {
        "region": "Магаданская обл.",
        "city": "Магадан",
        "addressLine": "Якутская ул., 14"
      },
      "packages": [
        { "length": 200, "width": 150, "height": 100, "weight": 1340000 }
      ]
    },
    "services": [
      { "name": "Услуга доставки", "sum": 1464.0, "vat": 20, "vatSum": 244.0, "createdAt": "..." },
      { "name": "Услуга страховки", "sum": 15.0, "vat": 20, "vatSum": 2.5, "createdAt": "..." },
      { "name": "Дополнительные услуги", "sum": 6.5, "vat": 20, "vatSum": 1.08, "createdAt": "..." }
    ],
    "totalDeliverySum": 1485.5
  }
}
```

### 8.4. Подключение callback

1. Реализовать HTTPS-endpoint на сервере партнёра
2. Передать URL и секретный токен менеджеру 5Post
3. 5Post настроит отправку callback'ов

---

## 9. Кэширование точек выдачи

### 9.1. Стратегия

Из-за отсутствия фильтрации и жёсткого rate limit кэширование **обязательно**.

**Рекомендуемый подход:**
- Хранить полный JSON всех точек в файле/БД
- TTL: 24 часа
- Обновлять 1-2 раза в сутки (после 06:00 МСК)
- Использовать кэш для всех операций: поиск, фильтрация, показ на карте

### 9.2. Структура кэша (файловый вариант)

```json
{
  "cached_at": "2025-03-01T10:00:00",
  "points_count": 25038,
  "points": [ ...сырые данные из API... ]
}
```

**Размер:** ~50-60 МБ (компактный JSON без отступов).

### 9.3. Постраничная загрузка (WooCommerce-подход)

Альтернатива полной выгрузке — загружать по 1 странице в минуту через cron.
Полное обновление за ~26 минут, минимальная нагрузка.

---

## 10. Фронтенд — выбор ПВЗ на карте

### 10.1. Виджет 5Post

5Post предоставляет готовый встраиваемый виджет: `https://fivepost.ru/widget`
Подключается JS-скриптом на страницу оформления заказа.

### 10.2. Собственная реализация на Яндекс.Картах

Для кастомной реализации нужно:

1. **Загрузить точки из кэша** (серверная часть)
2. **Отфильтровать** по:
   - Городу/региону получателя
   - Габаритам и весу заказа (`cellLimits`)
   - Способу оплаты (`cashAllowed`, `cardAllowed`)
3. **Отсортировать** по расстоянию от адреса клиента (формула Haversine)
4. **Показать на карте** (Яндекс.Карты API)

### 10.3. Данные для отображения ПВЗ на карте

Для каждой точки доступны:

```
id            — UUID (для API-заказа в receiverLocation)
name          — код ПВЗ (напр. "5POST-00513")
type          — тип (POSTAMAT / ISSUE_POINT / TOBACCO)
fullAddress   — полный адрес
shortAddress  — короткий адрес
address.lat   — широта
address.lng   — долгота
workHours[]   — расписание работы
phone         — телефон
additional    — доп. информация о расположении
cashAllowed   — принимает наличные
cardAllowed   — принимает карты
cellLimits    — ограничения ячейки
```

### 10.4. Формула расстояния (Haversine)

```python
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """Расстояние между двумя точками в км."""
    R = 6371  # Радиус Земли в км
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))
```

### 10.5. Фильтрация точек по вместимости

```python
def point_fits_cargo(point, width_mm, height_mm, length_mm, weight_mg):
    cl = point["cellLimits"]
    dims = sorted([width_mm, height_mm, length_mm])
    limits = sorted([cl["maxCellWidth"], cl["maxCellHeight"], cl["maxCellLength"]])
    return (dims[0] <= limits[0] and
            dims[1] <= limits[1] and
            dims[2] <= limits[2] and
            weight_mg <= cl["maxWeight"])
```

---

## 11. Получение статусов заказа

### 11.1. Polling

```
POST /api/v3/order-statuses
Authorization: Bearer {jwt}
Content-Type: application/json
```

```json
{
  "senderOrderIds": ["ORDER-2025-001", "ORDER-2025-002"]
}
```

### 11.2. Callback (рекомендуется)

Настраивается через менеджера 5Post. Callback приходит при каждой смене статуса заказа.

### 11.3. Основные статусы

| Статус | Описание |
|--------|----------|
| `NEW` | Заказ создан |
| `ACCEPTED` | Принят на складе 5Post |
| `IN_TRANSIT` | В пути |
| `READY_FOR_PICKUP` | Готов к выдаче |
| `DONE` | Выдан клиенту |
| `CANCELLED` | Отменён |
| `UNCLAIMED` | Не востребован |
| `REJECTED` | Отклонён (точка неактивна) |

**Статус `REJECTED` не является конечным** — 5Post может переадресовать заказ.

---

## 12. Получение этикетки

```
POST /api/v3/order-labels
Authorization: Bearer {jwt}
Content-Type: application/json
```

```json
{
  "senderOrderIds": ["ORDER-2025-001"]
}
```

Возвращает PDF-этикетку в base64.

---

## 13. Отмена заказа

```
DELETE /api/v3/orders/{senderOrderId}
Authorization: Bearer {jwt}
```

Отмена возможна до передачи заказа на склад 5Post.

---

## 14. Частые ошибки API

| Код | Описание | Решение |
|-----|----------|---------|
| 70 | paymentValue не сходится с формулой | Проверить: paymentValue = SUM(products) + deliveryCost |
| 401 | Невалидный/просроченный JWT | Обновить токен |
| 429 | Превышен rate limit | Подождать, использовать кэш |
| `LocationContractor not found` | Неверный senderLocation | Проверить partnerLocationId склада |
| `ReceiverLocation not found` | Неверная точка выдачи | Проверить UUID точки (может быть деактивирована) |

---

## 15. Рекомендуемая архитектура интеграции

### Бэкенд

```
┌─────────────────────────────────────────────────┐
│  CRON (1-2 раза в сутки)                        │
│  └── Загрузка точек выдачи → кэш (файл/БД)     │
├─────────────────────────────────────────────────┤
│  API Controller                                  │
│  ├── GET /delivery/points?city=...&lat=...&lon=  │
│  │   └── Поиск точек из кэша, фильтрация,       │
│  │       сортировка по расстоянию                │
│  ├── POST /delivery/calculate                    │
│  │   └── Расчёт стоимости (формулы раздела 7)   │
│  └── POST /delivery/create-order                 │
│       └── Создание заказа через 5Post API        │
├─────────────────────────────────────────────────┤
│  Webhook endpoint                                │
│  └── POST /webhook/5post                         │
│       ├── Статусы заказов                        │
│       └── Фактическая стоимость (раздел 8)       │
└─────────────────────────────────────────────────┘
```

### Фронтенд (оформление заказа)

```
1. Клиент вводит адрес
2. Геокодирование (DaData / Яндекс.Геокодер) → координаты
3. Запрос к бэкенду → список ближайших ПВЗ
4. Отображение точек на Яндекс.Карте
5. Клиент выбирает точку → показ карточки (адрес, режим, способы оплаты)
6. Расчёт стоимости доставки на бэкенде
7. Оформление заказа
```

---

## 16. Полезные ссылки

- Документация API: запросить у менеджера 5Post (не публичная)
- Виджет: https://fivepost.ru/widget
- Горячая линия: 8-800-511-88-00
- Поддержка партнёров: partner@x5.ru

---

## 17. НДС

Допустимые ставки НДС:
- `-1` — без НДС
- `0`, `5`, `7`, `10`, `20`, `22`

С 1 января 2026 года доступна ставка **22%** (переходный период до 31 марта 2026 — также принимается 20%).

---

*Документ создан на основе API 5Post v7.25 (январь 2026) и практического опыта интеграции.*
