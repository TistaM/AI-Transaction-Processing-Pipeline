import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "transaction_processor",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.pipeline"],  # tells Celery where task functions live
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,       # only mark task done AFTER it finishes (safer)
    result_expires=3600,
    worker_prefetch_multiplier=1,  # each worker takes 1 task at a time
)