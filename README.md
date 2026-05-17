# Feature Flags API

[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Tests](https://img.shields.io/badge/tests-67%20passed-brightgreen?logo=pytest&logoColor=white)](./tests)
[![Coverage](https://img.shields.io/badge/coverage-85%25%2B-brightgreen)](./coverage.xml)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](./Dockerfile)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

Production-grade feature flag platform built in Python. Sub-millisecond flag evaluation via in-process cache, zero I/O on the hot path.

```
p50 < 0.1ms  ·  p95 < 0.5ms  ·  p99 < 1ms  ·  100k evaluations/s on a single core
```

---

## Table of Contents

- [Architecture](#architecture)
- [Evaluation Logic](#evaluation-logic)
- [API Reference](#api-reference)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Observability](#observability)
- [Security](#security)
- [Tests](#tests)
- [Crash Recovery](#crash-recovery)
- [Limitations](#limitations)
- [What I'd Do Differently](#what-id-do-differently)

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                            CLIENT                                     │
│               REST / SDK / curl / any HTTP client                     │
└───────────────────────────┬───────────────────────────────────────────┘
                            │ HTTPS
┌───────────────────────────▼───────────────────────────────────────────┐
│                        FASTAPI APP                                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Middleware stack (outermost → innermost)                       │  │
│  │  SlowAPI (rate limit) → CORS → TrustedHost → Prometheus        │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────┐  ┌─────────────────┐  ┌───────────────────────┐   │
│  │  /flags      │  │  /evaluate      │  │  /webhooks            │   │
│  │  CRUD + rules│  │  hot path ──────┼──▶  dispatch w/ retry    │   │
│  │  + audit log │  │  100 req/min    │  │  HMAC-SHA256 signing  │   │
│  └──────┬───────┘  └────────┬────────┘  └───────────────────────┘   │
│         │                   │                                         │
│  ┌──────▼───────────────────▼──────────────────────────────────────┐  │
│  │                      deps.py                                    │  │
│  │          JWT Bearer (HS256)  ·  RBAC: admin/editor/viewer       │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────────────────────────────┘
                   │ reads (zero DB I/O on hot path)
┌──────────────────▼───────────────────────────────────────────────────┐
│                      IN-PROCESS CACHE                                 │
│                                                                       │
│   FlagCache { dict[flag_key → FlagData] }                            │
│   ├── warm_up() → bulk load from PostgreSQL on startup               │
│   ├── asyncio.Lock on all writes (safe for async tasks)              │
│   └── CacheNotReadyError if read before warm-up completes            │
│                                                                       │
│   EvaluationEngine (stateless, pure function)                        │
│   └── evaluate(flag_key, user_id, attrs, environment)                │
│       → EvaluationResult(value, reason, flag_version)                │
└──────────────────┬──────────────────────────────────────────────────-┘
         write     │           invalidate
┌────────▼─────────┴──────────────────────────────────────────────────┐
│                         POSTGRESQL 16                                 │
│                                                                       │
│  flags              (JSONB environments column)                       │
│  audit_logs         (immutable by design — no UPDATE endpoint)       │
│  webhooks                                                            │
│  webhook_deliveries                                                  │
│                                                                       │
│  asyncpg · SQLAlchemy 2.0 async · pool_size=20 · pool_pre_ping=True  │
└──────────────────────────────────────────────────────────────────────┘
         │                            ▲
         │ PUBLISH invalidation       │ SUBSCRIBE
         ▼                            │
┌─────────────────────────────────────┴────────────────────────────────┐
│                            REDIS 7                                    │
│                                                                       │
│  Channel: feature_flags:invalidate                                   │
│  Message: {"flag_key": "...", "version": N, "action": "update"}      │
│                                                                       │
│  Pub/Sub listener: asyncio.Task with automatic reconnect             │
│  Backoff: 1s → 2s → 5s → 10s → 30s                                  │
└──────────────────────────────────────────────────────────────────────┘
```

### Request lifecycle (evaluation endpoint)

```
POST /api/v1/evaluate
       │
       ├─ 1. SlowAPI: check rate limit bucket (in-memory)
       ├─ 2. JWT: decode + verify exp + verify role
       ├─ 3. EvaluationEngine.evaluate()   ← zero I/O, ~50µs
       │       ├─ FlagCache.get(flag_key)  ← dict lookup
       │       ├─ check override
       │       ├─ check enabled
       │       ├─ match targeting rules (priority order)
       │       ├─ rollout: mmh3(flag_key:user_id, seed=42) % 10_000
       │       └─ fallback to default_value
       ├─ 4. Record metrics (Counter + Histogram, non-blocking)
       └─ 5. Return EvaluationResult (JSON)
```

---

## Evaluation Logic

Five-level precedence chain. **First match wins.**

```
┌─────────────────────────────────────────────────────────────┐
│  Priority 1  │  OVERRIDE      │  env_config.override != null │
├─────────────────────────────────────────────────────────────┤
│  Priority 2  │  FLAG_DISABLED │  env_config.enabled == false │
├─────────────────────────────────────────────────────────────┤
│  Priority 3  │  TARGETING     │  first rule where ALL/ANY    │
│              │                │  conditions match user attrs  │
├─────────────────────────────────────────────────────────────┤
│  Priority 4  │  ROLLOUT       │  mmh3(key:user, seed=42)     │
│              │                │  % 10_000 < pct * 100        │
├─────────────────────────────────────────────────────────────┤
│  Priority 5  │  DEFAULT       │  flag.default_value          │
└─────────────────────────────────────────────────────────────┘
```

**Targeting operators:** `eq` · `neq` · `in` · `not_in` · `contains` · `starts_with` · `gt` · `gte` · `lt` · `lte`

**Condition combinator:** `AND` (all must pass) · `OR` (any passes)

**Rollout stability:** MurmurHash3 with `seed=42`. Same user always gets the same bucket across restarts, replicas, and language SDKs — as long as they use the same seed.

**Flag types:** `boolean` · `string` · `number` · `json`

---

## API Reference

### Authentication

All endpoints require `Authorization: Bearer <JWT>`. Tokens must contain `sub`, `exp`, and `role` claims. Algorithm `none` is explicitly rejected.

```
Roles hierarchy:
  admin  ──▶ full access (CRUD + deletes)
  editor ──▶ CRUD flags, rules, environments, webhooks (no deletes)
  viewer ──▶ GET only
```

### Endpoints

```
Flags
  POST   /api/v1/flags                                  admin, editor
  GET    /api/v1/flags                                  any
  GET    /api/v1/flags/{flag_key}                       any
  PATCH  /api/v1/flags/{flag_key}                       admin, editor
  DELETE /api/v1/flags/{flag_key}                       admin

Rules (scoped per environment)
  POST   /api/v1/flags/{flag_key}/rules?env=production  admin, editor
  PUT    /api/v1/flags/{flag_key}/rules/{rule_id}       admin, editor
  DELETE /api/v1/flags/{flag_key}/rules/{rule_id}       admin, editor

Environments
  POST   /api/v1/flags/{flag_key}/environments/{env}/enable   admin, editor
  POST   /api/v1/flags/{flag_key}/environments/{env}/disable  admin, editor

Audit
  GET    /api/v1/flags/{flag_key}/audit                 any

Evaluation  (hot path — no DB I/O)
  POST   /api/v1/evaluate           100 req/min per IP
  POST   /api/v1/evaluate/batch     200 req/min per IP

Webhooks
  POST   /api/v1/webhooks           admin, editor
  GET    /api/v1/webhooks           admin, editor
  DELETE /api/v1/webhooks/{id}      admin

Observability
  GET    /health     public
  GET    /metrics    Prometheus scrape (public — firewall in production)
  GET    /docs       only when DEBUG=true
```

### Example: evaluate a flag

```bash
curl -X POST https://api.example.com/api/v1/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "flag_key": "checkout-v2",
    "user_id": "usr_abc123",
    "environment": "production",
    "attributes": {
      "plan": "enterprise",
      "country": "BR"
    }
  }'
```

```json
{
  "flag_key": "checkout-v2",
  "value": true,
  "reason": "TARGETING_MATCH",
  "environment": "production",
  "flag_version": 7
}
```

### Flag payload

```json
{
  "key": "checkout-v2",
  "name": "Checkout V2",
  "flag_type": "boolean",
  "default_value": false,
  "environments": {
    "production": {
      "enabled": true,
      "override": null,
      "rollout_percentage": 20,
      "rules": [
        {
          "name": "Enterprise bypass",
          "priority": 1,
          "condition_combinator": "AND",
          "conditions": [
            { "attribute": "plan", "operator": "eq", "value": "enterprise" }
          ],
          "serve": true
        }
      ]
    }
  }
}
```

---

## Getting Started

### Prerequisites

- Docker + Docker Compose v2
- `openssl` (for generating a secure secret key)

### Run locally

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd feature-flags

# 2. Generate a secure secret key
echo "SECRET_KEY=$(openssl rand -hex 32)" > .env

# 3. Start all services
docker compose up -d

# 4. Apply migrations
docker compose exec api alembic upgrade head

# 5. (Optional) seed demo data
docker compose exec api python -m src.scripts.seed

# 6. Test the health endpoint
curl http://localhost:8000/health
# {"status": "ok", "version": "1.0.0"}
```

### Run without Docker

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e ".[test,dev]"

# Start PostgreSQL and Redis (however you prefer), then:
cp .env.example .env
# Edit .env with your DATABASE_URL, REDIS_URL, SECRET_KEY

alembic upgrade head
uvicorn src.main:app --reload
```

---

## Configuration

All configuration is read from environment variables (or a `.env` file). Copy `.env.example` to `.env` and fill in the values.

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `SECRET_KEY` | insecure placeholder | **yes** | JWT signing key. Generate: `openssl rand -hex 32` |
| `ENVIRONMENT` | `development` | **yes** | `production` rejects the insecure placeholder at startup |
| `DATABASE_URL` | `postgresql+asyncpg://...` | **yes** | Async PostgreSQL URL |
| `REDIS_URL` | `redis://localhost:6379/0` | **yes** | Redis connection URL |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | **yes** | Comma-separated list for TrustedHostMiddleware |
| `CORS_ORIGINS` | *(empty)* | if web frontend | Comma-separated allowed CORS origins |
| `DEBUG` | `false` | — | Enables Swagger UI, colorized logs, CORS `*` |
| `SENTRY_DSN` | *(empty)* | recommended | Sentry DSN. Empty = Sentry disabled |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | — | Fraction of transactions sampled (0.0–1.0) |
| `RATE_LIMIT_EVALUATION` | `1000/minute` | — | SlowAPI limit for the evaluate endpoint |
| `DB_POOL_SIZE` | `20` | — | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `10` | — | SQLAlchemy pool max overflow |

**Hard fail at startup:** if `ENVIRONMENT=production` and `SECRET_KEY` still holds the placeholder value, the process raises `ValueError` and refuses to start. There is no silent fallback.

---

## Observability

### Prometheus metrics

| Metric | Type | Labels | What it measures |
|---|---|---|---|
| `flag_evaluation_total` | Counter | `flag_key`, `result`, `reason` | Total evaluations by outcome |
| `flag_evaluation_duration_seconds` | Histogram | `flag_key`, `environment` | Evaluation latency distribution |
| `cache_hit_total` | Counter | — | In-process cache hits |
| `cache_miss_total` | Counter | — | Cache misses (flag not found) |
| `cache_size_flags` | Gauge | — | Number of flags loaded in cache |
| `cache_refresh_duration_seconds` | Histogram | — | Time to warm up cache |
| `pubsub_invalidations_total` | Counter | `action` | Cache invalidations received |
| `pubsub_lag_seconds` | Histogram | — | Latency between publish and receive |
| `webhook_dispatch_total` | Counter | `result` | Webhook delivery outcomes |
| `webhook_dispatch_duration_seconds` | Histogram | — | Webhook HTTP call latency |
| `db_pool_size` | Gauge | — | Configured pool size |
| `db_pool_checked_out` | Gauge | — | Connections currently in use |

Prometheus scrapes `/metrics`. A working `prometheus.yml` is included. Grafana can connect directly to the Prometheus container.

### Logging

**Development** (`DEBUG=true`): colorized, human-readable output via structlog ConsoleRenderer.

**Production** (`DEBUG=false`): newline-delimited JSON via structlog JSONRenderer. Every log line is a valid JSON object — ready for Datadog, CloudWatch, or ELK.

```json
{"event": "Sentry inicializado", "environment": "production", "level": "info", "timestamp": "2026-04-01T15:30:00Z"}
```

### Sentry

Set `SENTRY_DSN` to enable automatic error tracking and distributed tracing. The integration captures FastAPI exceptions and SQLAlchemy query spans. `send_default_pii=False` ensures tokens and personal data are never sent.

---

## Security

| Control | Implementation |
|---|---|
| Authentication | JWT Bearer HS256; `alg=none` explicitly rejected |
| Authorization | RBAC via `role` claim: `admin / editor / viewer` |
| Input validation | Pydantic v2 strict schemas on every request |
| SQL injection | SQLAlchemy ORM only — zero raw string interpolation |
| XSS | API returns JSON only — no HTML rendering |
| Rate limiting | SlowAPI per-IP on evaluation endpoints |
| Webhook authenticity | HMAC-SHA256 signature in `X-Hub-Signature-256` header |
| Host header injection | TrustedHostMiddleware with explicit allowlist |
| Secrets at startup | `ValueError` if placeholder `SECRET_KEY` in production |
| Container privilege | Non-root user `appuser` (uid/gid 1001) in Dockerfile |
| Audit trail | Immutable `audit_logs` table — no UPDATE or DELETE endpoint |
| Docs exposure | `/docs` and `/redoc` disabled in production |
| Sensitive data in logs | Only exception type is logged, never the token value |

---

## Tests

```
67 tests · 0 failures · SQLite in-memory (no external services required)
```

```bash
# Run all tests
pytest tests/unit tests/consistency tests/security

# With coverage report (requires 85% minimum)
pytest tests/unit tests/consistency tests/security --cov=src

# Security suite only
pytest tests/security -v

# Performance benchmarks (requires running services)
pytest tests/performance -v
```

### Test matrix

| Suite | Count | What it covers |
|---|---|---|
| `unit/core` | 17 | Evaluation precedence (5 levels), hashing distribution |
| `consistency` | 2 | Concurrent evaluation, cache invalidation under load |
| `security/authn_authz` | 12 | JWT expired, tampered, `alg=none`, RBAC enforcement |
| `security/injection` | 14 | SQL injection, XSS, command injection via all inputs |
| `security/input_validation` | 10 | Oversized payloads, deeply nested JSON, boundary values |
| `security/rate_limiting` | 4 | 429 after threshold, reset after window |
| `security/sensitive_data` | 8 | No tokens in responses, no stack traces in prod |

**Infrastructure:** Tests use SQLite in-memory with monkey-patched `JSONB→JSON` and `UUID` type handlers. The lifespan is replaced with a no-op. No Docker, no network, no flakiness.

---

## Crash Recovery

This section documents what actually happens when the system fails mid-flight.

### Scenario A: Redis dies while the API is running

```
t=0    API is serving normally. Cache warm. Pub/sub listener active.
       redis ping: OK

t=10s  Redis container killed: docker stop redis

t=11s  Pub/sub listener: asyncio exception caught
       LOG: "[pub/sub] conexão perdida: Connection refused"
       LOG: "[pub/sub] reconectando em 1s (tentativa 1)..."

t=12s  Reconnect attempt 1 → failed (Redis still down)
       Backoff: 2s

t=14s  Reconnect attempt 2 → failed
       Backoff: 5s

t=19s  Redis container restarted: docker start redis

t=19s  Reconnect attempt 3 → SUCCESS
       LOG: "[pub/sub] subscrito ao canal: feature_flags:invalidate"
       attempt counter reset to 0

During downtime (t=10s..t=19s):
  - ALL evaluation requests continue to succeed (cache is still warm)
  - Flag updates written to PostgreSQL are accepted
  - Cache becomes stale only for flags changed during the window
  - On reconnect, next flag update triggers normal invalidation again
  - Stale window: bounded by the Redis downtime duration
```

**Key property:** Redis failure degrades gracefully. The evaluation hot path has zero Redis dependency at read time.

### Scenario B: API process killed mid-request

```
t=0    POST /api/v1/flags  (admin creates a new flag)
       → flag written to PostgreSQL  ✓
       → audit_log written (same transaction)  ✓
       → SIGKILL received

t=0    Process dies. In-flight HTTP response never delivered.

t=1    Client receives connection reset / 502 from load balancer.
       Client retries. POST /api/v1/flags is idempotent on key uniqueness:
       → 409 Conflict (flag_key already exists)
       → Client uses GET /api/v1/flags/{key} to confirm the flag exists

t=2    New API process starts (restart: unless-stopped in compose).
       Lifespan runs:
         1. database.connect()  ✓
         2. redis.connect()     ✓
         3. cache.warm_up()     ← loads ALL flags from DB, including the new one
         4. redis.start_listener()
       API ready. Cache includes the flag created before the crash.
```

**Key property:** No in-flight state is lost. PostgreSQL is the source of truth. The cache is always rebuilt from scratch on startup — no cache corruption across restarts.

### Scenario C: PostgreSQL connection pool exhausted

```
Symptom: db_pool_checked_out gauge hits pool_size (20) + max_overflow (10) = 30

What happens:
  - New requests that require DB access (writes, audit logs) queue up
  - Evaluation requests continue unaffected (zero DB I/O)
  - After pool_timeout, queued requests get "QueuePool limit overflow" error → 500

Recovery:
  - Long-running queries identified via db_pool_checked_out Prometheus alert
  - Adjust DB_POOL_SIZE / DB_MAX_OVERFLOW via env var + rolling restart
  - No data loss
```

---

## Limitations

These are **known, deliberate trade-offs** — not bugs. Knowing what a system doesn't do is as important as knowing what it does.

### 1. Single-process cache — not suitable for fan-out at scale

The in-process `FlagCache` lives in each API replica's memory. Redis pub/sub propagates invalidations to all replicas within ~1–5ms under normal conditions. However:

- There is **no guarantee of exactly-once delivery** via Redis pub/sub. A message can be lost if a replica restarts between publish and receive.
- The **stale window on Redis failure** is unbounded (until reconnect).
- At extreme fan-out (10k+ replicas), the Redis pub/sub channel becomes a bottleneck.

For that scale, a distributed cache (Redis directly as read-through) or a gossip protocol would be more appropriate. This design is optimal for clusters of 2–50 replicas.

### 2. No SDK server-side targeting for anonymous users

The evaluation engine requires a `user_id` to compute rollout buckets. Anonymous users must be assigned a stable client-generated ID (e.g., stored in a cookie). There is no built-in anonymous ID management or cookie-setting logic — that responsibility belongs to the client.

### 3. Migrations are manual

This project uses Alembic, but there is no CI step that automatically runs `alembic upgrade head` on deploy. Blue/green deployments with schema changes require careful sequencing: deploy migration → deploy code. There is no zero-downtime migration framework (e.g., expand-contract) built in.

### 4. Webhook delivery has no dead-letter queue

After 3 failed attempts with exponential backoff, webhook deliveries are marked `failed` in `webhook_deliveries` and abandoned. There is no re-queue mechanism, no admin UI to retry, and no alerting when a webhook consistently fails. Consumers must poll the delivery log manually.

### 5. No multi-tenancy

All flags, users, and webhooks share a single namespace. There is no concept of organizations, projects, or workspaces. Adding multi-tenancy would require a `tenant_id` foreign key on every table and row-level security in PostgreSQL.

### 6. JWT is issued externally

This service validates JWTs but does not issue them. There is no `/auth/token` endpoint, no user registration, and no password management. You need an external identity provider (Auth0, Keycloak, your own auth service) to generate tokens with the correct `sub`, `exp`, and `role` claims.

---

## What I'd Do Differently

Honest retrospective. These are architectural decisions I made under time constraints that I'd revisit in a production system with a team.

### 1. Environments as a JSONB column was a mistake at this scale

I stored per-environment configuration (rules, rollout, enabled state) as a JSONB blob inside the `flags` table. It was fast to build and works fine for small flag sets. But it has a hard scaling ceiling:

- You cannot query `WHERE environments->>'production'->>'enabled' = 'true'` efficiently without a generated index.
- Partial updates to a single environment require reading the entire JSONB, merging in Python, and writing back — defeating optimistic locking.
- Adding a new field to the environment schema requires either a migration or a code-level default, with no schema enforcement at the DB level.

The right model is a separate `flag_environments` table with one row per `(flag_id, environment_name)`. It enables indexed queries, atomic per-environment updates, and proper foreign key constraints. I'd do this from day one if I were building this for a team.

### 2. I should have used OpenTelemetry instead of Prometheus + Sentry separately

The current stack has two separate observability pipelines: Prometheus (metrics) and Sentry (traces + errors). They don't share context — a Prometheus alert can't link directly to the Sentry trace that caused it.

OpenTelemetry would unify metrics, traces, and logs under a single instrumentation layer with W3C Trace Context propagation. The `trace_id` would appear in every log line, every metric exemplar, and every Sentry transaction — giving a single "click to trace" from anywhere in the stack. The migration cost is low (`opentelemetry-instrumentation-fastapi` exists), and I'd make this the default for any greenfield service today.

### 3. Evaluation audit was an afterthought

Right now, writes (flag CRUD) produce audit logs. But **evaluation events are not logged** — there is no record of which user got which value at what time. This is a significant operational gap:

- You cannot answer "why did user X see feature Y disabled last Tuesday?"
- You cannot do post-hoc analysis of rollout cohorts.
- Debugging production incidents requires correlating server logs with Prometheus metrics manually.

The right approach is an evaluation event stream: publish each evaluation result to a Kafka topic or a time-series table (with aggressive TTL), queryable by `flag_key + user_id + time range`. I skipped this because it adds write amplification on the hot path — but the operational value easily outweighs the cost with async publishing to a separate writer.

---

## Project Structure

```
feature-flags/
├── src/
│   ├── api/
│   │   ├── deps.py              # JWT auth, RBAC, session injection
│   │   └── v1/
│   │       ├── evaluation.py    # Hot path: evaluate + batch
│   │       ├── flags.py         # Flag CRUD + rules + audit
│   │       ├── environments.py  # Enable/disable per environment
│   │       └── webhooks.py      # Webhook CRUD + HMAC dispatch
│   ├── core/
│   │   ├── cache.py             # In-process FlagCache with asyncio.Lock
│   │   ├── evaluation.py        # 5-level precedence engine (pure, no I/O)
│   │   ├── hashing.py           # MurmurHash3 rollout (seed=42)
│   │   └── targeting.py         # 10-operator rule evaluator
│   ├── infra/
│   │   ├── database.py          # SQLAlchemy async engine + session factory
│   │   ├── metrics.py           # All Prometheus counters/histograms/gauges
│   │   └── redis.py             # Connection pool + pub/sub with auto-reconnect
│   ├── models/
│   │   ├── flag.py              # Flag + AuditLog ORM models
│   │   ├── webhook.py           # Webhook + WebhookDelivery ORM models
│   │   └── environment.py       # EnvironmentConfig + TargetingRule dataclasses
│   ├── schemas/
│   │   ├── flag.py              # Pydantic request/response schemas
│   │   └── evaluation.py        # EvaluationRequest + EvaluationResult schemas
│   ├── config.py                # Pydantic Settings — all env vars in one place
│   └── main.py                  # App factory, lifespan, middleware stack
├── sdk/
│   └── feature_flags_sdk/       # Python SDK (EvaluationResult, FlagValue models)
├── tests/
│   ├── conftest.py              # SQLite fixtures, JWT factories, no-op lifespan
│   ├── unit/core/               # Evaluation precedence + hashing distribution
│   ├── security/                # Authn/authz, injection, input validation, rate limiting
│   ├── consistency/             # Concurrency, cache invalidation under load
│   └── performance/             # Latency benchmarks + Locust load test
├── migrations/                  # Alembic migration scripts
├── Dockerfile                   # python:3.12-slim, non-root user (uid 1001)
├── docker-compose.yml           # postgres:16 + redis:7 + api + prometheus
├── prometheus.yml               # Prometheus scrape config
├── pyproject.toml               # Dependencies, ruff, mypy, bandit, pytest config
└── .env.example                 # All required env vars with documentation
```

---

## License

MIT