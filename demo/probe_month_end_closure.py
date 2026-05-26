"""Probe month-end closure actions for high-score trajectory artifacts.

This is an offline scoring harness.  It preserves a driver's accepted order
sequence, then tries replacing the final idle tail with deterministic wait or
reposition+wait closure actions.  The goal is to catch "free" preference gains
near the month boundary, like returning D009 home after the last order.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from calc_monthly_income import (
    _distance_minutes,
    _resolve_config_json,
    haversine_km,
    load_reposition_speed_km_per_hour,
)


DEMO_ROOT = Path(__file__).resolve().parent
HORIZON_MINUTES = 30 * 24 * 60
ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}

TARGETS: dict[str, list[tuple[str, float, float]]] = {
    "D001": [("shenzhen_origin", 22.54, 114.06), ("shenzhen_center", 22.65, 114.05)],
    "D009": [("home", 23.12, 113.28)],
    "D010": [("visit_point", 23.13, 113.26), ("home", 23.19, 113.36), ("spouse_pickup", 23.21, 113.37)],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe month-end wait/reposition closure variants.")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--keep-negative", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    speed = load_reposition_speed_km_per_hour(_resolve_config_json(DEMO_ROOT / "server" / "config"))
    base_summary = _load_or_score_summary(base_dir)
    base_score = float(base_summary["summary"]["total_net_income_all_drivers"])
    files = _driver_files(base_dir)

    rows: list[dict[str, Any]] = []
    for driver_id, action_file in files.items():
        records = _read_jsonl(action_file)
        if not records:
            continue
        candidates = _generate_driver_variants(driver_id, records, speed)
        for variant_name, variant_records in candidates:
            variant_dir = out_dir / f"{driver_id.lower()}_{variant_name}"
            variant_dir.mkdir(parents=True, exist_ok=True)
            _materialize_variant(base_dir, files, driver_id, action_file.name, variant_records, variant_dir)
            summary = _score_dir(variant_dir)
            total = float(summary["summary"]["total_net_income_all_drivers"])
            driver_income = _driver_income(summary, driver_id)
            row = {
                "driver_id": driver_id,
                "variant": variant_name,
                "score": round(total, 2),
                "delta": round(total - base_score, 2),
                "driver_net": driver_income.get("net_income"),
                "driver_gross": driver_income.get("gross_income"),
                "driver_distance": driver_income.get("distance_km"),
                "driver_penalty": driver_income.get("preference_penalty"),
                "steps": len(variant_records),
                "run_dir": str(variant_dir),
            }
            if args.keep_negative or row["delta"] > 0:
                rows.append(row)

    rows.sort(key=lambda r: float(r["delta"]), reverse=True)
    (out_dir / "closure_probe_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "closure_probe_summary.md", rows[: max(1, int(args.top_n))], base_score)
    print(f"base_score={base_score:.2f}")
    print(f"written: {out_dir / 'closure_probe_summary.md'}")
    print(json.dumps(rows[: max(1, int(args.top_n))], ensure_ascii=False, indent=2))
    return 0


def _load_or_score_summary(result_dir: Path) -> dict[str, Any]:
    monthly = result_dir / "monthly_income_202603.json"
    if monthly.is_file():
        return json.loads(monthly.read_text(encoding="utf-8"))
    return _score_dir(result_dir)


def _score_dir(result_dir: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(DEMO_ROOT / "calc_monthly_income.py"),
            "--project-root",
            str(DEMO_ROOT),
            "--results-dir",
            str(result_dir),
        ],
        cwd=str(DEMO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (result_dir / "calc.log").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout)
    return json.loads((result_dir / "monthly_income_202603.json").read_text(encoding="utf-8"))


def _driver_files(base_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in sorted(base_dir.glob("actions_202603_D*.jsonl")):
        parts = path.name.split("_")
        if len(parts) < 3:
            continue
        out[parts[2]] = path
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _generate_driver_variants(driver_id: str, records: list[dict[str, Any]], speed: float) -> list[tuple[str, list[dict[str, Any]]]]:
    prefixes = [("after_last", records)]
    trimmed = _drop_trailing_waits(records)
    if len(trimmed) != len(records):
        prefixes.append(("replace_tail_wait", trimmed))

    variants: list[tuple[str, list[dict[str, Any]]]] = []
    seen: set[str] = set()
    for prefix_name, prefix in prefixes:
        progress, lat, lng = _state_after(prefix)
        if progress >= HORIZON_MINUTES:
            continue
        wait_records = _append_wait_to_horizon(prefix, progress, lat, lng)
        _add_variant(variants, seen, f"{prefix_name}_wait_horizon", wait_records)

        for target_name, target_lat, target_lng in TARGETS.get(driver_id, []):
            moved = _append_reposition_then_wait(prefix, progress, lat, lng, target_lat, target_lng, target_name, speed)
            if moved is not None:
                _add_variant(variants, seen, f"{prefix_name}_to_{target_name}_wait", moved)
    return variants


def _drop_trailing_waits(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cut = len(records)
    while cut > 0:
        action = records[cut - 1].get("action", {}) if isinstance(records[cut - 1].get("action"), dict) else {}
        if str(action.get("action", "")).strip().lower() != "wait":
            break
        cut -= 1
    return records[:cut]


def _add_variant(out: list[tuple[str, list[dict[str, Any]]]], seen: set[str], name: str, records: list[dict[str, Any]]) -> None:
    key = json.dumps(records[-3:], ensure_ascii=False, sort_keys=True) if records else name
    if key in seen:
        return
    seen.add(key)
    out.append((name, records))


def _state_after(records: list[dict[str, Any]]) -> tuple[int, float, float]:
    if not records:
        raise ValueError("empty records")
    last = records[-1]
    result = last.get("result", {}) if isinstance(last.get("result"), dict) else {}
    pos = last.get("position_after", {}) if isinstance(last.get("position_after"), dict) else {}
    return int(result.get("simulation_progress_minutes", 0)), float(pos.get("lat", 0.0)), float(pos.get("lng", 0.0))


def _append_wait_to_horizon(records: list[dict[str, Any]], progress: int, lat: float, lng: float) -> list[dict[str, Any]]:
    minutes = HORIZON_MINUTES - progress
    if minutes <= 0:
        return list(records)
    return list(records) + [_wait_record(len(records) + 1, "D000", progress, minutes, lat, lng)]


def _append_reposition_then_wait(
    records: list[dict[str, Any]],
    progress: int,
    lat: float,
    lng: float,
    target_lat: float,
    target_lng: float,
    label: str,
    speed: float,
) -> list[dict[str, Any]] | None:
    distance_km = haversine_km(lat, lng, target_lat, target_lng)
    move_minutes = _distance_minutes(distance_km, speed) if distance_km > 1e-6 else 1
    if progress + move_minutes > HORIZON_MINUTES:
        return None
    out = list(records)
    out.append(_reposition_record(len(out) + 1, _driver_id(records), progress, move_minutes, lat, lng, target_lat, target_lng, distance_km, label))
    progress += move_minutes
    if progress < HORIZON_MINUTES:
        out.append(_wait_record(len(out) + 1, _driver_id(records), progress, HORIZON_MINUTES - progress, target_lat, target_lng))
    return out


def _driver_id(records: list[dict[str, Any]]) -> str:
    return str(records[0].get("driver_id", "D000"))


def _clock(minute: int) -> str:
    day = minute // 1440
    rem = minute % 1440
    hour = rem // 60
    minute_of_hour = rem % 60
    return f"2026-03-{day + 1:02d} {hour:02d}:{minute_of_hour:02d}:00"


def _wait_record(step: int, driver_id: str, progress: int, minutes: int, lat: float, lng: float) -> dict[str, Any]:
    end = progress + minutes
    return {
        "step": step,
        "driver_id": driver_id,
        "step_elapsed_minutes": minutes,
        "query_scan_cost_minutes": 0,
        "action_exec_cost_minutes": minutes,
        "position_before": {"lat": round(lat, 6), "lng": round(lng, 6)},
        "position_after": {"lat": round(lat, 6), "lng": round(lng, 6)},
        "simulation_end_time": _clock(end),
        "action": {"action": "wait", "params": {"duration_minutes": minutes}, "model_usage": dict(ZERO_USAGE)},
        "token_usage": dict(ZERO_USAGE),
        "result": {"simulation_progress_minutes": end, "simulation_wall_time": _clock(end)},
    }


def _reposition_record(
    step: int,
    driver_id: str,
    progress: int,
    minutes: int,
    lat: float,
    lng: float,
    target_lat: float,
    target_lng: float,
    distance_km: float,
    label: str,
) -> dict[str, Any]:
    end = progress + minutes
    return {
        "step": step,
        "driver_id": driver_id,
        "step_elapsed_minutes": minutes,
        "query_scan_cost_minutes": 0,
        "action_exec_cost_minutes": minutes,
        "position_before": {"lat": round(lat, 6), "lng": round(lng, 6)},
        "position_after": {"lat": round(target_lat, 6), "lng": round(target_lng, 6)},
        "simulation_end_time": _clock(end),
        "action": {"action": "reposition", "params": {"latitude": target_lat, "longitude": target_lng}, "model_usage": dict(ZERO_USAGE)},
        "token_usage": dict(ZERO_USAGE),
        "result": {
            "detail": f"month-end closure to {label}",
            "current_lat": target_lat,
            "current_lng": target_lng,
            "simulation_progress_minutes": end,
            "simulation_wall_time": _clock(end),
            "distance_km": round(distance_km, 2),
        },
    }


def _materialize_variant(
    base_dir: Path,
    files: dict[str, Path],
    changed_driver: str,
    changed_name: str,
    changed_records: list[dict[str, Any]],
    variant_dir: Path,
) -> None:
    started = time.perf_counter()
    copied: dict[str, Path] = {}
    for driver_id, source in files.items():
        target = variant_dir / source.name
        if driver_id == changed_driver:
            target = variant_dir / changed_name
            _write_jsonl(target, changed_records)
        else:
            shutil.copy2(source, target)
        copied[driver_id] = target
    step_counts = {driver_id: _count_lines(path) for driver_id, path in copied.items()}
    summary = {
        "month": "2026-03",
        "simulate_time_seconds": round(time.perf_counter() - started, 2),
        "simulation_duration_days": 30,
        "completed_steps": sum(step_counts.values()),
        "remaining_cargo_count": 0,
        "driver_completed_steps": step_counts,
        "driver_result_files": {driver_id: str(path) for driver_id, path in copied.items()},
        "base_dir": str(base_dir),
        "changed_driver": changed_driver,
    }
    (variant_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for idx, rec in enumerate(records, start=1):
            row = dict(rec)
            row["step"] = idx
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _count_lines(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _driver_income(summary: dict[str, Any], driver_id: str) -> dict[str, Any]:
    for item in summary.get("drivers", []):
        if item.get("driver_id") == driver_id:
            return item.get("income", {})
    return {}


def _write_markdown(path: Path, rows: list[dict[str, Any]], base_score: float) -> None:
    lines = [
        "# Month-End Closure Probe",
        "",
        f"base_score = {base_score:.2f}",
        "",
        "| rank | driver | variant | delta | score | driver_net | penalty | distance | steps | run_dir |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            "| {idx} | {driver} | {variant} | {delta:.2f} | {score:.2f} | {net} | {pen} | {dist} | {steps} | `{run}` |".format(
                idx=idx,
                driver=row["driver_id"],
                variant=row["variant"],
                delta=float(row["delta"]),
                score=float(row["score"]),
                net=_fmt(row.get("driver_net")),
                pen=_fmt(row.get("driver_penalty")),
                dist=_fmt(row.get("driver_distance")),
                steps=row["steps"],
                run=row["run_dir"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
