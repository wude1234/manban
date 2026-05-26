"""Probe one-step cargo replacement on an existing trajectory artifact.

This is a high-score exploration tool, not an online submission agent.  It keeps
an existing action skeleton, replaces one take_order step with candidate cargos,
then exactly replays the downstream actions that still fit.  The goal is to find
local route surgery points where a non-greedy cargo can improve the whole-month
score without re-mining an entire driver route.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from calc_monthly_income import (
    _distance_minutes,
    build_drivers_payload,
    compute_income,
    haversine_km,
    load_cargo_map,
    load_driver_cost_map,
    load_driver_preference_rules,
)
from server.bench.settings import load_settings
from surgery_replay_actions import (
    HORIZON_MINUTES,
    _progress,
    _read_actions,
    _replay,
)


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Search one-step cargo replacement on a replayed action file.")
    parser.add_argument("--driver", required=True, help="Driver id, e.g. D010.")
    parser.add_argument("--source", required=True, help="Existing actions_202603_*.jsonl to modify.")
    parser.add_argument(
        "--source-step",
        action="append",
        required=True,
        help="Existing action step number to replace. Can be repeated.",
    )
    parser.add_argument("--out-root", default="", help="Output root. Defaults to results/splice_replay_probe/<tag>.")
    parser.add_argument("--tag", default="", help="Run tag used when --out-root is omitted.")
    parser.add_argument("--candidate-limit", type=int, default=80)
    parser.add_argument("--max-pickup-km", type=float, default=260.0)
    parser.add_argument("--min-current-net", type=float, default=-800.0)
    parser.add_argument("--sort-key", choices=["current_net", "nph", "gross"], default="current_net")
    parser.add_argument("--skip-invalid", action="store_true", default=True)
    parser.add_argument("--no-skip-invalid", action="store_false", dest="skip_invalid")
    parser.add_argument("--fill-to-horizon", action="store_true", default=True)
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    settings = load_settings()
    speed = float(settings.reposition_speed_km_per_hour)
    driver_cost_map = load_driver_cost_map(settings.drivers_path)
    driver_preference_rules = load_driver_preference_rules(settings.drivers_path)
    cost_per_km = float(driver_cost_map.get(driver_id, 1.5))
    cargo_map = load_cargo_map(settings.cargo_dataset_path)
    rows = _read_actions(Path(args.source))
    if not rows:
        raise ValueError(f"empty source: {args.source}")

    tag = args.tag.strip() or f"{driver_id.lower()}_{int(time.time())}"
    out_root = Path(args.out_root) if args.out_root else DEMO_ROOT / "results" / "splice_replay_probe" / tag
    out_root.mkdir(parents=True, exist_ok=True)

    all_results: list[dict[str, Any]] = []
    for step_text in args.source_step:
        source_step = int(step_text)
        target_idx = _find_step_index(rows, source_step)
        target_row = rows[target_idx]
        target_action = (target_row.get("action") or {}).get("action")
        if target_action != "take_order":
            raise ValueError(f"source step {source_step} is not take_order: {target_action!r}")

        original_cargo = str(((target_row.get("action") or {}).get("params") or {}).get("cargo_id", ""))
        prefix_rows = rows[:target_idx]
        prefix_replayed, _ = _replay(
            prefix_rows,
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=False,
            fill_to_horizon=False,
        )
        progress = _progress(prefix_replayed)
        if prefix_replayed:
            pos = prefix_replayed[-1].get("position_after", {}) or {}
        else:
            pos = target_row.get("position_before", {}) or {}
        lat = float(pos.get("lat", 0.0))
        lng = float(pos.get("lng", 0.0))
        query_cost = int(target_row.get("query_scan_cost_minutes", 0) or 0)
        used_ids = _used_cargo_ids(prefix_replayed)
        candidates = _candidate_cargos(
            cargo_map,
            used_ids=used_ids,
            original_cargo=original_cargo,
            progress=progress,
            query_cost=query_cost,
            lat=lat,
            lng=lng,
            speed_km_per_hour=speed,
            cost_per_km=cost_per_km,
            max_pickup_km=max(1.0, float(args.max_pickup_km)),
            min_current_net=float(args.min_current_net),
            limit=max(1, int(args.candidate_limit)),
            sort_key=str(args.sort_key),
        )
        step_dir = out_root / f"step_{source_step:04d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

        step_results: list[dict[str, Any]] = []
        for rank, cand in enumerate(candidates, start=1):
            rows2 = _replace_cargo(rows, target_idx, str(cand["cargo_id"]))
            cand_dir = step_dir / f"{rank:03d}_{cand['cargo_id']}"
            cand_dir.mkdir(parents=True, exist_ok=True)
            try:
                income, skipped = _score_rows(
                    rows2,
                    driver_id=driver_id,
                    cargo_map=cargo_map,
                    driver_cost_map=driver_cost_map,
                    driver_preference_rules=driver_preference_rules,
                    speed_km_per_hour=speed,
                    out_dir=cand_dir,
                    skip_invalid=bool(args.skip_invalid),
                    fill_to_horizon=bool(args.fill_to_horizon),
                )
                result = {
                    "source_step": source_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "original_cargo": original_cargo,
                    "income": income,
                    "skipped_count": len(skipped),
                    "skipped": skipped[:10],
                    "candidate": cand,
                    "out_dir": str(cand_dir),
                }
            except Exception as exc:  # keep probing other alternatives
                result = {
                    "source_step": source_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "original_cargo": original_cargo,
                    "error": repr(exc),
                    "candidate": cand,
                    "out_dir": str(cand_dir),
                }
            step_results.append(result)
            all_results.append(result)
        step_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
        (step_dir / "results.json").write_text(json.dumps(step_results, ensure_ascii=False, indent=2), encoding="utf-8")
        best = step_results[0] if step_results else {}
        print(json.dumps({"source_step": source_step, "original_cargo": original_cargo, "best": best}, ensure_ascii=False))

    all_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
    (out_root / "summary.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    if all_results:
        print("best_overall:", json.dumps(all_results[0], ensure_ascii=False))
    print(f"written: {out_root}")
    return 0


def _find_step_index(rows: list[dict[str, Any]], source_step: int) -> int:
    for idx, row in enumerate(rows):
        if int(row.get("step", -1)) == source_step:
            return idx
    raise KeyError(f"step not found: {source_step}")


def _used_cargo_ids(rows: list[dict[str, Any]]) -> set[str]:
    used: set[str] = set()
    for row in rows:
        action = row.get("action") or {}
        if action.get("action") != "take_order":
            continue
        params = action.get("params") or {}
        cargo_id = str(params.get("cargo_id", "")).strip()
        if cargo_id:
            used.add(cargo_id)
    return used


def _candidate_cargos(
    cargo_map: dict[str, dict[str, Any]],
    *,
    used_ids: set[str],
    original_cargo: str,
    progress: int,
    query_cost: int,
    lat: float,
    lng: float,
    speed_km_per_hour: float,
    cost_per_km: float,
    max_pickup_km: float,
    min_current_net: float,
    limit: int,
    sort_key: str,
) -> list[dict[str, Any]]:
    action_start = progress + query_cost
    candidates: list[dict[str, Any]] = []
    for cargo_id, cargo in cargo_map.items():
        if cargo_id in used_ids or cargo_id == original_cargo:
            continue
        if not (int(cargo["create_minutes"]) <= action_start <= int(cargo["remove_minutes"])):
            continue
        pickup_km = haversine_km(lat, lng, float(cargo["start_lat"]), float(cargo["start_lng"]))
        if pickup_km > max_pickup_km:
            continue
        pickup_minutes = _distance_minutes(pickup_km, speed_km_per_hour) if pickup_km > 1e-6 else 0
        arrival = action_start + pickup_minutes
        load_start = cargo.get("load_start_minutes")
        load_end = cargo.get("load_end_minutes")
        wait_minutes = 0
        if isinstance(load_start, int) and isinstance(load_end, int):
            if arrival > load_end:
                continue
            wait_minutes = max(0, load_start - arrival)
        finish = action_start + pickup_minutes + wait_minutes + int(cargo["cost_time_minutes"])
        if finish > HORIZON_MINUTES:
            continue
        gross = float(cargo["price"])
        haul_km = float(cargo["distance_km"])
        current_net = gross - cost_per_km * (pickup_km + haul_km)
        if current_net < min_current_net:
            continue
        elapsed = max(1, finish - progress)
        nph = current_net / elapsed * 60.0
        candidates.append(
            {
                "cargo_id": cargo_id,
                "cargo_name": cargo.get("cargo_name", ""),
                "gross": round(gross, 2),
                "current_net": round(current_net, 2),
                "nph": round(nph, 2),
                "pickup_km": round(pickup_km, 2),
                "haul_km": round(haul_km, 2),
                "wait_minutes": int(wait_minutes),
                "finish_minutes": int(finish),
                "end_lat": round(float(cargo["end_lat"]), 6),
                "end_lng": round(float(cargo["end_lng"]), 6),
            }
        )
    if sort_key == "nph":
        candidates.sort(key=lambda item: (float(item["nph"]), float(item["current_net"])), reverse=True)
    elif sort_key == "gross":
        candidates.sort(key=lambda item: (float(item["gross"]), float(item["current_net"])), reverse=True)
    else:
        candidates.sort(key=lambda item: (float(item["current_net"]), float(item["nph"])), reverse=True)
    return candidates[:limit]


def _replace_cargo(rows: list[dict[str, Any]], target_idx: int, cargo_id: str) -> list[dict[str, Any]]:
    rows2 = [json.loads(json.dumps(row, ensure_ascii=False)) for row in rows]
    params = rows2[target_idx].setdefault("action", {}).setdefault("params", {})
    params["cargo_id"] = str(cargo_id)
    return rows2


def _score_rows(
    rows: list[dict[str, Any]],
    *,
    driver_id: str,
    cargo_map: dict[str, dict[str, Any]],
    driver_cost_map: dict[str, float],
    driver_preference_rules: dict[str, Any],
    speed_km_per_hour: float,
    out_dir: Path,
    skip_invalid: bool,
    fill_to_horizon: bool,
) -> tuple[float, list[dict[str, Any]]]:
    replayed, skipped = _replay(
        rows,
        driver_id=driver_id,
        cargo_map=cargo_map,
        speed_km_per_hour=speed_km_per_hour,
        insert_after_step={},
        skip_invalid=skip_invalid,
        fill_to_horizon=fill_to_horizon,
    )
    action_path = out_dir / f"actions_202603_{driver_id}_splice.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in replayed:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "simulate_time_seconds": 0.0,
        "completed_steps": len(replayed),
        "remaining_cargo_count": 0,
        "simulation_progress_minutes": _progress(replayed),
        "driver_completed_steps": {driver_id: len(replayed)},
        "driver_result_files": {driver_id: str(action_path.resolve())},
        "simulation_duration_days": 30,
        "splice_replay": {"skipped": skipped},
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    monthly = _score_action_files(
        [action_path],
        cargo_map=cargo_map,
        driver_cost_map=driver_cost_map,
        driver_preference_rules=driver_preference_rules,
        speed_km_per_hour=speed_km_per_hour,
    )
    (out_dir / "monthly_income_202603.json").write_text(json.dumps(monthly, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = next((d for d in monthly.get("drivers", []) if d.get("driver_id") == driver_id), {})
    shutil.copy2(action_path, out_dir / f"best_source_{driver_id}.jsonl")
    return _extract_net_income(payload.get("income")), skipped


def _score_action_files(
    files: list[Path],
    *,
    cargo_map: dict[str, dict[str, Any]],
    driver_cost_map: dict[str, float],
    driver_preference_rules: dict[str, Any],
    speed_km_per_hour: float,
) -> dict[str, Any]:
    income, token_by_driver, total_token_usage, validation_errors, preference_details = compute_income(
        files,
        cargo_map,
        driver_cost_map,
        driver_preference_rules,
        reposition_speed_km_per_hour=speed_km_per_hour,
        simulation_duration_days=30,
    )
    drivers = build_drivers_payload(income, token_by_driver, validation_errors, preference_details)
    return {
        "month": "2026-03",
        "simulate_time_seconds": 0.0,
        "result_files_count": len(files),
        "drivers": drivers,
        "summary": {
            "total_net_income_all_drivers": round(sum(float(d["income"]["net_income"]) for d in drivers), 2),
            "total_preference_penalty": round(sum(float(d["income"].get("preference_penalty", 0.0)) for d in drivers), 2),
            "total_token_usage": total_token_usage,
            "failed_driver_count": len(validation_errors),
            "failed_drivers": validation_errors,
        },
        "cost_meaning": "cost = distance_km * cost_per_km (driver cost per km)",
        "cost_metric": "net_income = gross_income - (distance_km * cost_per_km)",
    }


def _extract_net_income(income: Any) -> float:
    if isinstance(income, (int, float)):
        return float(income)
    if isinstance(income, dict):
        for key in ("net_income", "total_net_income", "score"):
            value = income.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return -1e18


if __name__ == "__main__":
    raise SystemExit(main())
