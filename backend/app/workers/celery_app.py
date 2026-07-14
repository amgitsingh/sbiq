from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery("qbcals")

celery_app.config_from_object(
    {
        "broker_url": settings.CELERY_BROKER_URL,
        "result_backend": settings.CELERY_RESULT_BACKEND,
        # Queues — enrichment and matching scale independently
        "task_queues": [
            Queue("enrichment"),
            Queue("matching"),
        ],
        "task_default_queue": "enrichment",
        # Route tasks to the correct queue by module prefix
        "task_routes": {
            "app.workers.enrichment_tasks.*": {"queue": "enrichment"},
            "app.workers.matching_tasks.*": {"queue": "matching"},
        },
        # Serialization
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        # Reliability
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "worker_prefetch_multiplier": 1,
        # Result expiry — keep results for 24 hours
        "result_expires": 86400,
        # Timezone
        "timezone": "Asia/Kolkata",
        "enable_utc": True,
    }
)

# Auto-discover tasks once the worker modules exist
celery_app.autodiscover_tasks(["app.workers"])
