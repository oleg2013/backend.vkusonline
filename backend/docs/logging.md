# Система логирования — руководство

## Общее описание

Система логов пишет структурированные JSON-записи в файлы на диске сервера (`/opt/vkus-backend/logs/`). Каждый лог автоматически маршрутизируется в нужный файл по имени модуля, который его создал.

Система работает в двух процессах:
- **vkus-api** — логирует HTTP-запросы, ошибки, работу роутеров
- **vkus-worker** — логирует фоновые задачи (email, синхронизация ПВЗ и т.д.)

Система логов **не связана с Docker-контейнерами** (PostgreSQL, Redis). Она пишет только в файлы на диск.

---

## Конфигурационный файл

Файл: **`log_config.yaml`** в корне проекта (на сервере: `/opt/vkus-backend/log_config.yaml`).

**Изменения применяются только после перезапуска сервисов:**
```bash
systemctl restart vkus-api vkus-worker
```

Если файл отсутствует или повреждён — система запустится с дефолтными настройками (всё включено на уровне INFO).

---

## Структура конфига

### 1. global — глобальные настройки

```yaml
global:
  log_dir: "logs"           # папка для логов (относительно рабочей директории)
  default_level: "INFO"     # минимальный уровень логирования
  format: "json"            # формат вывода в stdout
  stdout: true              # дублировать логи в stdout (видно в journalctl)
```

**Уровни логирования** (от самого подробного к самому строгому):
| Уровень   | Что попадёт в лог                                                   |
|-----------|---------------------------------------------------------------------|
| `DEBUG`   | Всё: отладочная информация, кеш-попадания, детали запросов          |
| `INFO`    | Нормальная работа: HTTP-запросы, отправка email, смена статусов     |
| `WARNING` | Предупреждения: таймауты, повторные попытки, подозрительные запросы |
| `ERROR`   | Ошибки: неудачные API-вызовы, ошибки БД, SMTP-ошибки                |

`default_level` — это глобальный фильтр. Если стоит `INFO`, то все `DEBUG`-записи будут отброшены **до того, как дойдут до файлов**. Это означает, что даже если у конкретного роутера или интеграции стоит `level: "DEBUG"`, но глобальный уровень `INFO` — DEBUG-записи всё равно не появятся.

**Чтобы увидеть DEBUG-логи:**
```yaml
global:
  default_level: "DEBUG"    # разрешить DEBUG глобально
```

**format** — влияет только на stdout (journalctl):
- `"json"` — машиночитаемый JSON (удобно для grep/jq)
- `"text"` — цветной human-readable формат (удобно для глаз)

В файлы всегда пишется JSON, независимо от этой настройки.

**stdout** — если `false`, логи пойдут только в файлы, в journalctl ничего не будет. Полезно если хочешь уменьшить нагрузку на диск journald.

---

### 2. retention — ротация и очистка

```yaml
retention:
  max_file_size_mb: 50       # ротация файла при превышении размера
  max_files: 5               # сколько ротированных копий хранить
  max_age_days: 30           # удалять логи старше N дней
  archive_after_days: 7      # сжимать папки requests/ в tar.gz через N дней
  detail_max_age_days: 3     # detail JSON хранить N дней
  cleanup_cron: "02:00"      # время ежедневной очистки (Worker job)
```

**Как работает ротация:**
- Когда файл (например `api.log`) достигает `max_file_size_mb` (50 МБ), он переименовывается в `api.log.1`, а создаётся новый пустой `api.log`
- Предыдущий `api.log.1` становится `api.log.2` и т.д.
- Когда копий больше `max_files` (5), самая старая удаляется
- Итого максимум на один файл: 50 МБ × 6 = 300 МБ (текущий + 5 ротированных)

**Очистка** выполняется Worker-задачей `cleanup_logs` ежедневно в 02:00:
1. Удаляет detail JSON старше `detail_max_age_days`
2. Архивирует папки requests/ старше `archive_after_days` в tar.gz
3. Удаляет архивы старше `max_age_days`
4. Чистит лишние ротированные файлы

---

### 3. api — настройки API-сервиса

#### 3.1 summary — общий лог всех HTTP-запросов

```yaml
api:
  summary:
    enabled: true       # писать ли api/api.log
    level: "INFO"
```

Файл: `logs/api/api.log`

Каждая строка — один HTTP-запрос:
```json
{"ts": "2026-03-13T17:47:54Z", "level": "info", "logger": "apps.api.requests", "msg": "http_request", "request_id": "86d3495c", "method": "POST", "path": "/api/v1/geo/city-suggest", "data": {"status": 200, "duration_ms": 124.8, "user_id": null, "ip": "109.228.88.151"}}
```

#### 3.2 detail_requests — полные request/response (для отладки)

```yaml
api:
  detail_requests:
    enabled: false              # ПО УМОЛЧАНИЮ ВЫКЛЮЧЕН — включать только для отладки!
    level: "DEBUG"
    include_headers: true       # записывать HTTP-заголовки
    include_request_body: true  # записывать тело запроса
    include_response_body: true # записывать тело ответа
    max_body_size: 10000        # обрезать body длиннее N символов
    mask_fields:                # поля, значения которых маскируются (***)
      - password
      - plain_password
      - access_token
      - refresh_token
      - Authorization
```

Когда `enabled: true`, для каждого HTTP-запроса создаётся отдельный JSON-файл:
```
logs/api/requests/2026-03-14/0001_86d3_17-47-54.json
```

Содержимое — полный request + response с заголовками и телами. Чувствительные поля из `mask_fields` автоматически заменяются на `***`.

**ВНИМАНИЕ:** при включении detail_requests объём логов резко возрастает! Используй только для отладки конкретной проблемы, потом выключай обратно.

**Типичный сценарий:** на проде сломался какой-то запрос, в `api.log` видно только статус 500. Включаешь `detail_requests`, перезапускаешь, воспроизводишь проблему, смотришь полный JSON с телом запроса/ответа, находишь причину, выключаешь обратно.

#### 3.3 errors — лог ошибок

```yaml
api:
  errors:
    enabled: true
    level: "WARNING"
    include_traceback: true
```

Файл: `logs/api/errors.log`

Сюда попадают **только** записи уровня WARNING и выше из API-части. Удобно для мониторинга — если файл растёт, значит есть проблемы.

#### 3.4 routers — индивидуальные логи роутеров

```yaml
api:
  routers:
    auth:          { enabled: true, level: "INFO" }
    checkout:      { enabled: true, level: "INFO" }
    payments:      { enabled: true, level: "INFO" }
    delivery:      { enabled: true, level: "INFO" }
    admin:         { enabled: true, level: "INFO" }
    webhooks:      { enabled: true, level: "INFO" }
    orders:        { enabled: true, level: "INFO" }
    public_orders: { enabled: true, level: "INFO" }
    catalog:       { enabled: false }    # выключен — слишком частые запросы
    cart:          { enabled: false }     # выключен — слишком частые запросы
    geo:           { enabled: false }     # выключен
```

Когда роутер включён (`enabled: true`), его логи пишутся в отдельный файл:
```
logs/api/auth/auth.log
logs/api/checkout/checkout.log
logs/api/payments/payments.log
logs/api/delivery/delivery.log    ← delivery_5post + delivery_magnit
logs/api/admin/admin.log
logs/api/webhooks/webhooks.log
logs/api/orders/orders.log
logs/api/public_orders/public_orders.log
```

**Важно:** даже если роутер выключен, его записи всё равно попадут в общий `api/api.log` (если summary включен) и в `api/errors.log` (если уровень WARNING+). `enabled: false` отключает только индивидуальный файл.

**Маршрутизация по имени модуля:**
- `apps.api.routers.auth` → `auth`
- `apps.api.routers.checkout` → `checkout`
- `apps.api.routers.delivery_5post` → `delivery`
- `apps.api.routers.delivery_magnit` → `delivery`
- `apps.api.routers.me` → `auth` (профиль относится к auth)
- `apps.api.routers.guest` → `auth` (гостевые сессии тоже)
- `packages.services.auth` → `auth` (сервисный слой auth)
- `packages.services.checkout` → `checkout`
- и т.д.

---

### 4. worker — настройки Worker-сервиса

#### 4.1 summary — общий лог Worker

```yaml
worker:
  summary:
    enabled: true
    level: "INFO"
```

Файл: `logs/worker/worker.log` — все записи от всех Worker-задач в одном файле.

Аналогично API, есть `logs/worker/errors.log` для ошибок.

#### 4.2 jobs — индивидуальные логи задач

```yaml
worker:
  jobs:
    email_queue:         { enabled: true,  level: "INFO" }
    cancel_unpaid:       { enabled: true,  level: "INFO" }
    reconcile_payments:  { enabled: true,  level: "INFO" }
    sync_5post:          { enabled: true,  level: "INFO" }
    sync_magnit:         { enabled: true,  level: "INFO" }
    poll_magnit:         { enabled: true,  level: "INFO" }
    cleanup_guests:      { enabled: false }
    cleanup_idempotency: { enabled: false }
```

Файлы:
```
logs/worker/email_queue/email_queue.log
logs/worker/cancel_unpaid/cancel_unpaid.log
logs/worker/reconcile_payments/reconcile_payments.log
logs/worker/sync_5post/sync_5post.log
logs/worker/sync_magnit/sync_magnit.log
logs/worker/poll_magnit/poll_magnit.log
```

Та же логика: `enabled: false` отключает только индивидуальный файл, в `worker.log` и `errors.log` записи всё равно попадут.

---

### 5. events — Event Dispatcher

```yaml
events:
  enabled: true
  level: "INFO"
```

Файл: `logs/events/events.log`

Сюда пишутся события системы: `order_created`, `order_status_changed`, `client_event`. Эти события запускают email-уведомления.

---

### 6. integrations — внешние API

```yaml
integrations:
  yookassa:
    enabled: true
    level: "INFO"
    log_request_body: true       # логировать тело запроса к API
    log_response_body: true      # логировать тело ответа от API
    mask_fields: [secret_key]    # маскировать поля

  fivepost:
    enabled: true
    level: "INFO"
    log_request_body: false
    log_response_body: false

  magnit:
    enabled: true
    level: "INFO"
    log_request_body: false
    log_response_body: false

  dadata:
    enabled: true
    level: "DEBUG"               # можно ставить DEBUG для детальной отладки
    log_request_body: true
    log_response_body: true
```

Файлы:
```
logs/integrations/yookassa/yookassa.log
logs/integrations/fivepost/fivepost.log
logs/integrations/magnit/magnit.log
logs/integrations/dadata/dadata.log
```

**log_request_body / log_response_body** — это флаги для кода интеграций. Если включены, в лог пишется полное тело запроса/ответа к внешнему API. Полезно для отладки, но увеличивает объём.

**mask_fields** — поля, значения которых маскируются. Для YooKassa маскируется `secret_key`.

---

## Структура файлов логов

```
logs/
├── api/
│   ├── api.log                    ← ВСЕ HTTP-запросы (summary)
│   ├── errors.log                 ← только WARNING+ ошибки API
│   ├── requests/                  ← detail JSON (только при enabled: true)
│   │   └── 2026-03-14/
│   │       └── 0001_86d3_17-47-54.json
│   ├── auth/auth.log
│   ├── checkout/checkout.log
│   ├── payments/payments.log
│   ├── delivery/delivery.log
│   ├── webhooks/webhooks.log
│   ├── orders/orders.log
│   ├── admin/admin.log
│   └── public_orders/public_orders.log
├── worker/
│   ├── worker.log                 ← ВСЕ задачи Worker (summary)
│   ├── errors.log                 ← только WARNING+ ошибки Worker
│   ├── email_queue/email_queue.log
│   ├── cancel_unpaid/cancel_unpaid.log
│   ├── reconcile_payments/reconcile_payments.log
│   ├── sync_5post/sync_5post.log
│   ├── sync_magnit/sync_magnit.log
│   └── poll_magnit/poll_magnit.log
├── events/
│   └── events.log                 ← EventDispatcher
├── integrations/
│   ├── yookassa/yookassa.log
│   ├── fivepost/fivepost.log
│   ├── magnit/magnit.log
│   └── dadata/dadata.log
└── _archive/                      ← сжатые старые логи
```

---

## Формат записи

Каждая строка в лог-файле — JSON-объект:

```json
{
  "ts": "2026-03-14T10:30:15.123456Z",
  "level": "info",
  "logger": "apps.api.routers.checkout",
  "msg": "order_created",
  "request_id": "a1b2c3d4-e5f6-...",
  "method": "POST",
  "path": "/api/v1/checkout",
  "data": {
    "order_id": 42,
    "order_type": "codflow",
    "total": 189000
  }
}
```

| Поле             | Описание                                                 |
|------------------|----------------------------------------------------------|
| `ts`             | Время в формате ISO 8601 (UTC)                           |
| `level`          | Уровень: debug, info, warning, error                     |
| `logger`         | Имя Python-модуля, создавшего запись                     |
| `msg`            | Событие (event name)                                     |
| `request_id`     | ID запроса (если есть)                                   |
| `method`, `path` | HTTP-метод и путь (если есть)                            |
| `data`           | Дополнительные данные (всё что не вошло в основные поля) |

---

## Маскирование секретов

Поля, перечисленные в `mask_fields`, автоматически маскируются в логах:

```
password: "my_secret_123"  →  password: "my_secre***"
Authorization: "Bearer eyJ..."  →  Authorization: "Bearer e***"
```

Правило: если значение длиннее 8 символов — показываются первые 8, остальное заменяется на `***`. Если короче 8 — показывается просто `***`.

Маскирование работает рекурсивно — вложенные объекты и массивы тоже обрабатываются.

---

## Типичные сценарии

### Отладка конкретного запроса

1. Включить detail requests:
```yaml
api:
  detail_requests:
    enabled: true
```
2. Перезапустить: `systemctl restart vkus-api vkus-worker`
3. Воспроизвести проблему
4. Посмотреть: `ls /opt/vkus-backend/logs/api/requests/$(date +%Y-%m-%d)/`
5. **Не забыть выключить обратно** и перезапустить!

### Посмотреть ошибки за сегодня

```bash
ssh vkus.com "cat /opt/vkus-backend/logs/api/errors.log | tail -50"
```

### Посмотреть логи конкретного роутера

```bash
ssh vkus.com "cat /opt/vkus-backend/logs/api/checkout/checkout.log | tail -20"
```

### Следить за email-отправкой

```bash
ssh vkus.com "tail -f /opt/vkus-backend/logs/worker/email_queue/email_queue.log"
```

### Посмотреть логи интеграции с YooKassa

```bash
ssh vkus.com "cat /opt/vkus-backend/logs/integrations/yookassa/yookassa.log | tail -20"
```

### Фильтрация JSON-логов через jq

```bash
# Все запросы со статусом 500
ssh vkus.com "cat /opt/vkus-backend/logs/api/api.log | jq -c 'select(.data.status == 500)'"

# Все запросы к checkout
ssh vkus.com "cat /opt/vkus-backend/logs/api/api.log | jq -c 'select(.path | contains(\"checkout\"))'"

# Запросы медленнее 1 секунды
ssh vkus.com "cat /opt/vkus-backend/logs/api/api.log | jq -c 'select(.data.duration_ms > 1000)'"
```

### Включить максимальную детализацию (временно)

```yaml
global:
  default_level: "DEBUG"

api:
  detail_requests:
    enabled: true

integrations:
  dadata:
    level: "DEBUG"
    log_request_body: true
    log_response_body: true
```

Перезапустить, отладить, **вернуть обратно**, перезапустить.

---

## Чего НЕ нужно делать

- **Не оставлять `detail_requests: enabled: true` на проде** — быстро забьёт диск
- **Не ставить `default_level: "DEBUG"` надолго** — слишком много записей
- **Не редактировать файлы логов вручную** — ротация может сломаться
- **Не удалять `log_config.yaml`** — система запустится с дефолтами, но поведение может отличаться от ожидаемого
