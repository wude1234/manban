"""Dynamic candidate-generation counterfactual probe.

This harness explores a different search mode from top-k reranking.  At a real
online decision step it generates extra actions from the observed market:

* deep value cargo candidates that may be outside the normal score band;
* reposition targets around valuable pickup/destination clusters;
* optional event waits around high-value cargo load windows.

Each branch is then handed back to the current base policy and scored with the
official monthly-income calculator.  Positive results still need to be
distilled into guarded online rules before they are submission candidates.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from counterfactual_rollout_probe import (
    DEMO_ROOT,
    FeatureSettings,
    _action_key,
    _action_label,
    _apply_action,
    _apply_preset_env,
    _clean_action,
    _clone_state,
    _decide,
    _driver_income,
    _driver_limit_env,
    _env_int,
    _float_or_none,
    _format_sim_clock,
    _load_base_strategy,
    _make_root_state,
    _parse_int_list,
    _parse_int_set,
    _record_action,
    _score_run,
    _with_zero_usage,
    _write_run,
)
from agent.feature_strategies.common import distance_to_minutes, haversine_km
from server.bench.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Dynamic candidate generation probe.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--preset", default="hot_v89_v88_d010_step103_105_sequence")
    parser.add_argument("--target-steps", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--deep-cargo-k", type=int, default=8)
    parser.add_argument("--deep-score-drop", type=float, default=2000.0)
    parser.add_argument("--reposition-k", type=int, default=8)
    parser.add_argument("--cluster-radius-km", type=float, default=35.0)
    parser.add_argument("--max-reposition-km", type=float, default=180.0)
    parser.add_argument("--point-sources", default="start,end", help="Comma-separated: start,end,centroid.")
    parser.add_argument("--event-waits", default="", help="Extra fixed waits plus 'load' for load-window waits.")
    parser.add_argument("--max-branches", type=int, default=24)
    parser.add_argument("--tail-max-steps", type=int, default=500)
    parser.add_argument("--horizon-minutes", type=int, default=30 * 1440)
    parser.add_argument("--baseline-score", type=float, default=None)
    parser.add_argument(
        "--force-query-on-target",
        action="store_true",
        help="Disable strategy pre-query actions only at target steps so wait/reposition guards cannot hide market alternatives.",
    )
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    target_steps = sorted(_parse_int_set(args.target_steps))
    if not target_steps:
        raise ValueError("--target-steps is empty")

    _apply_preset_env(args.preset)
    settings = load_settings()
    feature_settings = FeatureSettings(
        speed_km_per_hour=settings.reposition_speed_km_per_hour,
        simulation_horizon_minutes=int(args.horizon_minutes),
        fallback_wait_minutes=max(1, _env_int("AGENT_FALLBACK_WAIT_MINUTES", 60)),
    )

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(driver_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dynamic_probe_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    prefix_cache: dict[int, Any] = {}

    for target_step in target_steps:
        prefix = prefix_cache.get(target_step)
        if prefix is None:
            prefix = _run_prefix_to_decision(
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                target_step=target_step,
            )
            prefix_cache[target_step] = prefix

        step_start = prefix.progress()
        rule_action, diagnostics = _decide(
            prefix,
            driver_id,
            settings,
            feature_settings,
            disable_pre_query=bool(args.force_query_on_target),
        )
        after_query_progress = prefix.progress()
        candidates = _dynamic_branch_candidates(
            rule_action,
            diagnostics,
            settings=feature_settings,
            top_k=max(1, args.top_k),
            deep_cargo_k=max(0, args.deep_cargo_k),
            deep_score_drop=float(args.deep_score_drop),
            reposition_k=max(0, args.reposition_k),
            cluster_radius_km=max(1.0, float(args.cluster_radius_km)),
            max_reposition_km=max(1.0, float(args.max_reposition_km)),
            point_sources={part.strip().lower() for part in args.point_sources.split(",") if part.strip()},
            event_waits=str(args.event_waits),
            max_branches=max(1, int(args.max_branches)),
        )
        if not candidates:
            rows.append({"target_step": target_step, "status": "no_candidates", "rule_action": _clean_action(rule_action)})
            continue

        for rank, action in enumerate(candidates, start=1):
            branch = _clone_state(prefix)
            before_status = branch.manager.get_driver_status(driver_id)
            try:
                result = _apply_action(
                    branch.repo,
                    branch.manager,
                    driver_id,
                    action,
                    speed_km_per_hour=settings.reposition_speed_km_per_hour,
                    horizon_minutes=feature_settings.simulation_horizon_minutes,
                )
            except Exception as exc:
                rows.append(
                    {
                        "target_step": target_step,
                        "candidate_rank": rank,
                        "candidate_action": _clean_action(action),
                        "status": "apply_failed",
                        "error": repr(exc),
                    }
                )
                continue

            after_status = branch.manager.get_driver_status(driver_id)
            end_progress = branch.progress()
            record = _record_action(
                step=len(branch.history) + 1,
                driver_id=driver_id,
                step_start=step_start,
                before_status=before_status,
                after_status=after_status,
                after_query_progress=after_query_progress,
                end_progress=end_progress,
                action=_with_zero_usage(_clean_action(action)),
                result=result,
            )
            branch.history.append(record)
            branch = _complete_with_policy(
                branch,
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                max_steps=max(0, int(args.tail_max_steps)),
            )
            cand_dir = out_dir / f"step_{target_step:03d}" / f"candidate_{rank:02d}_{_action_label(action)}"
            cand_dir.mkdir(parents=True, exist_ok=True)
            _write_run(cand_dir, driver_id, branch, settings, simulate_time_seconds=round(time.perf_counter() - started, 2))
            score_payload = _score_run(cand_dir)
            income = _driver_income(score_payload, driver_id) if score_payload else {}
            score = _float_or_none(income.get("net_income"))
            rows.append(
                {
                    "target_step": target_step,
                    "candidate_rank": rank,
                    "candidate_action": _clean_action(action),
                    "candidate_label": str(action.get("_probe_label", "")),
                    "is_rule_action": _action_key(action) == _action_key(rule_action),
                    "score": score,
                    "delta_vs_baseline": None if score is None or args.baseline_score is None else round(score - args.baseline_score, 2),
                    "gross": _float_or_none(income.get("gross_income")),
                    "distance": _float_or_none(income.get("distance_km")),
                    "penalty": _float_or_none(income.get("preference_penalty")),
                    "steps": len(branch.history),
                    "progress_minutes": branch.progress(),
                    "simulation_wall_time": _format_sim_clock(branch.progress()),
                    "status": "ok",
                    "run_dir": str(cand_dir),
                }
            )

    rows.sort(key=lambda row: float(row.get("score") or -1e18), reverse=True)
    (out_dir / "dynamic_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "dynamic_summary.md", driver_id, args.preset, args.baseline_score, rows)
    print(f"written: {out_dir / 'dynamic_summary.md'}")
    print(json.dumps(rows[: min(len(rows), 24)], ensure_ascii=False, indent=2))
    return 0


def _run_prefix_to_decision(
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    target_step: int,
) -> Any:
    state = _make_root_state(settings, driver_id)
    strategy = _load_base_strategy()
    for _ in range(max(0, target_step - 1)):
        if state.progress() >= feature_settings.simulation_horizon_minutes or state.repo.size <= 0:
            break
        step_start = state.progress()
        action, _diagnostics = _decide(state, driver_id, settings, feature_settings, strategy=strategy)
        before_status = state.manager.get_driver_status(driver_id)
        after_query_progress = state.progress()
        result = _apply_action(
            state.repo,
            state.manager,
            driver_id,
            action,
            speed_km_per_hour=settings.reposition_speed_km_per_hour,
            horizon_minutes=feature_settings.simulation_horizon_minutes,
        )
        after_status = state.manager.get_driver_status(driver_id)
        state.history.append(
            _record_action(
                step=len(state.history) + 1,
                driver_id=driver_id,
                step_start=step_start,
                before_status=before_status,
                after_status=after_status,
                after_query_progress=after_query_progress,
                end_progress=state.progress(),
                action=_with_zero_usage(_clean_action(action)),
                result=result,
            )
        )
    return state


def _complete_with_policy(
    state: Any,
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    max_steps: int,
) -> Any:
    branch = _clone_state(state)
    strategy = _load_base_strategy()
    for _ in range(max_steps):
        if branch.progress() >= feature_settings.simulation_horizon_minutes or branch.repo.size <= 0:
            break
        step_start = branch.progress()
        action, _diagnostics = _decide(branch, driver_id, settings, feature_settings, strategy=strategy)
        before_status = branch.manager.get_driver_status(driver_id)
        after_query_progress = branch.progress()
        result = _apply_action(
            branch.repo,
            branch.manager,
            driver_id,
            action,
            speed_km_per_hour=settings.reposition_speed_km_per_hour,
            horizon_minutes=feature_settings.simulation_horizon_minutes,
        )
        after_status = branch.manager.get_driver_status(driver_id)
        branch.history.append(
            _record_action(
                step=len(branch.history) + 1,
                driver_id=driver_id,
                step_start=step_start,
                before_status=before_status,
                after_status=after_status,
                after_query_progress=after_query_progress,
                end_progress=branch.progress(),
                action=_with_zero_usage(_clean_action(action)),
                result=result,
            )
        )
    return branch


def _dynamic_branch_candidates(
    rule_action: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    settings: FeatureSettings,
    top_k: int,
    deep_cargo_k: int,
    deep_score_drop: float,
    reposition_k: int,
    cluster_radius_km: float,
    max_reposition_km: float,
    point_sources: set[str],
    event_waits: str,
    max_branches: int,
) -> list[dict[str, Any]]:
    rows = diagnostics.get("selectable_features")
    status = diagnostics.get("status") if isinstance(diagnostics.get("status"), dict) else {}
    current_lat = _as_float(status.get("current_lat"))
    current_lng = _as_float(status.get("current_lng"))
    valid = [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []
    valid.sort(key=lambda item: _as_float(item.get("score")), reverse=True)
    best_score = _as_float(valid[0].get("score")) if valid else 0.0

    actions: list[dict[str, Any]] = []
    if rule_action:
        actions.append(_label_action(_clean_action(rule_action), "rule"))

    for item in valid[:top_k]:
        cargo_id = str(item.get("cargo_id", "")).strip()
        if cargo_id:
            actions.append({"action": "take_order", "params": {"cargo_id": cargo_id}, "_probe_label": f"top_{cargo_id}"})

    deep_rows = [
        item
        for item in valid
        if best_score - _as_float(item.get("score")) <= deep_score_drop
    ]
    deep_rows.sort(key=lambda item: _deep_cargo_value(item, valid, settings), reverse=True)
    for item in deep_rows[:deep_cargo_k]:
        cargo_id = str(item.get("cargo_id", "")).strip()
        if cargo_id:
            actions.append({"action": "take_order", "params": {"cargo_id": cargo_id}, "_probe_label": f"deep_{cargo_id}"})

    if reposition_k > 0 and valid:
        point_rows = _dynamic_reposition_points(
            valid,
            current_lat=current_lat,
            current_lng=current_lng,
            point_sources=point_sources,
            cluster_radius_km=cluster_radius_km,
            max_reposition_km=max_reposition_km,
            limit=reposition_k,
            settings=settings,
        )
        for label, lat, lng, value in point_rows:
            actions.append(
                {
                    "action": "reposition",
                    "params": {"latitude": lat, "longitude": lng},
                    "_probe_label": f"dynrepos_{label}_{value:.1f}",
                }
            )

    fixed_waits = [v for v in _parse_int_list(event_waits.replace("load", "")) if v > 0]
    for minutes in fixed_waits:
        actions.append({"action": "wait", "params": {"duration_minutes": minutes}, "_probe_label": f"wait_{minutes}"})
    if "load" in {part.strip().lower() for part in event_waits.split(",")}:
        for minutes in _load_event_waits(valid, status, max_wait=720)[:6]:
            actions.append({"action": "wait", "params": {"duration_minutes": minutes}, "_probe_label": f"loadwait_{minutes}"})

    return _dedupe(actions)[:max_branches]


def _deep_cargo_value(item: dict[str, Any], rows: list[dict[str, Any]], settings: FeatureSettings) -> float:
    score = _as_float(item.get("score"))
    net = _as_float(item.get("estimated_net"))
    nph = _as_float(item.get("net_per_hour"))
    pickup = _as_float(item.get("pickup_minutes"))
    wait = _as_float(item.get("wait_minutes"))
    hotspot = _as_float(item.get("destination_hotspot_score"))
    visible_next = _visible_successor_value(item, rows, settings)
    slack = max(0.0, min(240.0, _as_float(item.get("lifecycle_slack_minutes"))))
    return score + 0.12 * net + 0.45 * nph + 80.0 * hotspot + 0.65 * visible_next + 0.03 * slack - 0.11 * pickup - 0.04 * wait


def _visible_successor_value(item: dict[str, Any], rows: list[dict[str, Any]], settings: FeatureSettings) -> float:
    finish = int(_as_float(item.get("finish_minutes")))
    end_lat = _as_float(item.get("end_lat"))
    end_lng = _as_float(item.get("end_lng"))
    cargo_id = str(item.get("cargo_id", ""))
    values: list[float] = []
    for other in rows:
        if str(other.get("cargo_id", "")) == cargo_id:
            continue
        pickup_km = haversine_km(end_lat, end_lng, _as_float(other.get("start_lat")), _as_float(other.get("start_lng")))
        pickup_minutes = distance_to_minutes(pickup_km, settings.speed_km_per_hour)
        if pickup_minutes > 180:
            continue
        arrival = finish + pickup_minutes
        load_end = other.get("load_end_minutes")
        if load_end is not None and arrival > int(_as_float(load_end)):
            continue
        remove_minutes = int(_as_float(other.get("remove_minutes")))
        if remove_minutes and remove_minutes < arrival:
            continue
        wait = max(0, int(_as_float(other.get("load_start_minutes"))) - arrival) if other.get("load_start_minutes") is not None else 0
        if wait > 240:
            continue
        value = 0.05 * _as_float(other.get("estimated_net")) + 0.35 * _as_float(other.get("net_per_hour"))
        value -= 0.16 * pickup_minutes + 2.2 * (wait / 60.0)
        value += 8.0 * _as_float(other.get("destination_hotspot_score"))
        values.append(value)
    return max(values, default=0.0)


def _dynamic_reposition_points(
    rows: list[dict[str, Any]],
    *,
    current_lat: float,
    current_lng: float,
    point_sources: set[str],
    cluster_radius_km: float,
    max_reposition_km: float,
    limit: int,
    settings: FeatureSettings,
) -> list[tuple[str, float, float, float]]:
    raw_points: list[tuple[str, float, float, float]] = []
    for item in rows:
        base = _point_item_value(item, rows, settings)
        if base <= 0:
            continue
        if "start" in point_sources:
            raw_points.append((f"start_{item.get('cargo_id')}", _as_float(item.get("start_lat")), _as_float(item.get("start_lng")), base))
        if "end" in point_sources:
            raw_points.append((f"end_{item.get('cargo_id')}", _as_float(item.get("end_lat")), _as_float(item.get("end_lng")), 0.72 * base))
    if "centroid" in point_sources:
        top = sorted(rows, key=lambda item: _point_item_value(item, rows, settings), reverse=True)[:12]
        if top:
            weight_sum = sum(max(1.0, _point_item_value(item, rows, settings)) for item in top)
            lat = sum(_as_float(item.get("start_lat")) * max(1.0, _point_item_value(item, rows, settings)) for item in top) / weight_sum
            lng = sum(_as_float(item.get("start_lng")) * max(1.0, _point_item_value(item, rows, settings)) for item in top) / weight_sum
            raw_points.append(("centroid_start", lat, lng, weight_sum / len(top)))

    scored: list[tuple[str, float, float, float]] = []
    for label, lat, lng, base in raw_points:
        if not lat or not lng:
            continue
        distance = haversine_km(current_lat, current_lng, lat, lng)
        if distance > max_reposition_km:
            continue
        cluster_value = _cluster_value(lat, lng, rows, cluster_radius_km, settings)
        value = cluster_value - 0.11 * distance
        if value <= 0:
            continue
        scored.append((label, round(lat, 5), round(lng, 5), value))

    scored.sort(key=lambda row: row[3], reverse=True)
    deduped: list[tuple[str, float, float, float]] = []
    for row in scored:
        _, lat, lng, _ = row
        if any(haversine_km(lat, lng, old_lat, old_lng) <= 8.0 for _, old_lat, old_lng, _ in deduped):
            continue
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def _point_item_value(item: dict[str, Any], rows: list[dict[str, Any]], settings: FeatureSettings) -> float:
    return (
        0.08 * max(0.0, _as_float(item.get("estimated_net")))
        + 0.50 * max(0.0, _as_float(item.get("net_per_hour")))
        + 35.0 * _as_float(item.get("destination_hotspot_score"))
        + 0.45 * _visible_successor_value(item, rows, settings)
        - 0.04 * max(0.0, _as_float(item.get("wait_minutes")))
    )


def _cluster_value(lat: float, lng: float, rows: list[dict[str, Any]], radius_km: float, settings: FeatureSettings) -> float:
    values: list[float] = []
    for item in rows:
        d = haversine_km(lat, lng, _as_float(item.get("start_lat")), _as_float(item.get("start_lng")))
        if d > radius_km:
            continue
        pickup_minutes = distance_to_minutes(d, settings.speed_km_per_hour)
        load_end = item.get("load_end_minutes")
        # Without simulating exact arrival after reposition, use current feasible
        # cargo value as a market-density proxy, discounted by local pickup.
        if load_end is not None and pickup_minutes > 240:
            continue
        value = _point_item_value(item, rows, settings) - 0.08 * pickup_minutes
        values.append(value)
    if not values:
        return 0.0
    values.sort(reverse=True)
    return values[0] + 0.35 * sum(values[1:4])


def _load_event_waits(rows: list[dict[str, Any]], status: dict[str, Any], *, max_wait: int) -> list[int]:
    current = int(_as_float(status.get("simulation_progress_minutes")))
    waits: set[int] = set()
    scored = sorted(rows, key=lambda item: _as_float(item.get("estimated_net")) + 6.0 * _as_float(item.get("net_per_hour")), reverse=True)
    for item in scored[:12]:
        load_start = item.get("load_start_minutes")
        if load_start is None:
            continue
        wait = int(_as_float(load_start)) - current
        if 15 <= wait <= max_wait:
            waits.add(wait)
    return sorted(waits)


def _label_action(action: dict[str, Any], label: str) -> dict[str, Any]:
    out = dict(action)
    out["_probe_label"] = label
    return out


def _dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for action in actions:
        key = _action_key(action)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def _as_float(value: Any) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _write_markdown(path: Path, driver_id: str, preset: str, baseline_score: float | None, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Dynamic Candidate Probe",
        "",
        f"driver = `{driver_id}`",
        f"preset = `{preset}`",
        f"baseline_score = `{baseline_score}`",
        "",
        "| step | rank | score | delta | penalty | label | action | run_dir |",
        "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows[:160]:
        lines.append(
            "| {step} | {rank} | {score} | {delta} | {penalty} | `{label}` | `{action}` | `{run_dir}` |".format(
                step=row.get("target_step", ""),
                rank=row.get("candidate_rank", ""),
                score=_fmt(row.get("score")),
                delta=_fmt(row.get("delta_vs_baseline")),
                penalty=_fmt(row.get("penalty")),
                label=row.get("candidate_label", ""),
                action=json.dumps(row.get("candidate_action"), ensure_ascii=False, separators=(",", ":")),
                run_dir=row.get("run_dir", ""),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _default_out_dir(driver_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEMO_ROOT / "results" / "dynamic_candidate_probe" / f"{stamp}_{driver_id}"


if __name__ == "__main__":
    raise SystemExit(main())
