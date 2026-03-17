# VKUS CLI — Техническая документация

> Интерактивный CLI для тестирования всех API-эндпоинтов vkus.online.
> Файл: `backend/scripts/vkus_cli.py` (~2200 строк).
> Запуск: `cd backend && python -m scripts.vkus_cli`

---

## 1. Архитектура

### 1.1 Общая схема

```
┌─────────────────────────────────────────────────────────────┐
│  main()                                                     │
│    └── CLIApp(base_url)                                     │
│          ├── FileLogger(detail_mode)  — иерархические логи  │
│          ├── VkusAPI(base_url, logger) — HTTP-клиент        │
│          └── state: dict              — .vkus_cli_state.json│
│                                                             │
│  CLIApp.run()  ← главный цикл                              │
│    ├── menu_delivery()   → _delivery_*()                    │
│    ├── menu_orders()     → _order_*()                       │
│    ├── menu_payment()    → _payment_*()                     │
│    ├── menu_auth()       → _auth_*()                        │
│    ├── menu_admin()                                         │
│    ├── menu_settings()                                      │
│    └── run_qa()          → _qa_*()                          │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Зависимости

| Пакет | Зачем | Обязательный |
|-------|-------|:------------:|
| `httpx` | Async HTTP-клиент для API-запросов | Да |
| `rich` | Цветные таблицы, панели в терминале | Нет (fallback на plain text) |
| `aiohttp` | Локальный webhook-сервер для тестирования оплаты | Нет (только для меню «Оплата») |

Все зависимости указаны в `backend/pyproject.toml`.

---

## 2. Классы

### 2.1 `FileLogger` — Иерархический логгер

**Назначение:** Пишет логи запросов/ответов в файловую иерархию по сессиям и меню.

#### Конструктор

```python
FileLogger(detail_mode: bool = False)
```

- `detail_mode=False` — только summary-логи (тела ответов обрезаются на 5000 символах).
- `detail_mode=True` — дополнительно создаются JSON-файлы с полным request/response.

#### Структура логов

```
logs/cli/
  2026-03-10_14-32-45/                     ← session_dir (одна папка на запуск CLI)
    session.log                             ← ВСЕ запросы сессии (с обрезкой)
    delivery/                               ← подпапка меню
      delivery.log                          ← summary-лог только для этого меню
      001_8d092b20_2026-03-10_14-33-01.json ← detail-файл (только при detail_mode=True)
      002_a4b5c6d7_2026-03-10_14-33-02.json
    orders/
      orders.log
    qa/
      qa.log
      003_f1e2d3c4_2026-03-10_14-35-10.json
    ...
```

#### Ключевые поля

| Поле | Тип | Описание |
|------|-----|----------|
| `session_dir` | `Path` | Корневая папка сессии: `logs/cli/{timestamp}/` |
| `_detail_mode` | `bool` | Писать ли полные detail-файлы |
| `_context` | `str \| None` | Текущее активное меню (`"delivery"`, `"qa"`, ...) |
| `_seq` | `int` | Глобальный счётчик запросов (001, 002, ...) |
| `_summary_files` | `dict[str, IO]` | Открытые файлы `{context}.log` |
| `_pending_request` | `dict` | Данные текущего запроса (для объединения с ответом в detail-файл) |
| `_session_log` | `IO` | Файл `session.log` |

#### Методы

| Метод | Описание |
|-------|----------|
| `set_context(name)` | Переключает запись в подпапку меню. Создаёт папку и summary-лог при первом вызове |
| `reset_context()` | Сбрасывает контекст (возврат в главное меню) |
| `request(method, url, headers, body, params=None)` | Логирует запрос: summary + stash для detail-файла |
| `response(status, elapsed_ms, body, request_id=None)` | Логирует ответ: summary (обрезка ≤5000 симв.) + detail JSON (если включен) |
| `info(msg)` | Информационная запись в оба лога |
| `detail_mode` (property) | Getter/setter для переключения режима на лету |
| `path` (property) | Возвращает `session_dir` (для отображения в UI) |
| `close()` | Закрывает все открытые файлы |

#### Формат detail-файла

Имя: `{seq:03d}_{request_id[:8]}_{YYYY-MM-DD_HH-MM-SS}.json`

```json
{
  "seq": 5,
  "request_id": "ff921d09-feeb-4a61-af2d-eb45fc4160d4",
  "request": {
    "method": "GET",
    "url": "https://api.vkus.online/api/v1/delivery/magnit/pickup-points?city=Москва&limit=200",
    "headers": { "Content-Type": "application/json" },
    "params": { "city": "Москва", "limit": 200 },
    "body": null,
    "timestamp": "2026-03-10T13:15:07.458051"
  },
  "response": {
    "status": 200,
    "elapsed_ms": 199,
    "body": { "ok": true, "data": [ ... полные данные ... ] }
  }
}
```

Записывается через `json.dumps(data, indent=2, ensure_ascii=False)` — кириллица читаема.

#### Механизм контекстного переключения

Контексты переключаются **централизованно** в `CLIApp.run()` (главный цикл):

```python
context = MENU_CONTEXTS.get(choice)  # "1" → "delivery", "6" → "qa", ...
if context:
    self.logger.set_context(context)
try:
    await self.menu_delivery()  # все вызовы API внутри пишутся в delivery/
finally:
    self.logger.reset_context()
```

**Ни один `menu_*` метод не содержит вызовов `set_context/reset_context`** — это делается только в `run()`.

---

### 2.2 `VkusAPI` — HTTP-клиент с логированием

**Назначение:** Обёртка над `httpx.AsyncClient` для вызова API с автоматическим логированием и разворачиванием envelope.

#### Конструктор

```python
VkusAPI(base_url: str, logger: FileLogger)
```

#### Ключевые поля

| Поле | Тип | Описание |
|------|-----|----------|
| `base_url` | `str` | Базовый URL без trailing slash |
| `logger` | `FileLogger` | Ссылка на логгер |
| `client` | `httpx.AsyncClient` | HTTP-клиент (timeout=30s) |
| `guest_session_id` | `str \| None` | Guest session UUID |
| `access_token` | `str \| None` | JWT токен пользователя |
| `refresh_token` | `str \| None` | Refresh токен |
| `admin_secret` | `str \| None` | Admin Bearer secret |
| `last_request_id` | `str \| None` | request_id последнего ответа |
| `last_elapsed_ms` | `int` | Время последнего запроса (мс) |

#### Метод `call()`

```python
async def call(
    method: str,          # "GET", "POST", "PUT"
    path: str,            # "/health", "/checkout/delivery-options"
    body: dict | None,    # JSON тело (для POST/PUT)
    params: dict | None,  # Query параметры (для GET)
    auth: str = "none",   # Режим авторизации
) -> Any                  # Возвращает data из envelope
```

**Режимы авторизации (`auth`):**

| Значение | Заголовок |
|----------|-----------|
| `"none"` | Без авторизации |
| `"guest"` | `X-Guest-Session-ID: {uuid}` |
| `"user"` | `Authorization: Bearer {access_token}` |
| `"admin"` | `Authorization: Bearer {admin_secret}` |
| `"guest+user"` | Оба заголовка |

**Поток выполнения:**
1. Формирует URL: `{base_url}/api/v1{path}`
2. Добавляет заголовки авторизации
3. `logger.request(method, url, headers, body, params=params)`
4. `httpx.request(method, url, json=body, params=params, headers=headers)`
5. Парсит JSON-ответ
6. `logger.response(status, elapsed, data, request_id)`
7. Если `ok=false` → бросает `ApiError`
8. Возвращает `data.get("data")`

#### Метод `ensure_guest()`

Создаёт guest session если ещё нет, вызывает `POST /guest/session/bootstrap`.

---

### 2.3 `ApiError` — Исключение API

```python
class ApiError(Exception):
    code: str        # "NETWORK_ERROR", "PARSE_ERROR", "AUTH_ERROR", ...
    message: str     # Человекочитаемое описание
    status: int      # HTTP статус (0 при сетевой ошибке)
    request_id: str  # request_id из ответа
```

Перехватывается в главном цикле `CLIApp.run()` и показывается пользователю.

---

### 2.4 `CLIApp` — Интерактивное приложение

**Назначение:** Главный класс — управляет меню, вводом, состоянием, вызовами API.

#### Конструктор

```python
CLIApp(base_url: str)
```

Порядок инициализации:
1. `load_state()` — загружает `.vkus_cli_state.json`
2. Читает `detail_server_response` из state
3. Создаёт `FileLogger(detail_mode=...)`
4. Создаёт `VkusAPI(base_url, logger)`
5. Восстанавливает `guest_session_id`, `access_token`, `refresh_token`, `admin_secret`

#### Утилиты ввода

| Метод | Описание |
|-------|----------|
| `ask(prompt, default="")` | Ввод строки с дефолтом |
| `ask_int(prompt, default=0)` | Ввод числа с дефолтом |
| `pause()` | Ожидание нажатия Enter |
| `show_menu(title, items)` | Отрисовка меню, возвращает выбранный пункт |
| `show_result(elapsed, request_id)` | Показывает время и request_id после API-вызова |
| `_meta_line()` | Строка состояния (guest id, token, путь лога) |

---

## 3. Меню и эндпоинты

### 3.1 Главное меню → `CLIApp.run()`

```
1. Доставка       → menu_delivery()    → контекст "delivery"
2. Заказы         → menu_orders()      → контекст "orders"
3. Оплата         → menu_payment()     → контекст "payment"
4. Авторизация    → menu_auth()        → контекст "auth"
5. Администрирование → menu_admin()    → контекст "admin"
6. QA             → run_qa()           → контекст "qa"
7. Настройки      → menu_settings()    → контекст "settings"
0. Выход
```

### 3.2 Доставка → `menu_delivery()`

| Пункт | Метод | API-эндпоинт | HTTP |
|-------|-------|-------------|------|
| 1. Автокомплит города | `_delivery_suggest()` | `/geo/city-suggest` | POST |
| 2. Варианты доставки | `_delivery_options()` | `/checkout/delivery-options` | POST |
| 3. Список ПВЗ | `_delivery_points()` | `/delivery/{provider}/pickup-points` | GET |
| 4. Расчёт стоимости | `_delivery_estimate()` | `/checkout/estimate-delivery` | POST |
| 5. Города Магнит | `_delivery_cities()` | `/delivery/magnit/cities` | GET |
| 6. Полный сценарий | `_delivery_flow()` | suggest → options → points → estimate | Цепочка |

**`_delivery_flow()`** — интерактивный 4-шаговый сценарий:
1. Город (autocomplete) → выбор
2. Провайдер (delivery-options) → выбор
3. ПВЗ (pickup-points) → выбор
4. Расчёт (estimate-delivery) → итог

### 3.3 Заказы → `menu_orders()`

| Пункт | Метод | API-эндпоинт | HTTP | Auth |
|-------|-------|-------------|------|------|
| 1. Создать заказ | `_order_create()` | `/guest/checkout/create-order` | POST | guest |
| 2. Статус | `_order_status()` | `/guest/orders/{num}/status` | GET | guest |
| 3. Детали | `_order_detail()` | `/guest/orders/{num}` | GET | guest |
| 4. Отменить | `_order_cancel()` | `/guest/orders/{num}/cancel` | POST | guest |
| 5. Список | `_order_list()` | `/me/orders` | GET | user |

**`_order_create()`** — полный checkout:
1. `ensure_guest()` → guest session
2. `_delivery_flow()` → город/провайдер/ПВЗ/расчёт
3. Ввод данных получателя (имя, телефон, email)
4. Выбор оплаты (card/cod)
5. `POST /guest/checkout/create-order`
6. Сохраняет `order_number` в state

### 3.4 Оплата → `menu_payment()`

| Пункт | Метод | API-эндпоинт | HTTP | Auth |
|-------|-------|-------------|------|------|
| 1. Полный тест E2E | `_payment_full_test()` | create-order → payment → webhook | Цепочка | guest |
| 2. Создать платёж | `_payment_create()` | `/guest/orders/{num}/payments/yookassa/create` | POST | guest |
| 3. Статус | `_order_status()` | `/guest/orders/{num}/status` | GET | guest |

**`_payment_full_test()`** — E2E тест:
1. `_order_create(payment_method="card")`
2. Получает `confirmation_url`
3. Открывает URL в браузере (`webbrowser.open`)
4. `run_webhook_server()` — ждёт YooKassa callback на `localhost:8080`
5. Проверяет статус заказа через API

### 3.5 Авторизация → `menu_auth()`

| Пункт | Метод | API-эндпоинт | HTTP |
|-------|-------|-------------|------|
| 1. Регистрация | `_auth_register()` | `/auth/register` | POST |
| 2. Логин | `_auth_login()` | `/auth/login` | POST |
| 3. Профиль | `_auth_profile()` | `/me` | GET (auth=user) |
| 4. Выход | `_auth_logout()` | `/auth/logout` | POST |

После логина/регистрации `access_token` и `refresh_token` сохраняются в state.

### 3.6 Администрирование → `menu_admin()`

| Пункт | API-эндпоинт | HTTP | Auth |
|-------|-------------|------|------|
| 1. Детали заказа | `/admin/orders/{num}` | GET | admin |
| 2. Статус кэша ПВЗ | `/admin/pickup-points/cache-status` | GET | admin |
| 3. Синхронизация 5Post | `/admin/jobs/sync-5post-points` | POST | admin |
| 4. Синхронизация Магнит | `/admin/jobs/sync-magnit-points` | POST | admin |
| 5. События провайдеров | `/admin/provider-events` | GET | admin |
| 6. Список заказов | `/admin/orders` | GET | admin |
| 7. Управление клиентами | `/admin/clients` | GET | admin |

При первом входе запрашивает admin secret (или берёт из env `VKUS_ADMIN_SECRET`).

#### Пункт 6: Список заказов (`admin_orders_list`)

Пагинированная таблица всех заказов:
- Колонки: #, Номер, Тип, Статус, Token, Клиент, Сумма, Позиций, Дата
- Навигация: **N**ext, **P**rev, **F**ilter (по статусу), [номер]=детали, **0**=назад
- Детали заказа показывают: полную информацию + UNIQUE_ORDER_ID + ссылку на tracking page
- Действия с заказом: 1. Изменить статус, 2. Отменить, 3. Удалить

#### Пункт 7: Управление клиентами (`admin_clients_list`)

Пагинированная таблица клиентов:
- Колонки: #, Email, Телефон, Имя, Пароль, Заказов, Сумма, Дата рег.
- Навигация: **N**ext, **P**rev, **S**earch, **C**reate, [номер]=детали, **0**=назад
- Действия с клиентом: 1. Заказы клиента, 2. Сбросить пароль, 3. Создать клиента, 4. Удалить

### 3.7 Настройки → `menu_settings()`

Показывает текущие настройки и позволяет изменить:

| Пункт | Действие |
|-------|----------|
| 1. Base URL | Изменить URL API |
| 2. Guest session | Сбросить guest session |
| 3. Admin secret | Задать admin secret |
| 4. Детальные ответы | Переключить `detail_server_response` (ВКЛ/ВЫКЛ) |

---

## 4. QA Suite → `run_qa()`

Автоматический прогон 25 тестов. Каждый тест — метод `_qa_*()` с сигнатурой:

```python
async def _qa_test_name(self, st: dict[str, Any]) -> str
```

- `st` — общий словарь состояния QA-прогона (передаётся между тестами).
- Возвращает строку-описание результата.
- Бросает `AssertionError` при неудаче.

### Порядок тестов и зависимости

```
 #  | Тест                      | Эндпоинт                         | Зависимость
----+---------------------------+----------------------------------+----------------
 1  | Health check              | GET /health                      | —
 2  | Bootstrap                 | GET /bootstrap                   | —
 3  | Guest session             | POST /guest/session/bootstrap    | → st[guest_session_id]
 4  | Catalog: list products    | GET /catalog/products            | —
 5  | Catalog: product by SKU   | GET /catalog/products/701        | —
 6  | Catalog: price check      | GET /catalog/products/{sku}      | —
 7  | City suggest              | POST /geo/city-suggest           | → st[city_clean]
 8  | Delivery options          | POST /checkout/delivery-options  | st[city_clean] → st[providers, cart_items]
 9  | Magnit points (10)        | GET /delivery/magnit/pickup-points | st[city_clean] → st[magnit_point]
10  | 5Post points (10)         | GET /delivery/5post/pickup-points  | st[city_clean]
11  | Magnit points HIGH (2000) | GET /delivery/magnit/pickup-points | st[city_clean]
12  | 5Post points HIGH (2000)  | GET /delivery/5post/pickup-points  | st[city_clean]
13  | Estimate delivery         | POST /checkout/estimate-delivery | st[magnit_point, cart_items] → st[estimate]
14  | Checkout quote            | POST /checkout/quote             | st[cart_items, estimate]
15  | Cart (add items)          | PUT /guest/cart/items            | st[cart_items], auth=guest
16  | Create order (COD)        | POST /guest/checkout/create-order| st[all] → st[order_number, public_token]
17  | Checkout: full order flow | POST /checkout/quote + create    | st[all]
18  | Order status              | GET /guest/orders/{num}/status   | st[order_number]
19  | Auth register             | POST /auth/register              | → api.access_token
20  | Profile (GET /me)         | GET /me                          | api.access_token
21  | Admin: list orders        | GET /admin/orders                | auth=admin
22  | Admin: order set status   | POST /admin/orders/{num}/set-status | st[order_number]
23  | Public: order tracking    | GET /orders/track/{token}        | st[public_token]
24  | COD: confirm order        | POST /orders/{token}/confirm     | creates new COD order
25  | Admin: list clients       | GET /admin/clients               | auth=admin
```

### Как добавить новый QA-тест

1. Создать метод `_qa_new_test(self, st: dict) -> str`
2. Добавить кортеж `("Название теста", self._qa_new_test)` в список `tests` внутри `run_qa()`
3. Если тест зависит от данных предыдущих — брать из `st`
4. Если тест создаёт данные для последующих — записывать в `st`

---

## 5. Конфигурация и состояние

### 5.1 Константы

| Константа | Значение | Описание |
|-----------|----------|----------|
| `DEFAULT_BASE_URL` | `"https://api.vkus.online"` | API по умолчанию |
| `API_PREFIX` | `"/api/v1"` | Префикс всех эндпоинтов |
| `STATE_FILE` | `".vkus_cli_state.json"` | Файл состояния |
| `LOG_DIR` | `Path("logs/cli")` | Корневая папка логов |
| `DEFAULT_SKU` | `"701"` | Товар по умолчанию для тестов (Кофе Espresso) |
| `WEBHOOK_PORT` | `8080` | Порт webhook-сервера |
| `WEBHOOK_TIMEOUT` | `300` | Таймаут ожидания webhook (секунды) |
| `MENU_CONTEXTS` | `{"1":"delivery",...}` | Маппинг номеров меню → названия контекстов |

### 5.2 State-файл `.vkus_cli_state.json`

```json
{
  "base_url": "https://api.vkus.online",
  "guest_session_id": "725db5c5-8b2b-4850-add5-bebcb3b6d4bf",
  "access_token": "eyJhbG...",
  "refresh_token": "abc123...",
  "admin_secret": "my-secret",
  "last_order": "VK-260310-ZYBJN7",
  "detail_server_response": false
}
```

Сохраняется при каждом вызове `_save()` (после логина, создания заказа, смены настроек).

### 5.3 Переменные окружения

| Переменная | Описание |
|------------|----------|
| `VKUS_ADMIN_SECRET` | Admin secret (приоритет над state) |
| `VKUS_API_URL` | Base URL (только если не передан через `--base-url`) |

---

## 6. Вспомогательные функции

### 6.1 Консольные хелперы

| Функция | Описание |
|---------|----------|
| `cprint(*args)` | Обёртка над `rich.Console.print()` с fallback |
| `make_table(title, columns, rows)` | Таблица. `columns = [(header, justify), ...]` |
| `make_panel(title, lines)` | Панель с рамкой. `lines = ["строка1", "строка2"]` |

Все три работают и без `rich` — просто выводят plain text.

### 6.2 `run_webhook_server(port, timeout)`

Запускает `aiohttp`-сервер на `0.0.0.0:{port}`, слушает:
- `POST /webhooks/yookassa`
- `POST /webhook`

Возвращает `dict` с payload или `None` при таймауте.

---

## 7. Карта файла (строки)

```
  1-15    Docstring, usage
 16-29    Imports
 31-39    Rich import (optional)
 41-61    Constants + MENU_CONTEXTS
 63-111   Console helpers (cprint, make_table, make_panel)
113-127   State management (load_state, save_state)
135-297   class FileLogger
304-310   class ApiError
313-388   class VkusAPI
396-430   run_webhook_server()
438-580   class CLIApp — __init__, _save, ask*, show_menu, run()
584-811   CLIApp — Delivery menu + methods
815-987   CLIApp — Orders menu + methods
991-1080  CLIApp — Payment menu + methods
1084-1167 CLIApp — Auth menu + methods
1171-1216 CLIApp — Admin menu
1220-1260 CLIApp — Settings menu
1264-1470 CLIApp — QA suite (run_qa + 14 test methods)
1478-1493 main() — argparse + asyncio.run
```

---

## 8. Как вносить изменения

### 8.1 Добавить новый API-эндпоинт в существующее меню

1. Создать метод `_section_new_action(self)` рядом с другими методами секции
2. Внутри вызвать `await self.api.call(method, path, body, params, auth)`
3. Отобразить результат через `make_table()` или `make_panel()`
4. Вызвать `self.show_result(self.api.last_elapsed_ms, self.api.last_request_id)`
5. Добавить пункт в `show_menu()` соответствующего `menu_*` метода
6. Добавить `elif choice == "N": await self._section_new_action()` в обработчик

### 8.2 Добавить новое подменю

1. Добавить пункт в главное меню внутри `run()` (список items)
2. Добавить номер в `MENU_CONTEXTS`: `"8": "new_section"`
3. Создать метод `menu_new_section(self)` с циклом `while True` + `show_menu` + dispatch
4. Добавить `elif choice == "8": await self.menu_new_section()` в `run()`
5. Контекст логгера переключится автоматически (централизованно в `run()`)

### 8.3 Добавить новый QA-тест

1. Создать метод `_qa_test_name(self, st: dict) -> str`
2. Добавить `("Название", self._qa_test_name)` в список `tests` внутри `run_qa()`
3. Использовать `st[key]` для входных данных, записывать результаты в `st`
4. Бросить `AssertionError("описание")` при неудаче
5. Вернуть строку-описание успеха

### 8.4 Изменить формат логирования

- **Summary-логи (обрезка):** метод `FileLogger.response()` — переменная `body_str`, порог `5000`
- **Detail-файлы (полный JSON):** там же, блок `if self._detail_mode and self._context:`
- **Формат имени файла:** строка `f"{seq:03d}_{rid_short}_{file_ts}.json"`
- **Что попадает в detail:** словарь `detail_data` (seq, request_id, request, response)

### 8.5 Добавить новую настройку

1. Добавить чтение из state в `CLIApp.__init__()`: `self.state.get("setting_name", default)`
2. Добавить запись в `CLIApp._save()`: `self.state["setting_name"] = value`
3. Добавить пункт в `menu_settings()` — отображение текущего значения + toggle/input
4. При необходимости — пробросить в `FileLogger` или `VkusAPI`

---

## 9. API Envelope

Все эндпоинты бэкенда возвращают стандартный формат:

```json
{
  "ok": true,
  "data": { ... },
  "request_id": "uuid"
}
```

При ошибке:

```json
{
  "ok": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable",
    "details": {}
  },
  "request_id": "uuid"
}
```

`VkusAPI.call()` автоматически:
- Разворачивает envelope, возвращает `data`
- При `ok=false` бросает `ApiError(code, message, status, request_id)`
- При сетевой ошибке бросает `ApiError("NETWORK_ERROR", ...)`
- При не-JSON ответе бросает `ApiError("PARSE_ERROR", ...)`

---

## 10. Полный список API-эндпоинтов, используемых CLI

| Метод | Путь | Auth | Используется в |
|-------|------|------|----------------|
| GET | `/health` | none | QA |
| GET | `/bootstrap` | none | QA |
| POST | `/guest/session/bootstrap` | none | ensure_guest, QA |
| POST | `/geo/city-suggest` | none | delivery, QA |
| POST | `/checkout/delivery-options` | none | delivery, QA |
| GET | `/delivery/magnit/pickup-points` | none | delivery, QA |
| GET | `/delivery/5post/pickup-points` | none | delivery, QA |
| GET | `/delivery/magnit/cities` | none | delivery |
| POST | `/checkout/estimate-delivery` | none | delivery, QA |
| POST | `/checkout/quote` | none | QA |
| PUT | `/guest/cart/items` | guest | QA |
| POST | `/guest/checkout/create-order` | guest | orders, payment, QA |
| GET | `/guest/orders/{num}/status` | guest | orders, payment, QA |
| GET | `/guest/orders/{num}` | guest | orders |
| POST | `/guest/orders/{num}/cancel` | guest | orders |
| GET | `/me/orders` | user | orders |
| POST | `/guest/orders/{num}/payments/yookassa/create` | guest | payment |
| POST | `/auth/register` | none | auth, QA |
| POST | `/auth/login` | none | auth |
| GET | `/me` | user | auth, QA |
| POST | `/auth/logout` | none | auth |
| GET | `/admin/orders/{num}` | admin | admin |
| GET | `/admin/orders` | admin | admin (list) |
| POST | `/admin/orders/{num}/set-status` | admin | admin |
| DELETE | `/admin/orders/{num}` | admin | admin |
| GET | `/admin/clients` | admin | admin (list) |
| GET | `/admin/clients/{id}` | admin | admin |
| POST | `/admin/clients/{id}/reset-password` | admin | admin |
| DELETE | `/admin/clients/{id}` | admin | admin |
| GET | `/admin/pickup-points/cache-status` | admin | admin |
| POST | `/admin/jobs/sync-5post-points` | admin | admin |
| POST | `/admin/jobs/sync-magnit-points` | admin | admin |
| GET | `/admin/provider-events` | admin | admin |
| GET | `/orders/track/{token}` | none | public tracking |
| POST | `/orders/{token}/confirm` | none | COD confirm |
| POST | `/orders/{token}/check-payment` | none | payment check |
| POST | `/orders/{token}/cancel` | none | public cancel |
| POST | `/auth/check-email` | none | email exists check |
