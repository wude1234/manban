"""Compare two simulator action traces for one or more drivers.

This is a post-run diagnostic tool. It reads existing action JSONL outputs and
monthly income JSON files, then reports where two policies diverged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare action traces between two run directories.")
    parser.add_argument("--base-run", required=True, help="Baseline run directory containing run_summary_202603.json.")
    parser.add_argument("--new-run", required=True, help="New run directory containing run_summary_202603.json.")
    parser.add_argument("--drivers", default="D007,D010", help="Comma-separated driver IDs.")
    parser.add_argument("--context", type=int, default=2, help="Steps of context around each divergence.")
    parser.add_argument("--max-diffs", type=int, default=20, help="Maximum divergence blocks per driver.")
    args = parser.parse_args()

    base_run = Path(args.base_run)
    new_run = Path(args.new_run)
    drivers = [item.strip().upper() for item in args.drivers.split(",") if item.strip()]

    base_income = _load_income(base_run)
    new_income = _load_income(new_run)

    print(f"BASE_RUN {base_run}")
    print(f"NEW_RUN  {new_run}")
    print()
    print("INCOME_DELTA")
    for driver_id in drivers:
        b = base_income.get(driver_id, {})
        n = new_income.get(driver_id, {})
        print(
            f"{driver_id} "
            f"net={_num(n, 'net_income') - _num(b, 'net_income'):+.2f} "
            f"gross={_num(n, 'gross_income') - _num(b, 'gross_income'):+.2f} "
            f"distance={_num(n, 'distance_km') - _num(b, 'distance_km'):+.2f} "
            f"penalty={_num(n, 'preference_penalty') - _num(b, 'preference_penalty'):+.2f}"
        )

    print()
    for driver_id in drivers:
        print("=" * 88)
        print(f"DRIVER {driver_id}")
        base_actions = _load_driver_actions(base_run, driver_id)
        new_actions = _load_driver_actions(new_run, driver_id)
        _print_action_summary("base", base_actions)
        _print_action_summary("new ", new_actions)
        print()
        _print_first_divergences(base_actions, new_actions, context=args.context, max_diffs=args.max_diffs)
        print()

    return 0


def _load_income(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "monthly_income_202603.json"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, dict[str, Any]] = {}
    for item in data.get("drivers", []):
        if isinstance(item, dict):
            driver_id = str(item.get("driver_id", "")).strip().upper()
            income = item.get("income")
            if driver_id and isinstance(income, dict):
                out[driver_id] = income
    return out


def _load_driver_actions(run_dir: Path, driver_id: str) -> list[dict[str, Any]]:
    summary_path = run_dir / "run_summary_202603.json"
    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    files = summary.get("driver_result_files", {})
    action_file = files.get(driver_id)
    if not action_file:
        matches = sorted(run_dir.glob(f"actions_202603_{driver_id}_*.jsonl"))
        if not matches:
            raise FileNotFoundError(f"cannot find actions for {driver_id} in {run_dir}")
        action_file = str(matches[0])
    actions: list[dict[str, Any]] = []
    with Path(action_file).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                actions.append(json.loads(line))
    return actions


def _print_action_summary(label: str, actions: list[dict[str, Any]]) -> None:
    take = 0
    wait = 0
    reposition = 0
    accepted = 0
    elapsed = 0
    query_scan = 0
    cargo_ids: list[str] = []
    for rec in actions:
        action = rec.get("action") or {}
        kind = str(action.get("action", "")).strip()
        elapsed += int(rec.get("step_elapsed_minutes", 0) or 0)
        query_scan += int(rec.get("query_scan_cost_minutes", 0) or 0)
        if kind == "take_order":
            take += 1
            cargo_id = str((action.get("params") or {}).get("cargo_id", "")).strip()
            if cargo_id:
                cargo_ids.append(cargo_id)
            result = rec.get("result") or {}
            if bool(result.get("accepted", False)):
                accepted += 1
        elif kind == "wait":
            wait += 1
        elif kind == "reposition":
            reposition += 1
    print(
        f"{label}: steps={len(actions)} take={take} accepted={accepted} "
        f"wait={wait} reposition={reposition} elapsed={elapsed} query_scan={query_scan}"
    )
    print(f"{label}: first_take_ids={','.join(cargo_ids[:16])}")


def _print_first_divergences(
    base_actions: list[dict[str, Any]],
    new_actions: list[dict[str, Any]],
    *,
    context: int,
    max_diffs: int,
) -> None:
    base_keys = [_action_key(item) for item in base_actions]
    new_keys = [_action_key(item) for item in new_actions]
    min_len = min(len(base_keys), len(new_keys))
    diff_indices = [idx for idx in range(min_len) if base_keys[idx] != new_keys[idx]]
    if len(base_keys) != len(new_keys):
        diff_indices.append(min_len)
    if not diff_indices:
        print("NO_DIVERGENCE: action sequences match at step/action level.")
        return

    print(f"DIVERGENCES total_step_diffs={len(diff_indices)} first={diff_indices[0] + 1}")
    printed = 0
    used_blocks: set[int] = set()
    for idx in diff_indices:
        block_start = max(0, idx - context)
        if block_start in used_blocks:
            continue
        used_blocks.add(block_start)
        block_end = min(max(len(base_actions), len(new_actions)), idx + context + 1)
        print("-" * 88)
        print(f"DIFF_BLOCK around_step={idx + 1}")
        for j in range(block_start, block_end):
            b = _compact_record(base_actions[j]) if j < len(base_actions) else "<missing>"
            n = _compact_record(new_actions[j]) if j < len(new_actions) else "<missing>"
            marker = "==" if j < len(base_keys) and j < len(new_keys) and base_keys[j] == new_keys[j] else "!="
            print(f"step {j + 1:03d} {marker}")
            print(f"  base {b}")
            print(f"  new  {n}")
        printed += 1
        if printed >= max_diffs:
            break


def _action_key(record: dict[str, Any]) -> tuple[Any, ...]:
    action = record.get("action") or {}
    params = action.get("params") or {}
    kind = str(action.get("action", "")).strip()
    if kind == "take_order":
        return kind, str(params.get("cargo_id", "")).strip()
    if kind == "wait":
        return kind, int(params.get("duration_minutes", 0) or 0)
    if kind == "reposition":
        return kind, round(float(params.get("latitude", 0.0)), 4), round(float(params.get("longitude", 0.0)), 4)
    return kind, json.dumps(params, sort_keys=True, ensure_ascii=False)


def _compact_record(record: dict[str, Any]) -> str:
    action = record.get("action") or {}
    params = action.get("params") or {}
    result = record.get("result") or {}
    before = record.get("position_before") or {}
    after = record.get("position_after") or {}
    kind = str(action.get("action", "")).strip()
    if kind == "take_order":
        detail = f"take cargo={params.get('cargo_id')} accepted={result.get('accepted')}"
        if "pickup_deadhead_km" in result:
            detail += f" pickup={float(result.get('pickup_deadhead_km') or 0):.2f}"
        if "haul_distance_km" in result:
            detail += f" haul={float(result.get('haul_distance_km') or 0):.2f}"
    elif kind == "wait":
        detail = f"wait duration={params.get('duration_minutes')}"
    elif kind == "reposition":
        detail = f"reposition to=({params.get('latitude')},{params.get('longitude')})"
    else:
        detail = f"{kind} params={params}"
    return (
        f"{detail} elapsed={record.get('step_elapsed_minutes')} "
        f"scan={record.get('query_scan_cost_minutes')} end={record.get('simulation_end_time')} "
        f"pos=({before.get('lat')},{before.get('lng')})->({after.get('lat')},{after.get('lng')})"
    )


def _num(data: dict[str, Any], key: str) -> float:
    try:
        return float(data.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
