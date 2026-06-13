import logging
import statistics
from typing import List, Dict

logger = logging.getLogger(__name__)

# Merchants that only operate in India — should never charge USD
DOMESTIC_ONLY_MERCHANTS = {
    "swiggy", "zomato", "ola", "irctc", "blinkit",
    "bigbasket", "dunzo", "meesho", "nykaa", "jiomart",
    "dmart", "flipkart", "myntra",
}

OUTLIER_MULTIPLIER = 3.0


def detect_anomalies(transactions: List[Dict]) -> List[Dict]:
    """
    Runs both anomaly detection passes on cleaned transactions.
    Adds is_anomaly (bool) and anomaly_reason (str) to each row.
    """
    logger.info(f"Running anomaly detection on {len(transactions)} transactions")

    for txn in transactions:
        txn["is_anomaly"] = False
        txn["anomaly_reason"] = None

    transactions = _detect_statistical_outliers(transactions)
    transactions = _detect_currency_mismatch(transactions)

    flagged = sum(1 for t in transactions if t["is_anomaly"])
    logger.info(f"Flagged {flagged} anomalies")
    return transactions


def _detect_statistical_outliers(transactions: List[Dict]) -> List[Dict]:
    """
    Algorithm:
      1. Group all amounts by account_id
      2. Calculate median for each account
      3. Flag any transaction where amount > 3 * median

    Uses median (not mean) because mean is skewed by outliers.
    Example: [100, 200, 150, 5000] -> mean=1362, median=175
    Median correctly shows 5000 is the outlier.
    """
    # Build dict: account_id -> list of amounts
    account_amounts: Dict[str, List[float]] = {}
    for txn in transactions:
        account_id = txn.get("account_id", "UNKNOWN")
        amount = txn.get("amount")
        if amount is not None and isinstance(amount, (int, float)):
            account_amounts.setdefault(account_id, []).append(float(amount))

    # Calculate median per account
    account_medians = {}
    for account_id, amounts in account_amounts.items():
        if len(amounts) >= 2:
            account_medians[account_id] = statistics.median(amounts)
        elif len(amounts) == 1:
            account_medians[account_id] = amounts[0]

    # Flag outliers
    for txn in transactions:
        account_id = txn.get("account_id", "UNKNOWN")
        amount = txn.get("amount")
        if amount is None or account_id not in account_medians:
            continue
        median = account_medians[account_id]
        if median > 0 and float(amount) > OUTLIER_MULTIPLIER * median:
            txn["is_anomaly"] = True
            txn["anomaly_reason"] = (
                f"Amount {amount} exceeds 3x account median "
                f"({median:.2f}) for account {account_id}"
            )

    return transactions


def _detect_currency_mismatch(transactions: List[Dict]) -> List[Dict]:
    """
    Flags transactions where a domestic-only merchant charges in USD.
    e.g., Swiggy should never charge USD — that's a red flag.
    """
    for txn in transactions:
        currency = txn.get("currency", "")
        merchant = txn.get("merchant", "")
        if not currency or not merchant:
            continue

        merchant_lower = merchant.lower().strip()
        is_domestic = any(d in merchant_lower for d in DOMESTIC_ONLY_MERCHANTS)

        if currency.upper() == "USD" and is_domestic:
            new_reason = f"USD charge on domestic-only merchant '{merchant}'"
            if txn["is_anomaly"] and txn["anomaly_reason"]:
                txn["anomaly_reason"] += f"; {new_reason}"
            else:
                txn["is_anomaly"] = True
                txn["anomaly_reason"] = new_reason

    return transactions