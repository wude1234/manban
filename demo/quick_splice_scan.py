"""Fast exact-scored one-step replacement scanner.

This is a high-score exploration harness, not a submission agent.  It reuses the
official income calculator in-process and only keeps summary rows plus the best
action file, so broad scans do not create thousands of per-candidate folders.
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
from splice_replay_probe import (
    _candidate_cargos,
    _extract_net_income,
    _find_step_index,
    _replace_cargo,
    _used_cargo_ids,
)
from surgery_replay_actions import _progress, _read_actions, _replay


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast broad one-step splice scan.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-step", action="append", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--out-root", default="")
    parser.add_argument("--candidate-limit", type=int, default=400)
    parser.add_argument("--max-pickup-km", type=float, default=360.0)
    parser.add_argument("--min-current-net", type=float, default=-1800.0)
    parser.add_argument("--sort-key", choices=["current_net", "nph", "gross"], default="current_net")
    parser.add_argument("--top-keep", type=int, default=20)
    parser.add_argument("--skip-invalid", action="store_true", default=True)
    parser.add_argument("--no-skip-invalid", action="store_false", dest="skip_invalid")
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
    out_root = Path(args.out_root) if args.out_root else DEMO_ROOT / "results" / "quick_splice_scan" / tag
    out_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_root / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_action_path = tmp_dir / f"actions_202603_{driver_id}_quick_splice.jsonl"

    all_results: list[dict[str, Any]] = []
    for step_text in args.source_step:
        source_step = int(step_text)
        target_idx = _find_step_index(rows, source_step)
        target_row = rows[target_idx]
        action = target_row.get("action") or {}
        if action.get("action") != "take_order":
            raise ValueError(f"source step {source_step} is not take_order")
        original_cargo = str((action.get("params") or {}).get("cargo_id", ""))

        prefix_replayed, _ = _replay(
            rows[:target_idx],
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=False,
            fill_to_horizon=False,
        )
        progress = _progress(prefix_replayed)
        pos = (prefix_replayed[-1].get("position_after", {}) if prefix_replayed else target_row.get("position_before", {})) or {}
        candidates = _candidate_cargos(
            cargo_map,
            used_ids=_used_cargo_ids(prefix_replayed),
            original_cargo=original_cargo,
            progress=progress,
            query_cost=int(target_row.get("query_scan_cost_minutes", 0) or 0),
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
                rows2 = _replace_cargo(rows, target_idx, str(cand["cargo_id"]))
                replayed, skipped = _replay(
                    rows2,
                    driver_id=driver_id,
                    cargo_map=cargo_map,
                    speed_km_per_hour=speed,
                    insert_after_step={},
                    skip_invalid=bool(args.skip_invalid),
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
                    "source_step": source_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "original_cargo": original_cargo,
                    "income": income,
                    "income_detail": payload.get("income"),
                    "skipped_count": len(skipped),
                    "skipped": skipped[:10],
                    "candidate": cand,
                }
            except Exception as exc:
                result = {
                    "source_step": source_step,
                    "rank": rank,
                    "cargo_id": cand["cargo_id"],
                    "original_cargo": original_cargo,
                    "error": repr(exc),
                    "candidate": cand,
                }
            step_results.append(result)
            all_results.append(result)

        step_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
        (out_root / f"step_{source_step:04d}_top.json").write_text(
            json.dumps(step_results[: max(1, int(args.top_keep))], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"source_step": source_step, "original_cargo": original_cargo, "best": step_results[0] if step_results else {}}, ensure_ascii=False), flush=True)

    all_results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
    (out_root / "summary.json").write_text(json.dumps(all_results[: max(1, int(args.top_keep))], ensure_ascii=False, indent=2), encoding="utf-8")
    if all_results:
        best = all_results[0]
        best_step = int(best["source_step"])
        best_idx = _find_step_index(rows, best_step)
        best_rows = _replace_cargo(rows, best_idx, str(best["cargo_id"]))
        replayed, skipped = _replay(
            best_rows,
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=bool(args.skip_invalid),
            fill_to_horizon=bool(args.fill_to_horizon),
        )
        best_path = out_root / f"actions_202603_{driver_id}_quick_best.jsonl"
        _write_jsonl(best_path, replayed)
        best["best_action_path"] = str(best_path)
        best["best_skipped_count"] = len(skipped)
        print("best_overall:", json.dumps(best, ensure_ascii=False), flush=True)
    print(f"written: {out_root}", flush=True)
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
