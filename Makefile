SRC        := app/ webhook_mock_server/ tests/ migrations/
PYTEST     := uv run python -m pytest
INFRA      := docker compose -f docker-compose.infra.yml
service    ?=

.DEFAULT_GOAL := help

##@ Help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Setup

.PHONY: install
install: ## Install dependencies, including dev
	uv sync --dev

##@ Local run (needs `make infra` and `make migrate`)

.PHONY: api relay consumer webhook-mock-server
api: ## Run the API with autoreload
	uv run uvicorn app.api.main:app --reload --no-access-log

relay: ## Run the outbox relay
	uv run faststream run app.worker.outbox_relay:app

consumer: ## Run the payments consumer
	uv run faststream run app.worker.consumer:app

webhook-mock-server: ## Run a local webhook mock server that logs incoming webhooks (port 9000)
	uv run uvicorn webhook_mock_server.main:app --port 9000 --no-access-log

##@ Code quality

.PHONY: check lint lint-fix format mypy
check: lint mypy test ## Lint, type-check and run all tests

lint: ## Check code with ruff
	uv run ruff check $(SRC)

lint-fix: ## Fix auto-fixable ruff issues
	uv run ruff check --fix $(SRC)

format: ## Format code with ruff
	uv run ruff format $(SRC)

mypy: ## Type-check with mypy
	uv run mypy app/ webhook_mock_server/

##@ Tests

.PHONY: test test-unit test-integration
test: ## Run all tests
	$(PYTEST) tests/ -v

test-unit: ## Run unit tests
	$(PYTEST) tests/unit/ -v

test-integration: ## Run integration tests (needs Docker for testcontainers)
	$(PYTEST) tests/integration/ -v

##@ Database migrations

.PHONY: migrate migrate-new migrate-down migration-current migration-head migration-history
migrate: ## Apply all migrations
	uv run alembic upgrade head

migrate-new: ## Autogenerate a revision from app/db models
	@read -p "Migration name: " name; \
	uv run alembic revision --autogenerate -m "$$name"

migrate-down: ## Roll back the last migration
	uv run alembic downgrade -1

migration-current: ## Show the applied revision
	uv run alembic current

migration-head: ## Show the latest revision
	uv run alembic heads

migration-history: ## Show the revision history
	uv run alembic history

##@ Docker: infrastructure only (postgres + rabbitmq)

.PHONY: infra-up infra-down
infra-up: ## Start postgres and rabbitmq
	$(INFRA) up -d

infra-down: ## Stop postgres and rabbitmq
	$(INFRA) down

##@ Docker: full app

.PHONY: build up up-mock down restart logs
build: ## Build the app image
	docker compose build

up: ## Start the whole app
	docker compose up -d

up-mock: ## Start the whole app with the webhook mock server
	docker compose --profile mock up -d

# --profile mock: plain `down` leaves the mock server running and can't remove the network.
down: ## Stop the whole app
	docker compose --profile mock down

restart: ## Rebuild and restart the whole app
	docker compose --profile mock down
	docker compose up -d --build

logs: ## Follow logs (all services or `make logs service=api`)
	docker compose logs -f --tail=100 $(service)
