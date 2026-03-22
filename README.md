# Real-Time Notification System (RNS)

A production-grade, multi-channel notification system built with Django — supports **Email**, **Push**, and **In-App (WebSocket)** delivery for 100K+ users with async processing, failure handling, and full observability.

**26 Docker containers | 7 architectural layers | 100% requirement coverage**

---

## Architecture

```
Client → Nginx → Django API / Daphne WS
                      ↓              ↓
                 RabbitMQ        Redis Channels
                 (3-node)         (pub/sub)
                      ↓              ↓
               Celery Workers    WebSocket → User
               ├── email-worker  → SendGrid/SES
               ├── push-worker   → Firebase FCM
               ├── inapp-worker  → Redis Channels
               ├── fanout-worker → Batch splitting
               └── celery-beat   → Scheduled tasks
                      ↓
               PgBouncer → PostgreSQL (Primary + Replica)
               Redis Cache + Redis Celery
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x + DRF + Django Channels + Daphne |
| Task Queue | Celery + RabbitMQ (3-node quorum cluster) |
| Database | PostgreSQL 16 (primary + read replica) + PgBouncer |
| Cache | Redis (3 isolated instances: channels, celery, cache) |
| Email | SendGrid (primary) + Amazon SES (failover) |
| Push | Firebase Cloud Messaging (FCM) |
| Proxy | Nginx (rate limiting + routing) |
| Monitoring | Prometheus + Grafana + ELK Stack + Jaeger |
| Security | bleach (XSS) + pybreaker (circuit breaker) |

---

## Quick Start

**Prerequisites**: Docker Desktop (4GB+ RAM, 5GB disk)

```bash
# Clone and setup
git clone https://github.com/rajchovatia/Task2.git
cd Task2

# Start all 26 containers
docker compose up -d --build

# Wait ~60s, then verify
docker compose ps

# Create admin user
docker compose exec api python manage.py createsuperuser

# Generate API token
docker compose exec api python manage.py shell -c "
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
user = User.objects.get(username='admin')
token, _ = Token.objects.get_or_create(user=user)
print(f'Token: {token.key}')
"

# Test
curl http://localhost:8000/api/v1/health/
# {"status": "ok"}
```

---

## API Endpoints

All endpoints require `Authorization: Token <your-token>` header (except health check).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health/` | Health check |
| `POST` | `/api/v1/notifications/` | Create notification |
| `GET` | `/api/v1/notifications/` | List notifications (paginated) |
| `GET` | `/api/v1/notifications/{id}/` | Get notification detail |
| `PATCH` | `/api/v1/notifications/{id}/read/` | Mark as read |
| `PATCH` | `/api/v1/notifications/mark-all-read/` | Mark all as read |
| `GET` | `/api/v1/notifications/unread-count/` | Unread count |
| `POST` | `/api/v1/notifications/bulk/` | Bulk notification (async) |
| `GET/PUT` | `/api/v1/preferences/` | Get/Update preferences |
| `WS` | `ws://localhost/ws/notifications/` | Real-time WebSocket |

### Example: Create Notification

```bash
curl -X POST http://localhost:8000/api/v1/notifications/ \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: unique-key-001" \
  -d '{
    "type": 1,
    "title": "Your order has shipped",
    "body": "Order #12345 is on its way",
    "recipient": 1,
    "metadata": {"order_id": "12345"}
  }'
```

---

## Key Features

| Feature | Implementation |
|---------|---------------|
| **3-Layer Idempotency** | API header → Redis SET NX → DB UNIQUE constraint |
| **Retry + Backoff** | Celery autoretry (5 attempts, exponential backoff) |
| **Circuit Breaker** | pybreaker: opens after 5 failures, resets after 60s |
| **Dead Letter Queue** | Failed tasks → DLQ → retried every 5 min by Celery Beat |
| **Provider Failover** | SendGrid down → auto-switch to Amazon SES |
| **User Preferences** | Per-user channel on/off, quiet hours, digest mode |
| **Bulk Fan-Out** | 100K+ users batched (1000/batch, 2s stagger) |
| **XSS Prevention** | bleach strips HTML from title/body |
| **User Isolation** | Users can only access their own notifications |

---

## Monitoring

| Service | URL | Login |
|---------|-----|-------|
| Django Admin | http://localhost:8000/admin/ | admin / (your password) |
| Grafana | http://localhost:3000 | admin / admin |
| RabbitMQ | http://localhost:15672 | guest / guest |
| Prometheus | http://localhost:9090 | — |
| Kibana | http://localhost:5601 | — |
| Jaeger | http://localhost:16686 | — |

---

## Database Schema

6 core tables with UUID primary keys:

| Table | Purpose |
|-------|---------|
| `notifications` | All notifications (title, body, recipient, read status) |
| `notification_types` | Channel config per type (channels[], priority) |
| `notification_deliveries` | Per-channel delivery tracking (status, attempts) |
| `notification_preferences` | User settings (channel toggles, quiet hours, digest) |
| `notification_analytics` | Engagement events (delivered, opened, clicked) |
| `fcm_django_fcmdevice` | Mobile device tokens for push notifications |

---

## Project Structure

```
├── config/              # Django settings, celery, ASGI/WSGI, tracing
├── apps/
│   ├── notifications/   # Core: models, views, tasks, consumers, providers
│   ├── analytics/       # Engagement tracking
│   └── devices/         # FCM device management
├── docker/              # Nginx, PostgreSQL, PgBouncer, RabbitMQ, Prometheus, Grafana, ELK
├── requirements/        # Python dependencies
├── Docs/                # Architecture, container docs, ENV guide, test results
├── docker-compose.yml   # All 26 containers
├── Dockerfile           # Python 3.11 image
└── Deployment-notes.md  # Deployment guide
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Deployment-notes.md](Deployment-notes.md) | Deployment guide + dashboard access |
| [Architecture Blueprint](Docs/Task2_Architecture_Blueprint.md) | Full system architecture |
| [Container Explanation](Docs/Container_Explanation.md) | All 26 containers + DB schema |
| [ENV Setup Guide](Docs/ENV_Setup_Guide.md) | Environment variables reference |
| [System Flow & Testing](Docs/System_Flow_and_Testing.md) | System flows + test results |

---

## Test Results

| Category | Status |
|----------|--------|
| Infrastructure (26 containers) | PASS |
| API Endpoints (CRUD, Auth, Pagination) | PASS |
| 3-Layer Idempotency | PASS |
| Multi-Channel Delivery | PASS |
| User Preferences & Quiet Hours | PASS |
| Bulk Notifications | PASS |
| WebSocket Real-Time | PASS |
| Failure Handling & Resilience | PASS |
| Monitoring & Observability | PASS |
| Security & Input Validation (24 cases) | PASS |

**Requirements Coverage: 25/25 (100%)**
