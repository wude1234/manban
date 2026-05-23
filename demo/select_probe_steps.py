"""Select suspicious action steps for counterfactual rollout probes.

This helper reads existing simulator action JSONL files and ranks steps that
are likely to hide long-horizon regret: long pickup deadhead, long elapsed time,
large waits, reposition branches, high query scan cost, and late-month states.
It does not score alternatives itself; it only chooses where the exact
full-tail probe should spend time.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank action steps for rollout probing.")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--drivers", default="D001,D002,D003,D004,D005,D006,D007,D008,D009,D010")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-step", type=int, default=1)
    parser.add_argument("--max-step", type=int, default=9999)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    drivers = [item.strip().upper() for item in args.drivers.split(",") if item.strip()]
    rows: list[dict[str, Any]] = []
    for driver_id in drivers:
        actions = _load_actions(results_dir, driver_id)
        ranked = [
            row
            for row in (_score_record(driver_id, rec) for rec in actions)
            if args.min_step <= int(row["step"]) <= args.max_step
        ]
        ranked.sort(key=lambda row: float(row["probe_score"]), reverse=True)
        rows.extend(ranked[: max(1, args.top_n)])

    text = _render(rows, top_n=args.top_n)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        out_path.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)
    return 0


def _load_actions(results_dir: Path, driver_id: str) -> list[dict[str, Any]]:
    matches = sorted(results_dir.glob(f"actions_202603_{driver_id}_*.jsonl"))
    if not matches:
        return []
    # Prefer the latest direct default run.
    path = matches[-1]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _score_record(driver_id: str, rec: dict[str, Any]) -> dict[str, Any]:
    action = rec.get("action") if isinstance(rec.get("action"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
    kind = str(action.get("action", "")).strip()
    step = int(rec.get("step", 0) or 0)
    elapsed = float(rec.get("step_elapsed_minutes", 0) or 0)
    scan = float(rec.get("query_scan_cost_minutes", 0) or 0)
    pickup = float(result.get("pickup_deadhead_km", 0.0) or 0.0)
    haul = float(result.get("haul_distance_km", 0.0) or 0.0)
    accepted = bool(result.get("accepted", False))
    progress = _parse_progress(rec)
    day = progress // 1440 + 1 if progress is not None else None
    late_weight = 1.0 + (0.20 if day and day >= 24 else 0.0) + (0.25 if day and day >= 28 else 0.0)

    if kind == "take_order":
        pickup_ratio = pickup / max(haul, 1.0)
        base = pickup * 1.8 + elapsed * 0.22 + scan * 0.8
        base += max(0.0, pickup_ratio - 0.35) * 90.0
        if accepted:
            base += 15.0
    elif kind == "wait":
        duration = float(params.get("duration_minutes", 0) or 0)
        base = duration * 0.65 + scan * 0.8
        if duration >= 180:
            base += 60.0
    elif kind == "reposition":
        base = elapsed * 0.7 + scan * 0.8 + 80.0
    else:
        base = elapsed * 0.2 + scan * 0.8

    # Query scan cost is a real time tax in this simulator and often marks a
    # noisy candidate set where a smaller or different branch can win.
    if scan >= 40:
        base += 25.0
    if elapsed >= 600:
        base += 40.0
    if pickup >= 80:
        base += 50.0

    return {
        "driver_id": driver_id,
        "step": step,
        "probe_score": round(base * late_weight, 2),
        "day": day,
        "action": kind,
        "cargo_id": str(params.get("cargo_id", "")).strip(),
        "wait_minutes": int(float(params.get("duration_minutes", 0) or 0)) if kind == "wait" else 0,
        "elapsed_minutes": round(elapsed, 2),
        "query_scan_minutes": round(scan, 2),
        "pickup_deadhead_km": round(pickup, 2),
        "haul_distance_km": round(haul, 2),
        "simulation_end_time": rec.get("simulation_end_time"),
    }


def _parse_progress(rec: dict[str, Any]) -> int | None:
    result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
    value = result.get("simulation_progress_minutes")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _render(rows: list[dict[str, Any]], *, top_n: int) -> str:
    by_driver: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_driver.setdefault(str(row["driver_id"]), []).append(row)
    lines = ["# Probe Step Candidates", ""]
    for driver_id in sorted(by_driver):
        items = sorted(by_driver[driver_id], key=lambda row: float(row["probe_score"]), reverse=True)[:top_n]
        steps = ",".join(str(row["step"]) for row in items)
        lines.append(f"## {driver_id}")
        lines.append("")
        lines.append(f"target_steps = `{steps}`")
        lines.append("")
        lines.append("| step | score | day | action | cargo | elapsed | scan | pickup | haul | end_time |")
        lines.append("| ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |")
        for row in items:
            lines.append(
                f"| {row['step']} | {row['probe_score']:.2f} | {row.get('day') or ''} | "
                f"{row['action']} | {row.get('cargo_id', '')} | {row['elapsed_minutes']:.2f} | "
                f"{row['query_scan_minutes']:.2f} | {row['pickup_deadhead_km']:.2f} | "
                f"{row['haul_distance_km']:.2f} | {row.get('simulation_end_time', '')} |"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
