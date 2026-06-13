from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class JobUploadResponse(BaseModel):
    """Returned immediately after POST /jobs/upload"""
    job_id: UUID
    status: str
    message: str
    filename: str


class JobStatusResponse(BaseModel):
    """Returned by GET /jobs/{job_id}/status"""
    job_id: UUID
    status: str
    filename: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None  # only populated when completed

    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    """One item in GET /jobs list"""
    job_id: UUID = Field(alias="id")
    status: str
    filename: str
    row_count_raw: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class TransactionOut(BaseModel):
    """One transaction in the results response"""
    id: UUID
    txn_id: Optional[str] = None
    date: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_failed: bool

    model_config = {"from_attributes": True}


class JobSummaryOut(BaseModel):
    """The LLM-generated summary"""
    total_spend_inr: float
    total_spend_usd: float
    top_merchants: Optional[List[str]] = None
    anomaly_count: int
    narrative: Optional[str] = None
    risk_level: Optional[str] = None
    category_breakdown: Optional[Dict[str, float]] = None

    model_config = {"from_attributes": True}


class JobResultsResponse(BaseModel):
    """Full results from GET /jobs/{job_id}/results"""
    job_id: UUID
    status: str
    cleaned_transactions: List[TransactionOut]
    flagged_anomalies: List[TransactionOut]
    category_spend: Dict[str, float]
    narrative_summary: Optional[JobSummaryOut] = None

    model_config = {"from_attributes": True}