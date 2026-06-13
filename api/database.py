import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")

# Engine = the actual connection pool to PostgreSQL
# pool_pre_ping checks if connection is alive before using it
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

# SessionLocal is a factory that makes new DB sessions
# autocommit=False means changes are NOT saved until you call db.commit()
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base is what all your model classes inherit from
# SQLAlchemy uses it to know which classes = which tables
Base = declarative_base()


# FastAPI dependency — injected into every route that needs DB access
# Opens session before route runs, closes it after (even on error)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()