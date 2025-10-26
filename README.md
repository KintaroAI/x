# Python Project

A Python project boilerplate with FastAPI backend and PostgreSQL database.

## Architecture

This project uses Docker Compose to orchestrate multiple services:

- **api**: FastAPI web server
- **worker**: APScheduler worker for scheduled tasks
- **db**: PostgreSQL database
- **redis**: Redis for caching and job queuing

## Prerequisites

- Docker and Docker Compose installed
- X (Twitter) API credentials

## Quick Start

### Development Environment

1. **Create environment file:**
   ```bash
   cp env.dev.example .env
   # Edit .env and add your X API credentials
   ```

2. **Start the development environment:**
   ```bash
   make dev
   ```
   Or manually:
   ```bash
   docker compose --profile dev up -d
   ```

3. **Access the application:**
   - UI: http://localhost:8000
   - API Docs: http://localhost:8000/docs

4. **View logs:**
   ```bash
   make logs
   # Or for a specific service
   docker compose logs -f api
   ```

5. **Stop services:**
   ```bash
   make down
   ```

### Production Environment

1. **Create environment file:**
   ```bash
   cp env.prod.example .env
   # Edit .env with production credentials and secure passwords
   ```

2. **Start the production environment:**
   ```bash
   make prod
   ```
   Or manually:
   ```bash
   docker compose --profile prod -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

3. **Initialize database (first time setup):**
   ```bash
   make init-db
   ```
   Or run migrations manually:
   ```bash
   make migrate
   # Or manually
   docker compose exec api alembic upgrade head
   ```

4. **View logs:**
   ```bash
   docker compose logs -f
   ```

## Environment Variables

Key environment variables (defined in `.env.dev` or `.env.prod`):

- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password  
- `POSTGRES_DB`: Database name
- `X_CLIENT_ID`: X API client ID
- `X_CLIENT_SECRET`: X API client secret
- `X_REDIRECT_URI`: OAuth redirect URI
- `ENVIRONMENT`: Environment (dev/prod)

## Development Commands

```bash
# Start development environment
make dev

# Start production environment
make prod

# Stop all containers
make down

# View logs
make logs

# Initialize database (creates tables)
make init-db

# Update database (rebuild container and apply migrations)
make update-db

# Run database migrations
make migrate

# Create a new migration
make migrate-create

# Access database shell
make shell-db

# Clean up (removes containers and volumes)
make clean

# Build Docker images
make build
```

## Project Structure

```
.
├── src/                  # Application source code
│   ├── main.py          # FastAPI application
│   ├── worker.py        # APScheduler worker
│   ├── models.py        # Database models
│   ├── database.py      # Database utilities
│   └── audit.py         # Audit logging utilities
├── templates/            # HTML templates (HTMX)
│   ├── base.html        # Base template
│   └── index.html       # Main page
├── migrations/           # Database migrations
│   ├── env.py           # Alembic configuration
│   └── versions/        # Migration files
├── docker-compose.yml   # Docker Compose configuration
├── Dockerfile           # Docker image definition
├── Makefile            # Development commands
├── requirements.txt     # Python dependencies
└── pyproject.toml      # Project configuration
```

## Development

### Local Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .

# Run the API
python -m src.main

# Run the worker
python -m src.worker
```
