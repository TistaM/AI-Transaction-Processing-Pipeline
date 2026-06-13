# AI-Powered Transaction Processing Pipeline

## Overview

This project is a backend system for processing raw financial transaction CSV files. The uploaded CSV may contain dirty data such as mixed date formats, inconsistent casing, missing categories, duplicate rows, currency issues, and suspiciously large transactions.

The system accepts a CSV file through a FastAPI endpoint, creates a background processing job, cleans the data, detects anomalies, uses Gemini LLM to classify missing transaction categories, generates a narrative summary, and stores the final results in PostgreSQL.

The complete system runs with one command using Docker Compose.


## Tech Stack

- **FastAPI** – REST API development
- **PostgreSQL** – persistent database storage
- **Redis** – message broker for background jobs
- **Celery** – asynchronous job processing
- **Gemini API** – LLM-based classification and summary generation
- **Pandas** – CSV cleaning and transformation
- **Docker & Docker Compose** – containerised setup

## Main Features

- Upload transaction CSV file
- Create and track processing job
- Process CSV asynchronously using Celery worker
- Clean dirty transaction data
- Remove duplicate rows
- Normalise dates, amounts, currency, and status values
- Detect suspicious transactions
- Classify missing categories using Gemini LLM
- Generate a structured spending summary
- Retrieve job status and final results through API endpoints


## Project Structure

project/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── data/
│   └── transactions.csv
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── celery_client.py
│   └── routes/
│       └── jobs.py
└── worker/
    ├── Dockerfile
    ├── requirements.txt
    ├── celery_app.py
    ├── models_worker.py
    └── tasks/
        ├── pipeline.py
        ├── cleaning.py
        ├── anomaly.py
        └── llm.py


## Environment Setup

Create a .env file in the root directory using .env.example.

-- env
DATABASE_URL=postgresql://txnuser:txnpass@postgres:5432/transactions_db
REDIS_URL=redis://redis:6379/0
GEMINI_API_KEY=your_gemini_api_key_here
UPLOAD_DIR=/app/uploads
MAX_FILE_SIZE=10485760


The real .env file is ignored using .gitignore and should not be pushed to GitHub

## How to Run

Make sure Docker Desktop is running.

From the project root folder, run:

---bash
docker compose up --build


This starts all services:

- FastAPI API
- Celery worker
- Redis
- PostgreSQL

Once the containers are running, open the API documentation:

---text
http://localhost:8000/docs


Health check:

---text
http://localhost:8000/health


## API Endpoints

| Method | Endpoint                 | Description                               |
| ------ | ------------------------ | ----------------------------------------- |
| GET    | /health                  | Checks if API is running                  |
| POST   | /jobs/upload             | Uploads transaction CSV and creates a job |
| GET    | /jobs/{job_id}/status    | Checks processing status                  |
| GET    |  /jobs/{job_id}/results  | Returns full processed output             |
| GET    |  /jobs                   | Lists all jobs                            |
| GET    |  /jobs?status=completed  | Filters jobs by status                    |


## Example Usage

### 1. Upload CSV
---bash
curl -X POST "http://localhost:8000/jobs/upload" \
  -F "file=@data/transactions.csv"

Example response:

---json
{
  "job_id": "d455089e-cc68-4d7a-a339-abb2a21498af",
  "status": "pending",
  "message": "Job enqueued. Poll /jobs/{job_id}/status for updates.",
  "filename": "transactions.csv"
}


### 2. Check Job Status

---bash
curl http://localhost:8000/jobs/d455089e-cc68-4d7a-a339-abb2a21498af/status


Example completed response:

---json
{
  "job_id": "d455089e-cc68-4d7a-a339-abb2a21498af",
  "status": "completed",
  "filename": "transactions.csv",
  "row_count_raw": 95,
  "row_count_clean": 85,
  "error_message": null,
  "summary": {
    "total_transactions": 85,
    "anomaly_count": 10,
    "total_spend_inr": 1032918.22,
    "total_spend_usd": 35219.2,
    "risk_level": "medium"
  }
}



### 3. Get Final Results

---bash
curl http://localhost:8000/jobs/d455089e-cc68-4d7a-a339-abb2a21498af/results


This returns:

- cleaned transactions
- flagged anomalies
- category spend breakdown
- LLM-generated narrative summary

### 4. List Jobs

---bash
curl http://localhost:8000/jobs


Filter completed jobs:

---bash
curl "http://localhost:8000/jobs?status=completed"


## Processing Pipeline

When a CSV file is uploaded, the worker runs the following steps:

1. **Data Cleaning**

   - Normalises date formats to `YYYY-MM-DD`
   - Removes currency symbols from amounts
   - Converts currency and status values to uppercase
   - Fills blank categories as `Uncategorised`
   - Removes duplicate rows

2. **Anomaly Detection**

   - Flags transactions where amount is greater than 3 times the account median
   - Flags USD transactions for domestic-only merchants such as Swiggy, Ola, IRCTC, Zomato, etc.

3. **LLM Classification**

   - Sends uncategorised transactions to Gemini in batches
   - Assigns one of the allowed categories:

     - Food
     - Shopping
     - Travel
     - Transport
     - Utilities
     - Cash Withdrawal
     - Entertainment
     - Other

4. **LLM Narrative Summary**

   - Generates total spend by currency
   - Finds top merchants
   - Counts anomalies
   - Creates a short spending summary
   - Assigns risk level: low, medium, or high

5. **Result Storage**

   - Stores cleaned transactions, anomalies, and summary in PostgreSQL
   - Marks the job as completed


## Successful Test Run

A successful run on the provided `transactions.csv` produced:

---text
Raw rows: 95
Clean rows: 85
Duplicates removed: 10
Anomalies flagged: 10
Risk level: medium
Status: completed


Worker logs also confirmed:

---text
Pipeline started
Removed 10 duplicate rows
Flagged 10 anomalies
Classifying 13 transactions with LLM
Narrative generated. Risk level: medium
Pipeline completed


## Architecture

The system uses an asynchronous backend architecture. FastAPI receives the CSV upload, validates it, saves the file, creates a job record in PostgreSQL, and sends a Celery task to Redis. The Celery worker picks up the task, cleans the CSV, detects anomalies, calls Gemini for category classification and narrative summary generation, then stores the processed transactions and summary back in PostgreSQL.

A separate high-level architecture diagram is available here:

[Architecture Diagram]()


## Bottlenecks and Scaling

If traffic increases by 100x, the main bottlenecks would be:

- API upload handling
- local Docker volume file storage
- Celery worker concurrency
- Redis queue backlog
- PostgreSQL insert and polling load
- Gemini API latency and rate limits

For production, I would improve the system by:

- scaling API and worker containers horizontally
- storing uploaded files in S3 or Google Cloud Storage
- using managed PostgreSQL and Redis
- adding connection pooling with PgBouncer
- adding monitoring with Prometheus/Grafana
- caching repeated merchant classifications
- using Alembic migrations instead of automatic table creation
- adding authentication, rate limiting, and stricter CORS rules

## Known Limitations

- No authentication is implemented
- No frontend UI is included
- Uploaded files are stored in Docker volume
- No pagination for very large result sets
- LLM output depends on Gemini API availability
- Current setup is designed for assignment-scale CSV files

## Submission Notes

The project can be tested by running:

---bash

docker compose up --build

Then opening:

text
http://localhost:8000/docs

The repository includes:

1.source code
2.Docker setup
3.API endpoints
4.sample transaction CSV
5.README instructions
6.architecture explanation
7.curl examples
