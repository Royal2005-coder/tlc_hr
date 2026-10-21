"""Payroll review and service-proration policies; statutory calculation stays in payroll.py."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def effective_base(segments):
    """Normalize by paid days: native HRMS applies payment_days/total_working_days once."""
    paid = sum(Decimal(str(row["payment_days"])) for row in segments)
    if paid <= 0:
        return Decimal(0)
    return sum(Decimal(str(row["base"])) * Decimal(str(row["payment_days"])) for row in segments) / paid


def variance_percent(previous, current):
    old, new = Decimal(str(previous or 0)), Decimal(str(current or 0))
    if not old:
        return Decimal(0) if not new else Decimal(100)
    return abs(new - old) * 100 / abs(old)


def service_bonus(reference_salary, multiplier, period_start, period_end, joining_date, relieving_date=None):
    """Company-declared calendar-service formula, not a statutory entitlement or legal rate."""
    start, end = date.fromisoformat(str(period_start)), date.fromisoformat(str(period_end))
    joined = date.fromisoformat(str(joining_date))
    left = date.fromisoformat(str(relieving_date)) if relieving_date else end
    if start > end or Decimal(str(multiplier)) < 0:
        raise ValueError("Invalid bonus period or multiplier")
    days = max(0, (min(end, left) - max(start, joined)).days + 1)
    return money(Decimal(str(reference_salary)) * Decimal(str(multiplier)) * days / ((end - start).days + 1))


def safe_csv_cell(value):
    """Protect spreadsheet consumers without changing numeric values."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
