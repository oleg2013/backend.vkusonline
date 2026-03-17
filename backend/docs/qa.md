# QA Guide

## Running Tests

```bash
# All tests
make test

# With coverage
pytest --cov=packages --cov=apps --cov-report=term-missing

# Specific test file
pytest tests/unit/test_security.py

# Specific test
pytest tests/unit/test_security.py::test_hash_password

# Full QA (lint + format + tests)
make qa
```

## Test Categories

### Unit Tests (`tests/unit/`)

No database or external services required.

- `test_security.py` — Password hashing, JWT, token generation
- `test_utils.py` — Haversine, phone/email validation, order number generation
- `test_delivery_utils.py` — 5Post cell limits, cost calculation, Magnit parcel sizing
- `test_receipt_builder.py` — YooKassa receipt construction, VAT codes
- `test_discounts.py` — Discount calculation logic
- `test_idempotency.py` — Idempotency key caching

### Integration Tests (`tests/integration/`)

Use in-memory SQLite, no external services.

- `test_auth_flow.py` — Register, login, refresh, logout
- `test_guest_session.py` — Session lifecycle, merge
- `test_cart.py` — Cart CRUD, merge
- `test_checkout.py` — Quote, order creation, idempotency, cancellation
- `test_payments.py` — Payment creation, status processing

### Contract Tests (`tests/contract/`)

Mock external APIs with `respx`.

- `test_yookassa_mock.py` — Payment creation, status fetch
- `test_fivepost_mock.py` — JWT auth, pickup points

### E2E Smoke Tests

```bash
# Start services
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head

# Seed data
docker compose exec api python -m scripts.seed_catalog

# Run smoke test
pytest tests/e2e/ -v
```

## Code Quality

```bash
# Lint
ruff check .

# Format check
ruff format --check .

# Auto-fix
ruff check --fix .
ruff format .
```

## Live Provider Tests

Only run with real credentials (set env vars):

```bash
FIVEPOST_API_KEY=... LIVE_TESTS=1 pytest tests/contract/ -k live -v
```

## Coverage Targets

| Area | Target |
|------|--------|
| Security utils | 95%+ |
| Business logic (checkout, cart) | 85%+ |
| Integration clients | 70%+ (with mocks) |
| API routers | 70%+ |
