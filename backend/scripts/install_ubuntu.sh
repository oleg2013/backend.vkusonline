#!/usr/bin/env bash
# -------------------------------------------------------------------
# VKUS ONLINE backend -- server bootstrap for Ubuntu 22.04 / 24.04
# Run as root:  bash install_ubuntu.sh
# -------------------------------------------------------------------
set -euo pipefail

APP_USER="vkus"
APP_DIR="/opt/vkus-online"
DATA_DIR="/var/lib/vkus-online"
PYTHON_MIN="3.12"

# ---------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------
echo ">>> Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    software-properties-common curl gnupg2 lsb-release \
    build-essential libpq-dev git

# ---------------------------------------------------------------
# 2. Python 3.12+
# ---------------------------------------------------------------
echo ">>> Installing Python ${PYTHON_MIN}+ ..."
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv python3.12-dev

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# ---------------------------------------------------------------
# 3. PostgreSQL 16
# ---------------------------------------------------------------
echo ">>> Installing PostgreSQL 16..."
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg
echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] \
    http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
apt-get update -qq
apt-get install -y -qq postgresql-16

systemctl enable --now postgresql

# Create DB user and database
sudo -u postgres psql -c "CREATE USER vkus WITH PASSWORD 'vkus_secret';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE vkus_online OWNER vkus;" 2>/dev/null || true

# ---------------------------------------------------------------
# 4. Redis 7
# ---------------------------------------------------------------
echo ">>> Installing Redis..."
apt-get install -y -qq redis-server
systemctl enable --now redis-server

# ---------------------------------------------------------------
# 5. nginx
# ---------------------------------------------------------------
echo ">>> Installing nginx..."
apt-get install -y -qq nginx
systemctl enable --now nginx

# ---------------------------------------------------------------
# 6. Application user & directories
# ---------------------------------------------------------------
echo ">>> Creating application user and directories..."
id -u ${APP_USER} &>/dev/null || useradd -r -m -s /bin/bash ${APP_USER}

mkdir -p ${APP_DIR}
mkdir -p ${DATA_DIR}/{storage,logs}

chown -R ${APP_USER}:${APP_USER} ${APP_DIR} ${DATA_DIR}

# ---------------------------------------------------------------
# 7. systemd -- api
# ---------------------------------------------------------------
echo ">>> Creating systemd service: vkus-api..."
cat > /etc/systemd/system/vkus-api.service <<EOF
[Unit]
Description=VKUS ONLINE API
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn apps.api.main:app \\
    --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------------------------------------------------------------
# 8. systemd -- worker
# ---------------------------------------------------------------
echo ">>> Creating systemd service: vkus-worker..."
cat > /etc/systemd/system/vkus-worker.service <<EOF
[Unit]
Description=VKUS ONLINE Background Worker
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service

[Service]
Type=exec
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/.venv/bin/python -m apps.worker.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ---------------------------------------------------------------
# 9. nginx reverse proxy
# ---------------------------------------------------------------
echo ">>> Configuring nginx reverse proxy..."
cat > /etc/nginx/sites-available/vkus-online <<'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/docs {
        deny all;
        return 404;
    }
}
EOF

ln -sf /etc/nginx/sites-available/vkus-online /etc/nginx/sites-enabled/vkus-online
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ---------------------------------------------------------------
# Done
# ---------------------------------------------------------------
echo ""
echo "============================================="
echo "  Installation complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "  1. Clone the repo into ${APP_DIR}:"
echo "       git clone <repo-url> ${APP_DIR}"
echo ""
echo "  2. Create a virtual environment:"
echo "       cd ${APP_DIR}"
echo "       python3.12 -m venv .venv"
echo "       source .venv/bin/activate"
echo "       uv pip install -r backend/pyproject.toml"
echo ""
echo "  3. Copy and edit the env file:"
echo "       cp ${APP_DIR}/backend/.env.example ${APP_DIR}/backend/.env"
echo "       nano ${APP_DIR}/backend/.env"
echo ""
echo "  4. Run migrations:"
echo "       cd ${APP_DIR}/backend"
echo "       alembic upgrade head"
echo ""
echo "  5. Start services:"
echo "       systemctl enable --now vkus-api vkus-worker"
echo ""
echo "  6. (Optional) Set up SSL with certbot:"
echo "       apt install certbot python3-certbot-nginx"
echo "       certbot --nginx -d your-domain.com"
echo ""
