# Сервисы и перезапуск

## Архитектура сервисов

На сервере работают **4 компонента**, связанных с бэкендом:

```
┌─────────────────────┐      ┌──────────────────────┐
│   vkus-api           │      │   vkus-worker          │
│   (systemd)          │      │   (systemd)            │
│                      │      │                        │
│   FastAPI + Uvicorn  │      │   APScheduler          │
│   HTTP API :8000     │      │   9 фоновых задач      │
│                      │      │                        │
│   apps/api/main.py   │      │   apps/worker/main.py  │
└──────────┬───────────┘      └──────────┬─────────────┘
           │                             │
           └──────────┬──────────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
    ▼                 ▼                 ▼
┌─────────┐   ┌────────────┐   ┌────────────┐
│  Nginx   │   │  Redis     │   │ PostgreSQL │
│ (system) │   │  (Docker)  │   │ (Docker)   │
│  :443    │   │  :6379     │   │  :5432     │
└─────────┘   └────────────┘   └────────────┘
```

### 1. vkus-api (systemd)
- FastAPI + Uvicorn, HTTP API на порту 8000
- Обрабатывает все входящие запросы (15 роутеров)
- При событиях (заказ создан, статус изменён) кладёт email в Redis-очередь
- Пишет логи в `logs/api/`

### 2. vkus-worker (systemd)
- APScheduler, 9 фоновых задач (email, отмена заказов, синхронизация ПВЗ и др.)
- Пишет логи в `logs/worker/`

### 3. PostgreSQL (Docker-контейнер)
- Основная база данных: 14 таблиц (заказы, пользователи, товары, платежи и др.)
- Образ: `postgres:16-alpine`
- Порт: `127.0.0.1:5432` (только localhost)
- Данные хранятся в Docker volume `postgres_data` (переживают перезапуск контейнера)
- Свои логи внутри контейнера (см. `docker logs`)
- **Система логов бэкенда НЕ пишет в PostgreSQL** — логи идут только в файлы и stdout

### 4. Redis (Docker-контейнер)
- Очереди, кеш, rate limiting
- Образ: `redis:7-alpine`
- Порт: `127.0.0.1:6379` (только localhost, с паролем)
- Данные: Docker volume `redis_data`
- Что хранит Redis:
  - `email:msgs`, `email:pending`, `email:processing`, `email:dead` — email-очередь
  - `email:sent:{id}` — dedup-ключи (TTL 24ч)
  - `dadata:*` — кеш подсказок адресов (24ч-7д)
  - `rate_limit:*` — счётчики rate limiting
  - `idempotency:*` — кеш идемпотентности
- **Система логов бэкенда НЕ использует Redis** — логи пишутся в файлы напрямую

### Что НЕ относится к бэкенду (PrestaShop — старый магазин)
- `httpd` (Apache) — веб-сервер PrestaShop
- `php-fpm` — PHP для PrestaShop
- `mariadb` — база данных PrestaShop

Не трогай их при деплое бэкенда.

---

**Общие свойства vkus-api и vkus-worker:**
- Загружают конфигурацию (`log_config.yaml`, `.env`) **один раз при старте**
- Имеют собственный Python-процесс и свою копию кода в памяти
- Общаются только через Redis и PostgreSQL
- **НЕ подхватывают изменения файлов/конфигов без рестарта**

## Команды управления

### Перезапуск (самая частая операция)

```bash
# С локальной машины:
ssh vkus.com "systemctl restart vkus-api vkus-worker"

# Если уже на сервере:
systemctl restart vkus-api vkus-worker
```

**Всегда перезапускай ОБА сервиса.** Worker — отдельный процесс, он не узнает об изменениях в коде или конфигах без рестарта.

### Проверка статуса

```bash
systemctl status vkus-api vkus-worker
```

### Логи запуска (systemd journal)

```bash
# Последние 20 строк
journalctl -u vkus-api -n 20 --no-pager
journalctl -u vkus-worker -n 20 --no-pager

# В реальном времени (follow)
journalctl -u vkus-api -f
journalctl -u vkus-worker -f
```

### Остановка / запуск по отдельности

```bash
systemctl stop vkus-api
systemctl start vkus-api

systemctl stop vkus-worker
systemctl start vkus-worker
```

## Docker-контейнеры (PostgreSQL + Redis)

### Проверка состояния

```bash
# На сервере:
cd /opt/vkus-backend && docker compose ps
```

### Логи контейнеров

```bash
# PostgreSQL
docker logs vkus-backend-postgres-1 --tail 20
docker logs vkus-backend-postgres-1 -f          # follow

# Redis
docker logs vkus-backend-redis-1 --tail 20
docker logs vkus-backend-redis-1 -f
```

### Перезапуск контейнеров

**Обычно перезапускать контейнеры НЕ нужно.** Они работают постоянно и переживают перезапуск API/Worker. Перезапускать стоит только если:
- Контейнер упал (проверь через `docker compose ps`)
- Нужно изменить конфигурацию Docker (пароль Redis, параметры PostgreSQL)
- Обновление версии (postgres:16 → postgres:17)

```bash
# Перезапуск конкретного контейнера
cd /opt/vkus-backend && docker compose restart redis
cd /opt/vkus-backend && docker compose restart postgres

# Перезапуск обоих
cd /opt/vkus-backend && docker compose restart redis postgres

# Полная пересоздание (если изменился docker-compose.yml)
cd /opt/vkus-backend && docker compose down && docker compose up -d
```

**ВНИМАНИЕ**: `docker compose down` останавливает контейнеры, но данные сохраняются в Docker volumes (`postgres_data`, `redis_data`). Но `docker compose down -v` **УДАЛИТ ВСЕ ДАННЫЕ** — никогда не используй флаг `-v` на проде!

### Влияние на бэкенд при перезапуске контейнеров

| Контейнер      | Что произойдёт если перезапустить                                                                                                                                                   |
|----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **PostgreSQL** | API и Worker потеряют соединение. Запросы упадут с 500, worker-задачи упадут с ошибкой. После старта PostgreSQL соединения восстановятся автоматически (SQLAlchemy pool reconnect). |
| **Redis**      | Email-очередь, кеш и rate limiting станут недоступны. Email не будет отправляться. После старта Redis всё восстановится — данные сохраняются на диск (volume).                      |

**Рекомендация**: если нужно перезапустить контейнеры, делай это в период минимальной нагрузки (ночь). Перезапуск занимает 2-5 секунд.

### Система логов и Docker-контейнеры

Система логов бэкенда (`log_config.yaml`, файлы в `logs/`) **никак не связана с Docker-контейнерами**:
- Логи бэкенда пишутся в файлы на диск сервера (`/opt/vkus-backend/logs/`)
- PostgreSQL и Redis имеют свои собственные логи внутри контейнеров (доступны через `docker logs`)
- Изменение `log_config.yaml` не влияет на PostgreSQL/Redis
- Перезапуск контейнеров не влияет на файлы логов бэкенда

## Когда нужен рестарт

| Что изменилось                        | Нужен рестарт?                                      |
|---------------------------------------|-----------------------------------------------------|
| Код Python (роутеры, сервисы, модели) | Да, оба                                             |
| `log_config.yaml`                     | Да, оба                                             |
| `.env`                                | Да, оба                                             |
| Email-шаблоны (`templates/email/`)    | Да, оба (шаблоны читаются при загрузке)             |
| Alembic-миграция                      | Сначала `alembic upgrade head`, потом рестарт обоих |
| `nginx.conf`                          | `systemctl reload nginx` (отдельно, не vkus-*)      |
| Данные в PostgreSQL / Redis           | Нет                                                 |

## Что происходит с email-очередью при рестарте

Очередь email хранится в **Redis**, не в памяти процесса. При рестарте ничего не теряется:

| Состояние письма            | Где хранится                       | Что произойдёт                                                                     |
|-----------------------------|------------------------------------|------------------------------------------------------------------------------------|
| **Pending** (ждёт отправки) | `email:pending` (Redis ZSet)       | Worker подберёт через ~5 сек после старта                                          |
| **Processing** (в процессе) | `email:processing` (Redis ZSet)    | У каждого письма lease 60 сек. После истечения `_reclaim_stale()` вернёт в pending |
| **Sent** (отправлено)       | `email:sent:{id}` (Redis, TTL 24ч) | Не затрагивается                                                                   |
| **Dead** (5 неудач)         | `email:dead` (Redis Hash)          | Не затрагивается                                                                   |

**Единственный edge case**: если Worker отправил письмо через SMTP, но упал до записи `email:sent:{id}` — письмо может отправиться повторно. Это окно в миллисекунды и не критично.

## Задачи Worker (9 шт)

| Задача                       | Интервал       | Описание                                  |
|------------------------------|----------------|-------------------------------------------|
| `process_email_queue`        | 5 сек          | Отправка email из Redis                   |
| `cancel_unpaid_orders`       | 10 мин         | Автоотмена неоплаченных PREPAID (>30 мин) |
| `reconcile_pending_payments` | 30 мин         | Сверка платежей с YooKassa                |
| `poll_magnit_statuses`       | 2 часа         | Опрос Magnit API                          |
| `sync_5post_points`          | ежедневно 6:30 | Синхронизация ПВЗ 5Post                   |
| `sync_magnit_points`         | ежедневно 7:00 | Синхронизация ПВЗ Magnit                  |
| `cleanup_logs`               | ежедневно 2:00 | Ротация и очистка логов                   |
| `cleanup_guest_sessions`     | ежедневно 3:00 | Удаление старых гостевых сессий           |
| `cleanup_idempotency_keys`   | ежедневно 4:00 | Удаление старых ключей идемпотентности    |

## Порядок деплоя

```bash
# 1. Скопировать файлы на сервер
scp -r backend/* vkus.com:/opt/vkus-backend/

# 2. Если есть миграция
ssh vkus.com "cd /opt/vkus-backend && .venv/bin/alembic upgrade head"

# 3. Перезапустить ОБА сервиса
ssh vkus.com "systemctl restart vkus-api vkus-worker"

# 4. Проверить
ssh vkus.com "systemctl status vkus-api vkus-worker"
curl https://api.vkus.online/api/v1/health
```
