"""Straight-line depreciation service (Metode Garis Lurus).

Formula:
    Penyusutan per Tahun = (Harga Perolehan - Nilai Sisa) / Umur Ekonomis
    Penyusutan per Bulan = Penyusutan per Tahun / 12
    Akumulasi Penyusutan = Penyusutan per Bulan * bulan_terpakai
    Nilai Buku            = max(Harga Perolehan - Akumulasi Penyusutan, Nilai Sisa)
"""
from datetime import date, datetime
from typing import List, Dict, Any


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Unsupported date value: {value!r}")


def months_between(start: date, end: date) -> int:
    """Number of full months elapsed from start to end (inclusive of start month)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If the day-of-month of `end` >= day-of-month of `start`, that month has completed.
    if end.day >= start.day:
        months += 1
    return max(months, 0)


def compute_depreciation(
    acquisition_cost: float,
    salvage_value: float,
    useful_life_years: int,
    acquisition_date,
    as_of=None,
) -> Dict[str, Any]:
    """Compute straight-line depreciation snapshot as of a given date."""
    cost = float(acquisition_cost or 0)
    salvage = float(salvage_value or 0)
    life_y = int(useful_life_years or 0)

    if life_y <= 0:
        return {
            "annual_depreciation": 0.0,
            "monthly_depreciation": 0.0,
            "months_elapsed": 0,
            "total_months": 0,
            "accumulated_depreciation": 0.0,
            "book_value": cost,
            "is_fully_depreciated": False,
            "depreciable_base": max(cost - salvage, 0.0),
        }

    depreciable_base = max(cost - salvage, 0.0)
    annual = depreciable_base / life_y
    monthly = annual / 12.0
    total_months = life_y * 12

    acq = _to_date(acquisition_date)
    ref = _to_date(as_of) if as_of else date.today()
    elapsed = min(months_between(acq, ref), total_months)

    accumulated = round(monthly * elapsed, 2)
    book_value = max(round(cost - accumulated, 2), salvage)
    fully = elapsed >= total_months

    return {
        "annual_depreciation": round(annual, 2),
        "monthly_depreciation": round(monthly, 2),
        "months_elapsed": elapsed,
        "total_months": total_months,
        "accumulated_depreciation": accumulated,
        "book_value": book_value,
        "is_fully_depreciated": fully,
        "depreciable_base": round(depreciable_base, 2),
    }


def build_schedule(
    acquisition_cost: float,
    salvage_value: float,
    useful_life_years: int,
    acquisition_date,
) -> List[Dict[str, Any]]:
    """Yearly schedule from acquisition year to end of useful life."""
    cost = float(acquisition_cost or 0)
    salvage = float(salvage_value or 0)
    life_y = int(useful_life_years or 0)
    if life_y <= 0:
        return []

    depreciable_base = max(cost - salvage, 0.0)
    annual = depreciable_base / life_y
    acq = _to_date(acquisition_date)

    schedule = []
    accumulated = 0.0
    for i in range(life_y):
        year = acq.year + i
        accumulated += annual
        # Floor at depreciable base
        accumulated = min(accumulated, depreciable_base)
        book_value = max(cost - accumulated, salvage)
        schedule.append({
            "year": year,
            "period": i + 1,
            "depreciation": round(annual, 2),
            "accumulated_depreciation": round(accumulated, 2),
            "book_value": round(book_value, 2),
        })
    return schedule
