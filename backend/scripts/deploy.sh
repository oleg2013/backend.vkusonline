#!/usr/bin/env bash
# -------------------------------------------------------------------
# deploy.sh — deploy backend to vkus.com and restart services
# Usage:  bash scripts/deploy.sh
# Run from:  backend/  directory
# -------------------------------------------------------------------
set -euo pipefail

SERVER="root@vkus.com"
REMOTE_DIR="/opt/vkus-backend"

echo ">>> Syncing code to ${SERVER}:${REMOTE_DIR} ..."
rsync -avz --delete \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.docker.bak' \
  --exclude='data/' \
  ./ "${SERVER}:${REMOTE_DIR}/"

echo ">>> Restarting services..."
ssh "${SERVER}" 'systemctl restart vkus-api vkus-worker'

echo ">>> Checking status..."
ssh "${SERVER}" 'sleep 1 && systemctl is-active vkus-api vkus-worker'

echo ""
echo "✓ Deployed and restarted!"
