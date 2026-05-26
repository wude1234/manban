"""Replay an action JSONL after local wait/reposition surgery.

This is a high-score exploration utility for pre-recorded trajectory artifacts.
It does not call an agent.  It takes an existing valid driver trajectory,
inserts extra waits at selected positions, then recomputes all downstream timing
and distances for the same action skeleton where still feasible.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from calc_monthly_income import (
    _distance_minutes,
    haversine_km,
    load_cargo_map,
)
from server.bench.settings import load_settings


DEMO_ROOT = Path(__file__).resolve().parent
SIM_EPOCH = datetime(2026, 3, 1, 0, 0, 0)
HORIZON_MINUTES = 30 * 1440


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay an action file with inserted waits.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--insert-wait",
        action="append",
        default=[],
        help="Insert wait as after_step:minutes. Can be repeated.",
    )
    parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="Skip downstream take_order actions that no longer fit the cargo window.",
    )
    parser.add_argument("--fill-to-horizon", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    cargo_map = load_cargo_map(settings.cargo_dataset_path)
    source = Path(args.source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_actions(source)
    waits = _parse_waits(args.insert_wait)
    replayed, skipped = _replay(
        rows,
        driver_id=args.driver.strip().upper(),
        cargo_map=cargo_map,
        speed_km_per_hour=float(settings.reposition_speed_km_per_hour),
        insert_after_step=waits,
        skip_invalid=bool(args.skip_invalid),
        fill_to_horizon=bool(args.fill_to_horizon),
    )
    action_path = out_dir / f"actions_202603_{args.driver.strip().upper()}_surgery.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in replayed:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "simulate_time_seconds": 0.0,
        "completed_steps": len(replayed),
        "remaining_cargo_count": 0,
        "simulation_progress_minutes": _progress(replayed),
        "simulation_wall_time": _clock(_progress(replayed)) + ":00",
        "driver_completed_steps": {args.driver.strip().upper(): len(replayed)},
        "driver_result_files": {args.driver.strip().upper(): str(action_path.resolve())},
        "simulation_duration_days": int(settings.simulation_duration_days),
        "surgery": {"source": str(source), "insert_wait": args.insert_wait, "skipped": skipped},
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(DEMO_ROOT / "calc_monthly_income.py"),
            "--project-root",
            str(DEMO_ROOT),
            "--results-dir",
            str(out_dir),
        ],
        cwd=str(DEMO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (out_dir / "calc.log").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout, end="")
        return proc.returncode
    monthly = json.loads((out_dir / "monthly_income_202603.json").read_text(encoding="utf-8"))
    driver_payload = next((d for d in monthly.get("drivers", []) if d.get("driver_id") == args.driver.strip().upper()), {})
    print(json.dumps({"income": driver_payload.get("income"), "skipped": skipped, "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
    return 0


def _read_actions(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _parse_waits(items: list[str]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for item in items:
        if ":" not in item:
            raise ValueError(f"invalid --insert-wait {item!r}, expected after_step:minutes")
        step_s, minutes_s = item.split(":", 1)
        step = int(step_s)
        minutes = int(minutes_s)
        if step < 0 or minutes <= 0:
            raise ValueError(f"invalid --insert-wait {item!r}")
        out.setdefault(step, []).append(minutes)
    return out


def _replay(
    rows: list[dict[str, Any]],
    *,
    driver_id: str,
    cargo_map: dict[str, dict[str, Any]],
    speed_km_per_hour: float,
    insert_after_step: dict[int, list[int]],
    skip_invalid: bool,
    fill_to_horizon: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    progress = 0
    if not rows:
        return [], []
    pos0 = rows[0].get("position_before", {}) or {}
    lat = float(pos0.get("lat", 0.0))
    lng = float(pos0.get("lng", 0.0))
    out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        for minutes in insert_after_step.get(idx - 1, []):
            rec, progress, lat, lng = _make_wait(out, driver_id, progress, lat, lng, minutes, label="surgery inserted wait")
            out.append(rec)
        action_obj = row.get("action") or {}
        action_name = str(action_obj.get("action", "")).lower()
        params = action_obj.get("params", {}) or {}
        query_cost = int(row.get("query_scan_cost_minutes", 0) or 0)
        try:
            if action_name == "wait":
                minutes = int(params.get("duration_minutes", row.get("action_exec_cost_minutes", 0)) or 0)
                rec, progress, lat, lng = _make_wait(out, driver_id, progress, lat, lng, minutes, query_cost=query_cost)
            elif action_name == "reposition":
                rec, progress, lat, lng = _make_reposition(
                    out,
                    driver_id,
                    progress,
                    lat,
                    lng,
                    float(params["latitude"]),
                    float(params["longitude"]),
                    speed_km_per_hour=speed_km_per_hour,
                    query_cost=query_cost,
                )
            elif action_name == "take_order":
                rec, progress, lat, lng = _make_take(
                    out,
                    driver_id,
                    progress,
                    lat,
                    lng,
                    str(params["cargo_id"]),
                    cargo_map=cargo_map,
                    speed_km_per_hour=speed_km_per_hour,
                    query_cost=query_cost,
                )
            else:
                raise ValueError(f"unsupported action {action_name!r}")
        except Exception as exc:
            if not skip_invalid or action_name != "take_order":
                raise
            skipped.append({"source_step": idx, "cargo_id": params.get("cargo_id"), "reason": repr(exc), "progress": progress})
            continue
        out.append(rec)
    for minutes in insert_after_step.get(len(rows), []):
        rec, progress, lat, lng = _make_wait(out, driver_id, progress, lat, lng, minutes, label="surgery inserted wait")
        out.append(rec)
    if fill_to_horizon and progress < HORIZON_MINUTES:
        rec, progress, lat, lng = _make_wait(out, driver_id, progress, lat, lng, HORIZON_MINUTES - progress, label="fill horizon wait")
        out.append(rec)
    return out, skipped


def _make_wait(
    out: list[dict[str, Any]],
    driver_id: str,
    progress: int,
    lat: float,
    lng: float,
    minutes: int,
    *,
    query_cost: int = 0,
    label: str = "replayed wait",
) -> tuple[dict[str, Any], int, float, float]:
    end = min(HORIZON_MINUTES, progress + query_cost + max(0, minutes))
    exec_minutes = max(0, end - progress - query_cost)
    rec = _base_record(out, driver_id, progress, query_cost, exec_minutes, lat, lng, lat, lng)
    rec["action"] = {"action": "wait", "params": {"duration_minutes": exec_minutes}, "model_usage": _zero_usage()}
    rec["result"] = {"simulation_progress_minutes": end, "simulation_wall_time": _clock(end) + ":00", "detail": label}
    return rec, end, lat, lng


def _make_reposition(
    out: list[dict[str, Any]],
    driver_id: str,
    progress: int,
    lat: float,
    lng: float,
    target_lat: float,
    target_lng: float,
    *,
    speed_km_per_hour: float,
    query_cost: int,
) -> tuple[dict[str, Any], int, float, float]:
    distance = haversine_km(lat, lng, target_lat, target_lng)
    exec_minutes = _distance_minutes(distance, speed_km_per_hour)
    end = progress + query_cost + exec_minutes
    if end > HORIZON_MINUTES:
        raise ValueError("reposition exceeds horizon")
    rec = _base_record(out, driver_id, progress, query_cost, exec_minutes, lat, lng, target_lat, target_lng)
    rec["action"] = {
        "action": "reposition",
        "params": {"latitude": round(target_lat, 6), "longitude": round(target_lng, 6)},
        "model_usage": _zero_usage(),
    }
    rec["result"] = {
        "current_lat": round(target_lat, 6),
        "current_lng": round(target_lng, 6),
        "simulation_progress_minutes": end,
        "simulation_wall_time": _clock(end) + ":00",
        "distance_km": round(distance, 2),
    }
    return rec, end, target_lat, target_lng


def _make_take(
    out: list[dict[str, Any]],
    driver_id: str,
    progress: int,
    lat: float,
    lng: float,
    cargo_id: str,
    *,
    cargo_map: dict[str, dict[str, Any]],
    speed_km_per_hour: float,
    query_cost: int,
) -> tuple[dict[str, Any], int, float, float]:
    cargo = cargo_map[cargo_id]
    action_start = progress + query_cost
    if not (int(cargo["create_minutes"]) <= action_start <= int(cargo["remove_minutes"])):
        raise ValueError(f"cargo {cargo_id} not active at {action_start}")
    pickup_km = haversine_km(lat, lng, float(cargo["start_lat"]), float(cargo["start_lng"]))
    pickup_minutes = _distance_minutes(pickup_km, speed_km_per_hour) if pickup_km > 1e-6 else 0
    arrival = action_start + pickup_minutes
    wait_minutes = 0
    load_start = cargo.get("load_start_minutes")
    load_end = cargo.get("load_end_minutes")
    if isinstance(load_start, int) and isinstance(load_end, int):
        if arrival > load_end:
            raise ValueError(f"cargo {cargo_id} misses load window at {arrival}>{load_end}")
        wait_minutes = max(0, load_start - arrival)
    exec_minutes = pickup_minutes + wait_minutes + int(cargo["cost_time_minutes"])
    end = action_start + exec_minutes
    if end > HORIZON_MINUTES:
        raise ValueError(f"cargo {cargo_id} exceeds horizon")
    end_lat = float(cargo["end_lat"])
    end_lng = float(cargo["end_lng"])
    rec = _base_record(out, driver_id, progress, query_cost, exec_minutes, lat, lng, end_lat, end_lng)
    rec["action"] = {"action": "take_order", "params": {"cargo_id": cargo_id}, "model_usage": _zero_usage()}
    rec["result"] = {
        "accepted": True,
        "detail": "surgery replay accepted cargo",
        "driver_id": driver_id,
        "cargo_id": cargo_id,
        "simulation_progress_minutes": end,
        "simulation_wall_time": _clock(end) + ":00",
        "pickup_deadhead_km": round(pickup_km, 2),
        "haul_distance_km": round(float(cargo["distance_km"]), 2),
        "income_eligible": end <= HORIZON_MINUTES,
    }
    return rec, end, end_lat, end_lng


def _base_record(
    out: list[dict[str, Any]],
    driver_id: str,
    progress: int,
    query_cost: int,
    exec_minutes: int,
    before_lat: float,
    before_lng: float,
    after_lat: float,
    after_lng: float,
) -> dict[str, Any]:
    end = progress + query_cost + exec_minutes
    return {
        "step": len(out) + 1,
        "driver_id": driver_id,
        "step_elapsed_minutes": query_cost + exec_minutes,
        "query_scan_cost_minutes": query_cost,
        "action_exec_cost_minutes": exec_minutes,
        "position_before": {"lat": round(before_lat, 6), "lng": round(before_lng, 6)},
        "position_after": {"lat": round(after_lat, 6), "lng": round(after_lng, 6)},
        "simulation_end_time": _clock(end),
        "token_usage": _zero_usage(),
    }


def _progress(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    result = rows[-1].get("result", {}) or {}
    return int(result.get("simulation_progress_minutes", 0) or 0)


def _clock(minutes: int) -> str:
    return (SIM_EPOCH + timedelta(minutes=int(minutes))).strftime("%Y-%m-%d %H:%M:%S")


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}


if __name__ == "__main__":
    raise SystemExit(main())
