"""Restricted counterfactual rollout probe.

This harness answers one narrow question:

    At an actual online decision step, what happens if we replace only the
    current take_order cargo with another top-k candidate and then hand control
    back to the same base policy until month end?

It is intentionally stricter than ``offline_beam_planner``.  There are no free
wait/reposition branches and no beam search.  The prefix is replayed with the
base policy, exactly one target-step order can be replaced, and the policy tail
is deterministic.  The output is a set of exact per-driver month scores that
can be compared against the current best run.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = DEMO_ROOT / "server"
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from agent.feature_strategies import load_strategy
from agent.feature_strategies.common import FeatureDecisionEngine, FeatureSettings
from offline_beam_planner import BeamSimulationApi, _apply_action, _clone_repo, _record_action, _zero_usage
from run_agentic_algo_grid import BASE_ENV, PRESETS
from server.bench.settings import load_settings
from simkit.cargo_repository import CargoRepository
from simkit.driver_state_manager import DriverStateManager


SIM_EPOCH = datetime(2026, 3, 1, 0, 0, 0)


@dataclass
class SimState:
    repo: CargoRepository
    manager: DriverStateManager
    history: list[dict[str, Any]] = field(default_factory=list)

    def progress(self) -> int:
        return int(self.manager.get_simulation_progress_minutes())


def main() -> int:
    parser = argparse.ArgumentParser(description="Restricted one-step counterfactual rollout probe.")
    parser.add_argument("--driver", required=True, help="Driver ID, e.g. D002.")
    parser.add_argument("--preset", default="hot_v30_d006_days_tail_nph60")
    parser.add_argument("--target-steps", required=True, help="Comma-separated 1-based target steps.")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--value-k",
        type=int,
        default=0,
        help="Add cargo branches with high destination/future value even if they are not top score.",
    )
    parser.add_argument("--value-max-score-drop", type=float, default=250.0)
    parser.add_argument("--value-destination-weight", type=float, default=120.0)
    parser.add_argument("--value-opportunity-weight", type=float, default=0.35)
    parser.add_argument("--value-net-weight", type=float, default=0.04)
    parser.add_argument("--value-nph-weight", type=float, default=0.25)
    parser.add_argument("--tail-max-steps", type=int, default=500)
    parser.add_argument("--horizon-minutes", type=int, default=30 * 1440)
    parser.add_argument("--extra-waits", default="", help="Optional comma-separated wait branches in minutes.")
    parser.add_argument(
        "--reposition-points",
        default="",
        help="Optional reposition branches as label:lat:lng entries separated by comma or semicolon.",
    )
    parser.add_argument("--baseline-score", type=float, default=None)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    target_steps = _parse_int_set(args.target_steps)
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
    started = time.perf_counter()

    rows: list[dict[str, Any]] = []
    for target_step in sorted(target_steps):
        prefix = _run_prefix_to_decision(
            driver_id=driver_id,
            settings=settings,
            feature_settings=feature_settings,
            target_step=target_step,
        )
        target_step_start = prefix.progress()
        rule_action, diagnostics = _decide(prefix, driver_id, settings, feature_settings)
        target_after_query = prefix.progress()
        candidates = _branch_candidates(
            rule_action,
            diagnostics,
            top_k=max(1, args.top_k),
            value_k=max(0, args.value_k),
            value_max_score_drop=float(args.value_max_score_drop),
            value_destination_weight=float(args.value_destination_weight),
            value_opportunity_weight=float(args.value_opportunity_weight),
            value_net_weight=float(args.value_net_weight),
            value_nph_weight=float(args.value_nph_weight),
            extra_waits=_parse_int_list(args.extra_waits),
            reposition_points=_parse_reposition_points(args.reposition_points),
        )
        if not candidates:
            rows.append(
                {
                    "target_step": target_step,
                    "status": "no_take_order_candidates",
                    "rule_action": _clean_action(rule_action),
                    "progress_minutes": prefix.progress(),
                }
            )
            continue

        for rank, candidate in enumerate(candidates, start=1):
            branch = _clone_state(prefix)
            before_status = branch.manager.get_driver_status(driver_id)
            try:
                result = _apply_action(
                    branch.repo,
                    branch.manager,
                    driver_id,
                    candidate,
                    speed_km_per_hour=settings.reposition_speed_km_per_hour,
                    horizon_minutes=feature_settings.simulation_horizon_minutes,
                )
            except Exception as exc:
                rows.append(
                    {
                        "target_step": target_step,
                        "candidate_rank": rank,
                        "candidate_action": _clean_action(candidate),
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
                step_start=target_step_start,
                before_status=before_status,
                after_status=after_status,
                after_query_progress=target_after_query,
                end_progress=end_progress,
                action=_with_zero_usage(_clean_action(candidate)),
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
            cand_dir = out_dir / f"step_{target_step:03d}" / f"candidate_{rank:02d}_{_action_label(candidate)}"
            cand_dir.mkdir(parents=True, exist_ok=True)
            _write_run(cand_dir, driver_id, branch, settings, simulate_time_seconds=round(time.perf_counter() - started, 2))
            score_payload = _score_run(cand_dir)
            income = _driver_income(score_payload, driver_id) if score_payload else {}
            score = _float_or_none(income.get("net_income"))
            rows.append(
                {
                    "target_step": target_step,
                    "candidate_rank": rank,
                    "candidate_action": _clean_action(candidate),
                    "is_rule_action": _action_key(candidate) == _action_key(rule_action),
                    "score": score,
                    "delta_vs_baseline": None if score is None or args.baseline_score is None else round(score - args.baseline_score, 2),
                    "gross": _float_or_none(income.get("gross_income")),
                    "distance": _float_or_none(income.get("distance_km")),
                    "penalty": _float_or_none(income.get("preference_penalty")),
                    "steps": len(branch.history),
                    "progress_minutes": branch.progress(),
                    "run_dir": str(cand_dir),
                }
            )

    rows.sort(key=lambda row: (int(row.get("target_step", 0) or 0), -float(row.get("score") or -1e18)))
    (out_dir / "counterfactual_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "counterfactual_summary.md", driver_id, args.preset, rows)
    print(f"written: {out_dir / 'counterfactual_summary.md'}")
    print(json.dumps(rows[: min(len(rows), 20)], ensure_ascii=False, indent=2))
    return 0


def _run_prefix_to_decision(
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    target_step: int,
) -> SimState:
    if target_step < 1:
        raise ValueError("target_step must be >= 1")
    state = _make_root_state(settings, driver_id)
    strategy = _load_base_strategy()
    for _ in range(target_step - 1):
        if state.progress() >= feature_settings.simulation_horizon_minutes or state.repo.size <= 0:
            break
        step_start = state.progress()
        action, _diagnostics = _decide(state, driver_id, settings, feature_settings, strategy=strategy)
        _apply_recorded_action(state, driver_id, action, settings, feature_settings, step_start=step_start)
    return state


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


def _decide(
    state: SimState,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    *,
    strategy: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    api = BeamSimulationApi(
        state.repo,
        state.manager,
        state.history,
        nearest_cargo_limit=max(1, _env_int("AGENT_NEAREST_CARGO_LIMIT", 100)),
        nearest_cargo_limit_by_driver=_driver_limit_env(),
        cargo_view_batch_size=max(1, _env_int("AGENT_CARGO_VIEW_BATCH_SIZE", 10)),
    )
    engine = FeatureDecisionEngine(api, strategy or _load_base_strategy(), feature_settings)
    return engine.decide(driver_id)


def _apply_recorded_action(
    state: SimState,
    driver_id: str,
    action: dict[str, Any],
    settings: Any,
    feature_settings: FeatureSettings,
    *,
    step_start: int,
) -> None:
    before_status = state.manager.get_driver_status(driver_id)
    # The policy call already applied query scan cost to state.repo/state.manager.
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


def _branch_candidates(
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


def _make_root_state(settings: Any, driver_id: str) -> SimState:
    repo = CargoRepository(settings.cargo_dataset_path)
    repo.load()
    manager = DriverStateManager(settings.drivers_path)
    manager.load()
    manager.start_simulation(driver_id=driver_id, progress_minutes=0)
    repo.sync_time_minutes(0)
    return SimState(repo=repo, manager=manager)


def _clone_state(state: SimState) -> SimState:
    return SimState(repo=_clone_repo(state.repo), manager=copy.deepcopy(state.manager), history=copy.deepcopy(state.history))


def _load_base_strategy() -> Any:
    strategy_name = os.getenv("AGENT_STRATEGY", "new_release_agentic_planner_agent").strip()
    if strategy_name.lower() == "llm_rerank_agent":
        strategy_name = os.getenv("AGENT_LLM_RERANK_BASE_STRATEGY", "new_release_agentic_planner_agent").strip()
    return load_strategy(strategy_name)


def _apply_preset_env(preset: str) -> None:
    for key in list(os.environ):
        if key.startswith("AGENT_"):
            os.environ.pop(key, None)
    env: dict[str, str] = {}
    if preset:
        if preset not in PRESETS:
            raise KeyError(f"unknown preset: {preset}")
        env.update(PRESETS[preset])
    if env.pop("AGENT_USE_BASE_ENV", "1") != "0":
        base = dict(BASE_ENV)
        base.update(env)
        env = base
    for key, value in env.items():
        if key.startswith("AGENT_"):
            os.environ[key] = str(value)
    if os.getenv("AGENT_SUBMISSION_PROFILE") and os.getenv("AGENT_DISABLE_SUBMISSION_DEFAULTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        from agent.submission_defaults import apply_submission_defaults

        apply_submission_defaults()


def _write_run(out_dir: Path, driver_id: str, state: SimState, settings: Any, *, simulate_time_seconds: float) -> None:
    action_path = out_dir / f"actions_202603_{driver_id}_counterfactual.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in state.history:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "month": "2026-03",
        "simulate_time_seconds": simulate_time_seconds,
        "simulation_duration_days": int(settings.simulation_duration_days),
        "completed_steps": len(state.history),
        "remaining_cargo_count": state.repo.size,
        "simulation_progress_minutes": state.progress(),
        "simulation_wall_time": _format_sim_clock(state.progress()) + ":00",
        "driver_completed_steps": {driver_id: len(state.history)},
        "driver_result_files": {driver_id: str(action_path.resolve())},
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _score_run(run_dir: Path) -> dict[str, Any] | None:
    cmd = [
        sys.executable,
        str(DEMO_ROOT / "calc_monthly_income.py"),
        "--project-root",
        str(DEMO_ROOT),
        "--results-dir",
        str(run_dir),
    ]
    proc = subprocess.run(cmd, cwd=str(DEMO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        (run_dir / "calc_error.log").write_text(proc.stderr + "\n" + proc.stdout, encoding="utf-8")
        return None
    path = run_dir / "monthly_income_202603.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _driver_income(payload: dict[str, Any], driver_id: str) -> dict[str, Any]:
    for item in payload.get("drivers", []) or []:
        if str(item.get("driver_id", "")).upper() == driver_id.upper():
            income = item.get("income")
            return income if isinstance(income, dict) else {}
    return {}


def _write_markdown(path: Path, driver_id: str, preset: str, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Counterfactual Rollout Probe",
        "",
        f"- driver: `{driver_id}`",
        f"- preset: `{preset}`",
        "",
        "| target_step | rank | rule | score | penalty | action | run_dir |",
        "| ---: | ---: | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        action = json.dumps(row.get("candidate_action"), ensure_ascii=False, separators=(",", ":"))
        lines.append(
            f"| {row.get('target_step')} | {row.get('candidate_rank', '')} | {row.get('is_rule_action', '')} | "
            f"{_fmt(row.get('score'))} | {_fmt(row.get('penalty'))} | `{action}` | `{row.get('run_dir', '')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _action_key(action: dict[str, Any]) -> tuple[Any, ...]:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    name = _action_name(action)
    if name == "take_order":
        return name, str(params.get("cargo_id", "")).strip()
    if name == "wait":
        return name, int(float(params.get("duration_minutes", 0) or 0))
    if name == "reposition":
        return name, round(float(params.get("latitude", 0.0) or 0.0), 5), round(float(params.get("longitude", 0.0) or 0.0), 5)
    return name, json.dumps(params, sort_keys=True, ensure_ascii=False)


def _clean_action(action: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dict(action).items() if not str(k).startswith("_")}


def _with_zero_usage(action: dict[str, Any]) -> dict[str, Any]:
    out = dict(action)
    out.setdefault("model_usage", _zero_usage())
    return out


def _action_name(action: dict[str, Any]) -> str:
    return str(action.get("action", "")).strip().lower()


def _action_label(action: dict[str, Any]) -> str:
    label = str(action.get("_probe_label", "")).strip()
    if label:
        return _safe_label(label)
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if _action_name(action) == "take_order":
        return f"cargo_{str(params.get('cargo_id', '')).strip()}"
    if _action_name(action) == "wait":
        return f"wait_{int(float(params.get('duration_minutes', 0) or 0))}"
    if _action_name(action) == "reposition":
        lat = round(float(params.get("latitude", 0.0) or 0.0), 3)
        lng = round(float(params.get("longitude", 0.0) or 0.0), 3)
        return _safe_label(f"reposition_{lat}_{lng}")
    return _action_name(action) or "action"


def _driver_limit_env() -> dict[str, int]:
    limits: dict[str, int] = {}
    for idx in range(1, 11):
        driver_id = f"D{idx:03d}"
        value = os.getenv(f"AGENT_{driver_id}_NEAREST_CARGO_LIMIT")
        if value is not None:
            limits[driver_id] = max(1, _env_int(f"AGENT_{driver_id}_NEAREST_CARGO_LIMIT", 100))
    return limits


def _parse_int_set(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        out.add(int(float(part)))
    return out


def _parse_int_list(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(float(part))
        except ValueError:
            continue
        if value > 0:
            out.append(value)
    return out


def _parse_reposition_points(raw: str) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = []
    for part in raw.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        pieces = item.split(":")
        if len(pieces) != 3:
            continue
        label = pieces[0].strip() or "point"
        try:
            lat = float(pieces[1])
            lng = float(pieces[2])
        except ValueError:
            continue
        out.append((_safe_label(label), lat, lng))
    return out


def _format_sim_clock(minutes: int) -> str:
    return (SIM_EPOCH + timedelta(minutes=int(minutes))).strftime("%Y-%m-%d %H:%M")


def _default_out_dir(driver_id: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEMO_ROOT / "results" / "counterfactual_rollout" / f"{ts}_{driver_id}"


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _safe_label(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)[:80] or "item"


if __name__ == "__main__":
    raise SystemExit(main())
