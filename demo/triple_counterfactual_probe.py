"""Exact three-step counterfactual rollout probe.

This is a narrow exploration harness for late-stage route-plan mining.  It is
not used by the submitted agent directly; positive traces must still be
distilled into guarded online rules and validated by a full grid run.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from counterfactual_rollout_probe import (
    FeatureSettings,
    _action_key,
    _action_label,
    _apply_preset_env,
    _clean_action,
    _clone_state,
    _decide,
    _driver_income,
    _env_int,
    _float_or_none,
    _parse_int_list,
    _parse_reposition_points,
    _score_run,
    _write_run,
)
from sequence_counterfactual_probe import (
    _advance_to_decision,
    _apply_branch_action,
    _complete_with_policy,
    _run_prefix_to_decision,
    _sequence_branch_candidates,
)
from server.bench.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Exact three-step counterfactual rollout probe.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--preset", default="hot_v76_d010_196038_106205150")
    parser.add_argument("--triples", required=True, help="Comma-separated a:b:c triples.")
    parser.add_argument("--top-k-first", type=int, default=3)
    parser.add_argument("--top-k-second", type=int, default=3)
    parser.add_argument("--top-k-third", type=int, default=3)
    parser.add_argument("--value-k-first", type=int, default=0)
    parser.add_argument("--value-k-second", type=int, default=0)
    parser.add_argument("--value-k-third", type=int, default=0)
    parser.add_argument("--value-max-score-drop", type=float, default=300.0)
    parser.add_argument("--value-destination-weight", type=float, default=120.0)
    parser.add_argument("--value-opportunity-weight", type=float, default=0.35)
    parser.add_argument("--value-net-weight", type=float, default=0.04)
    parser.add_argument("--value-nph-weight", type=float, default=0.25)
    parser.add_argument("--max-first-branches", type=int, default=3)
    parser.add_argument("--max-second-branches", type=int, default=4)
    parser.add_argument("--max-third-branches", type=int, default=4)
    parser.add_argument("--tail-max-steps", type=int, default=500)
    parser.add_argument("--horizon-minutes", type=int, default=30 * 1440)
    parser.add_argument("--first-extra-waits", default="")
    parser.add_argument("--second-extra-waits", default="")
    parser.add_argument("--third-extra-waits", default="")
    parser.add_argument("--first-reposition-points", default="")
    parser.add_argument("--second-reposition-points", default="")
    parser.add_argument("--third-reposition-points", default="")
    parser.add_argument("--baseline-score", type=float, default=None)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    triples = _parse_triples(args.triples)
    if not triples:
        raise ValueError("--triples is empty")

    _apply_preset_env(args.preset)
    settings = load_settings()
    feature_settings = FeatureSettings(
        speed_km_per_hour=settings.reposition_speed_km_per_hour,
        simulation_horizon_minutes=int(args.horizon_minutes),
        fallback_wait_minutes=max(1, _env_int("AGENT_FALLBACK_WAIT_MINUTES", 60)),
    )

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(driver_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "triple_probe_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    prefix_cache: dict[int, Any] = {}
    waits = [
        _parse_int_list(args.first_extra_waits),
        _parse_int_list(args.second_extra_waits),
        _parse_int_list(args.third_extra_waits),
    ]
    repos = [
        _parse_reposition_points(args.first_reposition_points),
        _parse_reposition_points(args.second_reposition_points),
        _parse_reposition_points(args.third_reposition_points),
    ]

    for first_step, second_step, third_step in triples:
        if not (first_step < second_step < third_step):
            rows.append({"first_step": first_step, "second_step": second_step, "third_step": third_step, "status": "invalid_triple"})
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
        first_candidates = _branch_candidates(first_rule, first_diag, args, stage=0, waits=waits, repos=repos)[: max(1, args.max_first_branches)]
        for first_rank, first_action in enumerate(first_candidates, start=1):
            after_first = _clone_state(prefix)
            try:
                _apply_branch_action(after_first, driver_id, first_action, settings, feature_settings, step_start=first_step_start)
            except Exception as exc:
                rows.append(_failed_row(first_step, second_step, third_step, first_rank, first_action, "first_apply_failed", exc))
                continue

            second_state = _advance_to_decision(
                after_first,
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                target_step=second_step,
            )
            if second_state is None:
                rows.append(_failed_row(first_step, second_step, third_step, first_rank, first_action, "second_unreachable"))
                continue

            second_step_start = second_state.progress()
            second_rule, second_diag = _decide(second_state, driver_id, settings, feature_settings)
            second_candidates = _branch_candidates(second_rule, second_diag, args, stage=1, waits=waits, repos=repos)[: max(1, args.max_second_branches)]
            for second_rank, second_action in enumerate(second_candidates, start=1):
                after_second = _clone_state(second_state)
                try:
                    _apply_branch_action(after_second, driver_id, second_action, settings, feature_settings, step_start=second_step_start)
                except Exception as exc:
                    rows.append(
                        _failed_row(
                            first_step,
                            second_step,
                            third_step,
                            first_rank,
                            first_action,
                            "second_apply_failed",
                            exc,
                            second_rank=second_rank,
                            second_action=second_action,
                        )
                    )
                    continue

                third_state = _advance_to_decision(
                    after_second,
                    driver_id=driver_id,
                    settings=settings,
                    feature_settings=feature_settings,
                    target_step=third_step,
                )
                if third_state is None:
                    rows.append(
                        _failed_row(
                            first_step,
                            second_step,
                            third_step,
                            first_rank,
                            first_action,
                            "third_unreachable",
                            second_rank=second_rank,
                            second_action=second_action,
                        )
                    )
                    continue

                third_step_start = third_state.progress()
                third_rule, third_diag = _decide(third_state, driver_id, settings, feature_settings)
                third_candidates = _branch_candidates(third_rule, third_diag, args, stage=2, waits=waits, repos=repos)[: max(1, args.max_third_branches)]
                for third_rank, third_action in enumerate(third_candidates, start=1):
                    branch = _clone_state(third_state)
                    try:
                        _apply_branch_action(branch, driver_id, third_action, settings, feature_settings, step_start=third_step_start)
                    except Exception as exc:
                        rows.append(
                            _failed_row(
                                first_step,
                                second_step,
                                third_step,
                                first_rank,
                                first_action,
                                "third_apply_failed",
                                exc,
                                second_rank=second_rank,
                                second_action=second_action,
                                third_rank=third_rank,
                                third_action=third_action,
                            )
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
                        / f"triple_{first_step:03d}_{second_step:03d}_{third_step:03d}"
                        / (
                            f"f{first_rank:02d}_{_action_label(first_action)}"
                            f"__s{second_rank:02d}_{_action_label(second_action)}"
                            f"__t{third_rank:02d}_{_action_label(third_action)}"
                        )
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
                            "third_step": third_step,
                            "first_rank": first_rank,
                            "second_rank": second_rank,
                            "third_rank": third_rank,
                            "first_action": _clean_action(first_action),
                            "second_action": _clean_action(second_action),
                            "third_action": _clean_action(third_action),
                            "is_rule_first": _action_key(first_action) == _action_key(first_rule),
                            "is_rule_second": _action_key(second_action) == _action_key(second_rule),
                            "is_rule_third": _action_key(third_action) == _action_key(third_rule),
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
    (out_dir / "triple_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "triple_summary.md", driver_id, args.preset, args.baseline_score, rows)
    print(f"written: {out_dir / 'triple_summary.md'}")
    print(json.dumps(rows[: min(len(rows), 20)], ensure_ascii=False, indent=2))
    return 0


def _branch_candidates(rule_action: dict[str, Any], diagnostics: dict[str, Any], args: argparse.Namespace, *, stage: int, waits: list[list[int]], repos: list[list[tuple[str, float, float]]]) -> list[dict[str, Any]]:
    top_k = [args.top_k_first, args.top_k_second, args.top_k_third][stage]
    value_k = [args.value_k_first, args.value_k_second, args.value_k_third][stage]
    return _sequence_branch_candidates(
        rule_action,
        diagnostics,
        top_k=max(1, int(top_k)),
        value_k=max(0, int(value_k)),
        value_max_score_drop=float(args.value_max_score_drop),
        value_destination_weight=float(args.value_destination_weight),
        value_opportunity_weight=float(args.value_opportunity_weight),
        value_net_weight=float(args.value_net_weight),
        value_nph_weight=float(args.value_nph_weight),
        extra_waits=waits[stage],
        reposition_points=repos[stage],
    )


def _failed_row(
    first_step: int,
    second_step: int,
    third_step: int,
    first_rank: int,
    first_action: dict[str, Any],
    status: str,
    exc: Exception | None = None,
    *,
    second_rank: int | None = None,
    second_action: dict[str, Any] | None = None,
    third_rank: int | None = None,
    third_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "first_step": first_step,
        "second_step": second_step,
        "third_step": third_step,
        "first_rank": first_rank,
        "first_action": _clean_action(first_action),
        "status": status,
    }
    if second_rank is not None:
        row["second_rank"] = second_rank
    if second_action is not None:
        row["second_action"] = _clean_action(second_action)
    if third_rank is not None:
        row["third_rank"] = third_rank
    if third_action is not None:
        row["third_action"] = _clean_action(third_action)
    if exc is not None:
        row["error"] = repr(exc)
    return row


def _parse_triples(raw: str) -> list[tuple[int, int, int]]:
    triples: list[tuple[int, int, int]] = []
    for part in raw.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        pieces = item.split(":")
        if len(pieces) != 3:
            raise ValueError(f"invalid triple: {item}")
        triples.append(tuple(int(float(piece.strip())) for piece in pieces))  # type: ignore[arg-type]
    return triples


def _write_markdown(path: Path, driver_id: str, preset: str, baseline_score: float | None, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Triple Counterfactual Probe",
        "",
        f"driver = `{driver_id}`",
        f"preset = `{preset}`",
        f"baseline_score = `{baseline_score}`",
        "",
        "| first | second | third | score | delta | penalty | f | s | t | status |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in rows[:120]:
        lines.append(
            "| {first_step} | {second_step} | {third_step} | {score} | {delta_vs_baseline} | {penalty} | `{f}` | `{s}` | `{t}` | {status} |".format(
                first_step=row.get("first_step", ""),
                second_step=row.get("second_step", ""),
                third_step=row.get("third_step", ""),
                score=row.get("score", ""),
                delta_vs_baseline=row.get("delta_vs_baseline", ""),
                penalty=row.get("penalty", ""),
                f=_action_label(row.get("first_action", {})),
                s=_action_label(row.get("second_action", {})),
                t=_action_label(row.get("third_action", {})),
                status=row.get("status", ""),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_out_dir(driver_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("results") / "triple_counterfactual" / f"{stamp}_{driver_id}"


if __name__ == "__main__":
    raise SystemExit(main())
