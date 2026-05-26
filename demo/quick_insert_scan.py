"""Fast exact-scored one-order insertion scanner.

This exploration harness inserts one candidate take_order after an existing
step, replays the remaining action skeleton, and lets invalid downstream orders
drop out.  It targets route-length changes that one-step replacement scans miss.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from calc_monthly_income import (
    build_drivers_payload,
    compute_income,
    load_cargo_map,
    load_driver_cost_map,
    load_driver_preference_rules,
)
from server.bench.settings import load_settings
from splice_replay_probe import _candidate_cargos, _extract_net_income, _used_cargo_ids
from surgery_replay_actions import _progress, _read_actions, _replay


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast broad one-order insertion scan.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--after-step", action="append", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--out-root", default="")
    parser.add_argument("--candidate-limit", type=int, default=400)
    parser.add_argument("--max-pickup-km", type=float, default=360.0)
    parser.add_argument("--min-current-net", type=float, default=-1800.0)
    parser.add_argument("--sort-key", choices=["current_net", "nph", "gross"], default="current_net")
    parser.add_argument("--query-cost", type=int, default=0)
    parser.add_argument("--top-keep", type=int, default=20)
    parser.add_argument("--fill-to-horizon", action="store_true", default=True)
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    settings = load_settings()
    speed = float(settings.reposition_speed_km_per_hour)
    cargo_map = load_cargo_map(settings.cargo_dataset_path)
    driver_cost_map = load_driver_cost_map(settings.drivers_path)
    driver_preference_rules = load_driver_preference_rules(settings.drivers_path)
    cost_per_km = float(driver_cost_map.get(driver_id, 1.5))
    rows = _read_actions(Path(args.source))
    if not rows:
        raise ValueError(f"empty source: {args.source}")

    tag = args.tag.strip() or f"{driver_id.lower()}_{int(time.time())}"
    out_root = Path(args.out_root) if args.out_root else DEMO_ROOT / "results" / "quick_insert_scan" / tag
    out_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_root / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_action_path = tmp_dir / f"actions_202603_{driver_id}_quick_insert.jsonl"
    all_original_used = _used_cargo_ids(rows)

    all_results: list[dict[str, Any]] = []
    for after_text in args.after_step:
        after_step = int(after_text)
        insert_idx = _find_insert_index(rows, after_step)
        prefix = rows[:insert_idx]
        prefix_replayed, _ = _replay(
            prefix,
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=False,
            fill_to_horizon=False,
        )
        progress = _progress(prefix_replayed)
        pos = (prefix_replayed[-1].get("position_after", {}) if prefix_replayed else rows[0].get("position_before", {})) or {}
        # Avoid reusing a cargo that already exists in the preserved skeleton.
        candidates = _candidate_cargos(
            cargo_map,
            used_ids=all_original_used,
            original_cargo="",
            progress=progress,
            query_cost=max(0, int(args.query_cost)),
            lat=float(pos.get("lat", 0.0)),
            lng=float(pos.get("lng", 0.0)),
            speed_km_per_hour=speed,
            cost_per_km=cost_per_km,
            max_pickup_km=max(1.0, float(args.max_pickup_km)),
            min_current_net=float(args.min_current_net),
            limit=max(1, int(args.candidate_limit)),
            sort_key=str(args.sort_key),
        )

        step_results: list[dict[str, Any]] = []
        for rank, cand in enumerate(candidates, start=1):
            try:
                inserted = _fake_take_row(driver_id, str(cand["cargo_id"]), query_cost=max(0, int(args.query_cost)))
                replayed, skipped = _replay(
                    prefix + [inserted] + rows[insert_idx:],
                    driver_id=driver_id,
                    cargo_map=cargo_map,
                    speed_km_per_hour=speed,
                    insert_after_step={},
                    skip_invalid=True,
                    fill_to_horizon=bool(args.fill_to_horizon),
                )
                _write_jsonl(tmp_action_path, replayed)
                monthly = _score_action_file(
                    tmp_action_path,
                    cargo_map=cargo_map,
                    driver_cost_map=driver_cost_map,
                    driver_preference_rules=driver_preference_rules,
                    speed_km_per_hour=speed,
                )
                payload = next((d for d in monthly.get("drivers", []) if d.get("driver_id") == driver_id), {})
                income = _extract_net_income(payload.get("income"))
                result = {
                    "after_step": after_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "income": income,
                    "income_detail": payload.get("income"),
                    "skipped_count": len(skipped),
                    "skipped": skipped[:10],
                    "candidate": cand,
                }
            except Exception as exc:
                result = {
                    "after_step": after_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "error": repr(exc),
                    "candidate": cand,
                }
            step_results.append(result)
            all_results.append(result)

        step_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
        (out_root / f"after_{after_step:04d}_top.json").write_text(
            json.dumps(step_results[: max(1, int(args.top_keep))], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"after_step": after_step, "best": step_results[0] if step_results else {}}, ensure_ascii=False), flush=True)

    all_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
    (out_root / "summary.json").write_text(json.dumps(all_results[: max(1, int(args.top_keep))], ensure_ascii=False, indent=2), encoding="utf-8")
    if all_results:
        best = all_results[0]
        insert_idx = _find_insert_index(rows, int(best["after_step"]))
        inserted = _fake_take_row(driver_id, str(best["cargo_id"]), query_cost=max(0, int(args.query_cost)))
        replayed, skipped = _replay(
            rows[:insert_idx] + [inserted] + rows[insert_idx:],
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=True,
            fill_to_horizon=bool(args.fill_to_horizon),
        )
        best_path = out_root / f"actions_202603_{driver_id}_insert_best.jsonl"
        _write_jsonl(best_path, replayed)
        best["best_action_path"] = str(best_path)
        best["best_skipped_count"] = len(skipped)
        print("best_overall:", json.dumps(best, ensure_ascii=False), flush=True)
    print(f"written: {out_root}", flush=True)
    return 0


def _find_insert_index(rows: list[dict[str, Any]], after_step: int) -> int:
    if after_step <= 0:
        return 0
    for idx, row in enumerate(rows):
        if int(row.get("step", -1)) == after_step:
            return idx + 1
    raise KeyError(f"step not found: {after_step}")


def _fake_take_row(driver_id: str, cargo_id: str, *, query_cost: int) -> dict[str, Any]:
    return {
        "step": -1,
        "driver_id": driver_id,
        "step_elapsed_minutes": 0,
        "query_scan_cost_minutes": max(0, int(query_cost)),
        "action_exec_cost_minutes": 0,
        "position_before": {"lat": 0.0, "lng": 0.0},
        "position_after": {"lat": 0.0, "lng": 0.0},
        "simulation_end_time": "",
        "token_usage": _zero_usage(),
        "action": {"action": "take_order", "params": {"cargo_id": cargo_id}, "model_usage": _zero_usage()},
        "result": {},
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _score_action_file(
    action_path: Path,
    *,
    cargo_map: dict[str, dict[str, Any]],
    driver_cost_map: dict[str, float],
    driver_preference_rules: dict[str, Any],
    speed_km_per_hour: float,
) -> dict[str, Any]:
    income, token_by_driver, total_token_usage, validation_errors, preference_details = compute_income(
        [action_path],
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
        "result_files_count": 1,
        "drivers": drivers,
        "summary": {
            "total_net_income_all_drivers": round(sum(float(d["income"]["net_income"]) for d in drivers), 2),
            "total_preference_penalty": round(sum(float(d["income"].get("preference_penalty", 0.0)) for d in drivers), 2),
            "total_token_usage": total_token_usage,
            "failed_driver_count": len(validation_errors),
            "failed_drivers": validation_errors,
        },
    }


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}


if __name__ == "__main__":
    raise SystemExit(main())
