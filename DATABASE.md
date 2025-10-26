# Database Setup Guide

## Overview

This project uses PostgreSQL with Alembic for database migrations. The `audit_log` table tracks system events and user activities.

## Database Schema

### audit_log Table

The `audit_log` table tracks all system events with the following fields:

- **id**: Primary key (auto-increment)
- **timestamp**: When the event occurred
- **level**: Log level (INFO, WARNING, ERROR, CRITICAL)
- **component**: Component that generated the event (api, worker, scheduler, etc.)
- **action**: Type of action (login, post_scheduled, error, etc.)
- **message**: Descriptive message
- **extra_data**: JSON string with additional context
- **user_id**: User identifier (if applicable)
- **ip_address**: Client IP address (if applicable)
- **created_at**: Record creation timestamp

**Indexes:**
- `timestamp` - For time-based queries
- `level` - For filtering by log level
- `user_id` - For user-specific queries

## Usage

### Starting the Database

1. **Development:**
   ```bash
   make dev
   make init-db
   ```

2. **Production:**
   ```bash
   make prod
   make init-db
   ```

### Running Migrations

After starting the database:

```bash
# First time setup (creates tables)
make init-db

# Apply pending migrations
make migrate
```

### Creating New Migrations

When you modify database models, create a migration:

```bash
make migrate-create
# Enter a descriptive migration message
```

### Database Access

Connect to the database shell:

```bash
make shell-db
```

Example queries:

```sql
-- View all audit logs
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 10;

-- Filter by level
SELECT * FROM audit_log WHERE level = 'ERROR';

-- Filter by user
SELECT * FROM audit_log WHERE user_id = 'some_user_id';

-- Count events by level
SELECT level, COUNT(*) FROM audit_log GROUP BY level;
```

### Using Audit Logging in Code

Import and use the audit logging functions:

```python
from src.audit import log_info, log_error, log_warning

# Log an info event
log_info(
    action="user_login",
    message="User logged in successfully",
    component="api",
    user_id="user123"
)

# Log an error event
log_error(
    action="database_error",
    message="Failed to connect to database",
    component="api",
    extra_data='{"error": "Connection timeout"}'
)

# Log with custom metadata
from src.audit import log_audit_event
import json

log_audit_event(
    level="WARNING",
    action="rate_limit_exceeded",
    message="API rate limit approaching",
    component="worker",
    extra_data=json.dumps({"limit": 100, "current": 95})
)
```

## Environment Variables

Key database configuration in `.env`:

```bash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=app_db_dev
POSTGRES_PORT=5432
```

## Makefile Commands

- `make init-db` - Initialize database (create tables)
- `make migrate` - Run pending migrations
- `make migrate-create` - Create a new migration
- `make shell-db` - Open PostgreSQL shell

## Troubleshooting

### Database connection errors

Check if the database container is running:
```bash
docker compose ps
```

Check database logs:
```bash
docker compose logs db
```

### Migration errors

Reset database (WARNING: this deletes all data):
```bash
make clean
make init-db
```

### View current migration status

```bash
docker compose exec api alembic current
```

### View migration history

```bash
docker compose exec api alembic history
```

