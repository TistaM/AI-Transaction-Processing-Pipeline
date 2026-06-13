import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, "/app")

from celery_app import app as celery_app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tasks.cleaning import clean_transactions
from tasks.anomaly import detect_anomalies
from tasks.llm import classify_transactions, generate_narrative_summary

logger = logging.getLogger(__name__)


def _get_db_session():
    """Create a DB session for the worker container."""
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    from models_worker import Base
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


@celery_app.task(
    name="tasks.pipeline.process_job",  # must match PIPELINE_TASK_NAME in api/celery_client.py
    bind=True,
    max_retries=0,          # don't retry the whole pipeline — LLM retries happen internally
    soft_time_limit=300,    # 5 minute warning
    time_limit=360,         # 6 minute hard kill
)
def process_job(self, job_id: str):
    """
    Orchestrates the full pipeline for one job:
    clean → anomaly detect → LLM classify → LLM summary → save to DB
    """
    logger.info(f"Pipeline started for job: {job_id}")
    db = None

    try:
        db = _get_db_session()
        from models_worker import Job, Transaction, JobSummary

        # Fetch job
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in DB")
            return
        if job.status != "pending":
            logger.warning(f"Job {job_id} status is '{job.status}', expected pending. Skipping.")
            return

        # Step 1: Mark as processing
        job.status = "processing"
        db.commit()

        # Step 2: Clean the CSV
        logger.info("Step 2: Cleaning data")
        if not job.file_path or not os.path.exists(job.file_path):
            raise FileNotFoundError(f"CSV not found at: {job.file_path}")

        cleaned_rows, raw_count, clean_count = clean_transactions(job.file_path)
        job.row_count_raw = raw_count
        job.row_count_clean = clean_count
        db.commit()

        if not cleaned_rows:
            raise ValueError("No valid rows after cleaning")

        # Step 3: Detect anomalies
        logger.info("Step 3: Detecting anomalies")
        cleaned_rows = detect_anomalies(cleaned_rows)
        anomaly_count = sum(1 for r in cleaned_rows if r.get("is_anomaly"))

        # Step 4: LLM classify uncategorised transactions
        logger.info("Step 4: LLM classification")
        cleaned_rows = classify_transactions(cleaned_rows)

        # Step 5: LLM narrative summary
        logger.info("Step 5: Generating narrative")
        narrative_data = generate_narrative_summary(cleaned_rows, anomaly_count)

        # Step 6: Save all transactions to DB
        logger.info(f"Step 6: Saving {len(cleaned_rows)} transactions")
        db.query(Transaction).filter(Transaction.job_id == job_id).delete()
        db.commit()

        transaction_objects = [
            Transaction(
                job_id=job_id,
                txn_id=row.get("txn_id"),
                date=row.get("date"),
                merchant=row.get("merchant"),
                amount=row.get("amount"),
                currency=row.get("currency"),
                status=row.get("status"),
                category=row.get("category"),
                account_id=row.get("account_id"),
                notes=row.get("notes"),
                is_anomaly=row.get("is_anomaly", False),
                anomaly_reason=row.get("anomaly_reason"),
                llm_category=row.get("llm_category"),
                llm_raw_response=row.get("llm_raw_response"),
                llm_failed=row.get("llm_failed", False),
            )
            for row in cleaned_rows
        ]
        db.bulk_save_objects(transaction_objects)
        db.commit()

        # Step 7: Save summary
        logger.info("Step 7: Saving summary")
        db.query(JobSummary).filter(JobSummary.job_id == job_id).delete()
        db.commit()

        if narrative_data:
            summary = JobSummary(
                job_id=job_id,
                total_spend_inr=narrative_data.get("total_spend_inr", 0),
                total_spend_usd=narrative_data.get("total_spend_usd", 0),
                top_merchants=narrative_data.get("top_merchants", []),
                anomaly_count=anomaly_count,
                narrative=narrative_data.get("narrative"),
                risk_level=narrative_data.get("risk_level", "medium"),
                category_breakdown=narrative_data.get("category_breakdown", {}),
            )
            db.add(summary)
            db.commit()

        # Step 8: Mark completed
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        db.commit()
        logger.info(f"Pipeline completed for job {job_id}")

    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}: {e}")
        if db:
            try:
                from models_worker import Job
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = str(e)[:1000]
                    job.completed_at = datetime.utcnow()
                    db.commit()
            except Exception as db_err:
                logger.error(f"Could not update job to failed: {db_err}")
        raise

    finally:
        if db:
            db.close()