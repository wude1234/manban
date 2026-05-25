"""Find orders that lead into long idle/wait traps.

The latest probes show that replacing actions at the long-wait step itself is
usually too late.  This helper ranks the previous order/route segment that put
the driver into that low-value state, so future probes can branch before the
trap.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze long-idle traps in action traces.")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--drivers", default="D001,D005,D009,D002,D007,D010")
    parser.add_argument("--min-wait-minutes", type=int, default=300)
    parser.add_argument("--out", default=str(DEMO_ROOT / "results" / "value_dataset" / "idle_traps.md"))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    drivers = {part.strip().upper() for part in args.drivers.split(",") if part.strip()}
    rows: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("actions_202603_D*.jsonl")):
        driver_id = _driver_id(path)
        if drivers and driver_id not in drivers:
            continue
        records = _load_jsonl(path)
        rows.extend(_idle_traps(driver_id, records, min_wait_minutes=max(1, int(args.min_wait_minutes))))

    rows.sort(key=lambda row: row["trap_score"], reverse=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(rows), encoding="utf-8")
    out_path.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {out_path}")
    print(json.dumps(rows[:20], ensure_ascii=False, indent=2))
    return 0


def _idle_traps(driver_id: str, records: list[dict[str, Any]], *, min_wait_minutes: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        action = _action(record)
        if action.get("action") != "wait":
            continue
        wait_minutes = _float(record.get("action_exec_cost_minutes"))
        if wait_minutes < min_wait_minutes:
            continue
        prev_order = _previous_action(records, idx, {"take_order", "reposition"})
        prev_real_order = _previous_action(records, idx, {"take_order"})
        next_order = _next_action(records, idx, {"take_order"})
        wait_start = _progress_before(record)
        prev_result = prev_order.get("result") if prev_order else {}
        prev_action = _action(prev_order) if prev_order else {}
        prev_real_result = prev_real_order.get("result") if prev_real_order else {}
        prev_real_action = _action(prev_real_order) if prev_real_order else {}
        next_action = _action(next_order) if next_order else {}
        pickup = _float(prev_result.get("pickup_deadhead_km")) if isinstance(prev_result, dict) else 0.0
        haul = _float(prev_result.get("haul_distance_km")) if isinstance(prev_result, dict) else 0.0
        real_pickup = _float(prev_real_result.get("pickup_deadhead_km")) if isinstance(prev_real_result, dict) else 0.0
        real_haul = _float(prev_real_result.get("haul_distance_km")) if isinstance(prev_real_result, dict) else 0.0
        trap_score = wait_minutes + 1.8 * pickup + 80.0 * max(0.0, pickup / max(1.0, haul) - 0.5)
        real_trap_score = wait_minutes + 1.8 * real_pickup + 80.0 * max(0.0, real_pickup / max(1.0, real_haul) - 0.5)
        if wait_start is not None and wait_start // 1440 + 1 >= 24:
            trap_score *= 1.2
            real_trap_score *= 1.2
        if wait_start is not None and wait_start // 1440 + 1 >= 28:
            trap_score *= 1.25
            real_trap_score *= 1.25
        rows.append(
            {
                "driver_id": driver_id,
                "wait_step": _int(record.get("step")),
                "wait_minutes": round(wait_minutes, 2),
                "wait_start": _format_progress(wait_start),
                "wait_day": None if wait_start is None else wait_start // 1440 + 1,
                "previous_step": _int(prev_order.get("step")) if prev_order else None,
                "previous_action": prev_action.get("action") if prev_action else None,
                "previous_cargo": _cargo_id(prev_action),
                "previous_pickup_km": round(pickup, 2),
                "previous_haul_km": round(haul, 2),
                "previous_pickup_haul_ratio": round(pickup / max(1.0, haul), 3),
                "previous_end_time": prev_order.get("simulation_end_time") if prev_order else None,
                "root_order_step": _int(prev_real_order.get("step")) if prev_real_order else None,
                "root_order_cargo": _cargo_id(prev_real_action),
                "root_order_pickup_km": round(real_pickup, 2),
                "root_order_haul_km": round(real_haul, 2),
                "root_order_pickup_haul_ratio": round(real_pickup / max(1.0, real_haul), 3),
                "root_order_end_time": prev_real_order.get("simulation_end_time") if prev_real_order else None,
                "next_step": _int(next_order.get("step")) if next_order else None,
                "next_cargo": _cargo_id(next_action),
                "trap_score": round(trap_score, 2),
                "root_trap_score": round(real_trap_score, 2),
            }
        )
    return rows


def _render(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Idle Trap Analysis",
        "",
        "Long waits are usually symptoms. This report points to the previous order/reposition that led into the idle state.",
        "",
        "| driver | wait_step | wait_h | wait_start | prev_step | prev_action | prev_cargo | root_order | root_cargo | root_p/h | next_step | next_cargo | trap_score | root_score |",
        "| --- | ---: | ---: | --- | ---: | --- | --- | ---: | --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in rows[:80]:
        lines.append(
            f"| {row['driver_id']} | {row['wait_step']} | {row['wait_minutes'] / 60.0:.2f} | {row['wait_start']} | "
            f"{row.get('previous_step') or ''} | {row.get('previous_action') or ''} | {row.get('previous_cargo') or ''} | "
            f"{row.get('root_order_step') or ''} | {row.get('root_order_cargo') or ''} | {row['root_order_pickup_haul_ratio']:.3f} | "
            f"{row.get('next_step') or ''} | {row.get('next_cargo') or ''} | {row['trap_score']:.2f} | {row['root_trap_score']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Probe Use",
            "",
            "- Probe the root_order_step when previous_step is a home/reposition action.",
            "- Probe the previous_step, not the wait_step, when previous_step is itself a take_order.",
            "- Prefer sequence pairs previous_step:wait_step or previous_step:next_step.",
            "- Candidate generation should penalize after-state idle risk, not only current order net/NPH.",
        ]
    )
    return "\n".join(lines) + "\n"


def _previous_action(records: list[dict[str, Any]], idx: int, kinds: set[str]) -> dict[str, Any] | None:
    for pos in range(idx - 1, -1, -1):
        if _action(records[pos]).get("action") in kinds:
            return records[pos]
    return None


def _next_action(records: list[dict[str, Any]], idx: int, kinds: set[str]) -> dict[str, Any] | None:
    for pos in range(idx + 1, len(records)):
        if _action(records[pos]).get("action") in kinds:
            return records[pos]
    return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _action(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    action = record.get("action")
    return action if isinstance(action, dict) else {}


def _cargo_id(action: dict[str, Any]) -> str:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    return str(params.get("cargo_id") or "")


def _progress_before(record: dict[str, Any]) -> int | None:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    try:
        return int(result.get("simulation_progress_minutes")) - int(float(record.get("step_elapsed_minutes", 0) or 0))
    except (TypeError, ValueError):
        return None


def _format_progress(progress: int | None) -> str:
    if progress is None:
        return ""
    day = progress // 1440 + 1
    minute = progress % 1440
    return f"D{day:02d} {minute // 60:02d}:{minute % 60:02d}"


def _driver_id(path: Path) -> str:
    for part in path.stem.split("_"):
        if part.startswith("D") and len(part) == 4:
            return part.upper()
    return path.stem


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
