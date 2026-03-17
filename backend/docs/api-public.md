# Public API

Base URL: `/api/v1`

All responses use envelope format:

```json
// Success
{"ok": true, "data": {...}, "request_id": "uuid"}

// Error
{"ok": false, "error": {"code": "ERROR_CODE", "message": "...", "details": {}}, "request_id": "uuid"}
```

## Endpoints

### Health
- `GET /health` — Service health check

### Bootstrap
- `GET /bootstrap` — Frontend configuration (delivery providers, payment providers, currency, min order amount)

### Auth
- `POST /auth/register` — Register new user. Body: `{email, password, phone?, first_name?, last_name?}`
- `POST /auth/login` — Login. Body: `{email, password}`. Returns: `{access_token, refresh_token, token_type, expires_in}`
- `POST /auth/refresh` — Refresh tokens. Body: `{refresh_token}`. Returns new token pair.
- `POST /auth/logout` — Logout. Body: `{refresh_token}`. Revokes refresh token.

### Guest Session
- `POST /guest/session/bootstrap` — Create or validate guest session. Body: `{guest_session_id}`. Returns: `{guest_session_id, created}`

### Catalog
- `GET /catalog/families` — List product families with variants
- `GET /catalog/products?category=&family=` — List products
- `GET /catalog/products/{sku}` — Get product by SKU
- `GET /catalog/collections` — List curated collections

### Geo (DaData)
- `POST /geo/city-suggest` — City autocomplete. Body: `{query}`
- `POST /geo/street-suggest` — Street autocomplete. Body: `{city, query}`
- `POST /geo/house-suggest` — House autocomplete. Body: `{city, street, query}`

### Delivery
- `GET /delivery/options` — Available delivery providers
- `GET /delivery/5post/pickup-points?city=&lat=&lon=&limit=50` — 5Post pickup points
- `POST /delivery/5post/estimate` — 5Post delivery estimate
- `GET /delivery/magnit/cities` — Cities with Magnit pickup points
- `GET /delivery/magnit/pickup-points?city=&lat=&lon=` — Magnit pickup points
- `GET /delivery/magnit/nearest-cities?lat=&lon=&limit=5` — Nearest cities with Magnit
- `POST /delivery/magnit/estimate` — Magnit delivery estimate

### Checkout
- `POST /checkout/quote` — Calculate order total. Body: `{items: [{sku, quantity}], delivery_provider, city}`
