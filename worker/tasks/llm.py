import json
import logging
import os
import time
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "Food", "Shopping", "Travel", "Transport",
    "Utilities", "Cash Withdrawal", "Entertainment", "Other",
}

BATCH_SIZE = 20   # transactions per LLM API call
MAX_RETRIES = 3
BASE_BACKOFF = 2  # seconds — doubles each retry: 2s, 4s, 8s


def _get_model():
    """Initialize and return Gemini model."""
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


# ────────────────────────────────────────────────────────────────
# OPERATION 1: Classify uncategorised transactions in batches
# ────────────────────────────────────────────────────────────────
def classify_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    For rows where category == "Uncategorised", calls Gemini in batches
    to assign one of the VALID_CATEGORIES.
    Batching means ~90 rows = ~5 API calls instead of 90 calls.
    """
    for txn in transactions:
        txn["llm_category"] = None
        txn["llm_raw_response"] = None
        txn["llm_failed"] = False

    # Collect only uncategorised rows (with their original index)
    uncategorised = [
        (i, txn) for i, txn in enumerate(transactions)
        if txn.get("category") == "Uncategorised"
    ]

    if not uncategorised:
        logger.info("All transactions already categorised — skipping LLM")
        return transactions

    logger.info(f"Classifying {len(uncategorised)} transactions with LLM")

    # Process batch by batch
    for batch_start in range(0, len(uncategorised), BATCH_SIZE):
        batch = uncategorised[batch_start: batch_start + BATCH_SIZE]
        success, results = _classify_batch_with_retry(batch)

        if success and results:
            for original_idx, category in results:
                transactions[original_idx]["llm_category"] = category
        else:
            # Mark whole batch as failed — DO NOT fail the entire job
            for original_idx, _ in batch:
                transactions[original_idx]["llm_failed"] = True
            logger.warning(f"Batch starting at {batch_start} failed — marked as llm_failed")

    return transactions


def _classify_batch_with_retry(batch) -> Tuple[bool, Optional[List]]:
    """Retry the LLM call up to MAX_RETRIES times with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            results = _call_llm_classify(batch)
            return True, results
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = BASE_BACKOFF ** attempt  # 2s, 4s, 8s
                logger.warning(f"LLM attempt {attempt} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All {MAX_RETRIES} LLM attempts failed: {e}")
    return False, None


def _call_llm_classify(batch) -> List[Tuple[int, str]]:
    """
    Sends ONE API call to Gemini with a batch of transactions.
    Returns list of (original_index, category) tuples.
    """
    model = _get_model()

    # Build numbered list of transactions for the prompt
    lines = []
    for pos, (original_idx, txn) in enumerate(batch):
        merchant = txn.get("merchant", "Unknown")
        amount = txn.get("amount", 0)
        currency = txn.get("currency", "INR")
        notes = txn.get("notes", "")
        line = f'{pos + 1}. merchant="{merchant}", amount={amount} {currency}'
        if notes:
            line += f', notes="{notes}"'
        lines.append(line)

    prompt = f"""You are a financial transaction classifier.

Classify each transaction into EXACTLY ONE of:
Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other

TRANSACTIONS:
{chr(10).join(lines)}

RULES:
- Use ONLY the category names listed above, exactly as written
- Return ONLY valid JSON, no markdown, no explanation

OUTPUT FORMAT:
[
  {{"index": 1, "category": "Food"}},
  {{"index": 2, "category": "Travel"}}
]"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Store raw response on first transaction for debugging
    if batch:
        batch[0][1]["llm_raw_response"] = raw[:500]

    # Strip markdown fences if Gemini wrapped the JSON
    clean = raw
    if clean.startswith("```"):
        lines_list = clean.split("\n")
        clean = "\n".join(lines_list[1:-1])

    classifications = json.loads(clean)

    results = []
    for item in classifications:
        pos = item.get("index", 0) - 1  # convert 1-based to 0-based
        category = item.get("category", "Other")
        if category not in VALID_CATEGORIES:
            category = "Other"
        if 0 <= pos < len(batch):
            original_idx = batch[pos][0]
            results.append((original_idx, category))

    return results


# ────────────────────────────────────────────────────────────────
# OPERATION 2: Generate narrative summary (single LLM call)
# ────────────────────────────────────────────────────────────────
def generate_narrative_summary(transactions: List[Dict], anomaly_count: int) -> Optional[Dict]:
    """
    One LLM call to produce a structured JSON summary with:
    - Total spend by currency
    - Top 3 merchants
    - Anomaly count
    - 2-3 sentence narrative
    - risk_level: low / medium / high
    """
    # Pre-compute stats to give LLM useful context
    inr_total = sum(
        t.get("amount", 0) or 0
        for t in transactions
        if t.get("currency") == "INR" and t.get("status") == "SUCCESS"
    )
    usd_total = sum(
        t.get("amount", 0) or 0
        for t in transactions
        if t.get("currency") == "USD" and t.get("status") == "SUCCESS"
    )

    merchant_counts: Dict[str, int] = {}
    for t in transactions:
        m = t.get("merchant", "Unknown")
        merchant_counts[m] = merchant_counts.get(m, 0) + 1
    top_merchants = sorted(merchant_counts, key=merchant_counts.get, reverse=True)[:3]

    category_spend: Dict[str, float] = {}
    for t in transactions:
        cat = t.get("llm_category") or t.get("category") or "Uncategorised"
        category_spend[cat] = category_spend.get(cat, 0) + (t.get("amount") or 0)

    prompt = f"""You are a financial analyst. Generate a summary of this spending data.

DATA:
- INR total (successful transactions): {inr_total:.2f}
- USD total (successful transactions): {usd_total:.2f}
- Top merchants: {', '.join(top_merchants)}
- Total transactions: {len(transactions)}
- Anomalies flagged: {anomaly_count}
- Category breakdown: {json.dumps(category_spend)}

Return ONLY valid JSON in this exact format, no markdown:
{{
  "total_spend_inr": {inr_total:.2f},
  "total_spend_usd": {usd_total:.2f},
  "top_merchants": {json.dumps(top_merchants)},
  "anomaly_count": {anomaly_count},
  "narrative": "2-3 sentences describing spending patterns and key observations.",
  "risk_level": "low or medium or high",
  "category_breakdown": {json.dumps(category_spend)}
}}"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            model = _get_model()
            response = model.generate_content(prompt)
            raw = response.text.strip()

            clean = raw
            if clean.startswith("```"):
                lines_list = clean.split("\n")
                clean = "\n".join(lines_list[1:-1])

            result = json.loads(clean)
            if result.get("risk_level") not in {"low", "medium", "high"}:
                result["risk_level"] = "medium"

            logger.info(f"Narrative generated. Risk level: {result.get('risk_level')}")
            return result

        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = BASE_BACKOFF ** attempt
                logger.warning(f"Narrative attempt {attempt} failed: {e}. Waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"All narrative attempts failed: {e}")

    # Fallback — computed values, no LLM narrative
    return {
        "total_spend_inr": inr_total,
        "total_spend_usd": usd_total,
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
        "narrative": "LLM narrative generation failed. Manual review recommended.",
        "risk_level": "medium",
        "category_breakdown": category_spend,
    }