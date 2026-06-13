import uuid
import logging
from typing import List, Dict, Tuple, Optional
import pandas as pd
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


def clean_transactions(file_path: str) -> Tuple[List[Dict], int, int]:
    """
    Reads and cleans the CSV file.
    Returns (cleaned_rows, raw_count, clean_count)
    """
    logger.info(f"Reading CSV: {file_path}")

    # dtype=str — read everything as string first, we convert types ourselves
    # na_filter=False — don't auto-convert empty strings to NaN
    try:
        df = pd.read_csv(file_path, dtype=str, na_filter=False)
    except Exception as e:
        raise ValueError(f"Could not read CSV: {e}")

    raw_count = len(df)

    # Normalize column names — strip spaces and lowercase
    df.columns = [col.strip().lower() for col in df.columns]

    # Replace empty strings with None, drop fully empty rows
    df = df.replace("", None)
    df = df.dropna(how="all")

    # Clean each column
    df["txn_id"] = df["txn_id"].apply(
        lambda x: x.strip() if (x and x.strip()) else str(uuid.uuid4())
    )
    df["date"] = df["date"].apply(_normalize_date)
    df["amount"] = df["amount"].apply(_normalize_amount)
    df["currency"] = df["currency"].apply(lambda x: x.strip().upper() if x else "INR")
    df["status"] = df["status"].apply(lambda x: x.strip().upper() if x else "UNKNOWN")
    df["merchant"] = df["merchant"].apply(lambda x: x.strip() if x else "Unknown Merchant")
    df["category"] = df["category"].apply(lambda x: x.strip() if (x and x.strip()) else "Uncategorised")
    df["account_id"] = df["account_id"].apply(lambda x: x.strip() if x else "UNKNOWN")
    df["notes"] = df["notes"].apply(lambda x: x.strip() if x else "")

    # Remove exact duplicate rows
    # Only check meaningful columns (not generated UUIDs)
    before_dedup = len(df)
    df = df.drop_duplicates(
        subset=["txn_id", "date", "merchant", "amount", "currency", "account_id"],
        keep="first",
    )
    dupes_removed = before_dedup - len(df)
    if dupes_removed > 0:
        logger.info(f"Removed {dupes_removed} duplicate rows")

    clean_count = len(df)

    # Convert to list of dicts, replace NaN with None
    cleaned_rows = df.where(df.notna(), None).to_dict(orient="records")
    return cleaned_rows, raw_count, clean_count


def _normalize_date(date_str: Optional[str]) -> Optional[str]:
    """
    Converts any date format to ISO 8601 (YYYY-MM-DD).
    Handles: DD-MM-YYYY, YYYY/MM/DD, and most other formats.
    dayfirst=True means "01/02/2024" is read as Jan 2nd, not Feb 1st.
    """
    if not date_str or not date_str.strip():
        return None
    try:
        normalized = date_str.strip().replace("/", "-")
        parsed = date_parser.parse(normalized, dayfirst=True)
        return parsed.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        logger.warning(f"Could not parse date: {date_str}")
        return date_str.strip()


def _normalize_amount(amount_str: Optional[str]) -> Optional[float]:
    """
    Converts amount string to float.
    Strips $, ₹, commas. Returns None if unparseable.
    """
    if not amount_str or not amount_str.strip():
        return None
    try:
        cleaned = (
            amount_str.strip()
            .replace("$", "").replace("₹", "").replace("€", "").replace("£", "")
            .replace(",", "").strip()
        )
        return float(cleaned)
    except (ValueError, TypeError):
        logger.warning(f"Could not parse amount: {amount_str}")
        return None