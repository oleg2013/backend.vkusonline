# Private API

## Guest-Bound Endpoints

Required header: `X-Guest-Session-ID: <uuid>`

### Cart
- `GET /guest/cart` — Get guest cart
- `PUT /guest/cart/items` — Set cart items (replaces all). Body: `[{product_sku, quantity}]`
- `PATCH /guest/cart/items/{item_id}` — Update item quantity. Body: `{quantity}`
- `DELETE /guest/cart/items/{item_id}` — Remove item
- `DELETE /guest/cart` — Clear cart

### Checkout
- `POST /guest/checkout/create-order` — Create order from cart. Body: `{items, customer_email, customer_phone, customer_name, delivery_provider, delivery_city, pickup_point_id, idempotency_key}`

### Orders
- `GET /guest/orders/{order_number}` — Get order details
- `GET /guest/orders/{order_number}/status` — Get order status
- `POST /guest/orders/{order_number}/cancel` — Cancel order
- `POST /guest/orders/{order_number}/retry-payment` — Retry payment

### Payments
- `POST /guest/orders/{order_number}/payments/yookassa/create` — Create payment. Body: `{idempotency_key, confirmation_type?}`

---

## Customer JWT Endpoints

Required header: `Authorization: Bearer <access_token>`

### Profile
- `GET /me` — Get profile
- `PATCH /me` — Update profile. Body: `{first_name?, last_name?, phone?}`

### Addresses
- `GET /me/addresses` — List saved addresses
- `POST /me/addresses` — Add address
- `PATCH /me/addresses/{id}` — Update address
- `DELETE /me/addresses/{id}` — Delete address

### Session Merge
- `POST /me/merge-guest-session` — Merge guest cart and session. Requires `X-Guest-Session-ID` header.

### Cart (same as guest but user-scoped)
- `GET /me/cart`
- `PUT /me/cart/items`
- `PATCH /me/cart/items/{item_id}`
- `DELETE /me/cart/items/{item_id}`

### Orders
- `GET /me/orders?page=&per_page=` — List orders
- `GET /me/orders/{order_number}` — Order details
- `GET /me/orders/{order_number}/status` — Order status
- `POST /me/orders/{order_number}/cancel` — Cancel
- `POST /me/orders/{order_number}/retry-payment` — Retry payment

### Discounts
- `GET /me/discounts` — Personal discounts
- `GET /me/loyalty-summary` — Loyalty program summary

---

## Admin Endpoints

Required header: `Authorization: Bearer <admin_token>` (APP_SECRET_KEY)

- `GET /admin/orders/{order_number}` — Full order with events
- `GET /admin/orders/{order_number}/labels` — Shipping labels
- `POST /admin/jobs/sync-5post-points` — Trigger 5Post sync
- `POST /admin/jobs/sync-magnit-points` — Trigger Magnit sync
- `POST /admin/jobs/poll-magnit-statuses` — Trigger Magnit polling
- `POST /admin/orders/{order_number}/refresh-provider-state` — Refresh from provider
- `GET /admin/provider-events` — Webhook event log
- `GET /admin/pickup-points/cache-status` — Cache statistics

---

## Webhooks

- `POST /webhooks/yookassa` — YooKassa payment notifications
- `POST /webhooks/5post` — 5Post delivery status callbacks
