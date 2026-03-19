# Deployment Guide

## Prerequisites

- VPS with Ubuntu 22.04 or Rocky Linux 9
- 2+ CPU cores, 4+ GB RAM
- PostgreSQL 16
- Redis 7
- Python 3.12+
- nginx

## Docker Deployment (Recommended)

```bash
# 1. Clone repository
git clone <repo> /opt/vkus-backend
cd /opt/vkus-backend/backend

# 2. Configure
cp .env.example .env
# Edit .env with production values:
# - APP_ENV=production
# - APP_DEBUG=false
# - Strong APP_SECRET_KEY and JWT_SECRET_KEY
# - Real database credentials
# - Provider API keys

# 3. Build and start
docker compose up -d --build

# 4. Run migrations
docker compose exec api alembic upgrade head

# 5. Seed catalog
docker compose exec api python -m scripts.seed_catalog
```

## nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name api.vkus.online;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.vkus.online;

    ssl_certificate /etc/letsencrypt/live/api.vkus.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.vkus.online/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

## Persistent Volumes

| Path                       | Description                          |
| -------------------------- | ------------------------------------ |
| `/var/lib/postgresql/data` | Database files                       |
| `/var/lib/redis/data`      | Redis persistence                    |
| `./data/storage`           | Local file storage (labels, exports) |
| `./logs`                   | Application logs                     |

## Database Backup

```bash
# Daily backup via cron
0 2 * * * pg_dump -U vkus vkus_online | gzip > /backup/vkus_$(date +\%Y\%m\%d).sql.gz

# Restore
gunzip < backup.sql.gz | psql -U vkus vkus_online
```

## Updates

```bash
cd /opt/vkus-backend
git pull
cd backend
docker compose build
docker compose exec api alembic upgrade head
docker compose up -d
```

## Log Rotation

Add to `/etc/logrotate.d/vkus`:

```
/opt/vkus-backend/backend/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
}
```

## Migration Flow

Always run migrations before starting the new version:

```bash
docker compose exec api alembic upgrade head
docker compose up -d --build
```

## Health Check

```bash
curl http://localhost:8000/api/v1/health
# Expected: {"ok": true, "data": {"status": "healthy"}}
```

## Monitoring

- Check `/api/v1/health` endpoint
- Monitor PostgreSQL connections
- Monitor Redis memory usage
- Watch application logs for errors
- Check `/api/v1/admin/pickup-points/cache-status` for sync freshness
