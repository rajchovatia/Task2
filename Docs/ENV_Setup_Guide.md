# ENV Setup Guide — Real-Time Notification System

> **Config File**: `config/settings/base.py` reads all environment variables

---

## 1. Quick Start

```bash
# Step 1: Copy example file
cp .env.example .env

# Step 2: Generate SECRET_KEY (REQUIRED)
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# Copy output and paste after SECRET_KEY= in .env

# Step 3: Start everything
docker compose up -d --build
```

### Minimum Required Variables

| Variable | Why Required |
|----------|-------------|
| `SECRET_KEY` | Django won't start without it — no fallback |
| `POSTGRES_PASSWORD` | Database won't connect |

Everything else is optional — defaults are set in `base.py` and Docker Compose.

---

## 2. Django Settings

| Variable | What it does | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Cryptographic signing — CSRF tokens, sessions, password hashing | None (must set) |
| `DEBUG` | Debug mode — detailed error pages, SQL logging | `False` |
| `ALLOWED_HOSTS` | Allowed domains/IPs for HTTP Host header validation | `localhost,127.0.0.1` |

**Generate SECRET_KEY:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> **Production**: `DEBUG=False` is mandatory. Set `ALLOWED_HOSTS` to your specific domains only.

---

## 3. PostgreSQL Settings

```
Django → PgBouncer (6432) → PostgreSQL Primary (5432) / Replica (5433)
```

### Primary Database

| Variable | What it does | Default |
|----------|-------------|---------|
| `POSTGRES_DB` | Database name | `RNS` |
| `POSTGRES_USER` | Login username | `notif_user` |
| `POSTGRES_PASSWORD` | Login password | `notif_pass_123` |
| `POSTGRES_HOST` | Database hostname | `pgbouncer` |
| `POSTGRES_PORT` | PgBouncer port (not PostgreSQL directly) | `6432` |

### Replica Database

| Variable | What it does | Default |
|----------|-------------|---------|
| `POSTGRES_REPLICA_DB` | Read-only replica database name | `RNS_replica` |
| `POSTGRES_REPLICA_HOST` | Replica hostname | `pgbouncer` |
| `POSTGRES_REPLICA_PORT` | Replica port via PgBouncer | `6432` |
| `REPLICATION_PASSWORD` | PostgreSQL streaming replication password (internal, not used by Django) | `repl_pass_123` |

---

## 4. Redis Settings

3 separate Redis instances with different purposes:

| Instance | Service | Purpose | Default URL |
|----------|---------|---------|-------------|
| Channels | `redis-channels:6379` | WebSocket real-time messaging | `redis://redis-channels:6379/0` |
| Celery | `redis-celery:6379` | Task results storage | `redis://redis-celery:6379/0` |
| Cache | `redis-cache:6379` | App cache (unread counts, rate limits, idempotency) | `redis://redis-cache:6379/0` |

| Variable | What it does |
|----------|-------------|
| `REDIS_CHANNELS_URL` | Redis for Django Channels (WebSocket) |
| `REDIS_CELERY_URL` | Redis for Celery result backend |
| `REDIS_CACHE_URL` | Redis for Django cache framework |

---

## 5. RabbitMQ Settings

3-node cluster for high availability. If one node goes down, the other two keep working.

| Variable | What it does | Default |
|----------|-------------|---------|
| `RABBITMQ_URL` | RabbitMQ connection string | `amqp://guest:guest@rabbitmq-1:5672/` |
| `CELERY_BROKER_URL` | Celery broker (must match `RABBITMQ_URL`) | `amqp://guest:guest@rabbitmq-1:5672/` |
| `RABBITMQ_ERLANG_COOKIE` | Shared secret for cluster node authentication (must be SAME on all 3 nodes) | `rns_cluster_cookie_secret` |
| `RABBITMQ_MANAGEMENT_PORT` | Management UI port (`http://localhost:15672`) | `15672` |

---

## 6. SendGrid (Email) Settings

| Variable | What it does | Default |
|----------|-------------|---------|
| `SENDGRID_API_KEY` | SendGrid API authentication | `SG.xxxxxxxxxxxxxxxxxxxx` (placeholder) |
| `DEFAULT_FROM_EMAIL` | "From" address in emails (must be verified in SendGrid) | `notifications@example.com` |

### Get SendGrid API Key

1. Sign up at **https://signup.sendgrid.com/**
2. Go to **Settings → API Keys → Create API Key**
3. Set permissions to **Full Access** (or enable "Mail Send" under Restricted)
4. Copy the key immediately (shown only once)
5. Paste in `.env`: `SENDGRID_API_KEY=SG.your-key-here`

**Without key**: System still runs — email tasks go to queue but delivery fails. In-app and Push notifications work normally.

**Free Alternative**: [Brevo](https://www.brevo.com/) — 300 emails/day free, supported by Django Anymail.

---

## 7. Firebase (Push) Settings

| Variable | What it does | Default |
|----------|-------------|---------|
| `FCM_SERVER_KEY` | FCM API authentication for push notifications | `your-fcm-server-key-here` (placeholder) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to Firebase service account JSON file | `/app/firebase-credentials.json` |

### Get Firebase Credentials

1. Go to **https://console.firebase.google.com/** → Create/select project
2. **Server Key**: Project Settings → Cloud Messaging tab → copy Legacy Server Key
3. **Service Account JSON**: Project Settings → Service Accounts → Generate New Private Key
4. Copy JSON file to project root: `cp ~/Downloads/your-file.json ./firebase-credentials.json`

**Without key**: Push tasks go to queue but delivery fails. Email and In-app notifications work normally.

---

## 8. Celery Settings

| Variable | What it does | Default |
|----------|-------------|---------|
| `CELERY_BROKER_URL` | Where Celery picks up tasks (RabbitMQ) | `amqp://guest:guest@rabbitmq-1:5672/` |
| `CELERY_RESULT_BACKEND` | Where Celery stores task results (Redis) | `redis://redis-celery:6379/0` |

```
API creates task → RabbitMQ (broker) → Worker processes → Redis (result backend)
```

---

## 9. OpenTelemetry / Jaeger Settings

| Variable | What it does | Default |
|----------|-------------|---------|
| `OTEL_ENABLED` | Enable/disable tracing | `True` |
| `OTEL_JAEGER_HOST` | Jaeger collector hostname | `jaeger` |
| `OTEL_JAEGER_PORT` | Jaeger collector UDP port | `6831` |
| `OTEL_SERVICE_NAME` | Service name shown in Jaeger UI | `rns-notification-system` |

Jaeger UI: `http://localhost:16686`

---

## 10. Notification System Tuning

All optional — defaults are production-ready.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `CIRCUIT_BREAKER_FAIL_MAX` | `5` | Failures before circuit opens (blocks requests) |
| `CIRCUIT_BREAKER_RESET_TIMEOUT` | `60` sec | Wait time before retrying after circuit opens |
| `IDEMPOTENCY_TTL` | `86400` (24h) | How long idempotency keys stay valid |
| `DLQ_MAX_ATTEMPTS` | `10` | Max retries for dead letter queue messages |
| `DLQ_BATCH_SIZE` | `100` | Messages processed per DLQ batch |
| `DIGEST_MAX_NOTIFICATIONS` | `50` | Max notifications per digest email |
| `CLEANUP_READ_AFTER_DAYS` | `90` | Days before read notifications are deleted |
| `CLEANUP_FCM_AFTER_DAYS` | `30` | Days before inactive FCM tokens are cleaned |
| `BULK_BATCH_SIZE` | `1000` | Users processed per bulk notification batch |
| `DEFAULT_NOTIFICATION_PRIORITY` | `5` | Default priority (1=highest, 10=lowest) |

---

## 11. Container × Variable Matrix

| Variable | api | ws | email-worker | push-worker | inapp-worker | fanout-worker | celery-beat | postgres | pgbouncer | redis | rabbitmq |
|----------|:---:|:--:|:------------:|:-----------:|:------------:|:-------------:|:-----------:|:--------:|:---------:|:-----:|:--------:|
| `SECRET_KEY` | Y | Y | Y | Y | Y | Y | Y | - | - | - | - |
| `DEBUG` | Y | Y | Y | Y | Y | Y | Y | - | - | - | - |
| `ALLOWED_HOSTS` | Y | Y | - | - | - | - | - | - | - | - | - |
| `POSTGRES_*` | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | - |
| `REDIS_CHANNELS_URL` | - | Y | - | - | Y | - | - | - | - | Y | - |
| `REDIS_CELERY_URL` | Y | - | Y | Y | Y | Y | Y | - | - | Y | - |
| `REDIS_CACHE_URL` | Y | Y | Y | Y | Y | Y | Y | - | - | Y | - |
| `RABBITMQ_URL` | Y | - | Y | Y | Y | Y | Y | - | - | - | Y |
| `SENDGRID_API_KEY` | - | - | Y | - | - | - | - | - | - | - | - |
| `FCM_SERVER_KEY` | - | - | - | Y | - | - | - | - | - | - | - |
| `OTEL_*` | Y | Y | Y | Y | Y | Y | Y | - | - | - | - |

`Y` = used, `-` = not used

---

## 12. Security Checklist (Production)

### Must Change

| # | Action | Risk if not changed |
|---|--------|-------------------|
| 1 | Generate new `SECRET_KEY` | Session hijack, CSRF bypass |
| 2 | Set `DEBUG=False` | Sensitive info leak (stack traces, SQL, settings) |
| 3 | Set specific `ALLOWED_HOSTS` | HTTP Host header attacks |
| 4 | Strong `POSTGRES_PASSWORD` (16+ chars) | Data breach |
| 5 | Change RabbitMQ credentials (remove `guest/guest`) | Unauthorized queue access |
| 6 | Change `RABBITMQ_ERLANG_COOKIE` | Unauthorized cluster access |
| 7 | Strong `REPLICATION_PASSWORD` | Unauthorized DB replication |

### Recommended

| # | Action | Risk |
|---|--------|------|
| 8 | Change Grafana password (default: admin/admin) | Monitoring data leak |
| 9 | Use production SendGrid key | Email limits on test key |
| 10 | Restrict Firebase JSON file permissions (`chmod 600`) | Push notification abuse |
| 11 | Set Redis passwords | Data theft |
| 12 | Confirm `.env` is in `.gitignore` | All secrets leaked to git |

> **Never** commit `.env` to git. For real production, use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.).
