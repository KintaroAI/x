Awesome project. Here’s a lean, future-proof setup that keeps your Python backend in charge, isolates dev/prod, and makes scheduling + metrics on X straightforward.

# Frontend choice

**FastAPI + HTMX + Tailwind** — “Python-first” dashboard: server-rendered templates with sprinkles of interactivity (no heavy SPA build).
   Pros: one repo, simple mental model, great for private internal tools.
   Cons: fewer prebuilt components than React.

**Recommendation:** Start with **FastAPI + HTMX** for speed. If you outgrow it, you can slip in a Next.js frontend later without changing your backend contracts.

---

# Backend (Python)

* **Web framework:** **FastAPI** (typed endpoints, great docs, async, easy OpenAPI).
* **HTTP client:** **httpx** (async + timeouts + retries).
* **ORM:** **SQLAlchemy 2.0** (or **SQLModel** if you prefer Pydantic-style models).
* **Migrations:** **Alembic** (first-class with SQLAlchemy).
* **Scheduling:**

  * Start simple with **APScheduler** (CronTrigger + DateTrigger) running inside a dedicated worker process.
  * If you later need distributed reliability, move to **Celery**/**Dramatiq** + **Redis/RabbitMQ**, but APScheduler is perfect for one-user scheduling.
* **Auth with X:** OAuth 2.0 (PKCE) and the **Create Post** endpoint (formerly “POST /2/tweets”). Public & private metrics are available via the metrics fields on tweet lookups (impressions, likes, replies, etc.), with private metrics for owned/authorized accounts. ([X Developer Platform][1])

> Note on X access tiers: pricing and limits change. As of late 2025, X offers Free/Basic/Pro/Enterprise, with Basic/Pro being the common paid tiers; pay-per-use is being tested. Plan your polling cadence and volume with your tier’s caps in mind. ([X Developer][2])

> Policy sanity check: you’re managing a **single** account, scheduling its own posts (not cross-posting many accounts or blasting replies). That aligns with X’s automation rules; avoid spammy/duplicative behavior. ([Help Center][3])

---

# Database

* **PostgreSQL** (battle-tested, great JSON support, window functions, indexes).
* **Migrations:** **Alembic**. You’ll love its autogenerate and revision history.
* **Why not SQLite?** Fine for local prototyping, but you’ll want Postgres to run APScheduler with a DB job store and to avoid locking quirks.

**Core tables (minimum viable):**

* `accounts` — your single X account (id, handle, access_token, refresh_token, scopes, rotated_at).
* `posts` — drafts + scheduled posts (id, text, media_refs, created_at, updated_at).
* `schedules` — one-off or recurring (post_id, kind: one_shot|cron|rrule, schedule_spec, timezone, next_run_at, enabled).
* `publish_jobs` — each attempt to publish (id, schedule_id, planned_at, started_at, finished_at, status, error).
* `published_posts` — mapping to X post id (post_id, x_post_id, published_at, url).
* `metrics_snapshots` — time series (x_post_id, captured_at, impressions, likes, replies, reposts, bookmarks, profile_clicks, link_clicks, video_views, …).
* `audit_log` — who/what/when (optional but handy).

---

# Scheduling design

* **One-shot posts:** store `planned_at`; APScheduler runs **DateTrigger** jobs that call your “publish” service.
* **Recurring posts:** store a cron string or an iCal RRULE; use **CronTrigger** or parse RRULE → next run.
* **Idempotency:** before publishing, check if this schedule already produced a post within a small window; keep a `dedupe_key` (schedule_id + planned_at).
* **Metrics refresh:** enqueue a periodic job (e.g., hourly) that fetches metrics for *recently published* posts and appends to `metrics_snapshots`. Use the metrics fields returned by X’s tweet lookup endpoints (public vs private/organic where permitted by your access level). ([X Developer][4])

---

# Dev vs personal isolation

**Use Docker Compose with profiles + separate env files + separate Postgres DBs:**

```
repo/
  backend/
  frontend/              # optional if using Next.js
  deploy/
    docker-compose.yml
    docker-compose.dev.yml
    docker-compose.prod.yml
  .env.dev
  .env.prod
  alembic/
  Makefile
```

* **Profiles:** `docker compose --profile dev up` vs `--profile prod up`.
* **Env files:** keep `X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REDIRECT_URI`, DB URLs, Redis URL, etc. Use **Docker secrets** or an external vault for prod.
* **Two X apps:** Ideally create **separate X API apps** for dev and prod (distinct keys/redirect URIs), so dev experiments never touch your live account. ([X Developer][5])
* **Network:** give backend, worker, db, and redis their own compose services; bind backend to `localhost` in dev; put a reverse proxy (Caddy or Nginx) in prod.
* **Migrations:** `alembic upgrade head` runs automatically on container start (optional), or via `make migrate`.
* **“Dry run” mode:** a flag that logs the payload instead of posting to X (useful in dev even with live keys).

---

# Minimal service breakdown

* `api` (FastAPI): auth, CRUD posts/schedules, publish endpoint (internal), metrics endpoint, web UI pages (if HTMX).
* `worker` (APScheduler): pulls due schedules → calls api service or directly executes publish function; periodic metrics refresh; retry with exponential backoff.
* `db` (Postgres).
* `redis` (optional): if you adopt Celery/Dramatiq later.

---

# Posting & metrics on X (nuts & bolts)

* **Publish:** call **Create Post** (`POST /2/tweets`), optionally handle media via v1.1 media endpoints (upload/init/append/finalize) if you add images/video. ([X Developer Platform][1])
* **Read performance:** use lookup endpoints with `tweet.fields=public_metrics` (likes, replies, reposts, quote_count, etc.). For impressions and deeper organic metrics on your own posts, use private/organic metrics where your plan and auth scope allow. ([X Developer][4])
* **Resilience:** wrap calls with timeouts & retries; handle occasional 503s or platform incidents gracefully (queue and retry). There have been API outages that affected create/fetch endpoints; bake in exponential backoff. ([Android Central][6])

---

# UX you can ship in week 1

* **Drafts**: textarea, character counter, media attachments pipeline (optional).
* **Scheduling**: one-shot time picker and a simple cron builder (daily/weekly presets).
* **Outbox**: upcoming posts with pause/skip.
* **Published**: table with post text, link, published_at, last metrics snapshot.
* **Analytics**: sparkline per post (impressions/likes over time), totals for last 7/30 days.

---

# Testing & quality

* **Contract tests:** define OpenAPI for your endpoints; generate a simple client for the frontend.
* **HTTP mocks:** `respx` for `httpx` to simulate X without hitting the network.
* **Data migrations:** write Alembic revisions early; add `seed` scripts for dev data.
* **Config:** Pydantic Settings class loading from env; assert required secrets at startup.

---

# Security & keys

* Store tokens encrypted at rest (e.g., Fernet with a KMS-backed key or at least a Docker secret in prod).
* Limit scopes to what you need (post/manage tweets, read metrics). Rotate secrets regularly. ([X Developer][5])

---

## Quick starter template (what I’d scaffold)

* **FastAPI + HTMX** for the MVP dashboard.
* **Postgres + Alembic** for state + migrations.
* **APScheduler** worker for publish & metrics polling.
* **Docker Compose** with `dev` and `prod` profiles and separate X apps.
* **httpx** with retry/backoff for X API calls.

If you want, I can draft:

* a minimal **docker-compose** (api, worker, db)
* the **SQLAlchemy models + Alembic revision 0001**
* the **APScheduler wiring** for one-shot & cron
* and **two FastAPI endpoints**: `POST /posts` (draft) and `POST /schedules` (create schedule)

—all wired to a stubbed X client (real call behind a `--dry-run` flag).

[1]: https://docs.x.com/x-api/posts/create-post?utm_source=chatgpt.com "Create or Edit Post"
[2]: https://developer.x.com/en/products/x-api/enterprise/enterprise-api-interest-form?utm_source=chatgpt.com "Apply for enterprise API access | Twitter Developer Platform - X"
[3]: https://help.x.com/en/rules-and-policies/x-automation?utm_source=chatgpt.com "X's automation development rules - Help Center"
[4]: https://developer.x.com/en/docs/x-api/metrics?utm_source=chatgpt.com "Metrics"
[5]: https://developer.x.com/en/docs/x-api?utm_source=chatgpt.com "Twitter API Documentation | Docs | Twitter Developer Platform"
[6]: https://www.androidcentral.com/apps-software/twitter/x-appears-to-be-suffering-an-outage-heres-what-we-know?utm_source=chatgpt.com "It wasn't just you - X (Twitter) resolved a major outage today"
