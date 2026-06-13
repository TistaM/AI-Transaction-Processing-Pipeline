import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import Job, JobSummary, Transaction
from schemas import (
    JobListItem, JobResultsResponse, JobStatusResponse,
    JobSummaryOut, JobUploadResponse, TransactionOut,
)

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 10 * 1024 * 1024))


# ────────────────────────────────────────────────────────────
# POST /jobs/upload
# ────────────────────────────────────────────────────────────
@router.post("/upload", response_model=JobUploadResponse, status_code=202)
async def upload_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Validate file extension
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max size is 10MB.")

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate CSV has required columns
    try:
        header_line = content.decode("utf-8").split("\n")[0].lower()
        required_columns = {"txn_id", "date", "merchant", "amount", "currency"}
        found_columns = {col.strip().strip('"') for col in header_line.split(",")}
        missing = required_columns - found_columns
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"CSV missing required columns: {missing}"
            )
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    # Save file to disk with job_id in filename to avoid collisions
    job_id = uuid.uuid4()
    safe_filename = f"{job_id}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(content)

    # Count rows (minus header)
    row_count = content.decode("utf-8").count("\n") - 1

    # Create Job record in DB
    job = Job(
        id=job_id,
        filename=file.filename,
        status="pending",
        row_count_raw=row_count,
        file_path=file_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Enqueue Celery task — sends message to Redis
    # Worker picks it up and runs the pipeline
    try:
        from celery_client import enqueue_job
        enqueue_job(str(job_id))
    except Exception as e:
        job.status = "failed"
        job.error_message = f"Failed to enqueue: {str(e)}"
        db.commit()
        raise HTTPException(status_code=503, detail="Could not enqueue job. Redis may be down.")

    return JobUploadResponse(
        job_id=job_id,
        status="pending",
        message="Job enqueued. Poll /jobs/{job_id}/status for updates.",
        filename=file.filename,
    )


# ────────────────────────────────────────────────────────────
# GET /jobs/{job_id}/status
# ────────────────────────────────────────────────────────────
@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    summary_data = None
    if job.status == "completed" and job.summary:
        summary_data = {
            "total_transactions": job.row_count_clean,
            "anomaly_count": job.summary.anomaly_count,
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "risk_level": job.summary.risk_level,
        }

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary_data,
    )


# ────────────────────────────────────────────────────────────
# GET /jobs/{job_id}/results
# ────────────────────────────────────────────────────────────
@router.get("/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    if job.status == "pending":
        raise HTTPException(status_code=400, detail="Job is still pending.")
    if job.status == "processing":
        raise HTTPException(status_code=400, detail="Job is still processing.")
    if job.status == "failed":
        raise HTTPException(status_code=400, detail=f"Job failed: {job.error_message}")

    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in transactions if t.is_anomaly]

    # Build category spend breakdown
    category_spend = {}
    for txn in transactions:
        cat = txn.llm_category or txn.category or "Uncategorised"
        currency = txn.currency or "INR"
        key = f"{cat} ({currency})"
        category_spend[key] = category_spend.get(key, 0) + (txn.amount or 0)

    narrative_summary = None
    if job.summary:
        narrative_summary = JobSummaryOut(
            total_spend_inr=job.summary.total_spend_inr or 0,
            total_spend_usd=job.summary.total_spend_usd or 0,
            top_merchants=job.summary.top_merchants,
            anomaly_count=job.summary.anomaly_count or 0,
            narrative=job.summary.narrative,
            risk_level=job.summary.risk_level,
            category_breakdown=job.summary.category_breakdown,
        )

    return JobResultsResponse(
        job_id=job_id,
        status=job.status,
        cleaned_transactions=[TransactionOut.model_validate(t) for t in transactions],
        flagged_anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_spend=category_spend,
        narrative_summary=narrative_summary,
    )


# ────────────────────────────────────────────────────────────
# GET /jobs
# ────────────────────────────────────────────────────────────
@router.get("", response_model=List[JobListItem])
def list_jobs(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
):
    valid_statuses = {"pending", "processing", "completed", "failed"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Choose from: {valid_statuses}")

    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)

    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()
    return [JobListItem.model_validate(job) for job in jobs]