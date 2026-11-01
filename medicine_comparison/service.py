from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Any

from medicine_comparison.config import ATC_GROUPS, DEFAULT_ATC
from medicine_comparison.source import SpreadsheetSnapshot, fetch_latest_spreadsheets

CACHE_SECONDS = 4 * 60 * 60


def _pair_key(medicine: dict[str, Any]) -> str:
    code = medicine.get("code")
    if code:
        return str(code)
    return (
        f"{medicine.get('name', '').casefold()}|"
        f"{medicine.get('package', '').casefold()}"
    )


def _change(current: Any, previous: Any) -> Any:
    if current is None or previous is None:
        return None
    return current - previous


def build_comparison(snapshots: list[SpreadsheetSnapshot]) -> dict[str, Any]:
    latest, previous = snapshots
    previous_by_key = {_pair_key(item): item for item in previous.medicines}
    rows: list[dict[str, Any]] = []
    current_keys: set[str] = set()

    for current_item in latest.medicines:
        key = _pair_key(current_item)
        current_keys.add(key)
        previous_item = previous_by_key.get(key)
        rows.append(
            {
                "current": current_item,
                "previous": previous_item,
                "price_change": _change(
                    current_item["price"],
                    previous_item["price"] if previous_item else None,
                ),
                "copay_change": _change(
                    current_item["copay"],
                    previous_item["copay"] if previous_item else None,
                ),
                "status": "new" if previous_item is None else "existing",
            }
        )

    for previous_item in previous.medicines:
        if _pair_key(previous_item) not in current_keys:
            rows.append(
                {
                    "current": None,
                    "previous": previous_item,
                    "price_change": None,
                    "copay_change": None,
                    "status": "removed",
                }
            )

    rows.sort(
        key=lambda row: (
            (row["current"] or row["previous"])["name"].casefold(),
            (row["current"] or row["previous"])["package"].casefold(),
        )
    )
    return {"latest": latest, "previous": previous, "rows": rows}


class ComparisonService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cache: dict[tuple[str, str | None], tuple[float, dict[str, Any]]] = {}

    def get_comparison(
        self, atc_code: str = DEFAULT_ATC, previous_period: str | None = None
    ) -> dict[str, Any]:
        if atc_code not in ATC_GROUPS:
            raise ValueError(f"Nepodporovaná ATC skupina: {atc_code}")
        cache_key = (atc_code, previous_period)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and monotonic() - cached[0] < CACHE_SECONDS:
                return cached[1]
            if cached is not None:
                try:
                    snapshots = fetch_latest_spreadsheets(
                        atc_code=atc_code, previous_period=previous_period
                    )
                    comparison = build_comparison(snapshots)
                    self._cache[cache_key] = (monotonic(), comparison)
                except Exception:
                    return cached[1]
                return comparison
            snapshots = fetch_latest_spreadsheets(
                atc_code=atc_code, previous_period=previous_period
            )
            comparison = build_comparison(snapshots)
            self._cache[cache_key] = (monotonic(), comparison)
            return comparison
