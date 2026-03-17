#!/usr/bin/env bash
# -------------------------------------------------------------------
# VKUS ONLINE -- QA pipeline: lint + format check + tests with coverage
# -------------------------------------------------------------------
set -euo pipefail

echo "=== Ruff check ==="
ruff check .

echo ""
echo "=== Ruff format check ==="
ruff format --check .

echo ""
echo "=== Pytest with coverage ==="
pytest --cov=apps --cov=packages --cov-report=term-missing -q

echo ""
echo "All checks passed."
