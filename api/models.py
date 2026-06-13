import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float,
    ForeignKey, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Job(Base):
    __tablename__ = "jobs"

    # UUID primary key — globally unique, safe to expose in public URLs
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    filename = Column(String(255), nullable=False)

    # Enum enforces only these exact values can be stored
    status = Column(
        Enum("pending", "processing", "completed", "failed", name="job_status"),
        nullable=False,
        default="pending",
    )

    row_count_raw = Column(Integer, nullable=True)    # rows in original CSV
    row_count_clean = Column(Integer, nullable=True)  # rows after deduplication

    # server_default=func.now() means the DB fills this in automatically
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)

    # Relationships — not columns, just Python shortcuts
    # job.transactions gives you all Transaction rows for this job
    # cascade="all, delete-orphan" means deleting Job auto-deletes Transactions
    transactions = relationship(
        "Transaction", back_populates="job", cascade="all, delete-orphan"
    )
    # uselist=False makes this one-to-one (returns object, not list)
    summary = relationship(
        "JobSummary", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key links this row back to its parent Job
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # index makes queries by job_id much faster
    )

    # Cleaned transaction fields (mirrors CSV columns but normalized)
    txn_id = Column(String(100), nullable=True)
    date = Column(String(20), nullable=True)       # stored as "2024-01-15"
    merchant = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)   # "INR" or "USD"
    status = Column(String(20), nullable=True)     # "SUCCESS", "FAILED", "PENDING"
    category = Column(String(100), nullable=True)
    account_id = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Anomaly detection results
    is_anomaly = Column(Boolean, default=False, nullable=False)
    anomaly_reason = Column(Text, nullable=True)

    # LLM classification results
    llm_category = Column(String(100), nullable=True)
    llm_raw_response = Column(Text, nullable=True)  # raw LLM output for debugging
    llm_failed = Column(Boolean, default=False, nullable=False)

    job = relationship("Job", back_populates="transactions")


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # unique=True enforces one summary per job (one-to-one)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    total_spend_inr = Column(Float, default=0.0)
    total_spend_usd = Column(Float, default=0.0)

    # JSON column stores Python list: ["Amazon", "Swiggy", "IndiGo"]
    top_merchants = Column(JSON, nullable=True)
    anomaly_count = Column(Integer, default=0)

    # LLM-generated content
    narrative = Column(Text, nullable=True)
    risk_level = Column(
        Enum("low", "medium", "high", name="risk_level"), nullable=True
    )

    # JSON column stores dict: {"Food": 5000.0, "Travel": 12000.0}
    category_breakdown = Column(JSON, nullable=True)

    job = relationship("Job", back_populates="summary")