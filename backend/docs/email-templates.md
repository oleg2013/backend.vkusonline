# Email-шаблоны — руководство

## Общее описание

При событиях (создание заказа, смена статуса, регистрация клиента) система находит подходящие шаблоны, подставляет данные заказа/клиента вместо `#PLACEHOLDER#` токенов, и кладёт письмо в Redis-очередь. Worker отправляет письма каждые 5 секунд.

## Мета-поля (плейсхолдеры)

В шаблонах используются токены вида `#ИМЯ_ПОЛЯ#`. При рендеринге они заменяются на реальные значения.

### Поля заказа

Доступны во всех шаблонах CODFLOW и PREPAID. Заполняются автоматически из данных заказа.

| Плейсхолдер         | Описание                            | Пример значения                                   |
|---------------------|-------------------------------------|---------------------------------------------------|
| `#ORDER_ID#`        | Номер заказа                        | `VK-20260314-001`                                 |
| `#ORDER_DATE#`      | Дата создания заказа                | `14.03.2026 12:30`                                |
| `#ORDER_USER#`      | Имя клиента                         | `Иван Иванов`                                     |
| `#EMAIL#`           | Email клиента                       | `ivan@example.com`                                |
| `#PHONE#`           | Телефон клиента                     | `+79001234567`                                    |
| `#ORDER_LIST#`      | Состав заказа (товары + итоги)      | Многострочный текст с позициями, доставкой, итого |
| `#PRICE#`           | Итоговая сумма                      | `650.00 руб.`                                     |
| `#UNIQUE_ORDER_ID#` | Токен для публичной ссылки на заказ | `a1b2c3d4...`                                     |

### Поля доставки

Доступны во всех шаблонах CODFLOW и PREPAID. Заполняются из данных доставки заказа.

| Плейсхолдер         | Описание                                                               | Пример значения           |
|---------------------|------------------------------------------------------------------------|---------------------------|
| `#DELIVERCOMPANY#`  | Название компании доставки                                             | `5Post`, `Магнит Пост`    |
| `#PVZNAME#`         | Название пункта выдачи                                                 | `ПВЗ Арбат, ул. Арбат 10` |
| `#PVZID#`           | Идентификатор пункта выдачи                                            | `PP-12345`                |
| `#PVZDETAILS#`      | HTML-карточка пункта выдачи (адрес, режим работы, телефон, примечание) | Styled HTML block         |
| `#PVZDETAILS_TEXT#` | Текстовая версия деталей ПВЗ                                           | Многострочный текст       |

`#PVZDETAILS#` автоматически подгружает данные из кеша ПВЗ (`pickup_points_cache`) по `delivery_provider` + `pickup_point_id` заказа. Содержимое зависит от провайдера:

| Поле         | 5Post                                   | Магнит |
|--------------|-----------------------------------------|--------|
| Название     | Да                                      | Да     |
| Адрес        | Да                                      | Да     |
| Режим работы | Да (сгруппированный: Пн-Пт, Сб-Вс)      | Да     |
| Телефон      | Да                                      | Нет    |
| Примечание   | Да (напр. "Касса в магазине Пятёрочка") | Нет    |

Маппинг `delivery_provider` → `DELIVERCOMPANY`:
- `5post` → `5Post`
- `magnit` → `Магнит Пост`
- Другие значения передаются как есть

### Системные поля

Доступны во всех шаблонах. Берутся из конфигурации (`.env`).

| Плейсхолдер        | Описание                               | Откуда берётся           |
|--------------------|----------------------------------------|--------------------------|
| `#SERVER_NAME#`    | Домен сайта                            | `SERVER_NAME` в .env     |
| `#SHOP_NAME#`      | Название магазина                      | `SHOP_NAME` в .env       |
| `#SALE_EMAIL#`     | Email для связи (показывается клиенту) | `SALE_EMAIL` в .env      |
| `#SYS_SHOP_EMAIL#` | Email отправителя (SMTP)               | `SMTP_FROM_EMAIL` в .env |

### Поля клиентских событий

Доступны только в шаблонах OTHERS (CLIENTNEW, CLIENTRESETPASS, CLIENTREMINDPASS). Передаются в контексте события.

| Плейсхолдер             | Описание                                        | Пример значения |
|-------------------------|-------------------------------------------------|-----------------|
| `#CLIENTPASSWORD#`      | Пароль клиента (сгенерированный или сброшенный) | `Xk9mP2qr`      |
| `#CLIENTREGISTER_DATE#` | Дата регистрации                                | `14.03.2026`    |

---

## Формат файла шаблона

Файл `.template` состоит из заголовков `@@KEY: value` и тела после `@@BODY:`:

```
@@ENABLED: true
@@FROM: #SYS_SHOP_EMAIL#
@@TO: #EMAIL#
@@SUBJECT: #SHOP_NAME# — Заказ ##ORDER_ID# подтверждён
@@BODY:
Здравствуйте, #ORDER_USER#!

Ваш заказ ##ORDER_ID# от #ORDER_DATE# подтверждён.

Доставка: #DELIVERCOMPANY#
Пункт выдачи: #PVZNAME#

Состав заказа:
#ORDER_LIST#

Отследить: https://#SERVER_NAME#/#/orders/#UNIQUE_ORDER_ID#

С уважением,
#SHOP_NAME#
#SALE_EMAIL#
```

### Заголовки

| Заголовок   | Обязателен | Описание                                             |
|-------------|------------|------------------------------------------------------|
| `@@ENABLED` | Нет        | `true` (по умолчанию) или `false` — отключает шаблон |
| `@@FROM`    | Нет        | Адрес отправителя (по умолчанию `#SYS_SHOP_EMAIL#`)  |
| `@@TO`      | Нет        | Адрес получателя (по умолчанию `#EMAIL#`)            |
| `@@SUBJECT` | Да         | Тема письма                                          |
| `@@BODY`    | Да         | Маркер начала тела письма                            |

`@@TO` определяет кому уйдёт письмо:
- `#EMAIL#` — клиенту
- `#SALE_EMAIL#` — администратору

---

## Структура директорий

```
templates/email/
├── CODFLOW/                          ← Наложенный платёж
│   ├── PENDING_CONFIRMATION/         ← Заказ создан, ждёт подтверждения клиентом
│   │   └── client_confirm_request.template
│   ├── CONFIRMED_BY_CLIENT/          ← Клиент подтвердил, ждёт подтверждения магазина
│   │   ├── admin_confirm.template
│   │   └── client_confirm.template
│   ├── CONFIRMED/                    ← Магазин подтвердил
│   │   └── (шаблоны по необходимости)
│   ├── SHIPPED/                      ← Отправлен
│   │   └── client_shipped.template
│   ├── READY_FOR_PICKUP/             ← В пункте выдачи
│   │   └── client_ready.template
│   ├── DELIVERED/                    ← Вручён
│   │   └── client_delivered.template
│   ├── CLIENT_DONT_PICKUP/           ← Клиент не забрал
│   │   └── admin_aware.template
│   └── RETURNED_TO_SUPPLIER/         ← Возврат поставщику
│       └── admin_aware.template
│
├── PREPAID/                          ← Предоплата картой
│   ├── PENDING_PAYMENT/              ← Ожидает оплаты
│   │   └── client_pay_request.template
│   ├── PAID/                         ← Оплачен
│   │   ├── admin_msg.template
│   │   └── client_paid.template          (DISABLED)
│   ├── CONFIRMED/                    ← Подтверждён
│   │   ├── admin_confirm.template        (DISABLED)
│   │   └── client_confirm.template       (DISABLED)
│   ├── SHIPPED/                      ← Отправлен
│   │   └── client_shipped.template
│   ├── READY_FOR_PICKUP/             ← В пункте выдачи
│   │   └── client_ready.template
│   ├── DELIVERED/                    ← Вручён
│   │   ├── admin_msg.template
│   │   └── client_delivered.template
│   └── RETURNED_TO_SUPPLIER/         ← Возврат поставщику
│       └── admin_aware.template
│
└── OTHERS/                           ← Клиентские события (не заказы)
    ├── CLIENTNEW/                    ← Регистрация
    │   ├── admin_aware.template
    │   └── client_welcome.template
    ├── CLIENTRESETPASS/               ← Сброс пароля
    │   └── client_newpass.template
    └── CLIENTREMINDPASS/              ← Напоминание пароля
        └── client_remindpass.template
```

**Именование файлов:**
- `client_*.template` — письмо клиенту (`@@TO: #EMAIL#`)
- `admin_*.template` — письмо администратору (`@@TO: #SALE_EMAIL#`)

---

## Как добавить новый шаблон

1. Создай файл `.template` в нужной папке:
   ```
   templates/email/{ORDER_TYPE}/{STATUS}/{имя}.template
   ```

2. Добавь заголовки и тело:
   ```
   @@FROM: #SYS_SHOP_EMAIL#
   @@TO: #EMAIL#
   @@SUBJECT: Тема с #PLACEHOLDER#
   @@BODY:
   Текст письма с #PLACEHOLDER#
   ```

3. Перезапусти сервисы:
   ```bash
   systemctl restart vkus-api vkus-worker
   ```

Шаблон подхватится автоматически — система сканирует папку при каждом событии.

**Важно:** шаблоны загружаются с диска при каждом событии (не кешируются), поэтому после копирования на сервер достаточно рестарта для подхвата изменений в коде обработчиков. Сами файлы шаблонов перечитываются при каждом вызове `find_templates()`.

## Как отключить шаблон

Добавь `@@ENABLED: false` в заголовки:
```
@@ENABLED: false
@@FROM: #SYS_SHOP_EMAIL#
...
```

Или удали файл.

---

## Как работает маршрутизация

1. Происходит событие (например, `order_status_changed` с `new_status = "confirmed_by_client"`)
2. Обработчик определяет `order_type` заказа (`CODFLOW` или `PREPAID`)
3. Ищет шаблоны: `templates/email/CODFLOW/CONFIRMED_BY_CLIENT/*.template`
4. Для каждого найденного шаблона:
   - Загружает файл, проверяет `@@ENABLED`
   - Собирает контекст (`build_order_context`) — все мета-поля из таблиц выше
   - Подставляет `#PLACEHOLDER#` → реальные значения
   - Кладёт письмо в Redis-очередь
5. Worker (каждые 5 сек) берёт из очереди и отправляет через SMTP

Для событий клиента (`CLIENTNEW`, `CLIENTRESETPASS`, `CLIENTREMINDPASS`) путь:
`templates/email/OTHERS/{EVENT_NAME}/*.template`

---

## Список всех шаблонов

### CODFLOW (8 шт, все включены)

| Событие              | Файл                   | Кому   | Тема                                  |
|----------------------|------------------------|--------|---------------------------------------|
| PENDING_CONFIRMATION | client_confirm_request | Клиент | Подтвердите заказ                     |
| CONFIRMED_BY_CLIENT  | client_confirm         | Клиент | Заказ подтверждён                     |
| CONFIRMED_BY_CLIENT  | admin_confirm          | Админ  | Клиент подтвердил заказ (нал. платёж) |
| SHIPPED              | client_shipped         | Клиент | Заказ отправлен                       |
| READY_FOR_PICKUP     | client_ready           | Клиент | Заказ готов к выдаче                  |
| DELIVERED            | client_delivered       | Клиент | Заказ вручён                          |
| CLIENT_DONT_PICKUP   | admin_aware            | Админ  | Клиент не забрал заказ                |
| RETURNED_TO_SUPPLIER | admin_aware            | Админ  | Заказ возвращён поставщику            |

### PREPAID (10 шт, 3 отключены)

| Событие              | Файл               | Кому   | Тема                       | Включён |
|----------------------|--------------------|--------|----------------------------|---------|
| PENDING_PAYMENT      | client_pay_request | Клиент | Оплатите заказ             | Да      |
| PAID                 | admin_msg          | Админ  | Оплачен заказ (предоплата) | Да      |
| PAID                 | client_paid        | Клиент | Оплата получена            | **Нет** |
| CONFIRMED            | admin_confirm      | Админ  | Оплачен заказ              | **Нет** |
| CONFIRMED            | client_confirm     | Клиент | Заказ подтверждён          | **Нет** |
| SHIPPED              | client_shipped     | Клиент | Заказ отправлен            | Да      |
| READY_FOR_PICKUP     | client_ready       | Клиент | Заказ готов к выдаче       | Да      |
| DELIVERED            | admin_msg          | Админ  | Заказ доставлен клиенту    | Да      |
| DELIVERED            | client_delivered   | Клиент | Заказ вручён               | Да      |
| RETURNED_TO_SUPPLIER | admin_aware        | Админ  | Заказ возвращён поставщику | Да      |

### OTHERS (4 шт, все включены)

| Событие          | Файл              | Кому   | Тема                         |
|------------------|-------------------|--------|------------------------------|
| CLIENTNEW        | client_welcome    | Клиент | Добро пожаловать             |
| CLIENTNEW        | admin_aware       | Админ  | Новый клиент зарегистрирован |
| CLIENTRESETPASS  | client_newpass    | Клиент | Ваш новый пароль             |
| CLIENTREMINDPASS | client_remindpass | Клиент | Напоминание пароля           |
