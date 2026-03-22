# Deployment Notes — Real-Time Notification System (RNS)

> **Version**: 1.0
> **Last Updated**: March 22, 2026
> **Stack**: Django 5.x | Python 3.11 | PostgreSQL 16 | RabbitMQ 3.13 | Redis 7 | Docker Compose

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration](#2-environment-configuration)
3. [First-Time Deployment](#3-first-time-deployment)
4. [Container Architecture](#4-container-architecture)
5. [Port Mapping Reference](#5-port-mapping-reference)
6. [Post-Deployment Verification](#6-post-deployment-verification)
7. [Scaling Workers](#7-scaling-workers)
8. [Updating & Redeployment](#8-updating--redeployment)
9. [Backup & Restore](#9-backup--restore)
10. [Troubleshooting](#10-troubleshooting)
11. [Production Hardening Checklist](#11-production-hardening-checklist)
12. [Dashboard Access & Guide](#12-dashboard-access--guide)

---

## 1. Prerequisites

| Software | Minimum Version | Purpose |
|----------|----------------|---------|
| Docker Desktop | 24.x+ | Container runtime |
| Docker Compose | v2.x (included in Desktop) | Multi-container orchestration |
| Git | 2.x+ | Source control |
| 8 GB RAM | Minimum | 26 containers need ~6-8 GB |
| 10 GB Disk | Minimum | Docker images + volumes |

No need to install Python, PostgreSQL, Redis, or RabbitMQ locally — everything runs inside Docker.

---

## 2. Environment Configuration

Copy the example environment file and customize:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `django-insecure-change-me-in-prod` | Django secret key (MUST change in production) |
| `DEBUG` | `True` | Set `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `POSTGRES_DB` | `RNS` | Database name |
| `POSTGRES_USER` | `notif_user` | Database user |
| `POSTGRES_PASSWORD` | `notif_pass_123` | Database password |
| `REPLICATION_PASSWORD` | `repl_pass_123` | PostgreSQL replication password |

### Optional — External Providers

| Variable | Description | Default Behavior Without It |
|----------|-------------|----------------------------|
| `SENDGRID_API_KEY` | SendGrid email API key | Email tasks queue but don't deliver |
| `DEFAULT_FROM_EMAIL` | Sender email address | Uses `notifications@example.com` |
| `FCM_SERVER_KEY` | Firebase push notification key | Push tasks queue but don't deliver |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to Firebase JSON credentials | Push delivery skipped |

### Optional — Tuning Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `CIRCUIT_BREAKER_FAIL_MAX` | `5` | Failures before circuit breaker opens |
| `CIRCUIT_BREAKER_RESET_TIMEOUT` | `60` | Seconds before circuit breaker retries |
| `IDEMPOTENCY_TTL` | `86400` | Idempotency key TTL in seconds (24h) |
| `DLQ_MAX_ATTEMPTS` | `10` | Max retry attempts for dead-letter messages |
| `DLQ_BATCH_SIZE` | `100` | Messages processed per DLQ cycle |
| `BULK_BATCH_SIZE` | `1000` | Recipients per bulk notification batch |
| `CLEANUP_READ_AFTER_DAYS` | `90` | Days before read notifications are deleted |
| `CLEANUP_FCM_AFTER_DAYS` | `30` | Days before inactive FCM tokens are removed |

---

## 3. First-Time Deployment

```bash
# Step 1: Clone and navigate to project
cd Task2

# Step 2: Create .env from example
cp .env.example .env
# Edit .env with your values (especially SECRET_KEY for production)

# Step 3: Build and start all 26 containers
docker compose up -d --build

# Step 4: Wait 60 seconds for all services to initialize
# PostgreSQL, RabbitMQ cluster, and Elasticsearch need time to start

# Step 5: Verify all containers are running
docker compose ps
# Expected: 26 containers, all showing "Up"

# Step 6: Create admin superuser
docker compose exec api python manage.py createsuperuser
# Recommended: Username: admin, Email: admin@test.com, Password: admin123

# Step 7: Generate API token for testing
docker compose exec api python manage.py shell -c "
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
user = User.objects.get(username='admin')
token, _ = Token.objects.get_or_create(user=user)
print(f'Your API Token: {token.key}')
"

# Step 8: Create notification types
docker compose exec api python manage.py shell -c "
from apps.notifications.models import NotificationType
NotificationType.objects.get_or_create(name='order_update', defaults={'template':'Order {order_id} updated','channels':['email','push','inapp'],'priority':1})
NotificationType.objects.get_or_create(name='promotion', defaults={'template':'Special offer: {title}','channels':['email','inapp'],'priority':5})
NotificationType.objects.get_or_create(name='system_alert', defaults={'template':'System: {message}','channels':['inapp'],'priority':1})
print('Notification types created!')
"

# Step 9: Verify health
curl http://localhost:8000/api/v1/health/
# Expected: {"status": "ok"}
```

### What Happens During Startup

1. **PostgreSQL Primary** starts → creates database, replicator role, extensions
2. **PostgreSQL Replica** connects to primary → begins streaming replication
3. **PgBouncer** starts → pools connections to both databases
4. **RabbitMQ Cluster** forms → 3 nodes join, quorum queues created
5. **Redis instances** (3) start → channels, celery, cache
6. **Django API** runs migrations automatically via `docker-entrypoint.sh`
7. **Daphne WebSocket** server starts on port 8001
8. **Celery Workers** (4) connect to RabbitMQ and start consuming queues
9. **Celery Beat** starts scheduled task scheduler
10. **Monitoring stack** (Prometheus, Grafana, ELK, Jaeger) initializes

---

## 4. Container Architecture

```
26 Containers — 7 Layers

LAYER 1: LOAD BALANCER (1)
  └── nginx              → Routes HTTP to API, WebSocket to Daphne

LAYER 2: APPLICATION (2)
  ├── api                → Django REST API (WSGI)
  └── ws                 → Daphne WebSocket Server (ASGI)

LAYER 3: WORKERS (6)
  ├── email-worker       → Sends emails via SendGrid/SES (4 threads)
  ├── push-worker        → Sends push via Firebase FCM (4 threads)
  ├── inapp-worker       → Delivers via WebSocket/Redis Channels (2 threads)
  ├── fanout-worker      → Splits bulk notifications into batches (2 threads)
  └── celery-beat        → Runs scheduled tasks (DLQ retry, cleanup, digests)

LAYER 4: MESSAGE BROKER (3)
  ├── rabbitmq-1         → Seed node (Management UI on port 15672)
  ├── rabbitmq-2         → Cluster member
  └── rabbitmq-3         → Cluster member

LAYER 5: DATA (6)
  ├── postgres-primary   → Write database
  ├── postgres-replica   → Read-only replica (streaming replication)
  ├── pgbouncer          → Connection pooler (transaction mode)
  ├── redis-channels     → WebSocket pub/sub
  ├── redis-celery       → Task results + idempotency keys
  └── redis-cache        → App cache (preferences, unread counts)

LAYER 6: MONITORING (8)
  ├── prometheus              → Metrics collection (scrapes every 15s)
  ├── grafana                 → Dashboards and alerting
  ├── elasticsearch           → Log storage and indexing
  ├── logstash                → Log pipeline (JSON → Elasticsearch)
  ├── kibana                  → Log search UI
  ├── jaeger                  → Distributed tracing
  ├── redis-exporter-cache    → Redis metrics for Prometheus
  ├── redis-exporter-celery   → Redis metrics for Prometheus
  └── redis-exporter-channels → Redis metrics for Prometheus
```

---

## 5. Port Mapping Reference

| Port | Service | Protocol | Access |
|------|---------|----------|--------|
| **80** | Nginx | HTTP | Main entry point (routes to API + WebSocket) |
| **8000** | Django API | HTTP | REST API (direct access, bypasses Nginx) |
| **8001** | Daphne | WebSocket | WebSocket server (direct access) |
| **5432** | PostgreSQL Primary | TCP | Database writes |
| **5433** | PostgreSQL Replica | TCP | Database reads |
| **6432** | PgBouncer | TCP | Connection pooler |
| **5672** | RabbitMQ | AMQP | Message broker |
| **15672** | RabbitMQ Management | HTTP | Queue management UI |
| **6379-6382** | Redis (3 instances) | TCP | Cache/Channels/Celery |
| **9090** | Prometheus | HTTP | Metrics explorer |
| **3000** | Grafana | HTTP | Dashboards |
| **9200** | Elasticsearch | HTTP | Log storage API |
| **5044** | Logstash | TCP | Log ingestion |
| **5601** | Kibana | HTTP | Log search UI |
| **16686** | Jaeger | HTTP | Tracing UI |

---

## 6. Post-Deployment Verification

Run these checks after deployment to confirm everything works:

```bash
# 1. Check all containers are UP
docker compose ps

# 2. Health check
curl http://localhost:8000/api/v1/health/

# 3. Create a test notification (replace TOKEN with your token)
TOKEN=your_token_here
curl -X POST http://localhost:8000/api/v1/notifications/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type":1,"title":"Deployment Test","body":"System is working"}'

# 4. Check RabbitMQ queues exist
curl -s -u guest:guest http://localhost:15672/api/queues | python -m json.tool | grep name

# 5. Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | python -m json.tool | grep health

# 6. Check Elasticsearch cluster
curl http://localhost:9200/_cluster/health

# 7. Verify worker logs (no errors)
docker compose logs --tail=20 email-worker
docker compose logs --tail=20 push-worker
docker compose logs --tail=20 inapp-worker
```

---

## 7. Scaling Workers

Scale individual workers based on load:

```bash
# Scale email workers to 5 instances
docker compose up --scale email-worker=5 -d

# Scale push workers to 3 instances
docker compose up --scale push-worker=3 -d

# Scale multiple workers at once
docker compose up --scale email-worker=5 --scale push-worker=3 --scale fanout-worker=4 -d
```

### Scaling Guidelines

| Queue Depth | Action |
|------------|--------|
| email_queue > 10,000 | Scale email-worker to 5-10 |
| push_queue > 10,000 | Scale push-worker to 5-10 |
| bulk_queue > 50,000 | Scale fanout-worker to 4-8 |
| API response time > 500ms | Scale api to 2-3 instances |

---

## 8. Updating & Redeployment

```bash
# Pull latest code changes
git pull origin main

# Rebuild and restart (zero-downtime for workers)
docker compose up -d --build

# If database schema changed
docker compose exec api python manage.py migrate

# Full restart (if needed)
docker compose down
docker compose up -d --build

# Nuclear option — clean rebuild (destroys all data)
docker compose down --rmi all --volumes --remove-orphans
docker system prune -af --volumes
docker compose up -d --build
```

---

## 9. Backup & Restore

### Database Backup

```bash
# Backup PostgreSQL
docker compose exec postgres-primary pg_dump -U notif_user RNS > backup_$(date +%Y%m%d).sql

# Restore from backup
docker compose exec -T postgres-primary psql -U notif_user RNS < backup_20260322.sql
```

### Volume Backup

```bash
# List all volumes
docker volume ls | grep task2

# Backup a volume
docker run --rm -v task2_postgres_primary_data:/data -v $(pwd):/backup alpine tar czf /backup/pg_data.tar.gz /data
```

---

## 10. Troubleshooting

| Problem | Diagnosis | Fix |
|---------|-----------|-----|
| Container keeps restarting | `docker compose logs <service>` | Check logs for errors |
| API returns 502 | `docker compose ps api` | Restart: `docker compose restart api` |
| Notifications not delivering | `docker compose logs email-worker` | Check worker logs + RabbitMQ queues |
| Database connection error | `docker compose logs pgbouncer` | Check PgBouncer config + PostgreSQL status |
| RabbitMQ cluster split | `http://localhost:15672` → Cluster tab | Restart RabbitMQ nodes: `docker compose restart rabbitmq-1 rabbitmq-2 rabbitmq-3` |
| Elasticsearch out of memory | `docker stats elasticsearch` | Increase `ES_JAVA_OPTS` in docker-compose.yml |
| Redis out of memory | `docker compose exec redis-cache redis-cli info memory` | Increase `maxmemory` or scale |
| Migrations failed | `docker compose logs api` | Run manually: `docker compose exec api python manage.py migrate` |
| WebSocket not connecting | `docker compose logs ws` | Check Daphne logs and Redis Channels connectivity |
| High CPU on workers | `docker stats` | Scale workers or reduce concurrency |

### Useful Debug Commands

```bash
# View real-time logs for any service
docker compose logs -f api
docker compose logs -f email-worker

# Enter a container shell
docker compose exec api bash

# Django shell (for data inspection)
docker compose exec api python manage.py shell

# Check resource usage
docker stats --no-stream

# Check RabbitMQ queue depths
docker compose exec rabbitmq-1 rabbitmqctl list_queues name messages consumers
```

---

## 11. Production Hardening Checklist

| # | Item | Status | Action |
|---|------|--------|--------|
| 1 | Change `SECRET_KEY` | Required | Generate a strong random key |
| 2 | Set `DEBUG=False` | Required | In `.env` |
| 3 | Set `ALLOWED_HOSTS` | Required | Your domain(s) only |
| 4 | Set `CORS_ALLOWED_ORIGINS` | Required | Replace `*` with specific frontend URLs |
| 5 | Add rate limiting | Recommended | Add DRF throttling classes |
| 6 | Enable HTTPS | Required | Configure SSL in Nginx |
| 7 | Add `Strict-Transport-Security` | Recommended | In Nginx config |
| 8 | Add `Content-Security-Policy` | Recommended | In Nginx config |
| 9 | Change RabbitMQ credentials | Required | Set `RABBITMQ_USER` and `RABBITMQ_PASS` in `.env` |
| 10 | Change Grafana password | Required | Set `GRAFANA_ADMIN_PASSWORD` in `.env` |
| 11 | Change database passwords | Required | Update `POSTGRES_PASSWORD` and `REPLICATION_PASSWORD` |
| 12 | Configure SendGrid API key | For email delivery | Set `SENDGRID_API_KEY` in `.env` |
| 13 | Configure Firebase credentials | For push notifications | Set `FCM_SERVER_KEY` and credentials file |
| 14 | Use Gunicorn instead of runserver | ✅ Done | Configured in docker-compose.yml: `gunicorn config.wsgi:application --workers 4 --threads 2 --worker-class gthread` |
| 15 | Enable PostgreSQL SSL | Recommended | Configure SSL certificates for DB connections |
| 16 | Set up log rotation | Recommended | Configure logrotate for container logs |
| 17 | Set up automated backups | Required | Schedule `pg_dump` via cron or Celery Beat |

---

## 12. Dashboard Access & Guide

All dashboards are accessible when containers are running. No additional setup needed.

### Dashboard 1: Django Admin Panel

| | |
|---|---|
| **URL** | http://localhost:8000/admin/ |
| **Login** | Username: `admin` / Password: `admin123` |
| **Purpose** | Manage data — users, notifications, types, delivery records |

**What you'll see:**
- **Users** — All registered users and their tokens
- **Notification Types** — Types like `order_update`, `promotion` with channel configuration
- **Notifications** — Browse all notifications with status (read/unread), filter by recipient/type
- **Notification Deliveries** — Per-channel delivery tracking (pending → sent → failed) with attempt count and error messages
- **Notification Preferences** — User settings: email on/off, push on/off, quiet hours, digest mode
- **Notification Analytics** — Events: delivered, opened, clicked (for tracking engagement)
- **Auth Tokens** — API tokens assigned to each user

---

### Dashboard 2: Grafana — System Metrics Dashboard

| | |
|---|---|
| **URL** | http://localhost:3000 |
| **Login** | Username: `admin` / Password: `admin` |
| **Purpose** | Visual dashboards showing system performance in real-time |

**What you'll see:**
- **Notification Delivery Rate** — How many notifications are being sent per minute (line graph)
- **HTTP Response Codes** — Breakdown of 2xx (success), 4xx (client error), 5xx (server error) responses
- **RabbitMQ Queue Depth** — How many messages are waiting in email_queue, push_queue, inapp_queue, bulk_queue
- **Dead Letter Queue Count** — Failed messages that need attention
- **API Latency** — Response time percentiles (p50, p95, p99)
- **Celery Task Rate** — Tasks succeeded, failed, and retried per minute
- **Redis Memory Usage** — Memory consumption per Redis instance
- **WebSocket Active Connections** — How many users are connected in real-time

**How to use:**
1. Login → Click "Dashboards" in left sidebar
2. Select "RNS Notification Dashboard" (pre-configured)
3. Set time range (top-right): Last 15 minutes, 1 hour, etc.
4. Panels auto-refresh every 10 seconds

---

### Dashboard 3: RabbitMQ Management — Queue Monitor

| | |
|---|---|
| **URL** | http://localhost:15672 |
| **Login** | Username: `guest` / Password: `guest` |
| **Purpose** | Monitor message queues, see what's pending/processing |

**What you'll see:**
- **Overview tab** — Total messages, message rates, connections count
- **Queues tab** — The most important view:
  | Queue | Purpose |
  |-------|---------|
  | `email_queue` | Email delivery tasks waiting to be processed |
  | `push_queue` | Push notification tasks |
  | `inapp_queue` | In-app (WebSocket) notification tasks |
  | `bulk_queue` | Bulk fan-out tasks |
  | `dead_email` | Failed email deliveries (Dead Letter Queue) |
  | `dead_push` | Failed push deliveries |
  | `dead_inapp` | Failed in-app deliveries |
  | `dead_bulk` | Failed bulk tasks |
- **Connections tab** — Shows all connected workers (email@host, push@host, etc.)
- **Cluster tab** — 3-node cluster health (rabbitmq-1, rabbitmq-2, rabbitmq-3)

**How to read queue status:**
- **Ready** = Messages waiting to be picked up by a worker
- **Unacked** = Messages being processed right now
- **Total** = Ready + Unacked
- If "Ready" keeps growing → workers are too slow → scale them up

---

### Dashboard 4: Prometheus — Raw Metrics Explorer

| | |
|---|---|
| **URL** | http://localhost:9090 |
| **Login** | No login required |
| **Purpose** | Query raw metrics, check scrape targets health |

**What you'll see:**
- **Graph tab** — Enter PromQL queries to visualize any metric
- **Status → Targets** — Shows all 9 scrape targets and their health status:
  | Target | What It Monitors |
  |--------|-----------------|
  | django | API request metrics |
  | postgres | Database metrics |
  | redis-cache | Cache Redis metrics |
  | redis-celery | Celery Redis metrics |
  | redis-channels | Channels Redis metrics |
  | rabbitmq-1/2/3 | Queue metrics per node |

**Useful queries:**
```promql
# Total HTTP requests
django_http_requests_total_by_method_total

# API response time (95th percentile)
histogram_quantile(0.95, django_http_requests_latency_seconds_by_view_method_bucket)

# Redis memory usage
redis_memory_used_bytes

# RabbitMQ queue depth
rabbitmq_queue_messages
```

---

### Dashboard 5: Kibana — Log Search

| | |
|---|---|
| **URL** | http://localhost:5601 |
| **Login** | No login required |
| **Purpose** | Search and filter logs from all 26 containers in one place |

**First-time setup:**
1. Go to http://localhost:5601
2. Click "Discover" in left sidebar
3. Create index pattern: `logstash-*`
4. Select `@timestamp` as time field
5. Click "Create index pattern"

**What you can search:**
- All application logs in structured JSON format
- Filter by: `level` (INFO, ERROR, WARNING), `service`, `correlation_id`
- Search for specific notification IDs or error messages

**Example searches:**
```
level: "ERROR"                          → All errors
message: "delivery failed"             → Failed deliveries
correlation_id: "abc-123"              → Trace a single request
service: "email-worker" AND level: "ERROR"  → Email worker errors only
```

---

### Dashboard 6: Jaeger — Distributed Tracing

| | |
|---|---|
| **URL** | http://localhost:16686 |
| **Login** | No login required |
| **Purpose** | Trace a single request as it flows through the entire system |

**What you'll see:**
- **Search page** — Select service `rns-notification-system`, set time range, click "Find Traces"
- **Trace list** — Each trace shows one complete operation
- **Trace detail** — A timeline (waterfall) showing:
  ```
  API receives request         [2ms]
    → Saves to PostgreSQL      [5ms]
    → Publishes to RabbitMQ    [1ms]
    → Worker picks up task     [50ms]
      → Calls SendGrid API    [200ms]
      → Updates delivery       [3ms]
  Total: 261ms
  ```

**How to use:**
1. Select Service: `rns-notification-system`
2. Set time range (Last Hour)
3. Click "Find Traces"
4. Click any trace to see the full waterfall breakdown
5. Look for long spans (slow operations) or error spans (red)

---

### Dashboard Summary — Quick Reference

| Dashboard | URL | Login | What To Check |
|-----------|-----|-------|---------------|
| Django Admin | http://localhost:8000/admin/ | admin / admin123 | Data: users, notifications, deliveries |
| Grafana | http://localhost:3000 | admin / admin | Graphs: rates, latency, queue depth |
| RabbitMQ | http://localhost:15672 | guest / guest | Queues: pending messages, DLQ count |
| Prometheus | http://localhost:9090 | — | Targets: all 9 should be UP |
| Kibana | http://localhost:5601 | — | Logs: errors, failed deliveries |
| Jaeger | http://localhost:16686 | — | Traces: request flow, bottlenecks |
