# System Flow & Testing Guide

## Test Environment Setup

```
Users:
  admin      → Token: 7ae400a0add430a747ca63b4563788c4f977374c
  testuser1  → Token: 7933610402f7790bd902f277c8b3bf5ac3663c8c
  testuser2  → Token: ecec740ef1e9521ee020fd2ac701711c78c216a6
  testuser3  → Token: 0898fe9e0577271ea8ed4aa52b9ad5a8a585027a
  testuser4  → Token: 00984155b842b3fbd1a9559848740fd6f4f23e53
  testuser5  → Token: 8cfacb81ff1404aff4e94f3b79fbf6e43440a9f0

Notification Types:
  1. order_update  → [email, push, inapp]  priority: 1
  2. promotion     → [email, inapp]         priority: 5
  3. system_alert  → [email, push, inapp]  priority: 1
  4. chat_message  → [push, inapp]          priority: 2
  5. weekly_digest → [email]                priority: 8
```

---

## FLOW 1: Single Notification

### Request
```bash
curl -X POST http://localhost:8000/api/v1/notifications/ \
  -H "Authorization: Token 7ae400a0add430a747ca63b4563788c4f977374c" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-single-001" \
  -d '{
    "recipient": 2,
    "type": 1,
    "title": "Order #1234 Shipped",
    "body": "Your order has been shipped and will arrive in 2-3 days.",
    "metadata": {"order_id": "1234", "tracking": "TRK001"}
  }'
```

### Internal Flow
```
Client → Nginx (80) → Django API (8000)
  1. Nginx checks rate limit → forwards to Django
  2. Django authenticates token → validates data
  3. Idempotency check: Redis SET NX → DB UNIQUE constraint
  4. Creates notification in PostgreSQL
  5. Checks user preferences (which channels are enabled)
  6. Checks quiet hours (delay if active)
  7. Creates delivery records (pending) for each channel
  8. Enqueues Celery tasks → RabbitMQ (email_queue, push_queue, inapp_queue)
  9. Returns HTTP 201 immediately (delivery happens in background)
```

### Response
```json
HTTP 201 Created
{
  "id": "6d84962d-5d1e-4889-878a-67b97fce97e3",
  "title": "Order #1234 Shipped",
  "deliveries": [
    {"channel": "email", "status": "pending"},
    {"channel": "push",  "status": "pending"},
    {"channel": "inapp", "status": "pending"}
  ]
}
```

### Background Worker Processing

| Worker | Time | What Happens |
|--------|------|-------------|
| **In-App** | ~0.5s | Sends via Redis Channels → Daphne → user's WebSocket. Status: `sent` |
| **Push** | ~0.5s | Queries FCM devices → no devices registered → permanent failure, no retry. Status: `failed` |
| **Email** | ~1-2s | Tries SendGrid → fails → tries SES → fails → retries up to 5 times with backoff. Status: `pending` (retrying) |

---

## FLOW 2: User Preferences

### Set Preferences
```bash
curl -X PUT http://localhost:8000/api/v1/preferences/ \
  -H "Authorization: Token 7933610402f7790bd902f277c8b3bf5ac3663c8c" \
  -H "Content-Type: application/json" \
  -d '{
    "email_enabled": true,
    "push_enabled": false,
    "inapp_enabled": true,
    "quiet_hours_start": "22:00:00",
    "quiet_hours_end": "07:00:00",
    "digest_mode": "daily"
  }'
```

### Effect on Notifications
```
Channel filtering (type=order_update, channels=[email, push, inapp]):
  email → enabled  → INCLUDE
  push  → disabled → SKIP
  inapp → enabled  → INCLUDE
  Result: Only email + inapp deliveries created

Quiet hours (22:00 - 07:00):
  If current time is within quiet hours → tasks scheduled at 07:01 instead of immediate
  Uses Celery apply_async(eta=...) for delayed delivery
```

---

## FLOW 3: Bulk Notifications

### Request
```bash
curl -X POST http://localhost:8000/api/v1/notifications/bulk/ \
  -H "Authorization: Token 7ae400a0add430a747ca63b4563788c4f977374c" \
  -H "Content-Type: application/json" \
  -d '{
    "type": 3,
    "title": "System Maintenance Alert",
    "body": "Scheduled maintenance on March 25 from 2-4 AM UTC.",
    "recipient_ids": [2, 3, 4, 5, 6]
  }'
```

### Response
```json
HTTP 202 Accepted
{
  "status": "accepted",
  "task_id": "c4856652-cf87-4765-9226-c5a3e69994d7",
  "message": "Bulk notification queued for 5 recipients"
}
```

### Background Processing
```
1. Fan-out worker picks up task from bulk_queue
2. Splits recipients into batches (1000/batch, 2s stagger between batches)
3. Each batch: creates notifications → checks preferences → enqueues delivery tasks
4. Individual workers (email/push/inapp) process each notification
```

---

## FLOW 4: Failure Handling

### Retry Chain
```
Task fails → Celery retries (5 attempts, exponential backoff)
  → All retries exhausted → Dead Letter Queue (RabbitMQ)
  → Every 5 min, Celery Beat re-enqueues from DLQ (up to 10 total attempts)
  → 10 attempts exhausted → permanently marked as failed
```

### Failure Diagram
```
Send Email Task
     │
     ▼
Try SendGrid ──OK──▶ DELIVERED ✅
     │ Fail
     ▼
Try SES ──OK──▶ DELIVERED ✅
     │ Fail
     ▼
Celery Retry (5x with backoff: ~2s, ~4s, ~8s, ~16s, ~32s)
     │ All retries exhausted
     ▼
Dead Letter Queue → DLQ Processor re-enqueues (up to 10 total)
     │ 10 attempts exhausted
     ▼
FAILED ❌
```

### Circuit Breaker (pybreaker)
```
CLOSED (normal) → 5 consecutive failures → OPEN (blocks all requests for 60s)
  → After 60s → HALF-OPEN (allows 1 test request)
  → Success → CLOSED | Failure → OPEN again
```

### Permanent vs Transient Failures

| Type | Examples | Action |
|------|----------|--------|
| **Permanent** (no retry) | No FCM devices, invalid token, bad email address | Mark as failed immediately |
| **Transient** (retry) | Provider timeout, network error, rate limit, 500 error | Retry with backoff |

---

## FLOW 5: WebSocket Real-Time

```
1. Client connects: ws://localhost/ws/notifications/?token=<auth_token>
2. Server authenticates → user joins group "notifications_{user_id}"
3. Server sends current unread count

On new notification:
4. In-app worker → Redis Channels → Daphne → user's WebSocket
5. Sends: {"type": "new_notification", "id": "...", "title": "...", "body": "..."}
6. Sends: {"type": "unread_count", "count": 4}

Client can send:
  {"type": "mark_read", "notification_id": "uuid"}
  {"type": "mark_all_read"}
```

---

## FLOW 6: Idempotency (Duplicate Prevention)

```
Request with "Idempotency-Key: order-123-shipped" header
  → Layer 1: Redis SET NX (fast check, 24h TTL)
  → Layer 2: DB UNIQUE constraint (catches race conditions)
  → Result: Same key sent twice → returns existing notification (200 instead of 201)
```

---

## Test Results

| # | Test | Result |
|---|------|--------|
| 1 | Health check (`GET /api/v1/health/`) | ✅ `{"status": "ok"}` |
| 2 | Create single notification (3 channels) | ✅ Created with email + push + inapp deliveries |
| 3 | In-app delivery (WebSocket) | ✅ Delivered instantly via Redis Channels |
| 4 | Push failure (no devices) | ✅ Permanent failure, no retry |
| 5 | Email retry (no API keys) | ✅ SendGrid → SES failover, then Celery retry |
| 6 | Idempotency (duplicate request) | ✅ Redis prevents duplicate |
| 7 | List notifications (cursor pagination) | ✅ Paginated results with deliveries |
| 8 | Unread count | ✅ Accurate count |
| 9 | Mark single as read | ✅ `is_read=true`, `read_at` set |
| 10 | Mark all as read | ✅ `{"marked_read": 2}` |
| 11 | User preferences (disable push) | ✅ Push channel skipped |
| 12 | Quiet hours (22:00-07:00) | ✅ Tasks scheduled at 07:01 |
| 13 | Bulk notification (5 users) | ✅ Fan-out processed 5/5 |
| 14 | Promotion type (email + inapp only) | ✅ No push delivery created |
| 15 | Analytics tracking | ✅ 9 events recorded |
| 16 | XSS sanitization | ✅ `<script>` tags stripped |
| 17 | Metadata must be dict | ✅ String/array rejected |
| 18 | expires_at in the past | ✅ Rejected |
| 19 | Quiet hours paired validation | ✅ Must be set together or both null |
| 20 | Invalid JSON body | ✅ Parse error returned |
| 21 | Missing required fields | ✅ Lists all required fields |
| 22 | Wrong data types | ✅ Type error returned |
| 23 | Other user's notification access | ✅ 404 (user isolation) |
| 24 | Wrong HTTP method / Content-Type | ✅ 405 / 415 |

### Database State After Testing
```
Notifications: 9  |  Deliveries: 24  |  Analytics Events: 9

Delivery Status:  sent: 3 (inapp)  |  pending: 15 (email retrying)  |  failed: 6 (push, no devices)

Per User:
  testuser1: 5 notifications (3 read, 2 unread)
  testuser2-5: 1 notification each (unread)
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health/` | Health check (no auth) |
| POST | `/api/v1/notifications/` | Create notification |
| GET | `/api/v1/notifications/` | List notifications (paginated) |
| GET | `/api/v1/notifications/{id}/` | Get single notification |
| PATCH | `/api/v1/notifications/{id}/read/` | Mark as read |
| PATCH | `/api/v1/notifications/mark-all-read/` | Mark all as read |
| GET | `/api/v1/notifications/unread-count/` | Get unread count |
| POST | `/api/v1/notifications/bulk/` | Bulk notification |
| GET | `/api/v1/preferences/` | Get preferences |
| PUT | `/api/v1/preferences/` | Update preferences |
| POST | `/api/v1/devices/` | Register FCM device |
| GET | `/api/v1/devices/` | List devices |
| DELETE | `/api/v1/devices/{id}/` | Unregister device |
| GET | `/api/v1/analytics/` | View analytics |
| WS | `ws://localhost/ws/notifications/` | WebSocket connection |
