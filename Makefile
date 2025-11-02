.PHONY: help dev prod up down logs logs-api clean migrate init-db migrate-create migrate-create-simple shell-db update-db build build-api build-worker test test-rrule test-scheduler coverage shell-api shell-worker

help:
	@echo "Available commands:"
	@echo "  make dev             - Start development environment"
	@echo "  make prod            - Start production environment"
	@echo "  make down            - Stop all containers"
	@echo "  make logs            - View all service logs"
	@echo "  make logs-api        - View API logs only"
	@echo "  make clean           - Remove containers and volumes"
	@echo "  make build           - Build Docker images"
	@echo "  make build-api       - Rebuild API container"
	@echo "  make build-worker    - Recreate worker and beat containers"
	@echo "  make migrate         - Run database migrations"
	@echo "  make init-db         - Initialize database (create tables)"
	@echo "  make update-db       - Rebuild and apply database changes"
	@echo "  make migrate-create  - Create a new migration (interactive)"
	@echo "  make migrate-create-simple MSG='msg' - Create migration with message"
	@echo "  make shell-db        - Open PostgreSQL shell"
	@echo "  make shell-api       - Open shell in API container"
	@echo "  make shell-worker    - Open shell in worker container"
	@echo ""
	@echo "Testing commands:"
	@echo "  make test            - Run all tests"
	@echo "  make test-rrule      - Run RRULE-specific tests"
	@echo "  make test-scheduler  - Run scheduler service tests"
	@echo "  make coverage        - Run tests with coverage report"

dev:
	@echo "Starting development environment..."
	@test ! -f .env && cp env.dev.example .env || true
	docker compose --profile dev up -d

prod:
	@echo "Starting production environment..."
	@test ! -f .env && cp env.prod.example .env || true
	docker compose --profile prod -f docker-compose.yml -f docker-compose.prod.yml up -d

up:
	docker compose up -d

down:
	docker compose --profile dev --profile prod down

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

clean:
	docker compose down -v
	docker system prune -f

migrate:
	docker compose exec api alembic upgrade head

init-db:
	@echo "Initializing database..."
	docker compose up -d db
	sleep 5
	docker compose exec -T api alembic upgrade head
	@echo "Database initialized successfully!"

migrate-create:
	@echo "Creating new migration..."
	@read -p "Enter migration message: " msg; \
	docker compose exec api alembic revision --autogenerate -m "$$msg"

migrate-create-simple:
	@if [ -z "$(MSG)" ]; then \
		echo "Error: MSG parameter is required"; \
		echo "Usage: make migrate-create-simple MSG='your migration message'"; \
		echo "Example: make migrate-create-simple MSG='add user model'"; \
		exit 1; \
	fi; \
	echo "Creating new migration: $(MSG)"; \
	docker compose exec -T api alembic revision --autogenerate -m "$(MSG)"; \
	echo "Copying all migration files back to host..."; \
	docker compose cp api:/app/migrations/versions ./migrations/; \
	echo "Migration files synced to local filesystem."

shell-db:
	docker compose exec db psql -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app_db}

update-db:
	@echo "Updating database with latest changes..."
	#docker compose build api
	#docker compose up -d api
	#sleep 3
	docker compose exec -T api alembic upgrade head
	@echo "Database updated successfully!"

build:
	docker compose build

build-api:
	@echo "Rebuilding API container..."
	docker compose build api
	docker compose up -d --force-recreate api
	@echo "API container rebuilt and restarted!"

build-worker:
	@echo "Rebuilding worker and beat containers..."
	docker compose up -d --force-recreate worker beat
	@echo "Worker and beat containers recreated!"

# Testing commands
test:
	@echo "Running all tests..."
	docker compose exec api pytest tests/ -v

test-rrule:
	@echo "Running RRULE-specific tests..."
	docker compose exec api pytest tests/test_scheduler_service.py -k "rrule" -v

test-scheduler:
	@echo "Running scheduler service tests..."
	docker compose exec api pytest tests/test_scheduler_service.py -v

coverage:
	@echo "Running tests with coverage..."
	docker compose exec api pytest tests/ --cov=src --cov-report=html --cov-report=term

# Shell access commands
shell-api:
	@echo "Opening shell in API container..."
	docker compose exec api bash

shell-worker:
	@echo "Opening shell in worker container..."
	docker compose exec worker bash
