# VKUS Online Backend — Архитектура системы

Дата: 2026-03-13

```
┌─────────────────────────────────────────────────────────────────────┐
│                         КЛИЕНТЫ                                     │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  Frontend     │    │  CLI Tool    │    │  YooKassa Webhooks   │  │
│  │  (React SPA)  │    │  vkus_cli.py │    │  5Post Webhooks      │  │
│  │  :5173 local  │    │  25 QA tests │    │                      │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
└─────────┼───────────────────┼───────────────────────┼──────────────┘
          │ HTTPS             │ HTTPS                 │ HTTPS
          ▼                   ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Nginx (reverse proxy)                             │
│                    api.vkus.online :443                              │
└─────────────────────────────────┬───────────────────────────────────┘
                              │ :8000
          ┌───────────────────┴───────────────────────┐
          ▼                                           ▼
┌───────────────────────┐              ┌──────────────────────────┐
│   vkus-api            │              │   vkus-worker            │
│   (systemd service)   │              │   (systemd service)      │
│                       │              │                          │
│   FastAPI + Uvicorn   │              │   APScheduler            │
│   14 роутеров         │              │   8 фоновых задач        │
│                       │              │                          │
│ ┌───────────────────┐ │              │ ┌──────────────────────┐ │
│ │ /auth             │ │              │ │ Email queue    (5s)  │─┼──── SMTP ──→ Yandex
│ │ /catalog          │ │              │ │ Cancel unpaid (10m)  │ │          :587 STARTTLS
│ │ /cart             │ │              │ │ Reconcile pay (30m)  │ │
│ │ /checkout ────────┼─┼── events ──→│ │ Magnit status (2h)   │ │
│ │ /orders           │ │              │ │ 5Post sync   (daily) │ │
│ │ /payments         │ │              │ │ Magnit sync  (daily) │ │
│ │ /public_orders    │ │              │ │ Cleanup guest(daily) │ │
│ │ /webhooks ────────┼─┼── events ──→│ │ Cleanup idemp(daily) │ │
│ │ /admin            │ │              │ └──────────┬───────────┘ │
│ │ /geo              │ │              │            │ read/write  │
│ │ /delivery_5post   │ │              │            ▼             │
│ │ /delivery_magnit  │ │              │  ┌─────────────────────┐ │
│ │ /me               │ │              │  │ send_email.py       │ │
│ │ /guest            │ │              │  │ _reclaim_stale()    │ │
│ │ /health           │ │              │  │ _pick_and_send()    │ │
│ └───────────────────┘ │              │  └─────────────────────┘ │
│                       │              └────────────┬─────────────┘
│  Event Dispatcher     │                           │
│  (in-process pub/sub) │                           │
│  ┌──────────────────┐ │                           │
│  │ order_created    │ │                           │
│  │ status_changed   │ │                           │
│  │ client_event     │ │                           │
│  └────────┬─────────┘ │                           │
└───────────┼───────────┘                           │
            │ HSET+ZADD                             │ ZRANGEBYSCORE
            │ (enqueue)                             │ (dequeue + send)
            ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Redis :6379                                  │
│                    (пароль, только localhost)                        │
│                                                                     │
│  ┌─── Email Queue (reliable) ──────────────────────────────────┐   │
│  │                                                              │   │
│  │  API кладёт ──→ email:msgs      Hash  (payload)             │   │
│  │                  email:pending   ZSet  (score = timestamp)   │   │
│  │                                                              │   │
│  │  Worker берёт → email:processing ZSet  (score = deadline)   │   │
│  │                                                              │   │
│  │  Успех ──────→ email:sent:{id}  String (TTL 24ч, dedup)    │   │
│  │  5 фейлов ──→ email:dead        Hash  (мёртвое письмо)     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  dadata:*          — кеш подсказок адресов (24ч-7д)                │
│  rate_limit:*      — счётчики rate limiting                        │
│  idempotency:*     — кеш идемпотентности                          │
└─────────────────────────────────────────────────────────────────────┘
            │
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   PostgreSQL :5432 (Docker)                          │
│                   (только localhost)                                 │
│                                                                     │
│  14 таблиц:                                                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐  │
│  │ users      │ │ orders     │ │ products   │ │ payments       │  │
│  │ profiles   │ │ order_items│ │ families   │ │ payment_events │  │
│  │ refresh_tok│ │ order_evnts│ │ cart_items │ │ pickup_cache   │  │
│  │ guest_sess │ │ discounts  │ │ idemp_recs │ │ webhook_events │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

                    ВНЕШНИЕ СЕРВИСЫ
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  YooKassa    │  │  DaData      │  │  Yandex SMTP             │  │
│  │  Платежи     │  │  Адреса      │  │  smtp.yandex.ru:587      │  │
│  │  Возвраты    │  │  Геокодинг   │  │  STARTTLS                │  │
│  │  Webhooks    │  │  Кеш в Redis │  │  shop@coffee-tea.ru      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐                                │
│  │  5Post       │  │  Magnit Post │                                │
│  │  ПВЗ + доств │  │  ПВЗ + доств │                                │
│  │  Трекинг     │  │  Трекинг     │                                │
│  │  Этикетки    │  │  Этикетки    │                                │
│  │  Webhooks    │  │  Polling 2ч  │                                │
│  └──────────────┘  └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
```

## Поток заказа (Order Flow)

```
Клиент → POST /checkout → create_order()
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
         PREPAID (карта)               CODFLOW (налож. платёж)
              │                               │
     PENDING_PAYMENT                 PENDING_CONFIRMATION
              │                               │
     → YooKassa оплата              → POST /orders/{token}/confirm
              │                               │
           PAID                      CONFIRMED_BY_CLIENT
              │                        (клиент подтвердил,
         CONFIRMED                    ждёт подтверждения магазина)
              │                               │
              │                          CONFIRMED
              │                          (магазин подтвердил)
              │                               │
              └──────── admin ────────→ SHIPPED → READY_FOR_PICKUP → DELIVERED
                                                    │
                                          (или CLIENT_DONT_PICKUP
                                           → RETURNED_TO_SUPPLIER)
```

## Поток email

```
Событие (order_created / status_changed / client_event)
    │
    ▼
EventDispatcher → order_handlers.py
    │
    ▼
find_templates("templates/email/{TYPE}/{STATUS}/")
    │
    ▼
render_template(tmpl, context)  — подстановка #PLACEHOLDER#
    │
    ▼
Redis: HSET email:msgs + ZADD email:pending
    │
    ▼  (Worker каждые 5 сек)
ZRANGEBYSCORE email:pending → atomic ZREM → ZADD email:processing (lease 60s)
    │
    ▼
aiosmtplib → smtp.yandex.ru:587 STARTTLS
    │
    ├─ OK  → SETEX email:sent:{id} (24ч dedup) → HDEL email:msgs
    │
    └─ FAIL → retry с backoff (10s × attempt)
              └─ 5 fails → HSET email:dead (мёртвое письмо)
```

## Роутеры API (14 шт)

| Роутер           | Назначение                                            |
|------------------|-------------------------------------------------------|
| /health          | Healthcheck                                           |
| /auth            | Регистрация, логин, refresh, logout, check-email      |
| /guest           | Гостевые сессии                                       |
| /catalog         | Каталог товаров                                       |
| /geo             | Подсказки адресов (DaData)                            |
| /cart            | Корзина                                               |
| /checkout        | Создание заказа, расчёт доставки/оплаты               |
| /orders          | Заказы пользователя/гостя                             |
| /payments        | Создание платежа YooKassa                             |
| /delivery_5post  | ПВЗ и доставка 5Post                                  |
| /delivery_magnit | ПВЗ и доставка Magnit                                 |
| /me              | Профиль авторизованного пользователя                  |
| /public_orders   | Публичный трекинг заказа (без авторизации, по токену) |
| /webhooks        | Вебхуки YooKassa и 5Post                              |
| /admin           | Админ: заказы, клиенты, ручной запуск задач           |

## Таблицы БД (14 шт)

| Таблица                 | Назначение                                                     |
|-------------------------|----------------------------------------------------------------|
| users                   | Пользователи (email, phone, password_hash, plain_password)     |
| user_profiles           | Расширенный профиль (имя, фамилия)                             |
| refresh_tokens          | JWT refresh-токены с ротацией                                  |
| products                | Каталог: SKU, цена (копейки), вес, изображения, вкусы          |
| product_families        | Группировка продуктов (опционально)                            |
| orders                  | Заказы: статус, тип (PREPAID/CODFLOW), клиент, доставка, итого |
| order_items             | Позиции заказа                                                 |
| order_events            | Аудит-лог смены статусов                                       |
| payments                | Платежи, привязка к заказу                                     |
| payment_events          | Аудит-лог платежей                                             |
| pickup_point_cache      | Кеш ПВЗ (5Post, Magnit)                                        |
| guest_sessions          | Гостевые сессии (TTL 180д)                                     |
| idempotency_records     | Дедупликация запросов                                          |
| provider_webhook_events | Сырые вебхуки для отладки                                      |

## Система логирования

Конфигурация: `log_config.yaml`

```
logs/
├── api/
│   ├── api.log                  ← все HTTP-запросы (summary)
│   ├── errors.log               ← только WARNING+ ошибки
│   ├── requests/2026-03-13/     ← detail JSON (вкл/выкл в конфиге)
│   │   └── 0001_f350_17-39-58.json
│   ├── auth/auth.log            ← роутер /auth + сервис auth
│   ├── checkout/checkout.log    ← роутер /checkout + сервис checkout
│   ├── payments/payments.log    ← роутер /payments + сервис payments
│   ├── delivery/delivery.log    ← роутеры delivery_5post, delivery_magnit
│   ├── orders/orders.log        ← роутер /orders
│   ├── admin/admin.log          ← роутер /admin
│   └── public_orders/...
├── worker/
│   ├── worker.log               ← все worker-задачи (summary)
│   ├── errors.log               ← ошибки worker
│   ├── email_queue/email_queue.log
│   ├── cancel_unpaid/cancel_unpaid.log
│   ├── reconcile_payments/...
│   ├── sync_5post/...
│   ├── sync_magnit/...
│   └── poll_magnit/...
├── events/
│   └── events.log               ← EventDispatcher
├── integrations/
│   ├── yookassa/yookassa.log
│   ├── fivepost/fivepost.log
│   ├── magnit/magnit.log
│   └── dadata/dadata.log
└── _archive/                    ← сжатые старые логи
```

Ключевые возможности:
- **Маршрутизация**: логи автоматически попадают в нужный файл по имени logger
- **Маскирование**: password, access_token, Authorization маскируются (SuperSec***)
- **Ротация**: RotatingFileHandler (50 МБ, 5 копий)
- **Очистка**: Worker job `cleanup_logs` (ежедневно 02:00) — архивация, удаление старых
- **Detail JSON**: полные request/response для отладки (вкл/выкл в конфиге)
- **Два уровня**: summary (api.log/worker.log) + per-router/per-job файлы

## Фоновые задачи Worker (9 шт)

| Задача                     | Интервал       | Назначение                                    |
|----------------------------|----------------|-----------------------------------------------|
| process_email_queue        | 5 сек          | Отправка email из Redis-очереди               |
| cancel_unpaid_orders       | 10 мин         | Автоотмена неоплаченных PREPAID (>30 мин)     |
| reconcile_pending_payments | 30 мин         | Сверка статусов платежей с YooKassa           |
| poll_magnit_statuses       | 2 часа         | Опрос Magnit API по статусам доставок         |
| sync_5post_points          | ежедневно 6:30 | Синхронизация ПВЗ 5Post                       |
| sync_magnit_points         | ежедневно 7:00 | Синхронизация ПВЗ Magnit                      |
| cleanup_logs               | ежедневно 2:00 | Ротация, архивация и очистка логов            |
| cleanup_guest_sessions     | ежедневно 3:00 | Удаление просроченных гостевых сессий (>180д) |
| cleanup_idempotency_keys   | ежедневно 4:00 | Удаление просроченных ключей идемпотентности  |

## Сводка

| Компонент   | Технология            | Порт  |
|-------------|-----------------------|-------|
| API         | FastAPI + Uvicorn     | :8000 |
| Worker      | APScheduler (9 задач) | —     |
| БД          | PostgreSQL (Docker)   | :5432 |
| Кеш/очереди | Redis                 | :6379 |
| Прокси      | Nginx                 | :443  |
| SMTP        | Yandex STARTTLS       | :587  |
| Платежи     | YooKassa API          | —     |
| Адреса      | DaData API            | —     |
| Доставка    | 5Post + Magnit        | —     |
