.PHONY: help dev prod up down logs clean migrate init-db migrate-create shell-db update-db

help:
	@echo "Available commands:"
	@echo "  make dev             - Start development environment"
	@echo "  make prod            - Start production environment"
	@echo "  make down            - Stop all containers"
	@echo "  make logs            - View logs"
	@echo "  make clean           - Remove containers and volumes"
	@echo "  make build           - Build Docker images"
	@echo "  make migrate         - Run database migrations"
	@echo "  make init-db         - Initialize database (create tables)"
	@echo "  make update-db       - Rebuild and apply database changes"
	@echo "  make migrate-create  - Create a new migration"
	@echo "  make shell-db        - Open PostgreSQL shell"

dev:
	@echo "Starting development environment..."
	cp env.dev.example .env 2>/dev/null || true
	docker compose --profile dev up -d

prod:
	@echo "Starting production environment..."
	cp env.prod.example .env 2>/dev/null || true
	docker compose --profile prod -f docker-compose.yml -f docker-compose.prod.yml up -d

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

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

shell-db:
	docker compose exec db psql -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-app_db}

update-db:
	@echo "Updating database with latest changes..."
	docker compose build api
	docker compose up -d api
	sleep 3
	docker compose exec -T api alembic upgrade head
	@echo "Database updated successfully!"

build:
	docker compose build
