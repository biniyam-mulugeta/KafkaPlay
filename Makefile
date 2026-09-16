.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE      ?= docker compose
DEV_COMPOSE  := $(COMPOSE) -f docker-compose.dev.yml
PROFILE      ?=
PROFILE_ARG  := $(if $(PROFILE),--profile $(PROFILE),)
VENV         := backend/.venv
PY           := $(VENV)/bin/python

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- production ------------------------------------------------------------

.PHONY: up
up: ## Start the production stack
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the production stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Follow console logs
	$(COMPOSE) logs -f console

# --- development -----------------------------------------------------------

.PHONY: dev
dev: ## Start the dev stack (PROFILE=cluster|metrics for extras)
	$(DEV_COMPOSE) $(PROFILE_ARG) up -d --build
	@echo
	@echo "Console:  http://127.0.0.1:$${CONSOLE_PORT:-8080}"
	@echo "Login:    admin / kafkaplay-dev-password"

.PHONY: dev-down
dev-down: ## Stop the dev stack and remove its volumes
	$(DEV_COMPOSE) --profile cluster --profile metrics down -v

.PHONY: dev-logs
dev-logs: ## Follow dev stack logs
	$(DEV_COMPOSE) logs -f

.PHONY: seed
seed: ## Restart the data seeder
	$(DEV_COMPOSE) restart seeder

# --- local (no Docker) -----------------------------------------------------

.PHONY: install
install: ## Create the venv and install all dependencies
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "./backend[codecs,oidc,dev]"
	cd frontend && npm ci --no-audit --no-fund

.PHONY: backend
backend: ## Run the backend alone on :8080
	cd backend && .venv/bin/python -m uvicorn app.main:create_app --factory \
	  --reload --host 127.0.0.1 --port $${CONSOLE_PORT:-8080}

.PHONY: frontend
frontend: ## Run the Vite dev server on :5173 (proxies to the backend)
	cd frontend && npm run dev

# --- quality ---------------------------------------------------------------

.PHONY: test
test: test-backend test-frontend ## Run every test suite

.PHONY: test-backend
test-backend: ## Backend unit tests
	cd backend && .venv/bin/python -m pytest -q

.PHONY: test-integration
test-integration: ## Backend integration tests (needs KAFKAPLAY_TEST_BOOTSTRAP)
	cd backend && KAFKAPLAY_TEST_BOOTSTRAP=$${KAFKAPLAY_TEST_BOOTSTRAP:-localhost:9092} \
	  .venv/bin/python -m pytest -q -m integration

.PHONY: test-frontend
test-frontend: ## Frontend unit tests
	cd frontend && npm run test

.PHONY: e2e
e2e: ## Playwright smoke test against a running stack
	cd frontend && npx playwright test

.PHONY: lint
lint: ## Lint and typecheck everything
	cd backend && .venv/bin/ruff check app tests healthcheck.py && .venv/bin/ruff format --check app tests healthcheck.py
	cd backend && .venv/bin/mypy app healthcheck.py
	cd frontend && npm run lint && npm run typecheck

.PHONY: format
format: ## Auto-format the backend
	cd backend && .venv/bin/ruff format app tests healthcheck.py && .venv/bin/ruff check --fix app tests healthcheck.py

.PHONY: build
build: ## Build the production image
	docker build -t kafkaplay:local .
