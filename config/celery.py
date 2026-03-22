import os

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(["apps.notifications"], related_name="tasks_bulk")
app.autodiscover_tasks(["apps.notifications"], related_name="tasks_periodic")

default_exchange = Exchange("default", type="direct")
notification_exchange = Exchange("notifications", type="direct")
bulk_exchange = Exchange("bulk", type="direct")
dlx_exchange = Exchange("dlx", type="direct")

app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue(
        "email_queue",
        notification_exchange,
        routing_key="email",
        queue_arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": "dead_email",
            "x-max-length": 100000,
            "x-overflow": "reject-publish",
            "x-queue-type": "quorum",  # Durable quorum queue
        },
    ),
    Queue(
        "push_queue",
        notification_exchange,
        routing_key="push",
        queue_arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": "dead_push",
            "x-max-length": 100000,
            "x-overflow": "reject-publish",
            "x-queue-type": "quorum",
        },
    ),
    Queue(
        "inapp_queue",
        notification_exchange,
        routing_key="inapp",
        queue_arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": "dead_inapp",
            "x-max-length": 50000,
            "x-overflow": "reject-publish",
            "x-queue-type": "quorum",
        },
    ),
    Queue(
        "bulk_queue",
        bulk_exchange,
        routing_key="bulk",
        queue_arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": "dead_bulk",
            "x-max-length": 200000,
            "x-overflow": "reject-publish",
            "x-queue-type": "quorum",
        },
    ),
    # Dead Letter Queues
    Queue("dead_email", dlx_exchange, routing_key="dead_email"),
    Queue("dead_push", dlx_exchange, routing_key="dead_push"),
    Queue("dead_inapp", dlx_exchange, routing_key="dead_inapp"),
    Queue("dead_bulk", dlx_exchange, routing_key="dead_bulk"),
)

# ── Task routing ──
app.conf.task_routes = {
    "apps.notifications.tasks.send_email": {
        "queue": "email_queue",
        "routing_key": "email",
    },
    "apps.notifications.tasks.send_push": {
        "queue": "push_queue",
        "routing_key": "push",
    },
    "apps.notifications.tasks.send_inapp": {
        "queue": "inapp_queue",
        "routing_key": "inapp",
    },
    "apps.notifications.tasks_bulk.fan_out_bulk_notifications": {
        "queue": "bulk_queue",
        "routing_key": "bulk",
    },
    "apps.notifications.tasks_bulk.process_batch": {
        "queue": "bulk_queue",
        "routing_key": "bulk",
    },
}

app.conf.task_default_queue = "default"
app.conf.task_default_exchange = "default"
app.conf.task_default_routing_key = "default"

# ── Celery Beat Schedule ──
app.conf.beat_schedule = {
    "process-dead-letter-queue": {
        "task": "apps.notifications.tasks_periodic.process_dlq",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
    "send-digest-emails": {
        "task": "apps.notifications.tasks_periodic.send_digests",
        "schedule": crontab(hour=8, minute=0),  # Daily at 8 AM
    },
    "cleanup-old-notifications": {
        "task": "apps.notifications.tasks_periodic.cleanup_old",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    "cleanup-inactive-fcm-tokens": {
        "task": "apps.notifications.tasks_periodic.cleanup_fcm_tokens",
        "schedule": crontab(hour=4, minute=0),  # Daily at 4 AM
    },
    "publish-queue-metrics": {
        "task": "apps.notifications.tasks_periodic.publish_metrics",
        "schedule": 30.0,  # Every 30 seconds
    },
}
