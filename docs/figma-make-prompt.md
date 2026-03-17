# Prompt for Figma Make (Claude Opus 4.6)

## Task

Write a TypeScript API adapter (client SDK) for the VKUS Online backend — a premium tea & coffee e-commerce platform. The adapter should be a single file that provides typed functions for every endpoint, ready to use in a React/Next.js frontend.

## Requirements

- TypeScript with strict types (no `any`)
- Use native `fetch` (no axios) — works in browser and Next.js server components
- All functions return typed results
- Error handling via a custom `ApiError` class
- Base URL configurable via parameter or environment variable `NEXT_PUBLIC_API_URL`
- Guest session ID stored/read from `localStorage` (key: `vkus_guest_session_id`)
- Auth token stored/read from `localStorage` (key: `vkus_access_token`, `vkus_refresh_token`)
- Auto-refresh token on 401 response (one retry)
- Generate UUID v4 for idempotency keys where needed

## API Overview

**Base URL:** `https://api.vkus.online/api/v1` (fallback for local dev: `http://localhost:8000/api/v1`)

**Response wrapper** — every endpoint returns:
```json
{ "ok": true, "data": { ... }, "request_id": "uuid" }
```
On error:
```json
{ "ok": false, "error": { "code": "string", "message": "string", "details": null }, "request_id": "uuid" }
```

**Auth patterns:**
- Guest endpoints: header `X-Guest-Session-ID: <uuid>`
- User endpoints: header `Authorization: Bearer <access_token>`
- Public endpoints: no auth headers
- Admin endpoints: header `Authorization: Bearer <admin_secret>`

## Endpoints to implement

### Health
- `GET /health` → `{ status: "healthy" }`

### Bootstrap
- `GET /bootstrap` → `{ delivery_providers, payment_providers, currency, min_order_amount, guest_session_required }`
- `GET /delivery/options` → `Array<{ provider, name, description, available }>`

### Auth
- `POST /auth/register` body: `{ email, password, phone?, first_name, last_name }` → `{ access_token, refresh_token, token_type, expires_in }`
- `POST /auth/login` body: `{ email, password }` → same as register
- `POST /auth/refresh` body: `{ refresh_token }` → same as register
- `POST /auth/logout` body: `{ refresh_token }` → `{ message }`

### Guest Session
- `POST /guest/session/bootstrap` body: `{ guest_session_id }` → `{ guest_session_id, created }`

### Catalog
**DO NOT integrate catalog with API.** The catalog backend is not yet implemented (only a stub exists). The catalog data is currently hardcoded in local `.ts` files in the frontend project — keep it that way. Do not generate any `catalog.*` methods. We will integrate the catalog API separately later.

### Cart (Guest) — header: X-Guest-Session-ID
- `GET /guest/cart` → `{ id, items: Array<CartItem>, subtotal, items_count }` where CartItem = `{ id, product_sku, quantity, unit_price, total_price }`
- `PUT /guest/cart/items` body: `Array<{ product_sku, quantity }>` → same as GET cart
- `PATCH /guest/cart/items/:itemId` body: `{ quantity }` → same as GET cart
- `DELETE /guest/cart/items/:itemId` → `{ message }`
- `DELETE /guest/cart` → `{ message }`

### Cart (User) — header: Authorization Bearer
- `GET /me/cart` → same structure as guest cart
- `PUT /me/cart/items` → same as guest
- `PATCH /me/cart/items/:itemId` → same as guest
- `DELETE /me/cart/items/:itemId` → same as guest

### Checkout
- `POST /checkout/quote` body: `{ items: [{sku, quantity}], delivery_provider, delivery_city, delivery_address?, pickup_point_id? }` → `{ subtotal, discount_amount, delivery_price, total, items_detail }`
- `POST /guest/checkout/create-order` (header: X-Guest-Session-ID) body: `{ items, delivery_provider, delivery_city, delivery_address?, delivery_price?, pickup_point_id?, pickup_point_name?, customer_email, customer_phone, customer_name, idempotency_key }` → `{ order_number, status, total, guest_order_token }`
- `POST /me/checkout/create-order` (header: Authorization) body: same → `{ order_number, status, total }`

### Orders (Guest) — header: X-Guest-Session-ID
- `GET /guest/orders/:orderNumber` → full order details with items array
- `GET /guest/orders/:orderNumber/status` → `{ order_number, status, payment_status, shipment_status }`
- `POST /guest/orders/:orderNumber/cancel` → `{ order_number, status: "cancelled" }`
- `POST /guest/orders/:orderNumber/retry-payment` → `{ order_number, message }`

### Orders (User) — header: Authorization Bearer
- `GET /me/orders?page=&per_page=` → `{ items: Array<OrderSummary>, total, page, per_page }`
- `GET /me/orders/:orderNumber` → full order details
- `GET /me/orders/:orderNumber/status` → order status
- `POST /me/orders/:orderNumber/cancel` → cancelled order
- `POST /me/orders/:orderNumber/retry-payment` → retry result

### Payments
- `POST /guest/orders/:orderNumber/payments/yookassa/create` (header: X-Guest-Session-ID) body: `{ idempotency_key, confirmation_type? }` → `{ payment_id, confirmation_url, status }`
- `POST /me/orders/:orderNumber/payments/yookassa/create` (header: Authorization) body: same → same

### Delivery — 5Post (public, no auth)
- `GET /delivery/5post/pickup-points?city=&lat=&lon=&limit=` → `Array<PickupPoint>` where PickupPoint = `{ id, name, type, city, full_address, lat, lon, cash_allowed, card_allowed, distance_km }`
- `POST /delivery/5post/estimate` → `{ provider, estimated_cost, estimated_days_min, estimated_days_max }`

### Delivery — Magnit (public, no auth)
- `GET /delivery/magnit/cities` → `Array<{ city, pickup_points_count }>`
- `GET /delivery/magnit/pickup-points?city=&lat=&lon=&limit=` → `Array<PickupPoint>`
- `GET /delivery/magnit/nearest-cities?lat=&lon=&limit=` → `Array<{ city, distance_km, pickup_points_count }>`
- `POST /delivery/magnit/estimate` → `{ provider, estimated_cost, estimated_days_min, estimated_days_max }`

### Geo (public, no auth)
- `POST /geo/city-suggest` body: `{ query }` → `{ suggestions: Array<{ value, data }> }`
- `POST /geo/street-suggest` body: `{ city, query }` → same
- `POST /geo/house-suggest` body: `{ city, street, query }` → same

### User Profile — header: Authorization Bearer
- `GET /me` → `{ id, email, phone, first_name, last_name, display_name, created_at }`
- `PATCH /me` body: `{ first_name?, last_name?, phone? }` → `{ message }`
- `GET /me/addresses` → `Array<Address>`
- `POST /me/addresses` body: `{ label?, city, street?, house?, apartment?, postal_code?, full_address, lat?, lon?, is_default? }` → `{ id }`
- `PATCH /me/addresses/:addressId` body: same (all optional) → `{ message }`
- `DELETE /me/addresses/:addressId` → `{ message }`
- `POST /me/merge-guest-session` (also needs X-Guest-Session-ID) → `{ message }`
- `GET /me/discounts` → `Array<{ name, type, value, is_active }>`
- `GET /me/loyalty-summary` → `{ level, points, next_level }`

### Admin — header: Authorization Bearer (admin secret)
- `GET /admin/orders/:orderNumber` → detailed order with events
- `GET /admin/orders/:orderNumber/labels` → `{ labels: [] }`
- `POST /admin/jobs/sync-5post-points` → `{ job_name, status: "triggered" }`
- `POST /admin/jobs/sync-magnit-points` → same
- `POST /admin/jobs/poll-magnit-statuses` → same
- `POST /admin/orders/:orderNumber/refresh-provider-state` → `{ message }`
- `GET /admin/provider-events` → `Array<ProviderEvent>`
- `GET /admin/pickup-points/cache-status` → `Array<{ provider, points_count, last_synced_at }>`

## Output Structure

Generate a single file `api-client.ts` with:

1. **Types** — interfaces for all request/response objects (CartItem, Order, PickupPoint, Address, etc.). Do NOT include catalog types (Product, Family) — they are defined locally in the frontend project.
2. **ApiError class** — extends Error, has `code`, `message`, `details`, `statusCode`
3. **VkusApiClient class** — constructor takes `{ baseUrl?, onTokenRefreshed? }`, has methods for every endpoint grouped by domain:
   - `health.check()`
   - `bootstrap.get()`, `bootstrap.deliveryOptions()`
   - `auth.register(data)`, `auth.login(data)`, `auth.refresh()`, `auth.logout()`
   - `guest.bootstrap(sessionId)`
   - ~~`catalog.*`~~ — **SKIP, not integrated yet**
   - `cart.get()`, `cart.setItems(items)`, `cart.updateItem(itemId, quantity)`, `cart.removeItem(itemId)`, `cart.clear()`
   - `checkout.quote(data)`, `checkout.createOrder(data)`
   - `orders.list(page?)`, `orders.get(orderNumber)`, `orders.status(orderNumber)`, `orders.cancel(orderNumber)`, `orders.retryPayment(orderNumber)`
   - `payments.createYookassa(orderNumber, data)`
   - `delivery.fivepost.pickupPoints(params)`, `delivery.fivepost.estimate()`
   - `delivery.magnit.cities()`, `delivery.magnit.pickupPoints(params)`, `delivery.magnit.nearestCities(params)`, `delivery.magnit.estimate()`
   - `geo.citySuggest(query)`, `geo.streetSuggest(city, query)`, `geo.houseSuggest(city, street, query)`
   - `profile.get()`, `profile.update(data)`
   - `addresses.list()`, `addresses.create(data)`, `addresses.update(id, data)`, `addresses.delete(id)`
   - `admin.order(orderNumber)`, `admin.syncFivepost()`, `admin.syncMagnit()`, `admin.cacheStatus()`
4. **Helper**: `createVkusApi(baseUrl?)` factory function
5. Cart and checkout methods should auto-detect guest vs user mode based on whether an access token exists

## Code Style
- Use `camelCase` for JS, map to `snake_case` API fields
- JSDoc comments on public methods
- Group related types together
- Export all types and the client class
