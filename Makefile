.PHONY: help dev prod up down logs clean migrate

help:
	@echo "Available commands:"
	@echo "  make dev        - Start development environment"
	@echo "  make prod       - Start production environment"
	@echo "  make down       - Stop all containers"
	@echo "  make logs       - View logs"
	@echo "  make clean      - Remove containers and volumes"
	@echo "  make migrate    - Run database migrations"
	@echo "  make build      - Build Docker images"

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

build:
	docker compose build
