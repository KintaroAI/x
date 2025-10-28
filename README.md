# X Scheduler

A web application for scheduling and publishing posts to X (Twitter) with scheduled posting capabilities.

## Architecture

This project uses Docker Compose to orchestrate multiple services:

- **api**: FastAPI web server with HTMX-based UI
- **worker**: APScheduler worker for scheduled tasks (placeholder for future implementation)
- **db**: PostgreSQL database
- **redis**: Redis for caching and job queuing (configured but not yet actively used)

## Features

- 🐦 **Post Management**: Create, edit, and delete posts with support for text and media
- ⏰ **Scheduled Publishing**: Schedule posts for one-time or recurring publication
- 📊 **Job Tracking**: Track publish jobs with status monitoring (pending, running, completed, failed, cancelled)
- 📝 **Audit Logging**: Comprehensive audit trail of all system events
- 🎯 **Profile Caching**: Cached Twitter profile data with automatic expiration
- 🔐 **Token Management**: Automatic token refresh and management for Twitter API

## Prerequisites

- Docker and Docker Compose installed
- X (Twitter) API credentials (client ID and secret)
- PostgreSQL database (handled via Docker Compose)

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

3. **Initialize database (first time setup):**
   ```bash
   make init-db
   ```

4. **Access the application:**
   - UI: http://localhost:8000
   - API Docs: http://localhost:8000/docs

5. **View logs:**
   ```bash
   make logs          # All services
   make logs-api      # API service only
   # Or for a specific service
   docker compose logs -f api
   ```

6. **Stop services:**
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

4. **View logs:**
   ```bash
   make logs
   ```

## Environment Variables

Key environment variables (defined in `.env` or via env files):

- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password  
- `POSTGRES_DB`: Database name
- `X_CLIENT_ID`: X API client ID
- `X_CLIENT_SECRET`: X API client secret
- `X_REDIRECT_URI`: OAuth redirect URI
- `ENVIRONMENT`: Environment (dev/prod)
- `REDIS_URL`: Redis connection string (optional)

## Makefile Commands

```bash
# Development & Production
make dev             # Start development environment
make prod            # Start production environment
make down            # Stop all containers
make up              # Start containers (no profile)

# Logging
make logs            # View all service logs
make logs-api        # View API logs only

# Database Operations
make init-db         # Initialize database (create tables)
make update-db       # Update database (rebuild container and apply migrations)
make migrate         # Run database migrations
make migrate-create  # Create a new migration (interactive)
make migrate-create-simple MSG='message'  # Create migration with message
make shell-db        # Open PostgreSQL shell

# Building
make build           # Build Docker images
make build-api       # Rebuild API container only

# Cleanup
make clean           # Remove containers and volumes

# Help
make help            # Show all available commands
```

## Project Structure

```
.
├── src/                      # Application source code
│   ├── main.py              # FastAPI application entry point
│   ├── worker.py            # APScheduler worker (placeholder)
│   ├── models.py            # SQLAlchemy database models
│   ├── database.py          # Database utilities and session management
│   ├── audit.py             # Audit logging utilities
│   ├── api/                 # API endpoint modules
│   │   ├── routes.py        # Page routes and UI templates
│   │   ├── posts.py         # Post CRUD endpoints
│   │   ├── twitter.py       # Twitter/X API endpoints
│   │   └── audit.py         # Audit log endpoints
│   ├── services/            # Business logic services
│   │   └── twitter_service.py  # Twitter API service (token management, profile fetching)
│   └── utils/               # Utility functions
│       └── twitter_utils.py    # Twitter API helpers
├── templates/               # HTML templates (HTMX-based UI)
│   ├── base.html           # Base template
│   ├── index.html          # Main page (post listing)
│   ├── create_post.html    # Post creation/editing form
│   ├── view_post.html      # Post detail view
│   ├── audit_log.html      # Audit log viewer
│   └── health.html         # Health check page
├── migrations/              # Alembic database migrations
│   ├── env.py             # Alembic environment configuration
│   ├── script.py.mako     # Migration template
│   └── versions/           # Migration files
├── docker-compose.yml      # Docker Compose configuration
├── docker-compose.prod.yml # Production overrides
├── docker-compose.override.yml  # Development overrides
├── Dockerfile              # Docker image definition
├── Makefile               # Development commands
├── requirements.txt       # Python dependencies
├── pyproject.toml        # Project configuration
├── alembic.ini           # Alembic configuration
├── PLAN.md               # Project planning document
└── DATABASE.md           # Database documentation
```

## Database Models

The application uses the following main database tables:

- **AuditLog**: System event logging with timestamps, levels, and metadata
- **TokenManagement**: OAuth token storage and management
- **Account**: X/Twitter account information
- **Post**: Post content with text and media references
- **Schedule**: Post scheduling configuration (one-shot, cron, or RRULE)
- **PublishJob**: Individual publish job tracking with status
- **PublishedPost**: Mapping of posts to published X post IDs
- **MetricsSnapshot**: Time-series metrics for published posts
- **ProfileCache**: Cached Twitter profile data with expiration

## API Endpoints

### Page Routes (HTML)
- `GET /` - Main page (post listing)
- `GET /create-post` - Create new post
- `GET /edit-post/{post_id}` - Edit existing post
- `GET /view-post/{post_id}` - View post details
- `GET /audit-log` - Audit log viewer
- `GET /health-ux` - Health check page

### API Routes (JSON/HTML)
- `GET /api/health` - Health check
- `GET /api/hello` - Hello world
- `GET /api/posts` - List all posts
- `POST /api/posts` - Create new post
- `GET /api/posts/{post_id}` - Get post details
- `POST /api/posts/{post_id}` - Update post
- `DELETE /api/posts/{post_id}` - Delete post
- `POST /api/posts/{post_id}/restore` - Restore deleted post
- `POST /api/posts/{post_id}/instant-publish` - Publish post immediately
- `POST /api/twitter/profile` - Get Twitter profile
- `GET /api/audit-log` - Get audit log entries

## Development

### Local Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .

# Run the API
python -m src.main

# Run the worker (placeholder)
python -m src.worker
```

### Database Migrations

```bash
# Create a new migration
make migrate-create-simple MSG='add new field to posts'

# Apply migrations
make migrate

# Check migration status
docker compose exec api alembic current

# Rollback last migration
docker compose exec api alembic downgrade -1
```

## License

See LICENSE file for details.
