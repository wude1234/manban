"""Diagnose local simulation output.

Reads ``demo/results/monthly_income_202603.json`` and action logs, then prints
driver-level score, preference penalties, and simple action statistics.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = DEMO_ROOT / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose monthly income and action logs.")
    parser.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory containing monthly_income_202603.json and actions_202603_*.jsonl.",
    )
    parser.add_argument("--top", type=int, default=10, help="Driver rows to print.")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    income_path = results_dir / "monthly_income_202603.json"
    if not income_path.is_file():
        raise FileNotFoundError(income_path)

    income = json.loads(income_path.read_text(encoding="utf-8"))
    report = {
        "summary": income.get("summary", {}),
        "drivers": _driver_rows(income, limit=args.top),
        "actions": _action_stats(results_dir),
        "preference_hotspots": _preference_hotspots(income),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _driver_rows(income: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in income.get("drivers", []) or []:
        inc = item.get("income") or {}
        rows.append(
            {
                "driver_id": item.get("driver_id"),
                "net_income": inc.get("net_income"),
                "gross_income": inc.get("gross_income"),
                "distance_km": inc.get("distance_km"),
                "cost": inc.get("cost"),
                "preference_penalty": inc.get("preference_penalty"),
                "calculation_aborted": item.get("calculation_aborted"),
                "validation_error": item.get("validation_error"),
                "preference_rules": _rule_rows(item),
            }
        )
    rows.sort(key=lambda row: float(row.get("net_income") or 0.0))
    return rows[:limit]


def _rule_rows(driver_item: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pref = driver_item.get("preference_check") or {}
    for rule in pref.get("rules", []) or []:
        if not isinstance(rule, dict):
            continue
        penalty = float(rule.get("penalty", 0.0) or 0.0)
        if penalty <= 0:
            continue
        out.append(
            {
                "rule": rule.get("rule"),
                "penalty": round(penalty, 2),
                "detail": {k: v for k, v in rule.items() if k not in {"rule", "preference_text"}},
            }
        )
    out.sort(key=lambda row: float(row.get("penalty") or 0.0), reverse=True)
    return out


def _preference_hotspots(income: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in income.get("drivers", []) or []:
        driver_id = str(item.get("driver_id", ""))
        for rule in _rule_rows(item):
            rows.append({"driver_id": driver_id, **rule})
    rows.sort(key=lambda row: float(row.get("penalty") or 0.0), reverse=True)
    return rows


def _action_stats(results_dir: Path) -> dict[str, Any]:
    action_count: Counter[str] = Counter()
    accepted_false = 0
    steps_by_driver: dict[str, int] = {}
    wait_minutes_by_driver: defaultdict[str, int] = defaultdict(int)
    active_minutes_by_driver: defaultdict[str, int] = defaultdict(int)
    orders_by_driver_day: defaultdict[str, Counter[str]] = defaultdict(Counter)

    for path in sorted(results_dir.glob("actions_202603_*.jsonl")):
        driver_id = _driver_id_from_action_path(path)
        steps = 0
        previous_end = 0
        for record in _iter_jsonl(path):
            steps += 1
            action = record.get("action") or {}
            action_name = str(action.get("action", "")).strip().lower()
            action_count[action_name] += 1
            result = record.get("result") or {}
            end = _safe_int(result.get("simulation_progress_minutes"), previous_end)
            query_cost = _safe_int(record.get("query_scan_cost_minutes"), 0)
            exec_cost = _safe_int(record.get("action_exec_cost_minutes"), 0)
            action_start = previous_end + query_cost
            day_key = str(action_start // 1440 + 1)
            if action_name == "wait":
                wait_minutes_by_driver[driver_id] += exec_cost
            elif action_name in {"take_order", "reposition"}:
                active_minutes_by_driver[driver_id] += exec_cost
            if action_name == "take_order":
                if bool(result.get("accepted", False)):
                    orders_by_driver_day[driver_id][day_key] += 1
                else:
                    accepted_false += 1
            previous_end = end
        steps_by_driver[driver_id] = steps

    return {
        "action_count": dict(action_count),
        "accepted_false": accepted_false,
        "steps_by_driver": dict(sorted(steps_by_driver.items())),
        "wait_hours_by_driver": {k: round(v / 60.0, 2) for k, v in sorted(wait_minutes_by_driver.items())},
        "active_hours_by_driver": {k: round(v / 60.0, 2) for k, v in sorted(active_minutes_by_driver.items())},
        "orders_by_driver_day": {k: dict(v) for k, v in sorted(orders_by_driver_day.items())},
    }


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _driver_id_from_action_path(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return parts[2]
    return path.stem


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
