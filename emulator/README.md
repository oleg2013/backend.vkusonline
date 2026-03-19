# Delivery API Emulator (5Post & Magnit)

Эмулятор API служб доставки 5Post и Magnit для тестирования жизненного цикла заказов без обращения к реальным API вендоров.

## Быстрый старт

### 1. Установка зависимостей

```bash
cd emulator
pip install -e .
```

### 2. Настройка

```bash
cp .env.example .env
# Отредактируйте DATABASE_URL — должен указывать на ту же PostgreSQL, что и основной бэкенд
```

### 3. Запуск сервера

```bash
cd emulator
python main.py
# или
uvicorn main:app --host 0.0.0.0 --port 8001
```

Таблицы в БД создаются автоматически при старте (с префиксом `emul_`).

### 4. Переключение бэкенда на эмулятор

В `.env` основного бэкенда измените:

```env
FIVEPOST_BASE_URL=https://5post-emul-api.vkus.online
MAGNIT_BASE_URL=https://magnit-emul-api.vkus.online
```

Перезапустите бэкенд:

```bash
systemctl restart vkus-api vkus-worker
```

## CLI-админка

Интерактивный инструмент для управления заказами в эмуляторе:

```bash
cd emulator
python cli.py
```

### Возможности

| Команда | Описание                                   |
|---------|--------------------------------------------|
| **1**   | 5Post — Список заказов                     |
| **2**   | 5Post — Детали заказа                      |
| **3**   | 5Post — Продвинуть статус (следующий шаг)  |
| **4**   | 5Post — Продвинуть ВСЕ заказы на шаг       |
| **5**   | 5Post — Установить произвольный статус     |
| **6**   | 5Post — Показать lifecycle                 |
| **11**  | Magnit — Список заказов                    |
| **12**  | Magnit — Детали заказа                     |
| **13**  | Magnit — Продвинуть статус (следующий шаг) |
| **14**  | Magnit — Продвинуть ВСЕ заказы на шаг      |
| **15**  | Magnit — Установить произвольный статус    |
| **16**  | Magnit — Показать lifecycle                |
| **20**  | Статистика                                 |

## Эмулируемые эндпоинты

### 5Post

| Метод  | Путь                           | Описание                                   |
|--------|--------------------------------|--------------------------------------------|
| POST   | `/jwt-generate-claims/rs256/1` | Выдача JWT-токена (принимает любой apikey) |
| POST   | `/api/v3/orders`               | Создание заказа                            |
| GET    | `/api/v1/orders/{id}/status`   | Текущий статус и история                   |
| DELETE | `/api/v1/orders/{id}`          | Отмена заказа                              |
| GET    | `/api/v1/orders/{id}/label`    | Этикетка (заглушка PDF)                    |

### Magnit

| Метод  | Путь                                             | Описание                                   |
|--------|--------------------------------------------------|--------------------------------------------|
| POST   | `/api/v2/oauth/token`                            | OAuth2-токен (принимает любые credentials) |
| POST   | `/api/v2/magnit-post/orders`                     | Создание заказа                            |
| GET    | `/api/v2/magnit-post/orders/{id}`                | Статус и детали заказа                     |
| DELETE | `/api/v1/magnit-post/orders/{id}`                | Отмена заказа                              |
| GET    | `/api/v1/magnit-post/orders/{id}/status-history` | История статусов                           |
| GET    | `/api/v1/magnit-post/orders/{id}/label`          | Этикетка (заглушка PDF)                    |
| GET    | `/health`                                        | Проверка работоспособности                 |

## Жизненный цикл заказов

### 5Post — Happy Path

```
NEW/CREATED
  -> APPROVED/APPROVED
    -> IN_PROCESS/RECEIVED_IN_WAREHOUSE_IN_DETAILS (FIRST_MILE)
      -> IN_PROCESS/SORTED_IN_WAREHOUSE (FIRST_MILE)
        -> IN_PROCESS/COMPLECTED_IN_WAREHOUSE (FIRST_MILE)
          -> IN_PROCESS/READY_TO_BE_SHIPPED_FROM_WAREHOUSE (FIRST_MILE)
            -> IN_PROCESS/SHIPPED (LAST_MILE)
              -> IN_PROCESS/RECEIVED_IN_STORE (LAST_MILE)
                -> IN_PROCESS/PLACED_IN_POSTAMAT (LAST_MILE)
                  -> DONE/PICKED_UP (LAST_MILE)
```

**Ветка «не забрали» (от PLACED_IN_POSTAMAT):**

```
UNCLAIMED/READY_FOR_WITHDRAW_FROM_PICKUP_POINT (REVERSE_LAST_MILE)
  -> UNCLAIMED/WITHDRAWN_FROM_PICKUP_POINT (REVERSE_LAST_MILE)
    -> UNCLAIMED/RETURNED_TO_PARTNER (REVERSE_FIRST_MILE)
```

**Отмена:** `APPROVED -> CANCELLED/CANCELLED`

**Отклонение:** `NEW -> REJECTED/REJECTED`

### Magnit — Happy Path

```
NEW -> CREATED -> DELIVERING_STARTED -> ACCEPTED_AT_POINT -> ISSUED
```

**Ветка возврата (от ACCEPTED_AT_POINT):**

```
WAITING_RETURN -> RETURN_INITIATED -> RETURN_SEND_TO_WAREHOUSE
  -> RETURN_ACCEPTED_AT_WAREHOUSE -> RETURNED_TO_PROVIDER
```

**Отмена:** `NEW/CREATED -> CANCELED_BY_PROVIDER`

## Таблицы в БД

Все таблицы имеют префикс `emul_`:

| Таблица                        | Описание                |
|--------------------------------|-------------------------|
| `emul_fivepost_orders`         | Заказы 5Post            |
| `emul_fivepost_status_history` | История статусов 5Post  |
| `emul_magnit_orders`           | Заказы Magnit           |
| `emul_magnit_status_history`   | История статусов Magnit |

## Деплой на сервер

Эмулятор развёрнут на `vkus.com` в `/opt/delivery-emulator/`.

Systemd-сервис: `vkus-emulator`

```bash
# Управление
systemctl start vkus-emulator
systemctl stop vkus-emulator
systemctl restart vkus-emulator
systemctl status vkus-emulator

# Логи
journalctl -u vkus-emulator -f

# CLI на сервере
cd /opt/delivery-emulator
python cli.py
```

Nginx проксирует два домена на один порт (8001):
- `5post-emul-api.vkus.online` -> localhost:8001
- `magnit-emul-api.vkus.online` -> localhost:8001

SSL-сертификаты выпущены через Certbot (Let's Encrypt).
