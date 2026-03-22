import logging
from itertools import islice

from celery import shared_task
from django.contrib.auth import get_user_model

from django.conf import settings

from .models import NotificationDelivery, NotificationPreference, NotificationType
from .services import NotificationService

logger = logging.getLogger(__name__)

User = get_user_model()


@shared_task(
    bind=True,
    name="apps.notifications.tasks_bulk.fan_out_bulk_notifications",
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
)
def fan_out_bulk_notifications(self, validated_data):
    """
    Fan-out bulk notifications in batches of 1000.
    Each batch creates notifications and enqueues delivery tasks.
    """
    recipient_ids = validated_data["recipient_ids"]
    type_id = validated_data.get("type_id") or validated_data.get("type")
    if isinstance(type_id, dict):
        type_id = type_id.get("id")
        if type_id is None:
            logger.error("Bulk notification: type_id could not be extracted from dict")
            return {"status": "failed", "error": "invalid type_id format"}

    title = validated_data["title"]
    body = validated_data.get("body", "")
    metadata = validated_data.get("metadata", {})

    try:
        notification_type = NotificationType.objects.get(id=type_id)
    except NotificationType.DoesNotExist:
        logger.error("Bulk notification: type_id=%s not found", type_id)
        return {"status": "failed", "error": "notification type not found"}

    total = len(recipient_ids)
    processed = 0
    failed = 0

    # Process in batches
    it = iter(recipient_ids)
    batch_num = 0

    while True:
        batch = list(islice(it, settings.BULK_BATCH_SIZE))
        if not batch:
            break

        batch_num += 1
        logger.info(
            "Processing bulk batch %d (%d recipients)", batch_num, len(batch)
        )

        # Stagger batches to avoid spike
        if batch_num > 1:
            _process_batch.apply_async(
                args=[batch, notification_type.id, title, body, metadata],
                countdown=(batch_num - 1) * 2,  # 2s stagger between batches
            )
        else:
            _process_batch.delay(
                batch, notification_type.id, title, body, metadata
            )

        processed += len(batch)

    logger.info(
        "Bulk fan-out complete: total=%d, batches=%d", total, batch_num
    )
    return {
        "status": "completed",
        "total_recipients": total,
        "batches": batch_num,
    }


@shared_task(
    bind=True,
    name="apps.notifications.tasks_bulk.process_batch",
    max_retries=3,
    retry_backoff=True,
    acks_late=True,
)
def _process_batch(self, recipient_ids, type_id, title, body, metadata):
    """Process a single batch of bulk notifications."""
    notification_type = NotificationType.objects.get(id=type_id)
    users = User.objects.filter(id__in=recipient_ids)

    created = 0
    for user in users:
        try:
            NotificationService.create_notification({
                "recipient": user,
                "type": notification_type,
                "title": title,
                "body": body,
                "metadata": metadata,
            })
            created += 1
        except Exception as exc:
            logger.error(
                "Bulk: failed to create notification for user %s: %s",
                user.id, str(exc),
            )

    logger.info("Batch processed: %d/%d notifications created", created, len(recipient_ids))
    return {"created": created, "total": len(recipient_ids)}
