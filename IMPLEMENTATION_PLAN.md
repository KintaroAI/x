# Celery Worker Implementation Plan

## Overview
This document breaks down the QUEUE.md implementation into small, manageable iterations that can be completed and tested incrementally.

## Current State
- ✅ Database models exist (posts, schedules, publish_jobs, etc.)
- ✅ PostgreSQL and Redis containers configured
- ✅ API endpoints exist
- ❌ PublishJob missing fields: `enqueued_at`, `attempt`, `last_run_at`
- ❌ No Celery setup
- ❌ No worker tasks
- ❌ No scheduler service

---

## Implementation Phases

### Phase 1: Foundation Setup (Iteration 1-3)

#### Iteration 1: Install Dependencies & Setup Celery App
**Goal**: Get Celery installed and configured with basic setup

**Tasks:**
1. Add Celery and Celery Beat to `requirements.txt`
   - `celery>=5.3.0`
   - `celery[redis]>=5.3.0`
   - `flower>=2.0.0` (optional, for monitoring)
2. Create `src/celery_app.py` with basic configuration
3. Add Celery to docker-compose worker service
4. Test that worker can start and connect to Redis

**Deliverables:**
- Updated `requirements.txt`
- New file `src/celery_app.py`
- Updated `docker-compose.yml` worker command

**Test**: Run `celery -A src.celery_app inspect ping` to verify worker is running

---

#### Iteration 2: Database Schema Updates
**Goal**: Add missing fields to PublishJob and Schedule models

**Tasks:**
1. Update `PublishJob` model in `src/models.py`:
   - Add `enqueued_at` (DateTime)
   - Add `attempt` (Integer, default=0)
   - Update status enum to include all new states
   - Add unique constraint on `(schedule_id, planned_at)`
2. Update `Schedule` model:
   - Add `last_run_at` (DateTime)
   - Rename `enabled` to `active` for consistency
3. Create Alembic migration: `004_update_publish_job_fields.py`
4. Run migration

**Deliverables:**
- Updated `src/models.py`
- New migration file in `migrations/versions/`
- Migration applied to database

**Test**: Verify columns exist in database with `\d publish_jobs` in psql

---

#### Iteration 3: Redis Infrastructure Setup
**Goal**: Set up Redis client and helper functions

**Tasks:**
1. Create `src/utils/redis_utils.py`:
   - Redis client initialization
   - `acquire_dedupe_lock()` function
   - Helper for Redis operations
2. Update `src/database.py` to include Redis client
3. Add Redis connection testing

**Deliverables:**
- New file `src/utils/redis_utils.py`
- Updated `src/database.py`

**Test**: Simple script to test Redis connection and lock acquisition

---

### Phase 2: Core Task Implementation (Iterations 4-7)

#### Iteration 4: X API Client
**Goal**: Build a reusable client for X/Twitter API

**Tasks:**
1. Create `src/services/x_api_client.py`:
   - Class `XAPIClient` with methods for posting and fetching metrics
   - Support dry-run mode
   - Environment-driven configuration
   - Error handling for rate limits
2. Add environment variables for X API config
3. Create unit tests with mocked API calls

**Deliverables:**
- New file `src/services/x_api_client.py`
- Updated `.env.example` files
- Basic unit tests

**Test**: Test with dry-run mode against mock API

---

#### Iteration 5: Publish Post Task (Basic)
**Goal**: Implement the core publishing task

**Tasks:**
1. Create `src/tasks/publish.py`:
   - Task `publish_post(job_id)` with basic structure
   - Early-exit idempotency check
   - Basic error handling
   - Status updates (planned -> running -> succeeded/failed)
2. Configure task in `celery_app.py` with proper routing
3. Add to worker in docker-compose

**Deliverables:**
- New file `src/tasks/__init__.py`
- New file `src/tasks/publish.py`
- Updated `src/celery_app.py` with task routing

**Test**: Create a manual publish job and verify task execution

---

#### Iteration 6: State Machine & Atomic Updates
**Goal**: Implement robust state transitions

**Tasks:**
1. Create `src/utils/state_machine.py`:
   - Class `PublishJobStateMachine` with valid transitions
   - Validation logic
2. Update `publish_post` task to use state machine
3. Implement atomic status updates with `SELECT FOR UPDATE`
4. Add retry logic with exponential backoff

**Deliverables:**
- New file `src/utils/state_machine.py`
- Updated `src/tasks/publish.py`

**Test**: Verify transitions work and invalid transitions are rejected

---

#### Iteration 7: Schedule Resolution Service
**Goal**: Build scheduler logic to compute next run times

**Tasks:**
1. Create `src/services/scheduler_service.py`:
   - Class `ScheduleResolver` with methods for each schedule kind
   - `resolve_one_shot()`, `resolve_cron()`, `resolve_rrule()`
2. Install `rrule` package if needed
3. Add timezone handling

**Deliverables:**
- New file `src/services/scheduler_service.py`
- Updated `requirements.txt` if needed

**Test**: Unit tests for each schedule type

---

### Phase 3: Scheduler & Automation (Iterations 8-10)

#### Iteration 8: Scheduler Task (Beat)
**Goal**: Implement the periodic scheduler tick

**Tasks:**
1. Create `src/tasks/scheduler.py`:
   - Task `scheduler_tick()` that runs every minute
   - Query due schedules with `SELECT FOR UPDATE SKIP LOCKED`
   - Create publish_jobs with proper dedupe locks
   - Update schedule `next_run_at`
2. Configure Celery Beat schedule in `celery_app.py`
3. Add beat service to docker-compose

**Deliverables:**
- New file `src/tasks/scheduler.py`
- Updated `src/celery_app.py` with beat schedule
- Updated `docker-compose.yml` with beat service

**Test**: Watch scheduler create jobs for active schedules

---

#### Iteration 9: Rate Limiting
**Goal**: Implement API rate limiting

**Tasks:**
1. Add rate limit configuration to `celery_app.py`:
   - Configure `task_annotations` based on API tier
   - Set rate limits in task decorators
2. Update publish task with rate limit
3. Add environment variable `X_API_TIER` (free/basic/pro/enterprise)
4. Monitor rate limit headers from X API

**Deliverables:**
- Updated `src/celery_app.py`
- Updated environment files

**Test**: Verify task execution respects rate limits

---

#### Iteration 10: Error Handling & Retry Logic
**Goal**: Robust error handling with intelligent retries

**Tasks:**
1. Create `src/utils/retry_strategy.py`:
   - Class `RetryStrategy` with transient/permanent error classification
   - Exponential backoff calculator
2. Update `publish_post` task:
   - Add retry decorator config
   - Handle specific error types
   - Update job status on failure
3. Implement dead letter queue handler stub

**Deliverables:**
- New file `src/utils/retry_strategy.py`
- Updated `src/tasks/publish.py`

**Test**: Simulate various errors and verify retry behavior

---

### Phase 4: Advanced Features (Iterations 11-13)

#### Iteration 11: Metrics Collection
**Goal**: Automate metrics capture for published posts

**Tasks:**
1. Create `src/tasks/metrics.py`:
   - Task `capture_metrics(x_post_id, stage)`
   - Fetch metrics from X API
   - Store in `metrics_snapshots` table
2. Create `src/utils/metrics_polling.py`:
   - Class `MetricsPollingStrategy` with polling schedule
   - Schedule next capture based on stage
3. Integrate metrics capture into publish flow

**Deliverables:**
- New file `src/tasks/metrics.py`
- New file `src/utils/metrics_polling.py`
- Updated `src/tasks/publish.py`

**Test**: Verify metrics are collected and snapshots stored

---

#### Iteration 12: Media Preparation (Stub)
**Goal**: Prepare framework for media handling

**Tasks:**
1. Create `src/tasks/media.py`:
   - Task `prepare_media(media_refs)` (stub for now)
   - Basic structure for future implementation
2. Add media queue to celery routing
3. Update Post model if needed for media

**Deliverables:**
- New file `src/tasks/media.py`
- Updated routing

**Test**: Task can be called (returns success without doing work)

---

#### Iteration 13: Observability & Monitoring
**Goal**: Add logging and monitoring

**Tasks:**
1. Set up structured logging with structlog in `src/utils/logging_config.py`
2. Create `src/utils/observability.py`:
   - Custom Celery Task class with correlation IDs
   - Bind context vars for logging
3. Add Prometheus metrics export (optional):
   - Counters for job attempts
   - Histograms for job duration
4. Create health check task
5. Add Flower for Celery monitoring

**Deliverables:**
- New file `src/utils/observability.py`
- New file `src/utils/logging_config.py`
- Updated tasks to use structured logging
- Optional Prometheus integration

**Test**: Verify logs include correlation IDs and metrics

---

### Phase 5: Production Readiness (Iterations 14-16)

#### Iteration 14: API Integration & Endpoints
**Goal**: Connect API to new worker system

**Tasks:**
1. Update `src/api/posts.py`:
   - Modify schedule creation to use new system
   - Update instant publish to use Celery task
   - Add endpoint to cancel jobs
2. Add new API endpoints:
   - `POST /api/schedules/{id}/enable`
   - `POST /api/schedules/{id}/disable`
   - `GET /api/jobs/{id}/status`

**Deliverables:**
- Updated `src/api/posts.py`
- Updated `src/main.py` with new routes

**Test**: API can create schedules and trigger jobs

---

#### Iteration 15: Docker & Deployment
**Goal**: Production-ready container setup

**Tasks:**
1. Update `docker-compose.yml`:
   - Add dedicated worker services (publish, metrics, scheduler queues)
   - Add beat service
   - Add flower service for monitoring
   - Configure resource limits
2. Update environment variables documentation
3. Add production docker-compose file
4. Add health checks

**Deliverables:**
- Updated `docker-compose.yml`
- New `docker-compose.prod.yml`
- Updated environment examples

**Test**: Full stack runs and workers process jobs correctly

---

#### Iteration 16: Testing & Validation
**Goal**: Comprehensive testing and documentation

**Tasks:**
1. Write unit tests for:
   - All task functions
   - State machine
   - Scheduler resolution
   - Retry strategy
2. Write integration tests:
   - End-to-end publish flow
   - Schedule resolution
   - Error recovery
3. Load testing:
   - Concurrent jobs
   - Rate limit handling
   - Queue performance
4. Update documentation:
   - README with worker setup
   - Deployment guide
   - Architecture diagram

**Deliverables:**
- Test files in `tests/`
- Updated documentation
- Performance benchmarks

**Test**: All tests pass, system handles production load

---

## Success Criteria

After completing all iterations:

✅ Jobs are created automatically from schedules
✅ Jobs execute reliably with proper retry logic
✅ State transitions are atomic and validated
✅ Rate limiting is enforced
✅ Metrics are collected automatically
✅ System is observable with structured logs
✅ All tests pass
✅ Documentation is complete
✅ System runs stably in production-like environment

---

## Quick Start Checklist

Use this checklist when implementing each iteration:

- [ ] Update code changes
- [ ] Run tests (unit/integration)
- [ ] Update migrations if needed
- [ ] Update docker-compose if needed
- [ ] Update environment variables if needed
- [ ] Test manually (start services, create job, verify execution)
- [ ] Update documentation
- [ ] Commit with descriptive message

---

## Iteration Sizes

Each iteration should be:
- **Small**: Completable in 2-4 hours
- **Testable**: Can be verified independently
- **Incremental**: Builds on previous iterations
- **Reversible**: Can be easily rolled back if needed

---

## Notes

- Start with dry-run mode for all API calls during development
- Use feature flags to control rollout of new system
- Keep existing API working while building new system
- Test each iteration thoroughly before moving to next
- Monitor Redis and database performance as system grows

