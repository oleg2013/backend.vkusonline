# Magnit Post API — Статусы заказов

Источник: https://magnit-tech.github.io/mpost-api/ (swagger.yaml, модели `OrderStatus` / `OrderV1Status`)

## Все статусы (18)

| Статус | Название (RU) | Что происходит в реальности |
|---|---|---|
| `NEW` | Новый | Заказ только что создан через API. Посылка ещё не обработана системой Магнит. |
| `CREATED` | Создан | Заказ зарегистрирован в системе Магнит Пост. Ожидает передачи посылки на склад. |
| `DELIVERING_STARTED` | Доставка начата | Посылка принята на складе Магнит и отправлена в доставку. Едет транспортом до магазина-ПВЗ. |
| `ACCEPTED_AT_POINT` | Принят в ПВЗ | Посылка доставлена в магазин Магнит (или партнёрский ПВЗ). Клиент может забрать заказ на кассе. Обычно приходит SMS-уведомление. |
| `IN_COURIER_DELIVERY` | Курьерская доставка | Посылка передана курьеру для доставки "до двери". Используется при курьерской доставке, не через ПВЗ. |
| `ISSUED` | Выдан | Клиент забрал посылку в магазине Магнит (или получил от курьера). Доставка завершена успешно. |
| `DESTROYED` | Уничтожен | Посылка уничтожена (повреждена без возможности восстановления, или по решению таможни). Редкий статус. |
| `ACCEPTED_AT_WAREHOUSE` | Принят на складе | Посылка вернулась на склад (промежуточный или основной). Может быть при возврате или перемаршрутизации. |
| `REMOVED` | Удалён | Заказ удалён из системы. Административное действие. |
| `WAITING_RETURN` | Ожидает возврата | Клиент не забрал посылку в срок хранения (обычно 5-7 дней). Магазин подготавливает посылку к возврату. |
| `RETURN_INITIATED` | Возврат инициирован | Процесс возврата запущен. Посылка снята с полки магазина и ожидает забора транспортом. |
| `RETURN_SEND_TO_WAREHOUSE` | Возврат отправлен | Посылка отправлена обратно на склад Магнит Пост. В пути. |
| `POSSIBLY_DEFECTED` | Возможно повреждён | При приёмке или выдаче обнаружены признаки повреждения упаковки. Требуется осмотр и решение. |
| `DEFECTED` | Повреждён | Подтверждено повреждение посылки. Составляется акт. Может потребоваться компенсация клиенту. |
| `RETURN_ACCEPTED_AT_WAREHOUSE` | Возврат принят на складе | Возвращённая посылка принята на складе Магнит. Ожидает передачи обратно отправителю (нам). |
| `RETURNED_TO_PROVIDER` | Возвращён поставщику | Посылка возвращена нам (отправителю). Нужно решить: повторная отправка или возврат денег клиенту. |
| `CANCELED_BY_PROVIDER` | Отменён поставщиком | Мы (отправитель) отменили заказ через API. Посылка не была отправлена или возвращается. |
| `ACCEPTED_AT_CUSTOMS` | На таможне | Посылка проходит таможенное оформление. Для международных отправлений. |

## Жизненный цикл

### Нормальная доставка (5-10 дней)
```
NEW → CREATED → DELIVERING_STARTED → ACCEPTED_AT_POINT → ISSUED
 │       │              │                    │               │
 │       │              │                    │               └─ Клиент забрал в магазине
 │       │              │                    └─ Привезли в магазин Магнит, лежит на кассе
 │       │              └─ Посылка едет со склада в магазин
 │       └─ Система приняла заказ
 └─ Мы создали через API
```

### Курьерская доставка
```
NEW → CREATED → DELIVERING_STARTED → IN_COURIER_DELIVERY → ISSUED
```

### Возврат (клиент не забрал)
```
ACCEPTED_AT_POINT → WAITING_RETURN → RETURN_INITIATED → RETURN_SEND_TO_WAREHOUSE → RETURN_ACCEPTED_AT_WAREHOUSE → RETURNED_TO_PROVIDER
```

### Повреждение
```
... → POSSIBLY_DEFECTED → DEFECTED → (решение: возврат или компенсация)
```

### Исключения
- `CANCELED_BY_PROVIDER` — мы отменили заказ
- `DESTROYED` — посылка уничтожена
- `REMOVED` — удалён из системы
- `ACCEPTED_AT_CUSTOMS` — таможня (международные отправления)

## Что видит клиент на трекинг-странице

| Magnit статус | Что показываем клиенту |
|---|---|
| `NEW`, `CREATED` | "Заказ оформлен, готовится к отправке" |
| `DELIVERING_STARTED` | "Заказ в пути" |
| `ACCEPTED_AT_POINT` | "Ожидает вас в магазине Магнит" |
| `IN_COURIER_DELIVERY` | "Курьер в пути к вам" |
| `ISSUED` | "Заказ получен" |
| `WAITING_RETURN`, `RETURN_INITIATED` | "Заказ не был забран, возвращается" |
| `RETURN_SEND_TO_WAREHOUSE`, `RETURN_ACCEPTED_AT_WAREHOUSE` | "Заказ возвращается отправителю" |
| `RETURNED_TO_PROVIDER` | "Заказ возвращён отправителю" |
| `CANCELED_BY_PROVIDER` | "Заказ отменён" |
| `POSSIBLY_DEFECTED`, `DEFECTED` | "Проблема с заказом, свяжитесь с поддержкой" |
| `DESTROYED` | "Заказ повреждён, свяжитесь с поддержкой" |

## Маппинг на наши статусы

| Magnit статус | Наш OrderStatus |
|---|---|
| `NEW`, `CREATED` | `shipped` |
| `DELIVERING_STARTED` | `shipped` |
| `ACCEPTED_AT_POINT` | `ready_for_pickup` |
| `IN_COURIER_DELIVERY` | `shipped` |
| `ISSUED` | `delivered` |
| `WAITING_RETURN`, `RETURN_INITIATED`, `RETURN_SEND_TO_WAREHOUSE` | `client_dont_pickup` |
| `RETURN_ACCEPTED_AT_WAREHOUSE`, `RETURNED_TO_PROVIDER` | `returned_to_supplier` |
| `CANCELED_BY_PROVIDER`, `DESTROYED`, `REMOVED` | `cancelled` |
| `POSSIBLY_DEFECTED`, `DEFECTED` | требует ручного решения |
| `ACCEPTED_AT_CUSTOMS` | `shipped` |
| `ACCEPTED_AT_WAREHOUSE` | `shipped` (промежуточный) |

## API эндпоинты

- `POST /api/v2/magnit-post/orders` — создание заказа (V2 API, поддержка COD)
- `GET /api/v1/magnit-post/orders/{order_id}` — получить заказ (включает `status`)
- `GET /api/v1/magnit-post/orders/{order_id}/status-history` — история статусов
- `POST /api/v1/magnit-post/order-statuses` — актуальные статусы по нескольким заказам
- `DELETE /api/v1/magnit-post/orders/{order_id}` — отмена заказа
- `GET /api/v1/magnit-post/orders/{order_id}/label` — PDF-этикетка

## Сроки хранения

- Стандартный срок хранения в магазине Магнит: **5-7 дней**
- После истечения срока → `WAITING_RETURN` → возврат отправителю
- Срок хранения указывается в поле `storageEndDate` ответа API
