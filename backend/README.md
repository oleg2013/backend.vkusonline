# VKUS ONLINE Backend

Production backend for the VKUS ONLINE premium tea & coffee e-commerce platform.

## Stack

- **Python 3.13** + **FastAPI** + **Pydantic v2**
- **SQLAlchemy 2.x** (async) + **Alembic**
- **PostgreSQL 16** + **Redis 7**
- **HTTPX** for external API calls
- **APScheduler** for background jobs
- **Docker Compose** for deployment

## Quick Start

```bash
# Clone and enter project
cd backend

# Copy env
cp .env.example .env
# Edit .env with your credentials

# Start with Docker
make up

# Run migrations
make migrate

# Seed catalog
make seed

# Development mode (without Docker)
make dev
```

## Project Structure

```
backend/
  apps/
    api/          # FastAPI application, routers, middleware
    worker/       # Background job scheduler
  packages/
    core/         # Config, DB, Redis, security, utils
    models/       # SQLAlchemy ORM models
    schemas/      # Pydantic request/response schemas
    services/     # Business logic layer
    integrations/ # External provider clients (5Post, Magnit, YooKassa, DaData)
    enums/        # Shared enumerations
  migrations/     # Alembic database migrations
  tests/          # Unit, integration, contract, e2e tests
  scripts/        # Deployment and utility scripts
  docs/           # Architecture and API documentation
```

## Key Commands

| Command | Description |
|---------|-------------|
| `make dev` | Start dev server with hot reload |
| `make test` | Run test suite |
| `make qa` | Run linter + formatter check + tests |
| `make migrate` | Apply database migrations |
| `make up` | Start all services via Docker Compose |
| `make down` | Stop all services |
| `make seed` | Seed catalog with sample products |

## API Zones

| Zone | Auth | Description |
|------|------|-------------|
| Public | None | Catalog, health, bootstrap, geo, delivery discovery |
| Guest-bound | X-Guest-Session-ID | Cart, checkout, order management |
| Customer | JWT Bearer | Profile, addresses, order history, discounts |
| Admin | Admin token | Order management, job triggers, provider events |

## Documentation

- [Architecture](docs/architecture.md)
- [Public API](docs/api-public.md)
- [Private API](docs/api-private.md)
- [Frontend Integration](docs/frontend-integration.md)
- [Deployment](docs/deployment.md)
- [QA](docs/qa.md)
