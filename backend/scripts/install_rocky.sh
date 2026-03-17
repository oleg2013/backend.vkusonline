#!/usr/bin/env bash
# -------------------------------------------------------------------
# VKUS ONLINE backend -- server bootstrap for Rocky Linux 9
# Run as root:  bash install_rocky.sh
# -------------------------------------------------------------------
set -euo pipefail

APP_USER="vkus"
APP_DIR="/opt/vkus-online"
DATA_DIR="/var/lib/vkus-online"
PYTHON_MIN="3.12"

# ---------------------------------------------------------------
# 1. System packages & repositories
# ---------------------------------------------------------------
echo ">>> Installing system packages..."
dnf install -y -q epel-release
dnf install -y -q \
    gcc gcc-c++ make libpq-devel git curl \
    dnf-plugins-core

# ---------------------------------------------------------------
# 2. Python 3.12+
# ---------------------------------------------------------------
echo ">>> Installing Python ${PYTHON_MIN}+ ..."
dnf install -y -q python3.12 python3.12-devel python3.12-pip

# Install uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# ---------------------------------------------------------------
# 3. PostgreSQL 16
# ---------------------------------------------------------------
echo ">>> Installing PostgreSQL 16..."
dnf install -y -q \
    https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm \
    2>/dev/null || true
dnf -qy module disable postgresql 2>/dev/null || true
dnf install -y -q postgresql16-server postgresql16

/usr/pgsql-16/bin/postgresql-16-setup initdb 2>/dev/null || true
systemctl enable --now postgresql-16

# Create DB user and database
sudo -u postgres /usr/pgsql-16/bin/psql \
    -c "CREATE USER vkus WITH PASSWORD 'vkus_secret';" 2>/dev/null || true
sudo -u postgres /usr/pgsql-16/bin/psql \
    -c "CREATE DATABASE vkus_online OWNER vkus;" 2>/dev/null || true

# ---------------------------------------------------------------
# 4. Redis 7
# ---------------------------------------------------------------
echo ">>> Installing Redis..."
dnf install -y -q redis
systemctl enable --now redis

# ---------------------------------------------------------------
# 5. nginx
# ---------------------------------------------------------------
echo ">>> Installing nginx..."
dnf install -y -q nginx
systemctl enable --now nginx

# Open firewall ports
firewall-cmd --permanent --add-service=http 2>/dev/null || true
firewall-cmd --permanent --add-service=https 2>/dev/null || true
firewall-cmd --reload 2>/dev/null || true

# SELinux: allow nginx to connect to upstream
setsebool -P httpd_can_network_connect 1 2>/dev/null || true

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
After=network.target postgresql-16.service redis.service
Requires=postgresql-16.service redis.service

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
After=network.target postgresql-16.service redis.service
Requires=postgresql-16.service redis.service

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
cat > /etc/nginx/conf.d/vkus-online.conf <<'EOF'
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
echo "       dnf install certbot python3-certbot-nginx"
echo "       certbot --nginx -d your-domain.com"
echo ""
