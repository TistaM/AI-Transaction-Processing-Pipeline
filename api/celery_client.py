import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_sender = Celery(
    "api_sender",
    broker=REDIS_URL,
    backend=REDIS_URL
)

PIPELINE_TASK_NAME = "tasks.pipeline.process_job"


def enqueue_job(job_id: str) -> str:
    """
    Sends the process_job task to Redis.
    The worker picks it up and executes it.
    """
    result = celery_sender.send_task(
        PIPELINE_TASK_NAME,
        args=[job_id],
    )
    print(f"Enqueued job {job_id} -> Celery task {result.id}")
    return result.id