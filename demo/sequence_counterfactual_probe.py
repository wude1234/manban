"""Exact two-step counterfactual rollout probe.

This harness is stricter than the offline beam planner and broader than the
one-step counterfactual probe:

1. Replay the base policy to a first decision step.
2. Try a small set of first-step actions.
3. Rebase the trajectory under the policy until a second decision step.
4. Try a small set of second-step actions.
5. Hand the tail back to the base policy and score with calc_monthly_income.

It is intentionally an exploration tool, not a submission strategy.  The goal
is to find sequence-level route repairs after single-step regret mining has
saturated.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from counterfactual_rollout_probe import (
    DEMO_ROOT,
    FeatureSettings,
    SimState,
    _action_key,
    _action_label,
    _apply_action,
    _apply_preset_env,
    _apply_recorded_action,
    _clean_action,
    _clone_state,
    _decide,
    _driver_income,
    _env_int,
    _float_or_none,
    _fmt,
    _load_base_strategy,
    _make_root_state,
    _parse_int_list,
    _parse_int_set,
    _parse_reposition_points,
    _record_action,
    _score_run,
    _with_zero_usage,
    _write_run,
)
from server.bench.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Exact two-step counterfactual rollout probe.")
    parser.add_argument("--driver", required=True, help="Driver ID, e.g. D006.")
    parser.add_argument("--preset", default="hot_v61_d004_step7dg_step41fs_step93")
    parser.add_argument(
        "--pairs",
        required=True,
        help="Comma-separated first:second step pairs, e.g. 17:86,23:89.",
    )
    parser.add_argument("--top-k-first", type=int, default=3)
    parser.add_argument("--top-k-second", type=int, default=3)
    parser.add_argument(
        "--value-k-first",
        type=int,
        default=0,
        help="Add first-step cargo branches with high destination/future value even if they are not top score.",
    )
    parser.add_argument(
        "--value-k-second",
        type=int,
        default=0,
        help="Add second-step cargo branches with high destination/future value even if they are not top score.",
    )
    parser.add_argument("--value-max-score-drop", type=float, default=250.0)
    parser.add_argument("--value-destination-weight", type=float, default=120.0)
    parser.add_argument("--value-opportunity-weight", type=float, default=0.35)
    parser.add_argument("--value-net-weight", type=float, default=0.04)
    parser.add_argument("--value-nph-weight", type=float, default=0.25)
    parser.add_argument("--max-first-branches", type=int, default=4)
    parser.add_argument("--max-second-branches", type=int, default=5)
    parser.add_argument("--tail-max-steps", type=int, default=500)
    parser.add_argument("--horizon-minutes", type=int, default=30 * 1440)
    parser.add_argument("--first-extra-waits", default="")
    parser.add_argument("--second-extra-waits", default="")
    parser.add_argument(
        "--first-reposition-points",
        default="",
        help="label:lat:lng entries separated by comma or semicolon.",
    )
    parser.add_argument(
        "--second-reposition-points",
        default="",
        help="label:lat:lng entries separated by comma or semicolon.",
    )
    parser.add_argument("--baseline-score", type=float, default=None)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    pairs = _parse_pairs(args.pairs)
    if not pairs:
        raise ValueError("--pairs is empty")

    _apply_preset_env(args.preset)
    settings = load_settings()
    feature_settings = FeatureSettings(
        speed_km_per_hour=settings.reposition_speed_km_per_hour,
        simulation_horizon_minutes=int(args.horizon_minutes),
        fallback_wait_minutes=max(1, _env_int("AGENT_FALLBACK_WAIT_MINUTES", 60)),
    )

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(driver_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sequence_probe_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    prefix_cache: dict[int, SimState] = {}
    first_waits = _parse_int_list(args.first_extra_waits)
    second_waits = _parse_int_list(args.second_extra_waits)
    first_repos = _parse_reposition_points(args.first_reposition_points)
    second_repos = _parse_reposition_points(args.second_reposition_points)

    for first_step, second_step in pairs:
        if second_step <= first_step:
            rows.append({"first_step": first_step, "second_step": second_step, "status": "invalid_pair"})
            continue
        prefix = prefix_cache.get(first_step)
        if prefix is None:
            prefix = _run_prefix_to_decision(
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                target_step=first_step,
            )
            prefix_cache[first_step] = prefix

        first_step_start = prefix.progress()
        first_rule, first_diag = _decide(prefix, driver_id, settings, feature_settings)
        first_candidates = _sequence_branch_candidates(
            first_rule,
            first_diag,
            top_k=max(1, args.top_k_first),
            value_k=max(0, args.value_k_first),
            value_max_score_drop=float(args.value_max_score_drop),
            value_destination_weight=float(args.value_destination_weight),
            value_opportunity_weight=float(args.value_opportunity_weight),
            value_net_weight=float(args.value_net_weight),
            value_nph_weight=float(args.value_nph_weight),
            extra_waits=first_waits,
            reposition_points=first_repos,
        )[: max(1, args.max_first_branches)]
        if not first_candidates:
            rows.append({"first_step": first_step, "second_step": second_step, "status": "no_first_candidates"})
            continue

        for first_rank, first_action in enumerate(first_candidates, start=1):
            after_first = _clone_state(prefix)
            try:
                _apply_branch_action(
                    after_first,
                    driver_id,
                    first_action,
                    settings,
                    feature_settings,
                    step_start=first_step_start,
                )
            except Exception as exc:
                rows.append(
                    {
                        "first_step": first_step,
                        "second_step": second_step,
                        "first_rank": first_rank,
                        "first_action": _clean_action(first_action),
                        "status": "first_apply_failed",
                        "error": repr(exc),
                    }
                )
                continue

            rebased = _advance_to_decision(
                after_first,
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                target_step=second_step,
            )
            if rebased is None:
                rows.append(
                    {
                        "first_step": first_step,
                        "second_step": second_step,
                        "first_rank": first_rank,
                        "first_action": _clean_action(first_action),
                        "status": "second_step_unreachable",
                    }
                )
                continue

            second_step_start = rebased.progress()
            second_rule, second_diag = _decide(rebased, driver_id, settings, feature_settings)
            second_candidates = _sequence_branch_candidates(
                second_rule,
                second_diag,
                top_k=max(1, args.top_k_second),
                value_k=max(0, args.value_k_second),
                value_max_score_drop=float(args.value_max_score_drop),
                value_destination_weight=float(args.value_destination_weight),
                value_opportunity_weight=float(args.value_opportunity_weight),
                value_net_weight=float(args.value_net_weight),
                value_nph_weight=float(args.value_nph_weight),
                extra_waits=second_waits,
                reposition_points=second_repos,
            )[: max(1, args.max_second_branches)]
            if not second_candidates:
                rows.append(
                    {
                        "first_step": first_step,
                        "second_step": second_step,
                        "first_rank": first_rank,
                        "first_action": _clean_action(first_action),
                        "status": "no_second_candidates",
                    }
                )
                continue

            for second_rank, second_action in enumerate(second_candidates, start=1):
                branch = _clone_state(rebased)
                try:
                    _apply_branch_action(
                        branch,
                        driver_id,
                        second_action,
                        settings,
                        feature_settings,
                        step_start=second_step_start,
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "first_step": first_step,
                            "second_step": second_step,
                            "first_rank": first_rank,
                            "second_rank": second_rank,
                            "first_action": _clean_action(first_action),
                            "second_action": _clean_action(second_action),
                            "status": "second_apply_failed",
                            "error": repr(exc),
                        }
                    )
                    continue

                branch = _complete_with_policy(
                    branch,
                    driver_id=driver_id,
                    settings=settings,
                    feature_settings=feature_settings,
                    max_steps=max(0, int(args.tail_max_steps)),
                )
                cand_dir = (
                    out_dir
                    / f"pair_{first_step:03d}_{second_step:03d}"
                    / f"f{first_rank:02d}_{_action_label(first_action)}__s{second_rank:02d}_{_action_label(second_action)}"
                )
                cand_dir.mkdir(parents=True, exist_ok=True)
                _write_run(cand_dir, driver_id, branch, settings, simulate_time_seconds=round(time.perf_counter() - started, 2))
                score_payload = _score_run(cand_dir)
                income = _driver_income(score_payload, driver_id) if score_payload else {}
                score = _float_or_none(income.get("net_income"))
                rows.append(
                    {
                        "first_step": first_step,
                        "second_step": second_step,
                        "first_rank": first_rank,
                        "second_rank": second_rank,
                        "first_action": _clean_action(first_action),
                        "second_action": _clean_action(second_action),
                        "is_rule_first": _action_key(first_action) == _action_key(first_rule),
                        "is_rule_second": _action_key(second_action) == _action_key(second_rule),
                        "score": score,
                        "delta_vs_baseline": None if score is None or args.baseline_score is None else round(score - args.baseline_score, 2),
                        "gross": _float_or_none(income.get("gross_income")),
                        "distance": _float_or_none(income.get("distance_km")),
                        "penalty": _float_or_none(income.get("preference_penalty")),
                        "steps": len(branch.history),
                        "progress_minutes": branch.progress(),
                        "status": "ok",
                        "run_dir": str(cand_dir),
                    }
                )

    rows.sort(key=lambda row: float(row.get("score") or -1e18), reverse=True)
    (out_dir / "sequence_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "sequence_summary.md", driver_id, args.preset, args.baseline_score, rows)
    print(f"written: {out_dir / 'sequence_summary.md'}")
    print(json.dumps(rows[: min(len(rows), 20)], ensure_ascii=False, indent=2))
    return 0


def _run_prefix_to_decision(
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    target_step: int,
) -> SimState:
    state = _make_root_state(settings, driver_id)
    return _advance_to_decision(
        state,
        driver_id=driver_id,
        settings=settings,
        feature_settings=feature_settings,
        target_step=target_step,
    ) or state


def _advance_to_decision(
    state: SimState,
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    target_step: int,
) -> SimState | None:
    if target_step < 1:
        raise ValueError("target_step must be >= 1")
    branch = _clone_state(state)
    if len(branch.history) > target_step - 1:
        return None
    strategy = _load_base_strategy()
    while len(branch.history) < target_step - 1:
        if branch.progress() >= feature_settings.simulation_horizon_minutes or branch.repo.size <= 0:
            return None
        step_start = branch.progress()
        action, _diagnostics = _decide(branch, driver_id, settings, feature_settings, strategy=strategy)
        _apply_recorded_action(branch, driver_id, action, settings, feature_settings, step_start=step_start)
    return branch


def _complete_with_policy(
    state: SimState,
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    max_steps: int,
) -> SimState:
    branch = _clone_state(state)
    strategy = _load_base_strategy()
    for _ in range(max_steps):
        if branch.progress() >= feature_settings.simulation_horizon_minutes or branch.repo.size <= 0:
            break
        step_start = branch.progress()
        action, _diagnostics = _decide(branch, driver_id, settings, feature_settings, strategy=strategy)
        _apply_recorded_action(branch, driver_id, action, settings, feature_settings, step_start=step_start)
    return branch


def _apply_branch_action(
    state: SimState,
    driver_id: str,
    action: dict[str, Any],
    settings: Any,
    feature_settings: FeatureSettings,
    *,
    step_start: int,
) -> None:
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
    end_progress = state.progress()
    record = _record_action(
        step=len(state.history) + 1,
        driver_id=driver_id,
        step_start=step_start,
        before_status=before_status,
        after_status=after_status,
        after_query_progress=after_query_progress,
        end_progress=end_progress,
        action=_with_zero_usage(_clean_action(action)),
        result=result,
    )
    state.history.append(record)


def _sequence_branch_candidates(
    rule_action: dict[str, Any],
    diagnostics: dict[str, Any],
    *,
    top_k: int,
    value_k: int,
    value_max_score_drop: float,
    value_destination_weight: float,
    value_opportunity_weight: float,
    value_net_weight: float,
    value_nph_weight: float,
    extra_waits: list[int],
    reposition_points: list[tuple[str, float, float]],
) -> list[dict[str, Any]]:
    rows = diagnostics.get("selectable_features")
    candidates: list[dict[str, Any]] = []
    if isinstance(rows, list):
        valid = [item for item in rows if isinstance(item, dict)]
        valid.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        for item in valid[:top_k]:
            cargo_id = str(item.get("cargo_id", "")).strip()
            if cargo_id:
                candidates.append({"action": "take_order", "params": {"cargo_id": cargo_id}})
        if value_k > 0 and valid:
            best_score = float(valid[0].get("score", 0.0) or 0.0)
            value_rows = [
                item
                for item in valid
                if best_score - float(item.get("score", 0.0) or 0.0) <= value_max_score_drop
            ]
            value_rows.sort(
                key=lambda item: _candidate_future_value(
                    item,
                    destination_weight=value_destination_weight,
                    opportunity_weight=value_opportunity_weight,
                    net_weight=value_net_weight,
                    nph_weight=value_nph_weight,
                ),
                reverse=True,
            )
            for item in value_rows[:value_k]:
                cargo_id = str(item.get("cargo_id", "")).strip()
                if cargo_id:
                    candidates.append(
                        {
                            "action": "take_order",
                            "params": {"cargo_id": cargo_id},
                            "_probe_label": f"value_{cargo_id}",
                        }
                    )
    if rule_action:
        candidates.insert(0, _clean_action(rule_action))
    for minutes in extra_waits:
        candidates.append(
            {
                "action": "wait",
                "params": {"duration_minutes": minutes},
                "_probe_label": f"wait_{minutes}",
            }
        )
    for label, lat, lng in reposition_points:
        candidates.append(
            {
                "action": "reposition",
                "params": {"latitude": lat, "longitude": lng},
                "_probe_label": f"repos_{label}",
            }
        )
    return _dedupe_actions(candidates)


def _candidate_future_value(
    item: dict[str, Any],
    *,
    destination_weight: float,
    opportunity_weight: float,
    net_weight: float,
    nph_weight: float,
) -> float:
    return (
        destination_weight * _as_float(item.get("destination_hotspot_score"))
        + opportunity_weight * _as_float(item.get("destination_opportunity_value"))
        + net_weight * _as_float(item.get("estimated_net"))
        + nph_weight * _as_float(item.get("net_per_hour"))
    )


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_pairs(raw: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for part in raw.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"invalid pair: {item}")
        left, right = item.split(":", 1)
        pairs.append((int(float(left.strip())), int(float(right.strip()))))
    return pairs


def _write_markdown(path: Path, driver_id: str, preset: str, baseline_score: float | None, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Sequence Counterfactual Probe",
        "",
        f"- driver: `{driver_id}`",
        f"- preset: `{preset}`",
        f"- baseline_score: `{baseline_score if baseline_score is not None else ''}`",
        "",
        "| first | second | score | delta | penalty | first_action | second_action | run_dir |",
        "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        first_action = json.dumps(row.get("first_action"), ensure_ascii=False, separators=(",", ":"))
        second_action = json.dumps(row.get("second_action"), ensure_ascii=False, separators=(",", ":"))
        lines.append(
            f"| {row.get('first_step')} | {row.get('second_step')} | {_fmt(row.get('score'))} | "
            f"{_fmt(row.get('delta_vs_baseline'))} | {_fmt(row.get('penalty'))} | "
            f"`{first_action}` | `{second_action}` | `{row.get('run_dir', '')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_out_dir(driver_id: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEMO_ROOT / "results" / "sequence_counterfactual" / f"{ts}_{driver_id}"


if __name__ == "__main__":
    raise SystemExit(main())
