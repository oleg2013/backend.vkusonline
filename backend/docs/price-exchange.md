# Система обмена ценами

## Обзор

Система загружает актуальные цены из внешней ERP-системы через FTP. XML-файлы с ценами скачиваются периодически, парсятся и обновляют цены товаров в базе данных.

## Архитектура

FTP-сервер недоступен напрямую с Hetzner (passive FTP блокируется). Скачивание идёт через KZ-прокси (185.91.126.150) по SSH.

```
FTP-сервер (91.221.103.141:10921)
    │
    │  last_import_data_YYYY_MM_DD_HH_MM.xml  (UTF-16)
    ▼
┌─────────────────────┐
│  KZ Proxy            │ ← SSH root1@185.91.126.150
│  (185.91.126.150)    │   Python3 скачивает XML с FTP
└─────────────────────┘
    │  stdout (XML bytes)
    ▼
┌─────────────────────┐
│  vkus.com Worker     │ ← каждые 60 мин (настраивается)
│  1. SSH → KZ → FTP   │
│  2. XML parse        │
│  3. Match by SKU     │
│  4. Update prices    │
│  5. Log session      │
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│  PostgreSQL          │
│  - product_prices    │  ← цены по типам
│  - price_types       │  ← trade, base, sale, cost
│  - price_import_*    │  ← журналы импорта
└─────────────────────┘
```

## Типы цен

| Код     | Название         | Описание                                              |
|---------|------------------|-------------------------------------------------------|
| `trade` | Торговая цена    | Основная розничная цена. Обновляет `products.price`.   |
| `base`  | Базовая цена     | Базовая цена (справочная)                             |
| `sale`  | Цена со скидкой  | Если задана — товар продаётся со скидкой (бейдж на фронте) |
| `cost`  | Себестоимость     | Внутренняя себестоимость                              |

**Логика скидки:** если у товара задана цена `sale` — это сигнал что товар сейчас со скидкой. На фронте показывается бейдж "Скидка" и зачёркнутая старая цена (`trade`).

**Удаление цен:** если в XML тег цены пустой (`<sale currency="643"/>`) — цена удаляется из БД. Это снимает скидку с товара.

## Таблицы БД

### price_types
Справочник типов цен. Заполняется при миграции.

| Поле  | Тип         | Описание       |
|-------|-------------|----------------|
| id    | varchar(36) | UUID           |
| code  | varchar(50) | trade/base/sale/cost |
| label | varchar(255)| Человеческое название |

### product_prices
Цены товаров по типам. Unique constraint: `(product_id, price_type_id)`.

| Поле          | Тип         | Описание                |
|---------------|-------------|-------------------------|
| id            | varchar(36) | UUID                    |
| product_id    | varchar(36) | FK → products.id        |
| price_type_id | varchar(36) | FK → price_types.id     |
| price         | bigint      | Цена в копейках         |
| currency      | varchar(3)  | ISO 4217 (643 = RUB)    |
| updated_at    | timestamptz | Дата обновления         |

### price_import_sessions
Журнал сессий импорта.

| Поле          | Тип         | Описание                         |
|---------------|-------------|----------------------------------|
| id            | varchar(36) | UUID                             |
| started_at    | timestamptz | Начало импорта                   |
| finished_at   | timestamptz | Конец импорта                    |
| status        | varchar(20) | running / completed / failed     |
| file_name     | varchar(255)| Имя XML-файла                   |
| total_goods   | integer     | Всего товаров в XML              |
| matched       | integer     | Совпало с нашими SKU             |
| updated       | integer     | Цен обновлено                    |
| created       | integer     | Цен создано                      |
| deleted       | integer     | Цен удалено                      |
| skipped       | integer     | Пропущено (без изменений)        |
| errors        | integer     | Ошибок                           |
| error_message | text        | Текст ошибки (если failed)       |

### price_import_logs
Детальный журнал — что именно изменилось.

| Поле       | Тип         | Описание                              |
|------------|-------------|---------------------------------------|
| session_id | varchar(36) | FK → price_import_sessions.id         |
| sku        | varchar(50) | Артикул из XML                        |
| product_id | varchar(36) | Наш product.id (если совпал)          |
| price_type | varchar(50) | trade/base/sale/cost                  |
| old_price  | bigint      | Старая цена (копейки)                 |
| new_price  | bigint      | Новая цена (копейки)                  |
| action     | varchar(20) | created/updated/deleted/skipped       |

## Конфигурация (.env)

```env
PRICE_FTP_HOST=91.221.103.141
PRICE_FTP_PORT=10921
PRICE_FTP_USER=coffeeftp
PRICE_FTP_PASSWORD=S4QKI0v1g0
PRICE_SYNC_INTERVAL_MINUTES=60
PRICE_IMPORT_JOURNAL_RETENTION_DAYS=30
```

## XML формат

Файлы на FTP: `last_import_data_YYYY_MM_DD_HH_MM.xml` (UTF-16).

```xml
<import>
  <goods>
    <good id="..." parent="...">
      <name>Roasted coffee beans VKUS ESPRESSO, 1 kg</name>
      <barcode/>
      <article>701</article>
      <count>2314</count>
      <prices>
        <trade currency="643">3828</trade>
        <base currency="643"/>
        <sale currency="643">3329</sale>
        <cost currency="643">1248,71</cost>
      </prices>
    </good>
  </goods>
</import>
```

- `article` = наш `products.sku`
- Цены в рублях с запятой как десятичный разделитель (`1248,71`)
- Конвертируются в копейки: `1248,71` → `124871`
- Пустой тег = цена отсутствует (удалить если была)
- `count` — остаток на складе (пока не импортируется)
- `barcode` — игнорируется

## KZ-прокси

FTP-сервер за NAT (91.221.103.141) недоступен для data-transfer с Hetzner (passive FTP блокируется).
Скачивание идёт через промежуточный хост KZ (185.91.126.150):

- **SSH**: `root1@185.91.126.150` (SSH ключ vkus.com добавлен в authorized_keys)
- **Механизм**: vkus.com по SSH запускает Python-скрипт на KZ, который скачивает XML с FTP и отдаёт через stdout
- **Скорость**: ~5 секунд на весь цикл (FTP download + SSH transfer + parse)

Если KZ недоступен — синхронизация завершится с ошибкой (session status = "failed").

## API

### Публичный
- `GET /api/v1/catalog/products/{sku}/prices` — цены товара по SKU

### Админ
- `POST /api/v1/admin/jobs/sync-prices` — принудительная синхронизация
- `GET /api/v1/admin/price-import/sessions` — журнал сессий
- `GET /api/v1/admin/price-import/sessions/{id}` — детали сессии с логом

## CLI (vkus_cli.py)

Меню **9. Обмен ценами**:
1. Принудительная синхронизация
2. Журнал сессий (таблица)
3. Детали сессии (с логом изменений)
4. Цены товара по SKU

## Автоматические процессы

- **sync_prices** — каждые 60 минут (Worker)
- **cleanup_price_journals** — ежедневно в 03:30, удаляет журналы старше 30 дней

## Файлы

| Файл | Назначение |
|------|------------|
| `packages/models/price.py` | 4 модели (PriceType, ProductPrice, PriceImportSession, PriceImportLog) |
| `packages/integrations/price_ftp/client.py` | FTP клиент (download latest XML) |
| `packages/integrations/price_ftp/parser.py` | XML парсер (goods → ParsedGoodPrice) |
| `packages/services/prices/__init__.py` | Бизнес-логика (sync, get, cleanup) |
| `apps/worker/jobs/sync_prices.py` | Worker job |
| `apps/worker/jobs/cleanup_price_journals.py` | Очистка журналов |
| `apps/api/routers/admin.py` | Админ API (force sync, sessions) |
| `apps/api/routers/catalog.py` | Публичный API (product prices) |
