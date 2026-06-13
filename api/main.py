import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routes.jobs import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs on startup — creates all DB tables if they don't exist
    print("Starting up...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created/verified")

    upload_dir = os.getenv("UPLOAD_DIR", "/app/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    print(f"Upload directory ready: {upload_dir}")

    yield  # app runs here

    print("Shutting down...")


app = FastAPI(
    title="AI-Powered Transaction Processing API",
    description="Accepts dirty CSV files, processes them async, uses LLM to classify and summarize.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allows browser-based frontends to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all /jobs/* endpoints
app.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "service": "Transaction Processing API", "version": "1.0.0"}


@app.get("/", tags=["Health"])
def root():
    return {
        "message": "Transaction Processing API is running!",
        "docs": "http://localhost:8000/docs",
    }