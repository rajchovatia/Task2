# All 26 Containers — What They Do & How They Work Together

## System Overview

This is a **Real-time Notification System (RNS)** that can send notifications to 100K+ users via Email, Push (mobile), and In-App (WebSocket).

```
User Request → Nginx → Django API → RabbitMQ → Celery Workers → Email/Push/WebSocket
                                        ↓
                                   PostgreSQL (store)
                                   Redis (cache/realtime)
```

---

## LAYER 1: LOAD BALANCER (1 container)

### 1. Nginx (`nginx`)
- **What it does:** The "front door" of the system. Every request from the outside world hits Nginx first.
- **How it works:**
  - HTTP requests (REST API) → forwards to Django API (port 8000)
  - WebSocket requests (`ws://`) → forwards to Daphne WebSocket server (port 8001)
  - Rate limiting: Blocks users who send too many requests (prevents abuse)
  - Example: If a user sends 100+ requests per second, Nginx blocks them before they even reach Django
- **Port:** 80

---

## LAYER 2: APPLICATION (2 containers)

### 2. API (`api`) — Django REST Framework
- **What it does:** The main brain. Handles all REST API requests.
- **How it works:**
  1. User sends POST `/api/v1/notifications/` with title, body, recipient
  2. Django validates the data
  3. Saves notification to PostgreSQL database
  4. Sends a task to RabbitMQ saying "hey, deliver this notification"
  5. Returns response to user immediately (doesn't wait for delivery)
- **Key endpoints:**
  - `POST /api/v1/notifications/` — Create notification
  - `GET /api/v1/notifications/` — List user's notifications
  - `POST /api/v1/notifications/bulk/` — Send to many users at once
  - `POST /api/v1/notifications/mark-all-read/` — Mark all as read
  - `GET /api/v1/health/` — Health check
- **Port:** 8000

### 3. WebSocket Server (`ws`) — Daphne/ASGI
- **What it does:** Handles real-time WebSocket connections for instant notifications.
- **How it works:**
  1. User's browser/app opens a WebSocket connection: `ws://localhost/ws/notifications/`
  2. Server keeps this connection alive
  3. When a new notification is created, the in-app worker pushes it through Redis Channels
  4. Daphne receives it and instantly sends it to the connected user
  5. No polling needed — user gets notifications in real-time
- **Also handles:**
  - `mark_read` — User marks a notification as read via WebSocket
  - `mark_all_read` — User marks all as read
  - Sends unread count updates automatically
- **Port:** 8001

---

## LAYER 3: CELERY WORKERS (5 containers)

### 4. Email Worker (`email-worker`)
- **What it does:** Sends email notifications via SendGrid or Amazon SES.
- **How it works:**
  1. Picks up "send_email" tasks from `email_queue` in RabbitMQ
  2. Tries SendGrid first → if SendGrid is down, automatically tries Amazon SES (failover)
  3. Has a **Circuit Breaker**: If SendGrid fails 5 times in a row, it stops trying for 60 seconds (prevents hammering a dead service)
  4. If email fails, it retries up to 5 times with increasing delays (retry backoff)
  5. Updates the delivery record in PostgreSQL: "sent" or "failed"
- **Concurrency:** 4 parallel workers

### 5. Push Worker (`push-worker`)
- **What it does:** Sends mobile push notifications via Firebase Cloud Messaging (FCM).
- **How it works:**
  1. Picks up "send_push" tasks from `push_queue` in RabbitMQ
  2. Finds user's registered devices (phone/tablet) from FCMDevice table
  3. Sends push notification to all user's devices
  4. Same Circuit Breaker + retry logic as email worker
  5. If a device token is invalid (user uninstalled app), marks it as permanent failure — no retry
- **Concurrency:** 4 parallel workers

### 6. In-App Worker (`inapp-worker`)
- **What it does:** Delivers real-time in-app notifications via WebSocket.
- **How it works:**
  1. Picks up "send_inapp" tasks from `inapp_queue` in RabbitMQ
  2. Sends notification data to Redis Channels (pub/sub)
  3. Redis Channels broadcasts it to the Daphne WebSocket server
  4. Daphne pushes it to the user's open WebSocket connection
  5. Also sends updated "unread count" so the UI can show badge (like "3 new notifications")
- **Concurrency:** 2 parallel workers

### 7. Fan-Out Worker (`fanout-worker`)
- **What it does:** Handles bulk notifications (sending to thousands of users at once).
- **How it works:**
  1. When someone sends a bulk notification to 50,000 users
  2. Fan-out worker splits them into batches of 1,000
  3. Each batch is processed separately with a 2-second stagger (prevents system overload)
  4. Each batch creates individual notifications and enqueues them to email/push/inapp workers
  5. So: 50,000 users → 50 batches → each batch creates 1,000 notifications → workers deliver them
- **Concurrency:** 2 parallel workers

### 8. Celery Beat (`celery-beat`)
- **What it does:** The "scheduler" — runs periodic tasks on a schedule (like a cron job).
- **Scheduled tasks:**
  | Task | Schedule | What it does |
  |------|----------|-------------|
  | `process_dlq` | Every 5 min | Re-tries failed notifications from Dead Letter Queue |
  | `send_digests` | Daily 8 AM | Sends daily digest emails to users who prefer digest mode |
  | `cleanup_old` | Daily 3 AM | Deletes expired + old read notifications (90+ days) |
  | `cleanup_fcm_tokens` | Daily 4 AM | Deactivates inactive device tokens (30+ days) |
  | `publish_metrics` | Every 30 sec | Publishes delivery metrics for Prometheus monitoring |

---

## LAYER 4: MESSAGE BROKER (3 containers)

### 9, 10, 11. RabbitMQ Cluster (`rabbitmq-1`, `rabbitmq-2`, `rabbitmq-3`)
- **What it does:** The "post office" — holds all tasks/jobs in queues until workers pick them up.
- **Why 3 nodes?** High availability — if one node crashes, the other 2 keep working. Uses "quorum queues" which replicate messages across all 3 nodes.
- **Queues:**
  | Queue | Purpose | Max Size |
  |-------|---------|----------|
  | `email_queue` | Email delivery tasks | 100,000 |
  | `push_queue` | Push delivery tasks | 100,000 |
  | `inapp_queue` | In-app delivery tasks | 50,000 |
  | `bulk_queue` | Bulk fan-out tasks | 200,000 |
  | `dead_email/push/inapp/bulk` | Failed tasks (Dead Letter Queues) | Unlimited |
- **Dead Letter Queue (DLQ):** When a task fails too many times, it moves to DLQ for later retry via Celery Beat.
- **Port:** 5672 (AMQP), 15672 (Management UI)

---

## LAYER 5: DATABASE (3 containers)

### 12. PostgreSQL Primary (`postgres-primary`)
- **What it does:** The main database — stores ALL data (notifications, users, delivery records, preferences).
- **Handles:** All WRITE operations (INSERT, UPDATE, DELETE)
- **Tables:**
  - `notifications` — All notifications (UUID, title, body, recipient, read status)
  - `notification_types` — Types like "order_update", "promotion" with channel config
  - `notification_deliveries` — Delivery tracking per channel (status, attempts, errors)
  - `notification_preferences` — User preferences (email on/off, quiet hours, digest mode)
  - `notification_analytics` — Delivery events (delivered, opened, clicked)
  - `fcm_django_fcmdevice` — Registered mobile devices for push notifications
- **Port:** 5432

### 13. PostgreSQL Replica (`postgres-replica`)
- **What it does:** A read-only copy of the primary database.
- **How it works:**
  - Uses PostgreSQL Streaming Replication — every change on primary is instantly streamed to replica
  - All READ queries (list notifications, get unread count) go to replica
  - This reduces load on primary so it can focus on writes
  - Django's `PrimaryReplicaRouter` automatically routes: writes → primary, reads → replica
- **Port:** 5433

### 14. PgBouncer (`pgbouncer`)
- **What it does:** Connection pooler — sits between Django and PostgreSQL.
- **Why needed:**
  - PostgreSQL can handle ~500 connections max. With multiple workers + API servers, you'd easily exceed this.
  - PgBouncer maintains a pool of 50 connections and shares them among all Django instances
  - Uses "transaction mode" — connection is returned to pool after each transaction
  - Django connects to PgBouncer (port 6432), PgBouncer connects to PostgreSQL (port 5432)
- **Port:** 6432

---

## LAYER 6: REDIS (3 containers)

### 15. Redis Channels (`redis-channels`)
- **What it does:** Pub/Sub messaging for real-time WebSocket notifications.
- **How it works:**
  - When in-app worker sends a notification, it publishes to a Redis channel: `notifications_{user_id}`
  - Daphne WebSocket server subscribes to these channels
  - Redis instantly broadcasts the message to all subscribers
  - This is what makes WebSocket notifications real-time
- **Port:** 6380

### 16. Redis Celery (`redis-celery`)
- **What it does:** Two purposes:
  1. **Celery Result Backend** — stores task results (success/failure) so you can check task status
  2. **Idempotency Store** — Redis SET NX to prevent duplicate notifications (if same request is sent twice within 24 hours, the second one is rejected)
- **Port:** 6382

### 17. Redis Cache (`redis-cache`)
- **What it does:** Application cache for frequently accessed data.
- **What it caches:**
  - User notification preferences (avoids DB query every time)
  - Unread counts
  - Session data
  - Idempotency keys (24-hour TTL)
- **Port:** 6381

---

## LAYER 7: MONITORING & OBSERVABILITY (9 containers)

### 18. Prometheus (`prometheus`)
- **What it does:** Collects metrics from all services every 15 seconds.
- **What it monitors:** Request rates, response times, error rates, queue depths, Redis memory, etc.
- **Port:** 9090

### 19. Grafana (`grafana`)
- **What it does:** Beautiful dashboards to visualize Prometheus metrics.
- **Pre-built dashboard:** Shows notification delivery rates, failure rates, queue depths, latency
- **Port:** 3000 (login: admin/admin)

### 20, 21, 22. Redis Exporters (`redis-exporter-cache`, `redis-exporter-celery`, `redis-exporter-channels`)
- **What they do:** Convert Redis metrics into Prometheus format so Prometheus can scrape them.
- Each exporter monitors one Redis instance.

### 23. Elasticsearch (`elasticsearch`)
- **What it does:** Stores and indexes all application logs for searching.
- **Why not just files?** With 26 containers generating logs, you need a central place to search across all of them.
- **Port:** 9200

### 24. Logstash (`logstash`)
- **What it does:** Log pipeline — receives JSON logs from containers, processes them, and sends to Elasticsearch.
- **Port:** 5044

### 25. Kibana (`kibana`)
- **What it does:** Web UI for searching and visualizing logs stored in Elasticsearch.
- **Use case:** "Show me all failed email deliveries in the last hour" — Kibana can answer this
- **Port:** 5601

### 26. Jaeger (`jaeger`)
- **What it does:** Distributed tracing — tracks a single request as it flows through multiple services.
- **Example trace:** API receives request → creates notification → enqueues to RabbitMQ → worker picks up → sends email → marks as delivered. Jaeger shows the entire journey with timing for each step.
- **Port:** 16686

---

## How Everything Works Together — Complete Flow

```
                                    ┌─────────────────────────────────────────┐
                                    │         MONITORING LAYER                │
                                    │  Prometheus → Grafana (Dashboards)      │
                                    │  ELK Stack (Logs): ES → Logstash → Kibana│
                                    │  Jaeger (Distributed Tracing)           │
                                    │  Redis Exporters (3x)                   │
                                    └─────────────────────────────────────────┘
                                                    ▲ scrapes metrics
                                                    │
    ┌──────────┐     ┌──────────┐     ┌─────────────────────────────┐
    │  Client   │────▶│  Nginx   │────▶│  Django API   │  Daphne WS │
    │ (Browser/ │     │ (Port 80)│     │  (Port 8000)  │ (Port 8001)│
    │  Mobile)  │     └──────────┘     └───────┬───────┴─────┬──────┘
    └──────────┘                               │             │
                                               ▼             ▼
                              ┌─────────────────────┐  ┌──────────────┐
                              │     RabbitMQ         │  │ Redis        │
                              │  (3-node cluster)    │  │ Channels     │
                              │                      │  │ (pub/sub)    │
                              │  email_queue ────────┤  └──────┬───────┘
                              │  push_queue  ────────┤         │
                              │  inapp_queue ────────┤         │ real-time
                              │  bulk_queue  ────────┤         │ push
                              │  dead_letter ────────┤         ▼
                              └──────┬───────────────┘  ┌──────────────┐
                                     │                  │   Daphne WS  │──▶ User
                                     ▼                  └──────────────┘
                    ┌────────────────────────────────┐
                    │        CELERY WORKERS           │
                    │                                 │
                    │  email-worker ──▶ SendGrid/SES  │
                    │  push-worker  ──▶ Firebase FCM  │
                    │  inapp-worker ──▶ Redis Channels│
                    │  fanout-worker ──▶ Batch split  │
                    │  celery-beat  ──▶ Scheduled jobs│
                    └────────┬───────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │         DATA LAYER            │
              │                               │
              │  PgBouncer (connection pool)   │
              │       ▼              ▼        │
              │  PG Primary     PG Replica    │
              │  (writes)       (reads)       │
              │                               │
              │  Redis Cache (preferences)    │
              │  Redis Celery (task results)  │
              └──────────────────────────────┘
```

---

## Database Design — All Tables Explained

### Overview

PostgreSQL 16 with **6 core tables**. All tables use UUID primary keys (except `notification_types` which uses auto-increment). Data is split — writes go to primary, reads go to replica — with PgBouncer for connection pooling.

```
auth_user (Django built-in)
    │
    ├──< notifications (1:N) ── notification_types (N:1)
    │       │
    │       ├──< notification_deliveries (1:N)
    │       └──< notification_analytics (1:N)
    │
    ├──── notification_preferences (1:1)
    └──< fcm_django_fcmdevice (1:N)
```

---

### Table 1: `notification_types`

**Purpose:** Defines notification categories — which channels a notification is sent to and its priority.

| Field | Type | Description |
|-------|------|-------------|
| `id` | Auto-increment PK | Auto-generated primary key |
| `name` | VARCHAR (UNIQUE) | Type name like `order_update`, `promotion`, `security_alert` |
| `template` | TEXT | Message template (optional, for email body etc.) |
| `channels` | PostgreSQL Array (`text[]`) | Which channels to use — `{email, push, inapp}` |
| `priority` | INTEGER (1-10) | 1 = highest, 10 = lowest — workers process higher priority first |

**Example row:**
```
name: "order_update"
channels: {email, push, inapp}    ← sent on all three channels
priority: 1                        ← highest priority, delivered first
```

---

### Table 2: `notifications`

**Purpose:** Stores every notification created in the system. This is the **main table**.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Unique notification ID |
| `idempotency_key` | VARCHAR (UNIQUE, nullable) | Duplicate prevention key — second request with same key is rejected |
| `recipient_id` | FK → `auth_user` | Who receives the notification |
| `type_id` | FK → `notification_types` | Which notification type this belongs to |
| `title` | VARCHAR | Notification title (e.g., "Order Shipped!") |
| `body` | TEXT | Notification body/message |
| `metadata` | JSONB | Extra data — order ID, tracking URL, etc. Flexible field for any additional info |
| `is_read` | BOOLEAN (default FALSE) | Whether the user has read the notification |
| `read_at` | TIMESTAMP (nullable) | When it was read — NULL if unread |
| `created_at` | TIMESTAMP | When the notification was created |
| `expires_at` | TIMESTAMP (nullable) | When it expires — cleanup task deletes old expired notifications |

**Indexes:**

| Index Name | What it does |
|------------|-------------|
| `idx_notif_user_unread` | Partial index: `WHERE is_read = FALSE` — quickly fetches unread notifications, skips read ones |
| `idx_notif_expires` | Partial index: `WHERE expires_at IS NOT NULL` — helps cleanup task find expired notifications quickly |

---

### Table 3: `notification_deliveries`

**Purpose:** Per-channel delivery tracking. If a notification goes to 3 channels (email + push + inapp), **3 separate delivery records** are created. Each is tracked independently.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Unique delivery ID |
| `notification_id` | FK → `notifications` | Which notification this delivery belongs to |
| `channel` | VARCHAR | `email` / `push` / `inapp` |
| `status` | VARCHAR | `pending` → `sent` → `delivered` OR `failed` / `bounced` |
| `provider_id` | VARCHAR (nullable) | SendGrid message ID, FCM message ID — provider's tracking ID |
| `attempts` | INTEGER (default 0) | Number of delivery attempts — gives up after max 5 |
| `last_attempt_at` | TIMESTAMP (nullable) | When the last attempt was made |
| `error_message` | TEXT (nullable) | Error message on failure (for debugging) |
| `created_at` | TIMESTAMP | When the delivery record was created |

**Unique Constraint:** `(notification_id, channel)` — a notification can only be delivered once per channel. Prevents duplicate delivery.

**Index:**

| Index Name | What it does |
|------------|-------------|
| `idx_delivery_status` | Partial index: `WHERE status IN ('pending', 'failed')` — helps retry workers quickly find pending/failed deliveries. Skips already delivered records. |

---

### Table 4: `notification_preferences`

**Purpose:** Per-user notification settings — which channels are enabled, quiet hours configuration, and digest mode preference.

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | PK, FK → `auth_user` (OneToOne) | One user = one preferences record |
| `email_enabled` | BOOLEAN (default TRUE) | Email notifications on/off |
| `push_enabled` | BOOLEAN (default TRUE) | Push notifications on/off |
| `inapp_enabled` | BOOLEAN (default TRUE) | In-app notifications on/off |
| `quiet_hours_start` | TIME (nullable) | Quiet hours start — notifications are held after this time |
| `quiet_hours_end` | TIME (nullable) | Quiet hours end — held notifications are delivered after this time |
| `digest_mode` | VARCHAR | `instant` (default) / `hourly` / `daily` — instant delivers immediately, daily sends in 8 AM digest email |
| `channel_overrides` | JSONB (nullable) | Per-type overrides — e.g., `{"promotion": {"email": false}}` disables email for promotions |

---

### Table 5: `notification_analytics`

**Purpose:** Tracks engagement events — delivered, opened, clicked. Used for delivery metrics and analytics.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID (PK) | Unique analytics event ID |
| `notification_id` | FK → `notifications` | Which notification this event belongs to |
| `event_type` | VARCHAR | `delivered` / `opened` / `clicked` |
| `channel` | VARCHAR | Which channel the event occurred on |
| `metadata` | JSONB | Extra data — click URL, device info, etc. |
| `created_at` | TIMESTAMP | Event kyare thayu |

**Indexes:**

| Index | What it does |
|-------|-------------|
| `(notification_id, event_type)` | Quickly fetch specific events for a notification |
| `(created_at)` | For time-based analytics queries — e.g., "open rates in last 7 days" |

---

### Table 6: `fcm_django_fcmdevice` (provided by `fcm-django` package)

**Purpose:** Stores mobile device tokens for sending push notifications. This table is provided by the `fcm-django` third-party package.

| Field | Type | Description |
|-------|------|-------------|
| `id` | Auto PK | Device record ID |
| `user_id` | FK → `auth_user` | Which user owns this device |
| `registration_id` | VARCHAR | Device token — Firebase/APNs token used to send push notifications |
| `type` | VARCHAR | `ios` / `android` / `web` |
| `active` | BOOLEAN (default TRUE) | Whether device is active — set to `FALSE` when token becomes invalid |
| `date_created` | TIMESTAMP | When the device was registered |

---

### ER Diagram (Entity Relationships)

```
┌──────────────┐
│  auth_user   │
│ (Django)     │
└──────┬───────┘
       │
       ├──────────────────── 1:1 ────── notification_preferences
       │
       ├──────────────────── 1:N ────── fcm_django_fcmdevice
       │                                (user's multiple devices)
       │
       ├──────────────────── 1:N ────── notifications
       │                                    │
       │                notification_types ──┘ (N:1)
       │                (type defines channels/priority)
       │                                    │
       │                                    ├── 1:N ── notification_deliveries
       │                                    │          (per-channel delivery tracking)
       │                                    │
       │                                    └── 1:N ── notification_analytics
       │                                               (engagement events)
       │
```

---

### Read/Write Split — `PrimaryReplicaRouter`

Django uses a custom database router — `PrimaryReplicaRouter` — that automatically routes queries:

```
                    ┌─────────────────┐
                    │   Django ORM    │
                    │   Query         │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ PrimaryReplica  │
                    │    Router       │
                    └───┬─────────┬───┘
                        │         │
              WRITES    │         │   READS
              (INSERT,  │         │   (SELECT)
              UPDATE,   │         │
              DELETE)   │         │
                        ▼         ▼
              ┌──────────┐  ┌──────────┐
              │ postgres  │  │ postgres │
              │ primary   │  │ replica  │
              │ (5432)    │  │ (5433)   │
              └──────────┘  └──────────┘
```

**Rules:**
- **ALL writes** (INSERT, UPDATE, DELETE) → `postgres-primary`
- **ALL reads** (SELECT) → `postgres-replica`
- **Exception:** `auth`, `admin`, `sessions`, `contenttypes` tables → **always primary** (authentication data must always be fresh)

---

### Indexing Strategy

Carefully designed indexes — only where needed, no unnecessary indexes (which slow down writes):

| Index | Purpose | Type | Why |
|-------|---------|------|-----|
| `idx_notif_user_unread` | Fetch unread notifications per user | Partial (`WHERE is_read = FALSE`) | 90% notifications are eventually read — partial index keeps size small |
| `idempotency_key` UNIQUE | Duplicate notification prevention | Unique constraint | Prevents same notification from being created twice — DB level guarantee |
| `idx_delivery_status` | Find pending/failed deliveries for retry | Partial (`WHERE status IN ('pending', 'failed')`) | No need to search already delivered records — only pending/failed needed |
| `idx_notif_expires` | Cleanup expired notifications | Partial (`WHERE expires_at IS NOT NULL`) | Most notifications don't expire — only index expirable ones |
| `(notification_id, channel)` | One delivery record per channel | Unique constraint | Prevents duplicate delivery on same channel — DB level protection |
| `(notification_id, event_type)` | Analytics event lookup | Composite | Quickly fetch events for a specific notification |
| `(created_at)` on analytics | Time-range analytics queries | B-tree | Makes queries like "open rates in last 7 days" fast |

---

### Duplicate Prevention — 3-Layer Protection

**3 layers** to prevent duplicate notifications. If one layer fails, the next layer catches it:

```
Request arrives with X-Idempotency-Key header
        │
        ▼
┌─────────────────────────────────────┐
│  LAYER 1: Redis SET NX              │
│  cache.add(idemp_key, TTL=24h)      │
│                                     │
│  Checks Redis — if key exists,      │
│  REJECT (it's a duplicate!)         │
│  If new key, SET it and proceed     │
└──────────────┬──────────────────────┘
               │ (Key not in Redis — new request)
               ▼
┌─────────────────────────────────────┐
│  LAYER 2: DB UNIQUE Constraint      │
│  idempotency_key column (UNIQUE)    │
│                                     │
│  If Redis is down or race condition │
│  occurs (2 requests in same ms),    │
│  DB UNIQUE constraint catches it    │
│  → IntegrityError → REJECT          │
└──────────────┬──────────────────────┘
               │ (Not in DB either — definitely new)
               ▼
┌─────────────────────────────────────┐
│  LAYER 3: Delivery Unique Constraint│
│  (notification_id, channel) UNIQUE  │
│                                     │
│  Even if notification was created,  │
│  this constraint prevents duplicate │
│  delivery on the same channel       │
└─────────────────────────────────────┘
```

---

## Quick Access URLs (when containers are running)

| Service | URL | Purpose |
|---------|-----|---------|
| Django API | http://localhost:8000/api/v1/ | REST API |
| Health Check | http://localhost:8000/api/v1/health/ | System health |
| RabbitMQ UI | http://localhost:15672 | Queue monitoring (guest/guest) |
| Grafana | http://localhost:3000 | Dashboards (admin/admin) |
| Prometheus | http://localhost:9090 | Raw metrics |
| Kibana | http://localhost:5601 | Log search |
| Jaeger | http://localhost:16686 | Request tracing |
