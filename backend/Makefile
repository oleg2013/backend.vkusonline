.DEFAULT_GOAL := help

.PHONY: help dev test qa migrate migration up down logs build seed

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: ## Run API server with hot reload
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

test: ## Run test suite
	pytest

qa: ## Run linters and tests
	ruff check .
	ruff format --check .
	pytest

migrate: ## Apply all pending migrations
	alembic upgrade head

migration: ## Create a new migration (usage: make migration m="add users table")
	alembic revision --autogenerate -m "$(m)"

up: ## Start all containers in background
	docker compose up -d

down: ## Stop and remove containers
	docker compose down

logs: ## Follow container logs
	docker compose logs -f

build: ## Build Docker images
	docker compose build

seed: ## Seed catalog with sample products
	python -m scripts.seed_catalog
