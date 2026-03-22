# Task 2: Real-Time Notification System — Architecture Blueprint

> **Goal**: Fully scalable, Docker-based notification system supporting 100K–300K+ users, 50K–150K simultaneous notifications
> **Stack**: Django + Celery + RabbitMQ + PostgreSQL + Redis + Docker
> **Deployment**: All services managed as Docker containers via Docker Compose

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Technology Stack](#3-technology-stack)
4. [Component Explanation (All Services)](#4-component-explanation-all-services)
5. [Database Design](#5-database-design)
6. [Notification Flow (End-to-End)](#6-notification-flow-end-to-end)
7. [Scaling Strategy](#7-scaling-strategy)
8. [Failure Handling Strategy](#8-failure-handling-strategy)
9. [Monitoring & Observability](#9-monitoring--observability)
10. [Project Structure (Django + Docker)](#10-project-structure-django--docker)
11. [Docker Infrastructure](#11-docker-infrastructure)


---

## 1. System Overview

### What This System Does

A multi-channel real-time notification system that:
- Delivers **in-app** (WebSocket), **push** (FCM/APNs), and **email** (SendGrid/SES) notifications
- Handles **3 trigger sources**: user actions, system events, scheduled jobs
- Supports **bulk notifications** (50K–150K) without blocking transactional notifications
- Ensures **zero duplicate delivery** with 3-layer idempotency
- Manages **user preferences** (channel opt-out, quiet hours, digest mode)
- Provides **circuit breakers** and **multi-provider failover** for fault tolerance
- Runs **entirely in Docker** — every service is a Docker container

### Core Design Principles

| Principle | Implementation |
|-----------|---------------|
| **All-in-Docker** | Every service (DB, broker, cache, workers, monitoring) runs as Docker container |
| **Async-first** | All notification delivery is async via Celery + RabbitMQ |
| **Separate WSGI/ASGI** | REST API (Gunicorn) and WebSocket (Daphne) run in separate containers |
| **Channel isolation** | Separate queues and workers per notification channel |
| **Fail-safe** | Circuit breakers, DLQ, retry with backoff, multi-provider failover |
| **Observable** | Prometheus + Grafana + ELK + Jaeger — all as Docker containers |

---

## 2. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIENTS                                           │
│                                                                                      │
│   ┌───────────────┐     ┌───────────────┐     ┌───────────────┐                      │
│   │   Web App     │     │  Mobile App   │     │  Admin Panel  │                      │
│   │   (React)     │     │ (iOS/Android) │     │   (Django)    │                      │
│   └───────┬───────┘     └───────┬───────┘     └───────┬───────┘                      │
│     WebSocket + REST      FCM/APNs + REST        REST API                            │
└───────────┼─────────────────────┼─────────────────────┼──────────────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                    LOAD BALANCER — Nginx (Docker Container)                           │
│                    • Sticky sessions for WebSocket                                    │
│                    • Health checks on /health/                                        │
│                    • SSL termination                                                  │
│                    • Rate limiting (first layer)                                      │
└───────────┬──────────────────────────────────────────┬───────────────────────────────┘
            │ HTTP/REST (api.*)                         │ WebSocket (ws.*)
            ▼                                          ▼
┌───────────────────────────┐            ┌──────────────────────────────┐
│   GUNICORN (WSGI)         │            │   DAPHNE (ASGI)              │
│   Django REST Framework   │            │   Django Channels            │
│   Docker Container        │            │   Docker Container           │
│   4-8 worker processes    │            │   Handles 20-30K conn/pod    │
│                           │            │                              │
│  Endpoints:               │            │  WebSocket:                  │
│  POST /api/v1/notif/      │            │  ws://ws.*/notifications/    │
│  POST /api/v1/notif/bulk/ │            │  • Group messaging           │
│  GET  /api/v1/notif/      │            │  • Online presence tracking  │
│  PATCH /api/v1/notif/read │            │  • Auto-reconnection support │
│  GET  /api/v1/unread/     │            │                              │
│  PUT  /api/v1/preferences │            │  Auth: Token auth in query   │
│  POST /api/v1/devices/    │            │  param or first WS message   │
└───────────┬───────────────┘            └────────────┬─────────────────┘
            │                                         │
            ▼                                         │
┌─────────────────────────────────────────┐           │
│   API LAYER                             │           │
│   ┌───────────────────────────────────┐ │           │
│   │  API Gateway                      │ │           │
│   │  • Token Authentication (DRF)    │ │           │
│   │  • Rate Limiting (per-user)       │ │           │
│   │  • Idempotency Key Check          │ │           │
│   │  • Request Validation (DRF)       │ │           │
│   └───────────────┬───────────────────┘ │           │
│                   ▼                     │           │
│   ┌───────────────────────────────────┐ │           │
│   │  User Preferences Check           │ │           │
│   │  • Channel opt-out enforcement    │ │           │
│   │  • Quiet hours check             │ │           │
│   │  • Digest mode routing           │ │           │
│   └───────────────┬───────────────────┘ │           │
│                   ▼                     │           │
│   ┌───────────────────────────────────┐ │           │
│   │  Notification Service             │ │           │
│   │  • Fan-out routing per channel    │ │           │
│   │  • Persist to PostgreSQL          │ │           │
│   │  • Create delivery records        │ │           │
│   │  • Enqueue per-channel tasks      │ │           │
│   └───────────────┬───────────────────┘ │           │
└───────────────────┼─────────────────────┘           │
                    │ Enqueue                          │ Channel Layer
                    ▼                                  ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                       MESSAGE BROKER LAYER                                            │
│                                                                                      │
│   ┌───────────────────────────────────┐     ┌───────────────────────────────────┐    │
│   │  RabbitMQ Cluster (3 containers)  │     │  Redis Cluster (3 containers)     │    │
│   │  (Primary Message Broker)         │     │                                   │    │
│   │                                   │     │  Container 1: redis-channels      │    │
│   │  Queues:                          │     │  └── Django Channels pub/sub      │    │
│   │  ├── push_queue   ──► dead_push   │     │  └── WebSocket group messaging    │    │
│   │  ├── email_queue  ──► dead_email  │     │                                   │    │
│   │  ├── inapp_queue  ──► dead_inapp  │     │  Container 2: redis-celery        │    │
│   │  └── bulk_queue                   │     │  └── Celery result backend        │    │
│   │                                   │     │  └── Deduplication sets (SET NX)  │    │
│   │  Features:                        │     │  └── Rate limiting counters       │    │
│   │  • Quorum queues (durable)        │     │                                   │    │
│   │  • Priority levels 1-10           │     │  Container 3: redis-cache         │    │
│   │  • Dead Letter Exchange (DLX)     │     │  └── App cache (preferences)      │    │
│   │  • x-max-length: 100K/queue       │     │  └── Unread counts               │    │
│   │  • Back-pressure: reject-pub      │     │  └── Session cache               │    │
│   │  • Lazy queues for overflow       │     │                                   │    │
│   └───────────────────────────────────┘     └───────────────────────────────────┘    │
│                                                                                      │
└──────┬──────────────────┬──────────────────┬─────────────────┬───────────────────────┘
       │                  │                  │                 │
       ▼                  ▼                  ▼                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                       CELERY WORKER POOLS (Docker Containers)                        │
│                                                                                      │
│   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐                     │
│   │  EMAIL WORKERS   │ │  PUSH WORKERS    │ │  IN-APP WORKERS  │                     │
│   │  (gevent pool)   │ │  (gevent pool)   │ │  (prefork pool)  │                     │
│   │  Concurrency: 50 │ │  Concurrency: 50 │ │  Concurrency: 20 │                     │
│   │  Rate: 1000/min  │ │  Batch: 500/req  │ │                  │                     │
│   │  Retry: 5x exp   │ │  Retry: 5x exp   │ │  Sends via       │                     │
│   │  Backoff + jitter│ │  Backoff + jitter│ │  channel_layer   │                     │
│   │                  │ │                  │ │  .group_send()   │                     │
│   │  CIRCUIT BREAKER │ │  CIRCUIT BREAKER │ │                  │                     │
│   └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘                     │
│            │                    │                    │                               │
│            ▼                    ▼                    ▼                               │
│   ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐                     │
│   │  EMAIL PROVIDERS │ │  PUSH PROVIDERS  │ │  WebSocket via   │                     │
│   │                  │ │                  │ │  Redis Channel   │                     │
│   │  Primary:        │ │  FCM / APNs      │ │  Layer           │                     │
│   │  SendGrid        │ │                  │ │                  │                     │
│   │  Failover:       │ │  Device cleanup  │ │                  │                     │
│   │  AWS SES         │ │  on invalid token│ │                  │                     │
│   └──────────────────┘ └──────────────────┘ └──────────────────┘                     │
│                                                                                      │
│   ┌──────────────────┐ ┌──────────────────┐                                          │
│   │  FAN-OUT WORKER  │ │  CELERY BEAT     │                                          │
│   │                  │ │  (Scheduler)     │                                          │
│   │  Bulk notifs →   │ │                  │                                          │
│   │  Batch 1000/chunk│ │  • Email digests │                                          │
│   │  Staggered delay │ │  • DLQ re-process│                                          │
│   │  Priority: 10    │ │  • Cleanup old   │                                          │
│   │  (low, won't     │ │  • FCM token prune│                                         │
│   │  block transact.)│ │  • Health checks │                                          │
│   └──────────────────┘ └──────────────────┘                                          │
│                                                                                      │
│   ┌──────────────────────────────────────────────────────────────────────────────┐    │
│   │  RETRY ARC (with error classification)                                       │    │
│   │  Workers ──(on error)──→ Notification Service                                │    │
│   │                                                                              │    │
│   │  Error Classification:                                                       │    │
│   │  • Transient (timeout, 503) → retry with exp backoff + jitter               │    │
│   │  • Rate-limited (429) → retry with longer delay (60s+)                       │    │
│   │  • Permanent (invalid email, unregistered token) → DLQ, no retry            │    │
│   │  • Unknown → retry up to max, then DLQ                                       │    │
│   └──────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                       DATA LAYER (Docker Containers)                                 │
│                                                                                      │
│   ┌────────────────────────────────────────────────┐                                 │
│   │  PgBouncer Connection Pool                     │                                 │
│   │  • Max 200 client connections                  │                                 │
│   │  • Pool mode: transaction                      │                                 │
│   │  • Prevents DB connection exhaustion           │                                 │
│   └────────────────────┬───────────────────────────┘                                 │
│                        ▼                                                             │
│   ┌────────────────────────────────────────────────┐                                 │
│   │  PostgreSQL                                    │                                 │
│   │                                                │                                 │
│   │  PRIMARY (writes)                              │                                 │
│   │  ├── notifications                             │                                 │
│   │  ├── notification_deliveries                   │                                 │
│   │  ├── notification_types                        │                                 │
│   │  ├── notification_preferences                  │                                 │
│   │  ├── fcm_devices                               │                                 │
│   │  ├── notification_analytics                    │                                 │
│   │  └── django_celery_beat_*                      │                                 │
│   │                                                │                                 │
│   │  READ REPLICA x 1                              │                                 │
│   │  └── Django DB Router: reads → replica          │                                 │
│   │  └── Notification list, unread count, search   │                                 │
│   └────────────────────────────────────────────────┘                                 │
│                                                                                      │
│   ┌────────────────────────────────────────────────┐                                 │
│   │  Notification Log                              │                                 │
│   │  status · read · sent                          │                                 │
│   │  (stored in notification_deliveries table)     │                                 │
│   └────────────────────────────────────────────────┘                                 │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│              ANALYTICS SERVICE                                                       │
│              • Click tracking · Open tracking                                        │
│              • Delivery event feedback → Notification Service                        │
│              • Stored in notification_analytics table                                │
└──────────────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│              MONITORING & OBSERVABILITY (Docker Containers)                           │
│                                                                                      │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│   │  Prometheus   │  │   Grafana    │  │  ELK Stack   │  │   Jaeger     │            │
│   │  (Metrics)    │  │ (Dashboards) │  │  (Logging)   │  │  (Tracing)   │            │
│   │              │  │              │  │              │  │              │            │
│   │ django-      │  │ Alert rules: │  │ Structured   │  │ OpenTelemetry│            │
│   │ prometheus   │  │ • Queue depth│  │ JSON logs    │  │ distributed  │            │
│   │ celery       │  │ • Error rate │  │ via          │  │ trace from   │            │
│   │ exporter     │  │ • Latency    │  │ django-guid  │  │ API → Queue  │            │
│   │              │  │ • DLQ depth  │  │ correlation  │  │ → Worker     │            │
│   │              │  │ • WS conns   │  │ IDs          │  │ → Provider   │            │
│   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘            │
│                                                                                      │
│   ┌────────────────────────────────────────────────────────────────────────────┐      │
│   │  Scaling (Docker-based)                                                    │      │
│   │  • docker compose up --scale email-worker=10 --scale push-worker=5        │      │
│   │  • Nginx auto-discovers scaled containers                                 │      │
│   │  • Monitor queue depth via Prometheus → scale workers accordingly         │      │
│   └────────────────────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

| Layer | Technology | Purpose | Docker Container |
|-------|-----------|---------|-----------------|
| **Web Framework** | Django 5.x + DRF 3.15 | REST API, ORM, Admin | `api`, `ws` |
| **ASGI Server** | Daphne | WebSocket + HTTP serving | `ws` |
| **WSGI Server** | Gunicorn | REST API HTTP serving | `api` |
| **Real-Time** | Django Channels 5.x | WebSocket consumers, group messaging | `ws` |
| **Channel Layer** | channels_redis | Pub/Sub for WebSocket groups | uses `redis-channels` |
| **Task Queue** | Celery 5.5.x | Async notification processing | `email-worker`, `push-worker`, `inapp-worker` |
| **Message Broker** | RabbitMQ 3.13+ (3-node cluster) | Durable message queuing | `rabbitmq-1`, `rabbitmq-2`, `rabbitmq-3` |
| **Result Backend** | Redis 7.x | Celery task result storage | `redis-celery` |
| **Cache** | Redis 7.x | App caching, dedup sets, rate limiting | `redis-cache` |
| **Channel Layer Store** | Redis 7.x | WebSocket group messaging | `redis-channels` |
| **Database** | PostgreSQL 16 | Primary data store | `postgres-primary`, `postgres-replica` |
| **Connection Pool** | PgBouncer | DB connection pooling | `pgbouncer` |
| **Push Notifications** | fcm-django + firebase-admin | FCM HTTP v1 API | uses `push-worker` |
| **Email (Primary)** | django-anymail + SendGrid | Transactional + bulk email | uses `email-worker` |
| **Email (Failover)** | AWS SES via django-anymail | Backup email provider | uses `email-worker` |
| **Periodic Tasks** | django-celery-beat | Scheduled jobs (digests, cleanup) | `celery-beat` |
| **Input Sanitization** | bleach 6.x | XSS prevention, HTML tag stripping | within `api` |
| **Circuit Breaker** | pybreaker | Prevent cascade failures | within workers |
| **Metrics** | Prometheus + django-prometheus | Metric collection | `prometheus` |
| **Dashboards** | Grafana | Visualization + alerting | `grafana` |
| **Logging** | ELK Stack | Log aggregation + search | `elasticsearch`, `logstash`, `kibana` |
| **Tracing** | OpenTelemetry + Jaeger | Distributed tracing | `jaeger` |
| **Correlation** | django-guid | Request-to-task correlation ID | within `api`, `ws`, workers |
| **Load Balancer** | Nginx | HTTP + WebSocket routing | `nginx` |

---

## 4. Component Explanation (All Services)

### 4.1 Load Balancer — Nginx (Docker Container)

Routes traffic to Gunicorn (REST) and Daphne (WebSocket) containers. Sticky sessions ensure WebSocket connections stay on the same Daphne instance.

```
Nginx Configuration:

upstream api_backend {
    server api:8000;
    # When scaled: docker compose up --scale api=3
    # Nginx resolves all api containers via Docker DNS
}

upstream ws_backend {
    ip_hash;  # Sticky sessions for WebSocket
    server ws:8001;
}

server {
    location /api/ {
        proxy_pass http://api_backend;
    }
    location /ws/ {
        proxy_pass http://ws_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4.2 Separate WSGI + ASGI Servers

WebSocket connections are long-lived (minutes/hours). Running REST + WS in the same process causes WebSocket connections to consume worker slots meant for REST requests. Splitting them into separate containers eliminates this bottleneck.

| Server | Protocol | Process | Scaling |
|--------|----------|---------|---------|
| **Gunicorn** (WSGI) | HTTP/REST | Short-lived request-response (50-200ms) | Scale by request rate |
| **Daphne** (ASGI) | WebSocket | Long-lived connections (minutes-hours) | Scale by connection count |

### 4.3 API Layer

#### Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/notifications/` | Create/trigger a notification |
| `POST` | `/api/v1/notifications/bulk/` | Bulk notification (e.g., 50K users) |
| `GET` | `/api/v1/notifications/` | List user's notifications (paginated) |
| `GET` | `/api/v1/notifications/unread-count/` | Get unread notification count |
| `PATCH` | `/api/v1/notifications/{id}/read/` | Mark notification as read |
| `PATCH` | `/api/v1/notifications/mark-all-read/` | Mark all as read |
| `GET` | `/api/v1/notifications/preferences/` | Get user notification preferences |
| `PUT` | `/api/v1/notifications/preferences/` | Update preferences |
| `POST` | `/api/v1/devices/` | Register FCM device token |
| `DELETE` | `/api/v1/devices/{token}/` | Unregister device |

#### API Flow

```
1. Validate request payload (DRF Serializer)
2. Check idempotency key (X-Idempotency-Key header)
   └── If duplicate → return existing notification (200 OK)
3. Check user notification preferences
   └── Filter out disabled channels
4. Check quiet hours
   └── If in quiet hours → queue for later delivery (Celery ETA)
5. Persist notification to PostgreSQL (via PgBouncer)
6. Create NotificationDelivery records (1 per enabled channel)
7. Enqueue delivery tasks to RabbitMQ (1 per channel)
8. Return 201 Created with notification ID
```

### 4.4 Real-Time Delivery — Django Channels WebSocket

```python
# consumers.py
class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = f"notifications_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send unread count on connect
        count = await self.get_unread_count()
        await self.send_json({"type": "unread_count", "count": count})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_send(self, event):
        await self.send_json(event["data"])

    async def unread_count_update(self, event):
        await self.send_json({"type": "unread_count", "count": event["count"]})
```

### 4.5 Message Broker — RabbitMQ Cluster

#### Queue Architecture

```
RabbitMQ Cluster (3 Docker containers, quorum queues)
│
├── Exchange: notifications (type: direct)
│   ├── Queue: email_queue
│   │   ├── x-max-length: 100,000           ← back-pressure
│   │   ├── x-overflow: reject-publish       ← back-pressure
│   │   ├── x-dead-letter-exchange: dlx
│   │   └── x-queue-type: quorum             ← durability
│   │
│   ├── Queue: push_queue
│   │   ├── x-max-length: 100,000
│   │   ├── x-dead-letter-exchange: dlx
│   │   └── x-queue-type: quorum
│   │
│   └── Queue: inapp_queue
│       ├── x-max-length: 50,000
│       ├── x-dead-letter-exchange: dlx
│       └── x-queue-type: quorum
│
├── Exchange: bulk (type: direct)             ← separate from transactional
│   └── Queue: bulk_queue
│       └── Priority: 10 (low, won't block transactional)
│
└── Exchange: dlx (type: direct) — Dead Letter Exchange
    ├── Queue: dead_email
    ├── Queue: dead_push
    ├── Queue: dead_inapp
    └── Queue: dead_bulk
```

### 4.6 Celery Workers

```python
# Circuit breaker for external providers
import pybreaker

email_breaker = pybreaker.CircuitBreaker(
    fail_max=5,              # Open circuit after 5 consecutive failures
    reset_timeout=60,        # Try again after 60 seconds
    exclude=[RateLimitExceeded],  # Don't count rate limits as failures
)

@app.task(bind=True, max_retries=5, retry_backoff=True, retry_jitter=True, acks_late=True)
def send_email(self, notification_id):
    delivery = NotificationDelivery.objects.get(
        notification_id=notification_id, channel="email"
    )
    if delivery.status == "sent":
        return  # Idempotent

    try:
        email_breaker.call(send_via_provider, notification_id)
        delivery.status = "sent"
        delivery.save()
    except pybreaker.CircuitBreakerError:
        # Circuit is OPEN — provider is down, don't even try
        raise self.retry(countdown=60)
    except PermanentError:
        # Bad email, unsubscribed — don't retry, send to DLQ
        delivery.status = "failed"
        delivery.error_message = "permanent_failure"
        delivery.save()
    except Exception as exc:
        delivery.attempts += 1
        delivery.save()
        raise self.retry(exc=exc)
```

### 4.7 Multi-Provider Email Failover

```python
def send_via_provider(notification_id):
    """Try primary provider, failover to secondary."""
    notification = Notification.objects.get(id=notification_id)

    providers = [
        ("sendgrid", send_via_sendgrid),
        ("ses", send_via_ses),
    ]

    for provider_name, send_fn in providers:
        try:
            result = send_fn(notification)
            return result
        except ProviderUnavailableError:
            logger.warning(f"{provider_name} unavailable, trying next")
            continue

    raise AllProvidersDownError("All email providers failed")
```

### 4.8 Celery Beat Scheduler

```python
# Periodic tasks
app.conf.beat_schedule = {
    "process-dead-letter-queue": {
        "task": "apps.notifications.tasks_periodic.process_dlq",
        "schedule": crontab(minute="*/5"),           # Every 5 minutes
    },
    "send-digest-emails": {
        "task": "apps.notifications.tasks_periodic.send_digests",
        "schedule": crontab(hour=8, minute=0),       # Daily at 8 AM
    },
    "cleanup-old-notifications": {
        "task": "apps.notifications.tasks_periodic.cleanup_old",
        "schedule": crontab(hour=3, minute=0),       # Daily at 3 AM
    },
    "cleanup-inactive-fcm-tokens": {
        "task": "apps.notifications.tasks_periodic.cleanup_fcm_tokens",
        "schedule": crontab(hour=4, minute=0),       # Daily at 4 AM
    },
    "publish-queue-metrics": {
        "task": "apps.notifications.tasks_periodic.publish_metrics",
        "schedule": 30.0,                            # Every 30 seconds
    },
}
```

### 4.9 PgBouncer Connection Pool

Without PgBouncer, 50+ Celery workers each open 1+ DB connections = 50+ connections. PostgreSQL default `max_connections=100`. At 2x scale with 100+ workers the connections get exhausted.

```ini
# pgbouncer.ini
[databases]
notifications = host=postgres-primary port=5432 dbname=notifications

[pgbouncer]
pool_mode = transaction          # Release connection after each transaction
max_client_conn = 500            # Accept up to 500 from workers
default_pool_size = 50           # But only 50 actual DB connections
reserve_pool_size = 10           # Extra 10 for burst
reserve_pool_timeout = 3
```

### 4.10 Analytics Service

Tracks delivery events (delivered, opened, clicked) and feeds stats back to the notification service.

```python
class NotificationAnalytics(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=20)  # "delivered", "opened", "clicked"
    channel = models.CharField(max_length=20)
    metadata = models.JSONField(default=dict)      # click URL, device info, etc.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_analytics"
        indexes = [
            models.Index(fields=["notification", "event_type"]),
        ]
```

---

## 5. Database Design

### 5.1 Entity Relationship Diagram

```
┌──────────────────┐       ┌──────────────────────┐
│   auth_user      │       │  notification_types    │
│──────────────────│       │────────────────────────│
│  id (PK)         │       │  id (PK)               │
│  email           │       │  name (UNIQUE)          │
│  ...             │       │  template               │
└───────┬──────────┘       │  channels[] (ARRAY)     │
        │                  │  priority (1-10)         │
        │ 1:N              └──────────┬───────────────┘
        │                             │ 1:N
        ▼                             ▼
┌──────────────────────────────────────────────────┐
│               notifications                       │
│  (standard table with partial indexes)             │
│──────────────────────────────────────────────────│
│  id              UUID (PK, gen_random_uuid)       │
│  idempotency_key VARCHAR(255) UNIQUE              │
│  recipient_id    INTEGER (FK → auth_user)         │
│  type_id         INTEGER (FK → notification_types)│
│  title           VARCHAR(500)                     │
│  body            TEXT                              │
│  metadata        JSONB DEFAULT '{}'               │
│  is_read         BOOLEAN DEFAULT FALSE            │
│  read_at         TIMESTAMPTZ                      │
│  created_at      TIMESTAMPTZ DEFAULT NOW()        │
│  expires_at      TIMESTAMPTZ                      │
└───────┬──────────────────────────────────────────┘
        │ 1:N                          │ 1:N
        ▼                              ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│ notification_deliveries  │  │ notification_analytics    │
│──────────────────────────│  │──────────────────────────│
│ id         UUID (PK)     │  │ id          UUID (PK)     │
│ notification_id (FK)     │  │ notification_id (FK)     │
│ channel    VARCHAR(20)   │  │ event_type  VARCHAR(20)  │
│ status     VARCHAR(20)   │  │ channel     VARCHAR(20)  │
│ provider_id VARCHAR(255) │  │ metadata    JSONB        │
│ attempts   SMALLINT      │  │ created_at  TSTZ         │
│ last_attempt_at TSTZ     │  └──────────────────────────┘
│ error_message TEXT       │
│ created_at TSTZ          │
└──────────────────────────┘

┌──────────────────────────────────────────────────┐
│       notification_preferences                    │
│──────────────────────────────────────────────────│
│  user_id           INTEGER (PK, FK → auth_user)   │
│  email_enabled     BOOLEAN DEFAULT TRUE           │
│  push_enabled      BOOLEAN DEFAULT TRUE           │
│  inapp_enabled     BOOLEAN DEFAULT TRUE           │
│  quiet_hours_start TIME                           │
│  quiet_hours_end   TIME                           │
│  digest_mode       VARCHAR(20) DEFAULT 'instant'  │
│  channel_overrides JSONB DEFAULT '{}'             │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│       fcm_devices (via fcm-django)                │
│──────────────────────────────────────────────────│
│  id                BIGINT (PK)                    │
│  user_id           INTEGER (FK → auth_user)       │
│  registration_id   TEXT (device token)            │
│  type              VARCHAR(20) — ios/android/web   │
│  active            BOOLEAN DEFAULT TRUE           │
│  date_created      TIMESTAMPTZ                    │
└──────────────────────────────────────────────────┘
```

### 5.2 Django Models

```python
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField

User = get_user_model()


class NotificationType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    template = models.TextField(blank=True)
    channels = ArrayField(models.CharField(max_length=20), default=list)
    priority = models.SmallIntegerField(default=5)

    class Meta:
        db_table = "notification_types"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.ForeignKey(NotificationType, on_delete=models.CASCADE)
    title = models.CharField(max_length=500)
    body = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "-created_at"],
                condition=models.Q(is_read=False),
                name="idx_notif_user_unread",
            ),
            models.Index(
                fields=["expires_at"],
                condition=models.Q(expires_at__isnull=False),
                name="idx_notif_expires",
            ),
        ]


class NotificationDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        DELIVERED = "delivered"
        FAILED = "failed"
        BOUNCED = "bounced"

    class Channel(models.TextChoices):
        EMAIL = "email"
        PUSH = "push"
        INAPP = "inapp"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_id = models.CharField(max_length=255, blank=True, null=True)
    attempts = models.SmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_deliveries"
        unique_together = [("notification", "channel")]
        indexes = [
            models.Index(
                fields=["status", "channel"],
                condition=models.Q(status__in=["pending", "failed"]),
                name="idx_delivery_status",
            ),
        ]


class NotificationPreference(models.Model):
    class DigestMode(models.TextChoices):
        INSTANT = "instant"
        HOURLY = "hourly"
        DAILY = "daily"

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    inapp_enabled = models.BooleanField(default=True)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    digest_mode = models.CharField(max_length=20, choices=DigestMode.choices, default=DigestMode.INSTANT)
    channel_overrides = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "notification_preferences"


class NotificationAnalytics(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="analytics")
    event_type = models.CharField(max_length=20)  # delivered, opened, clicked
    channel = models.CharField(max_length=20)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_analytics"
        indexes = [
            models.Index(fields=["notification", "event_type"]),
            models.Index(fields=["created_at"]),
        ]
```

### 5.3 Indexing Strategy

| Index | Purpose | Type |
|-------|---------|------|
| `idx_notif_user_unread` | Fetch unread notifications per user (most frequent query) | Partial (`WHERE is_read=FALSE`) |
| `notifications.idempotency_key` | Duplicate check on create | Unique |
| `idx_delivery_status` | Find pending/failed deliveries for retry | Partial (`WHERE status IN (pending,failed)`) |
| `idx_notif_expires` | Cleanup expired notifications | Partial (`WHERE expires_at IS NOT NULL`) |
| `(notification, channel)` | One delivery per channel enforcement | Unique constraint |

### 5.4 Performance Strategy

The `notifications` table uses standard (non-partitioned) tables with partial indexes for performance. Key partial indexes (e.g., `idx_notif_user_unread` filtering on `is_read=FALSE`) ensure that frequent queries only scan relevant rows, providing efficient lookups without the complexity of table partitioning.

### 5.5 Duplicate Prevention (3-Layer)

| Layer | Mechanism | What It Catches |
|-------|-----------|-----------------|
| **API** | `X-Idempotency-Key` → UNIQUE column | Client retries, network issues |
| **Redis** | `SET NX` with TTL on `notif:{id}:{channel}` | Celery at-least-once redelivery |
| **DB** | `UNIQUE(notification_id, channel)` on deliveries | Race conditions in parallel workers |

---

## 6. Notification Flow (End-to-End)

### 6.1 Single Notification

```
Step 1: TRIGGER
  User A comments on User B's post

Step 2: LOAD BALANCER
  Nginx routes POST /api/v1/notifications/ → Gunicorn container

Step 3: API LAYER
  ├── Token Auth → validate token
  ├── Rate limit check → user under limit?
  ├── Idempotency key check → not duplicate
  ├── User preferences → B has email=ON, push=ON, inapp=ON
  ├── Quiet hours → B not in quiet hours
  ├── Save Notification to PostgreSQL (via PgBouncer)
  ├── Create 3 NotificationDelivery records
  └── Enqueue 3 Celery tasks → RabbitMQ cluster

Step 4: WORKERS
  EMAIL WORKER:
  ├── Dequeue from email_queue
  ├── Redis dedup check
  ├── Circuit breaker check → SendGrid circuit CLOSED (healthy)
  ├── Send via SendGrid
  ├── If SendGrid down → failover to AWS SES
  └── Update delivery status

  PUSH WORKER:
  ├── Dequeue from push_queue
  ├── Circuit breaker check → FCM circuit CLOSED
  ├── Fetch FCM tokens from DB
  ├── Send via FCM batch API
  └── Clean up invalid tokens

  IN-APP WORKER:
  ├── Dequeue from inapp_queue
  ├── channel_layer.group_send() → redis-channels → Daphne → WebSocket
  └── If user offline → notification in DB, shown on next login

Step 5: ANALYTICS
  Delivery events → notification_analytics table
  Stats feed back to notification service
```

### 6.2 Bulk 50K-150K Notification

```
Step 1: POST /api/v1/notifications/bulk/
  Body: { "type": "system_announcement", "audience": "all_active" }
  Response: 202 Accepted

Step 2: FAN-OUT WORKER (from bulk_queue)
  ├── Query target users (paginated, 1000 per batch)
  ├── For each batch:
  │   ├── bulk_create() 1000 Notification records
  │   ├── bulk_create() delivery records
  │   ├── Enqueue channel tasks (1000 per chunk)
  │   └── Sleep 100ms between chunks (staggered, prevent thundering herd)
  └── Priority: 10 (low — doesn't block transactional P1 notifications)

Step 3: PARALLEL PROCESSING
  ├── Email workers (gevent, concurrency=50 each)
  ├── Push workers (FCM batch, 500/request)
  ├── In-app workers (channel_layer.group_send)
  └── Scale workers: docker compose up --scale email-worker=10

Throughput for 150K notifications:
  Email: 10 workers x 50 conc = ~2,500/sec → 60 seconds
  Push:  5 workers x 500/batch = ~2,500/sec → 60 seconds
  InApp: 5 workers x 20 conc = ~100/sec → 25 minutes (acceptable, non-blocking)
```

---

## 7. Scaling Strategy

### 7.1 Horizontal Scaling Per Component

| Component | At 100K users | At 200K (2x) | At 300K (3x) | Docker Scaling Command |
|-----------|--------------|--------------|--------------|----------------------|
| **Gunicorn** | 2 containers | 4 containers | 6 containers | `--scale api=6` |
| **Daphne** | 2 containers | 4 containers | 6 containers | `--scale ws=6` |
| **Email Workers** | 5 containers | 10 containers | 20 containers | `--scale email-worker=20` |
| **Push Workers** | 3 containers | 6 containers | 10 containers | `--scale push-worker=10` |
| **InApp Workers** | 3 containers | 5 containers | 10 containers | `--scale inapp-worker=10` |
| **RabbitMQ** | 3-node cluster | 3-node cluster | 3-node cluster | Fixed cluster |
| **PostgreSQL** | Primary + 1 replica | Primary + 1 replica (current) | Primary + 1 replica (current) | Add replica containers |
| **Redis** | 3 containers | 3 containers (more RAM) | 3 containers | Increase memory limits |

### 7.2 Back-Pressure Management

| Scenario | Mechanism | Action |
|----------|-----------|--------|
| Queue full (100K msgs) | RabbitMQ `x-overflow: reject-publish` | API returns 503, client retries |
| Workers overwhelmed | `worker_prefetch_multiplier=1` | Fair dispatch, no hoarding |
| Provider rate limit | Celery `rate_limit="1000/m"` | Workers self-throttle |
| Bulk flood | Separate `bulk_queue` + priority 10 | Transactional (P1) always served first |
| DB connection full | PgBouncer queues excess connections | Transparent to workers |

### 7.3 Load Balancing

| Layer | Tool | Strategy |
|-------|------|----------|
| HTTP API | Nginx (Docker) | Round-robin across Gunicorn containers |
| WebSocket | Nginx (Docker) | Sticky sessions (ip_hash) |
| Celery Workers | RabbitMQ | Fair dispatch (workers pull tasks) |
| DB Reads | Django DB Router | Route to read replicas |
| Redis | Redis Sentinel | Auto-failover, client-side routing |

---

## 8. Failure Handling Strategy

### 8.1 Failure Scenarios

| Scenario | Handling |
|----------|----------|
| **Worker crashes** | `acks_late=True` → RabbitMQ re-delivers. Docker restarts container. |
| **Queue fills up** | `reject-publish` back-pressure → API 503 → scale workers with `--scale` |
| **Email provider down** | Circuit breaker opens → failover to backup provider |
| **Push provider down** | Circuit breaker → retry after 60s, notification in DB for next app open |
| **Database slow** | PgBouncer queues connections + read replicas offload reads |
| **Redis down** | Redis Sentinel promotes replica in 10-30s |
| **WebSocket disconnect** | Client reconnects → fetches missed notifications via REST API |
| **RabbitMQ node down** | Quorum queues maintain consensus with 2/3 nodes |

### 8.2 Retry Strategy

```
Error classification determines retry behavior:

┌─────────────────────────────────────────────────────────────┐
│  Error Type        │  Action                │  Example       │
├─────────────────────────────────────────────────────────────┤
│  Transient         │  Retry, exp backoff    │  Timeout, 503  │
│  Rate-limited      │  Retry, longer delay   │  429 from FCM  │
│  Permanent         │  No retry → DLQ        │  Bad email     │
│  Unknown           │  Retry 5x → DLQ       │  Unexpected    │
│  Circuit open      │  Retry after reset     │  Provider down │
└─────────────────────────────────────────────────────────────┘

Retry timeline: 1s → 2s → 4s → 8s → 16s (capped at 10min)
+ random jitter to prevent thundering herd
```

### 8.3 DLQ Processing

```
Automated DLQ re-processor via Celery Beat (every 5 min):

Every 5 minutes:
├── Scan dead_email, dead_push, dead_inapp, dead_bulk queues
├── For each message:
│   ├── Transient error + attempts < 10 → re-enqueue to original queue
│   ├── Permanent error → mark as permanently failed in DB
│   └── Unknown → flag for manual review
└── Send alert to ops team if DLQ depth > 0
```

---

## 9. Monitoring & Observability

### 9.1 Four Pillars (All as Docker Containers)

| Pillar | Tool | Purpose |
|--------|------|---------|
| **Metrics** | Prometheus + Grafana | Collect and visualize system metrics |
| **Logging** | ELK Stack (Elasticsearch + Logstash + Kibana) | Structured JSON log aggregation and search |
| **Tracing** | Jaeger + OpenTelemetry | Distributed tracing across API → Queue → Worker → Provider |
| **Correlation** | django-guid | Link request → task → delivery with a single correlation ID |

### 9.2 Key Metrics to Track

| Metric | Type | Purpose |
|--------|------|---------|
| `notifications_created_total` | Counter | Total created by type/channel |
| `notifications_delivered_total` | Counter | Successful deliveries |
| `notifications_failed_total` | Counter | Failed deliveries by error type |
| `notification_delivery_seconds` | Histogram | Latency from creation to delivery |
| `notification_queue_depth` | Gauge | Current queue sizes |
| `websocket_connections_active` | Gauge | Active WS connections per Daphne container |
| `notification_dlq_depth` | Gauge | Dead letter queue sizes |
| `circuit_breaker_state` | Gauge | Provider circuit state (0=closed, 1=open) |

### 9.3 Alert Rules (Grafana)

| Alert | Condition | Severity |
|-------|-----------|----------|
| Queue depth > 50,000 for 5 min | Scaling needed | Critical |
| Failure rate > 5% over 15 min | Provider issue | Critical |
| DLQ depth > 0 for 10 min | Inspect failures | Warning |
| p99 latency > 30s | Bottleneck | Warning |
| WS connections drop > 50% in 1 min | Daphne crash | Critical |
| Circuit breaker OPEN | Provider down | Critical |

### 9.4 Structured Logging

```python
LOGGING = {
    "version": 1,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "loggers": {
        "notifications": {"handlers": ["console"], "level": "INFO"},
    },
}

# Every log line includes:
# {
#   "timestamp": "2026-03-21T10:30:00Z",
#   "correlation_id": "abc-123",       ← from django-guid
#   "notification_id": "notif-456",
#   "channel": "email",
#   "status": "sent",
#   "duration_ms": 245,
#   "provider": "sendgrid"
# }
```

---

## 10. Project Structure (Django + Docker)

```
notification_system/
│
├── config/                              # Django project configuration
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py                     # Shared settings
│   │   ├── development.py             # Dev overrides (DEBUG=True)
│   │   └── production.py              # Production settings
│   ├── urls.py                         # Root URL configuration
│   ├── asgi.py                         # ASGI entry point (Daphne + Channels)
│   ├── wsgi.py                         # WSGI entry point (Gunicorn)
│   ├── celery.py                       # Celery app configuration
│   └── routing.py                      # Root WebSocket routing
│
├── apps/                                # Django applications
│   ├── __init__.py
│   │
│   ├── notifications/                   # Core notification app
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   # Notification, NotificationType, Delivery, Preference
│   │   ├── serializers.py              # DRF serializers
│   │   ├── views.py                    # REST API views
│   │   ├── urls.py                     # REST URL patterns
│   │   ├── consumers.py               # WebSocket consumers
│   │   ├── routing.py                  # WebSocket URL patterns
│   │   ├── tasks.py                    # Celery tasks (email, push, inapp)
│   │   ├── tasks_bulk.py              # Bulk fan-out tasks
│   │   ├── tasks_periodic.py          # Periodic tasks (digests, cleanup, DLQ)
│   │   ├── services.py                # NotificationService (business logic layer)
│   │   ├── idempotency.py             # Redis dedup helpers (SET NX)
│   │   ├── middleware.py              # WebSocket auth middleware
│   │   ├── admin.py                    # Admin panel registration
│   │   ├── pagination.py              # Cursor pagination for notification list
│   │   ├── filters.py                  # DRF filters
│   │   ├── providers/                  # External provider integrations
│   │   │   ├── __init__.py
│   │   │   ├── email.py               # SendGrid + SES failover
│   │   │   └── push.py                # FCM wrapper
│   │   ├── migrations/
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_models.py
│   │       ├── test_views.py
│   │       ├── test_tasks.py
│   │       ├── test_consumers.py
│   │       └── test_services.py
│   │
│   ├── analytics/                       # Analytics tracking app
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   # NotificationAnalytics model
│   │   ├── serializers.py
│   │   ├── views.py                    # Analytics API endpoints
│   │   ├── tasks.py                    # Async analytics processing
│   │   ├── urls.py
│   │   ├── migrations/
│   │   └── tests/
│   │
│   └── devices/                         # FCM device management app
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── views.py
│       ├── serializers.py
│       ├── urls.py
│       ├── migrations/
│       └── tests/
│
├── Dockerfile                           # Single Dockerfile for all app services
├── docker/                              # Docker support configuration
│   ├── nginx/
│   │   └── nginx.conf                  # Load balancer config
│   ├── pgbouncer/
│   │   └── pgbouncer.ini              # Connection pool config
│   ├── postgres/
│   │   └── init.sql                    # DB initialization
│   ├── rabbitmq/
│   │   └── rabbitmq.conf              # Cluster config
│   ├── prometheus/
│   │   └── prometheus.yml             # Metrics scrape targets
│   ├── grafana/
│   │   └── dashboards/                # Pre-built dashboard JSON files
│   ├── elk/
│   │   ├── logstash.conf              # Log pipeline config
│   │   └── kibana/                     # Kibana index patterns
│   └── jaeger/                         # Jaeger config (if needed)
│
├── docker-compose.yml                   # All services definition
├── .env.example                         # Environment variables template
├── requirements/
│   ├── base.txt                        # Shared dependencies
│   └── development.txt                 # Dev-only (debug toolbar, etc.)
├── manage.py
└── .gitignore
```

---

## 11. Docker Infrastructure

### 11.1 All Docker Compose Services

Every service runs as a Docker container. No external services required.

| # | Service Name | Image / Build | Port | Purpose |
|---|-------------|---------------|------|---------|
| 1 | `nginx` | nginx:alpine | 80, 443 | Load balancer + reverse proxy |
| 2 | `api` | Dockerfile | 8000 | Django REST API (Gunicorn) |
| 3 | `ws` | Dockerfile | 8001 | Django WebSocket (Daphne) |
| 4 | `email-worker` | Dockerfile | — | Celery email worker |
| 5 | `push-worker` | Dockerfile | — | Celery push worker |
| 6 | `inapp-worker` | Dockerfile | — | Celery in-app worker |
| 7 | `fanout-worker` | Dockerfile | — | Celery bulk fan-out worker |
| 8 | `celery-beat` | Dockerfile | — | Celery Beat scheduler |
| 9 | `postgres-primary` | postgres:16 | 5432 | PostgreSQL primary (writes) |
| 10 | `postgres-replica` | postgres:16 | 5433 | PostgreSQL read replica |
| 11 | `pgbouncer` | edoburu/pgbouncer | 6432 | Connection pooling |
| 12 | `redis-channels` | redis:7-alpine | 6379 | Django Channels pub/sub |
| 13 | `redis-celery` | redis:7-alpine | 6380 | Celery result backend + dedup |
| 14 | `redis-cache` | redis:7-alpine | 6381 | App cache + unread counts |
| 15 | `rabbitmq-1` | rabbitmq:3.13-management | 5672, 15672 | RabbitMQ node 1 |
| 16 | `rabbitmq-2` | rabbitmq:3.13-management | 5673 | RabbitMQ node 2 |
| 17 | `rabbitmq-3` | rabbitmq:3.13-management | 5674 | RabbitMQ node 3 |
| 18 | `prometheus` | prom/prometheus | 9090 | Metrics collection |
| 19 | `grafana` | grafana/grafana | 3000 | Dashboards + alerts |
| 20 | `elasticsearch` | elasticsearch:8.x | 9200 | Log storage + search |
| 21 | `logstash` | logstash:8.x | 5044 | Log pipeline |
| 22 | `kibana` | kibana:8.x | 5601 | Log visualization |
| 23 | `jaeger` | jaegertracing/all-in-one | 16686 | Distributed tracing UI |
| 24 | `redis-exporter-cache` | oliver006/redis_exporter | — | Prometheus exporter for redis-cache |
| 25 | `redis-exporter-celery` | oliver006/redis_exporter | — | Prometheus exporter for redis-celery |
| 26 | `redis-exporter-channels` | oliver006/redis_exporter | — | Prometheus exporter for redis-channels |

### 11.2 Docker Compose Structure

```yaml
# docker-compose.yml (simplified structure)
services:
  # --- Load Balancer ---
  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes: ["./docker/nginx/nginx.conf:/etc/nginx/nginx.conf"]
    depends_on: [api, ws]

  # --- Application ---
  api:
    build: .
    command: >
      gunicorn config.wsgi:application
      --bind 0.0.0.0:8000
      --workers 4
      --threads 2
      --worker-class gthread
    env_file: .env
    depends_on: [pgbouncer, redis-cache, rabbitmq-1]

  ws:
    build: .
    command: daphne -b 0.0.0.0 -p 8001 config.asgi:application
    env_file: .env
    depends_on: [redis-channels, pgbouncer]

  # --- Workers ---
  email-worker:
    build: .
    command: celery -A config worker -Q email_queue -c 50 -P gevent
    env_file: .env
    depends_on: [rabbitmq-1, pgbouncer, redis-celery]

  push-worker:
    build: .
    command: celery -A config worker -Q push_queue -c 50 -P gevent
    env_file: .env
    depends_on: [rabbitmq-1, pgbouncer, redis-celery]

  inapp-worker:
    build: .
    command: celery -A config worker -Q inapp_queue -c 20 -P prefork
    env_file: .env
    depends_on: [rabbitmq-1, redis-channels, redis-celery]

  fanout-worker:
    build: .
    command: celery -A config worker -Q bulk_queue -c 10 -P prefork
    env_file: .env
    depends_on: [rabbitmq-1, pgbouncer, redis-celery]

  celery-beat:
    build: .
    command: celery -A config beat --scheduler django_celery_beat.schedulers:DatabaseScheduler
    env_file: .env
    depends_on: [rabbitmq-1, pgbouncer]

  # --- Database ---
  postgres-primary:
    image: postgres:16
    volumes: ["postgres_data:/var/lib/postgresql/data", "./docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql"]
    environment: { POSTGRES_DB: notifications, POSTGRES_USER: notif_user, POSTGRES_PASSWORD: "${DB_PASSWORD}" }

  postgres-replica:
    image: postgres:16
    depends_on: [postgres-primary]
    environment: { POSTGRES_PRIMARY_HOST: postgres-primary }

  pgbouncer:
    image: edoburu/pgbouncer
    volumes: ["./docker/pgbouncer/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini"]
    depends_on: [postgres-primary]

  # --- Redis (3 isolated instances) ---
  redis-channels:
    image: redis:7-alpine
    command: redis-server --port 6379 --maxmemory 256mb

  redis-celery:
    image: redis:7-alpine
    command: redis-server --port 6379 --maxmemory 256mb

  redis-cache:
    image: redis:7-alpine
    command: redis-server --port 6379 --maxmemory 512mb

  # --- RabbitMQ Cluster ---
  rabbitmq-1:
    image: rabbitmq:3.13-management
    hostname: rabbitmq-1
    ports: ["5672:5672", "15672:15672"]
    environment: { RABBITMQ_ERLANG_COOKIE: "cluster_cookie" }

  rabbitmq-2:
    image: rabbitmq:3.13-management
    hostname: rabbitmq-2
    environment: { RABBITMQ_ERLANG_COOKIE: "cluster_cookie" }
    depends_on: [rabbitmq-1]

  rabbitmq-3:
    image: rabbitmq:3.13-management
    hostname: rabbitmq-3
    environment: { RABBITMQ_ERLANG_COOKIE: "cluster_cookie" }
    depends_on: [rabbitmq-1]

  # --- Monitoring ---
  prometheus:
    image: prom/prometheus
    volumes: ["./docker/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml"]

  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
    volumes: ["./docker/grafana/dashboards:/var/lib/grafana/dashboards"]
    depends_on: [prometheus]

  # --- Logging ---
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.12.0
    environment: { discovery.type: single-node, xpack.security.enabled: "false" }

  logstash:
    image: docker.elastic.co/logstash/logstash:8.12.0
    volumes: ["./docker/elk/logstash.conf:/usr/share/logstash/pipeline/logstash.conf"]
    depends_on: [elasticsearch]

  kibana:
    image: docker.elastic.co/kibana/kibana:8.12.0
    ports: ["5601:5601"]
    depends_on: [elasticsearch]

  # --- Tracing ---
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports: ["16686:16686"]

volumes:
  postgres_data:
```

### 11.3 Scaling with Docker Compose

```bash
# Scale workers during high load
docker compose up --scale email-worker=10 --scale push-worker=5 -d

# Scale API/WS containers
docker compose up --scale api=4 --scale ws=4 -d

# View running containers
docker compose ps

# View logs for specific service
docker compose logs -f email-worker
```

