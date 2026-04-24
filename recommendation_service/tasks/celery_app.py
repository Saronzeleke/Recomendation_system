from celery import Celery
from celery.schedules import crontab
import structlog
from kombu import Queue, Exchange

from core.config import settings

logger = structlog.get_logger()

# Create Celery app
celery_app = Celery(
    "serveease_tasks",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "tasks.update_features",
        "tasks.training_pipeline",
        "tasks.signal_collection"
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=3600,  # 1 hour
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("ml_training", Exchange("ml_training"), routing_key="ml_training"),
        Queue("feature_updates", Exchange("feature_updates"), routing_key="feature_updates"),
    ),
    task_routes={
        "tasks.update_features.*": {"queue": "feature_updates"},
        "tasks.training_pipeline.*": {"queue": "ml_training"},
        "tasks.signal_collection.*": {"queue": "default"},
    },
    beat_schedule={
        "refresh-materialized-view": {
            "task": "tasks.update_features.refresh_materialized_view",
            "schedule": crontab(minute="*/15"),  # Every 15 minutes
        },
        "update-service-vectors": {
            "task": "tasks.update_features.update_service_vectors",
            "schedule": crontab(minute=0, hour="*/2"),  # Every 2 hours
        },
        "train-ml-models": {
            "task": "tasks.training_pipeline.train_models",
            "schedule": crontab(minute=0, hour=3),  # Daily at 3 AM
        },
        "cleanup-old-signals": {
            "task": "tasks.signal_collection.cleanup_old_signals",
            "schedule": crontab(minute=0, hour=4),  # Daily at 4 AM
        },
    }
)

logger.info("celery_app_initialized")