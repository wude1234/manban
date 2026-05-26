"""Fast exact-scored action deletion scanner.

This high-score harness removes one existing action, replays the rest of the
trajectory, and exact-scores the result.  It tests whether dropping a low-value
or preference-risky action unlocks a better downstream timing pattern.
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
from splice_replay_probe import _extract_net_income, _find_step_index
from surgery_replay_actions import _read_actions, _replay


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast exact-scored one-action deletion scan.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--delete-step", action="append", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--out-root", default="")
    parser.add_argument("--top-keep", type=int, default=40)
    parser.add_argument("--fill-to-horizon", action="store_true", default=True)
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    settings = load_settings()
    speed = float(settings.reposition_speed_km_per_hour)
    cargo_map = load_cargo_map(settings.cargo_dataset_path)
    driver_cost_map = load_driver_cost_map(settings.drivers_path)
    driver_preference_rules = load_driver_preference_rules(settings.drivers_path)
    rows = _read_actions(Path(args.source))
    if not rows:
        raise ValueError(f"empty source: {args.source}")

    tag = args.tag.strip() or f"{driver_id.lower()}_{int(time.time())}"
    out_root = Path(args.out_root) if args.out_root else DEMO_ROOT / "results" / "quick_delete_scan" / tag
    out_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_root / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_action_path = tmp_dir / f"actions_202603_{driver_id}_quick_delete.jsonl"

    results: list[dict[str, Any]] = []
    for step_text in args.delete_step:
        source_step = int(step_text)
        target_idx = _find_step_index(rows, source_step)
        target = rows[target_idx]
        try:
            replayed, skipped = _replay(
                rows[:target_idx] + rows[target_idx + 1 :],
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
            result = {
                "delete_step": source_step,
                "deleted_action": target.get("action"),
                "income": _extract_net_income(payload.get("income")),
                "income_detail": payload.get("income"),
                "skipped_count": len(skipped),
                "skipped": skipped[:10],
            }
        except Exception as exc:
            result = {"delete_step": source_step, "deleted_action": target.get("action"), "error": repr(exc)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    results.sort(key=lambda item: float(item.get("income", -1e18) or -1e18), reverse=True)
    (out_root / "summary.json").write_text(json.dumps(results[: max(1, int(args.top_keep))], ensure_ascii=False, indent=2), encoding="utf-8")
    if results:
        best = results[0]
        idx = _find_step_index(rows, int(best["delete_step"]))
        replayed, skipped = _replay(
            rows[:idx] + rows[idx + 1 :],
            driver_id=driver_id,
            cargo_map=cargo_map,
            speed_km_per_hour=speed,
            insert_after_step={},
            skip_invalid=True,
            fill_to_horizon=bool(args.fill_to_horizon),
        )
        best_path = out_root / f"actions_202603_{driver_id}_delete_best.jsonl"
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
