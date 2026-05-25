"""Offline per-driver beam planner.

This is a search harness, not a submission agent.  It reuses the official
simkit transition functions, branches on the top scored cargo candidates, and
writes candidate action traces that can be evaluated by ``calc_monthly_income``.

The purpose is to discover high-value trajectory patterns that are too large
for manual preset sweeps.
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
from run_agentic_algo_grid import BASE_ENV, PRESETS
from server.bench.settings import load_settings
from simkit import simulation_actions
from simkit.cargo_repository import CargoRepository
from simkit.driver_state_manager import DriverStateManager


SIM_EPOCH = datetime(2026, 3, 1, 0, 0, 0)


@dataclass
class BeamNode:
    repo: CargoRepository
    manager: DriverStateManager
    history: list[dict[str, Any]] = field(default_factory=list)
    proxy_score: float = 0.0
    label: str = "root"

    def progress(self) -> int:
        return int(self.manager.get_simulation_progress_minutes())


class BeamSimulationApi:
    def __init__(
        self,
        repo: CargoRepository,
        manager: DriverStateManager,
        history: list[dict[str, Any]],
        *,
        nearest_cargo_limit: int,
        nearest_cargo_limit_by_driver: dict[str, int],
        cargo_view_batch_size: int,
    ) -> None:
        self.repo = repo
        self.manager = manager
        self.history = history
        self.nearest_cargo_limit = nearest_cargo_limit
        self.nearest_cargo_limit_by_driver = nearest_cargo_limit_by_driver
        self.cargo_view_batch_size = cargo_view_batch_size

    def get_driver_status(self, driver_id: str) -> dict[str, Any]:
        return self.manager.get_driver_status(driver_id)

    def query_cargo(self, driver_id: str, latitude: float, longitude: float) -> dict[str, Any]:
        limit = self.nearest_cargo_limit_by_driver.get(driver_id.upper(), self.nearest_cargo_limit)
        raw = simulation_actions.query_cargo(self.repo, self.manager, driver_id, latitude, longitude, k=limit)
        items = raw.get("items", [])
        item_count = len(items) if isinstance(items, list) else 0
        simulation_actions.apply_cargo_query_scan_cost(
            self.repo,
            self.manager,
            driver_id,
            item_count,
            cargo_view_batch_size=self.cargo_view_batch_size,
        )
        return raw

    def query_decision_history(self, driver_id: str, step: int) -> dict[str, Any]:
        records = list(self.history)
        if step == 0:
            out: list[dict[str, Any]] = []
        elif step == -1 or step >= len(records):
            out = records
        else:
            out = records[-max(0, step):]
        return {
            "driver_id": driver_id,
            "total_steps": len(records),
            "step_param": step,
            "returned_count": len(out),
            "records": out,
        }

    def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("offline beam planner does not call LLM")


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline single-driver beam planner.")
    parser.add_argument("--driver", required=True, help="Driver ID, e.g. D006.")
    parser.add_argument("--preset", default="hot_v30_best_d004strict", help="Preset env from run_agentic_algo_grid.py.")
    parser.add_argument("--beam-width", type=int, default=4)
    parser.add_argument("--branch-top-n", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=160)
    parser.add_argument("--horizon-minutes", type=int, default=30 * 1440)
    parser.add_argument("--extra-waits", default="", help="Comma-separated extra wait branches in minutes.")
    parser.add_argument("--event-waits", action="store_true", help="Add waits to the next cargo release and common work windows.")
    parser.add_argument("--min-event-wait", type=int, default=30, help="Ignore tiny event waits below this many minutes.")
    parser.add_argument("--lock-planned-drivers", default="D009,D010", help="Drivers whose non-order planned actions are treated as hard constraints.")
    parser.add_argument("--wait-score-threshold", type=float, default=1e9, help="Only add extra waits if top score <= this.")
    parser.add_argument("--rest-credit", type=float, default=0.0, help="Proxy credit for a long rest branch.")
    parser.add_argument("--score-final", action="store_true", help="Run calc_monthly_income.py for each final trace.")
    parser.add_argument("--complete-with-policy", action="store_true", help="After beam search, roll each candidate to month end with the base policy before scoring.")
    parser.add_argument("--complete-max-steps", type=int, default=400, help="Safety limit for --complete-with-policy tail rollout.")
    parser.add_argument("--out-dir", default="", help="Output dir. Defaults to results/beam_planner/<timestamp>_<driver>.")
    args = parser.parse_args()

    driver_id = args.driver.strip().upper()
    _apply_preset_env(args.preset)
    settings = load_settings()
    cost_by_driver = _load_driver_cost_map(settings.drivers_path)
    cargo_price: dict[str, float] = {}
    cargo_price.update(_load_cargo_price_map(settings.cargo_dataset_path))

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(driver_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "beam_config.json").write_text(
        json.dumps(vars(args), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    start = time.perf_counter()
    root = _make_root_node(settings, driver_id)
    beam = [root]
    completed: list[BeamNode] = []
    wait_minutes = _parse_int_list(args.extra_waits)
    locked_planned_drivers = {part.strip().upper() for part in args.lock_planned_drivers.split(",") if part.strip()}
    feature_settings = FeatureSettings(
        speed_km_per_hour=settings.reposition_speed_km_per_hour,
        simulation_horizon_minutes=args.horizon_minutes,
        fallback_wait_minutes=max(1, int(os.getenv("AGENT_FALLBACK_WAIT_MINUTES", "60"))),
    )

    for depth in range(max(1, args.max_steps)):
        expanded: list[BeamNode] = []
        for node in beam:
            if node.progress() >= args.horizon_minutes or node.repo.size <= 0:
                completed.append(node)
                continue
            expanded.extend(
                _expand_node(
                    node,
                    driver_id=driver_id,
                    settings=settings,
                    feature_settings=feature_settings,
                    branch_top_n=max(1, args.branch_top_n),
                    extra_waits=wait_minutes,
                    event_waits=bool(args.event_waits),
                    min_event_wait=max(1, args.min_event_wait),
                    locked_planned_drivers=locked_planned_drivers,
                    wait_score_threshold=args.wait_score_threshold,
                    rest_credit=float(args.rest_credit),
                    cost_per_km=float(cost_by_driver.get(driver_id, 1.5)),
                    cargo_price=cargo_price,
                )
            )
        if not expanded:
            break
        expanded.sort(key=lambda n: _rank_score(n, args.horizon_minutes), reverse=True)
        beam = expanded[: max(1, args.beam_width)]
        if depth % 10 == 0:
            print(
                f"depth={depth + 1} beam="
                + ", ".join(f"{n.label}:proxy={n.proxy_score:.1f}:t={n.progress()}" for n in beam[:3]),
                flush=True,
            )

    finals = completed + beam
    finals.sort(key=lambda n: _rank_score(n, args.horizon_minutes), reverse=True)
    finals = finals[: max(1, args.beam_width)]

    summary_rows: list[dict[str, Any]] = []
    for idx, node in enumerate(finals, start=1):
        output_node = (
            _complete_with_policy(
                node,
                driver_id=driver_id,
                settings=settings,
                feature_settings=feature_settings,
                max_steps=max(0, int(args.complete_max_steps)),
                cost_per_km=float(cost_by_driver.get(driver_id, 1.5)),
                cargo_price=cargo_price,
            )
            if args.complete_with_policy
            else node
        )
        cand_dir = out_dir / f"candidate_{idx:02d}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        _write_candidate_run(cand_dir, driver_id, output_node, settings, simulate_time_seconds=round(time.perf_counter() - start, 2))
        score_payload = _score_candidate(cand_dir) if args.score_final else None
        row = {
            "candidate": idx,
            "label": node.label,
            "proxy_score": round(node.proxy_score, 2),
            "progress_minutes": output_node.progress(),
            "steps": len(output_node.history),
            "beam_progress_minutes": node.progress(),
            "beam_steps": len(node.history),
            "run_dir": str(cand_dir),
        }
        if score_payload is not None:
            driver_income = _find_driver_income(score_payload, driver_id)
            row["exact_net_income"] = driver_income.get("net_income")
            row["exact_penalty"] = driver_income.get("preference_penalty")
            row["exact_gross"] = driver_income.get("gross_income")
            row["exact_distance"] = driver_income.get("distance_km")
        summary_rows.append(row)

    summary_rows.sort(key=lambda r: float(r.get("exact_net_income", r.get("proxy_score", 0.0)) or 0.0), reverse=True)
    (out_dir / "beam_summary.json").write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "beam_summary.md", driver_id, args.preset, summary_rows)
    print(f"written: {out_dir / 'beam_summary.md'}")
    print(json.dumps(summary_rows[: min(5, len(summary_rows))], ensure_ascii=False, indent=2))
    return 0


def _expand_node(
    node: BeamNode,
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    branch_top_n: int,
    extra_waits: list[int],
    event_waits: bool,
    min_event_wait: int,
    locked_planned_drivers: set[str],
    wait_score_threshold: float,
    rest_credit: float,
    cost_per_km: float,
    cargo_price: dict[str, float],
) -> list[BeamNode]:
    step_start = node.progress()
    before_status = node.manager.get_driver_status(driver_id)
    api = BeamSimulationApi(
        node.repo,
        node.manager,
        node.history,
        nearest_cargo_limit=max(1, _env_int("AGENT_NEAREST_CARGO_LIMIT", 100)),
        nearest_cargo_limit_by_driver=_driver_limit_env(),
        cargo_view_batch_size=max(1, _env_int("AGENT_CARGO_VIEW_BATCH_SIZE", 10)),
    )
    strategy_name = os.getenv("AGENT_STRATEGY", "new_release_agentic_planner_agent").strip()
    if strategy_name.lower() == "llm_rerank_agent":
        strategy_name = os.getenv("AGENT_LLM_RERANK_BASE_STRATEGY", "new_release_agentic_planner_agent").strip()
    engine = FeatureDecisionEngine(api, load_strategy(strategy_name), feature_settings)
    try:
        rule_action, diagnostics = engine.decide(driver_id)
    except Exception as exc:
        rule_action = {"action": "wait", "params": {"duration_minutes": 60}}
        diagnostics = {"error": repr(exc), "fallback": rule_action}

    after_query_progress = node.progress()
    if _must_lock_planned_action(driver_id, rule_action, diagnostics, locked_planned_drivers):
        branches = [_label_action(rule_action, "locked")]
    else:
        branches = _candidate_branch_actions(rule_action, diagnostics, branch_top_n=branch_top_n)
    top_score = _top_diagnostic_score(diagnostics)
    if extra_waits and top_score <= wait_score_threshold:
        for minutes in extra_waits:
            if minutes > 0:
                branches.append({"action": "wait", "params": {"duration_minutes": minutes}, "_beam_label": f"wait{minutes}"})
    if event_waits and top_score <= wait_score_threshold:
        for minutes in _event_wait_minutes(
            node.repo,
            after_query_progress,
            feature_settings.simulation_horizon_minutes,
            min_event_wait=min_event_wait,
        ):
            branches.append({"action": "wait", "params": {"duration_minutes": minutes}, "_beam_label": f"eventwait{minutes}"})
    branches = _dedupe_actions(branches)

    out: list[BeamNode] = []
    for action in branches:
        repo = _clone_repo(node.repo)
        manager = copy.deepcopy(node.manager)
        history = copy.deepcopy(node.history)
        result: dict[str, Any]
        action_start = manager.get_simulation_progress_minutes()
        try:
            result = _apply_action(
                repo,
                manager,
                driver_id,
                action,
                speed_km_per_hour=settings.reposition_speed_km_per_hour,
                horizon_minutes=feature_settings.simulation_horizon_minutes,
            )
        except Exception:
            continue
        after_status = manager.get_driver_status(driver_id)
        end_progress = manager.get_simulation_progress_minutes()
        clean_action = {k: v for k, v in action.items() if not k.startswith("_")}
        clean_action.setdefault("model_usage", _zero_usage())
        record = _record_action(
            step=len(history) + 1,
            driver_id=driver_id,
            step_start=step_start,
            before_status=before_status,
            after_status=after_status,
            after_query_progress=after_query_progress,
            end_progress=end_progress,
            action=clean_action,
            result=result,
        )
        history.append(record)
        proxy_delta = _proxy_delta(action, result, cargo_price=cargo_price, cost_per_km=cost_per_km)
        if _action_name(action) == "wait" and _int((action.get("params") or {}).get("duration_minutes")) >= 180:
            proxy_delta += rest_credit
        label = str(action.get("_beam_label") or _action_label(action))
        out.append(
            BeamNode(
                repo=repo,
                manager=manager,
                history=history,
                proxy_score=node.proxy_score + proxy_delta,
                label=f"{node.label}>{label}",
            )
        )
    return out


def _complete_with_policy(
    node: BeamNode,
    *,
    driver_id: str,
    settings: Any,
    feature_settings: FeatureSettings,
    max_steps: int,
    cost_per_km: float,
    cargo_price: dict[str, float],
) -> BeamNode:
    repo = _clone_repo(node.repo)
    manager = copy.deepcopy(node.manager)
    history = copy.deepcopy(node.history)
    completed = BeamNode(
        repo=repo,
        manager=manager,
        history=history,
        proxy_score=node.proxy_score,
        label=f"{node.label}>policy_tail",
    )
    for _ in range(max_steps):
        if completed.progress() >= feature_settings.simulation_horizon_minutes or completed.repo.size <= 0:
            break
        branches = _expand_node(
            completed,
            driver_id=driver_id,
            settings=settings,
            feature_settings=feature_settings,
            branch_top_n=1,
            extra_waits=[],
            event_waits=False,
            min_event_wait=30,
            locked_planned_drivers={driver_id.upper()},
            wait_score_threshold=-1e9,
            rest_credit=0.0,
            cost_per_km=cost_per_km,
            cargo_price=cargo_price,
        )
        if not branches:
            break
        completed = branches[0]
    return completed


def _candidate_branch_actions(rule_action: dict[str, Any], diagnostics: dict[str, Any], *, branch_top_n: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    selectable = diagnostics.get("selectable_features")
    if isinstance(selectable, list) and selectable:
        rows = [item for item in selectable if isinstance(item, dict)]
        rows.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        for item in rows[:branch_top_n]:
            cargo_id = str(item.get("cargo_id", "")).strip()
            if cargo_id:
                actions.append(
                    {
                        "action": "take_order",
                        "params": {"cargo_id": cargo_id},
                        "_beam_label": f"take:{cargo_id}",
                    }
                )
    if rule_action:
        actions.insert(0, dict(rule_action))
    planned = diagnostics.get("planned_action") or diagnostics.get("fallback")
    if isinstance(planned, dict):
        actions.insert(0, dict(planned))
    return actions


def _must_lock_planned_action(
    driver_id: str,
    rule_action: dict[str, Any],
    diagnostics: dict[str, Any],
    locked_planned_drivers: set[str],
) -> bool:
    if not rule_action:
        return False
    if bool(diagnostics.get("pre_query_action")):
        return True
    if driver_id.upper() not in locked_planned_drivers:
        return False
    return _action_name(rule_action) in {"wait", "reposition"}


def _label_action(action: dict[str, Any], label: str) -> dict[str, Any]:
    out = dict(action)
    out["_beam_label"] = f"{label}:{_action_label(action)}"
    return out


def _apply_action(
    repo: CargoRepository,
    manager: DriverStateManager,
    driver_id: str,
    action: dict[str, Any],
    *,
    speed_km_per_hour: float,
    horizon_minutes: int,
) -> dict[str, Any]:
    name = _action_name(action)
    params = action.get("params") or {}
    if name == "take_order":
        return simulation_actions.take_order(
            repo,
            manager,
            driver_id,
            str(params["cargo_id"]),
            reposition_speed_km_per_hour=speed_km_per_hour,
            simulation_horizon_minutes=horizon_minutes,
        )
    if name == "wait":
        return simulation_actions.wait(repo, manager, driver_id, max(1, _int(params.get("duration_minutes"))))
    if name == "reposition":
        return simulation_actions.reposition(
            repo,
            manager,
            driver_id,
            float(params["latitude"]),
            float(params["longitude"]),
            speed_km_per_hour=speed_km_per_hour,
        )
    raise ValueError(f"unsupported action: {name}")


def _record_action(
    *,
    step: int,
    driver_id: str,
    step_start: int,
    before_status: dict[str, Any],
    after_status: dict[str, Any],
    after_query_progress: int,
    end_progress: int,
    action: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    query_cost = max(0, after_query_progress - step_start)
    return {
        "step": step,
        "driver_id": driver_id,
        "step_elapsed_minutes": max(0, end_progress - step_start),
        "query_scan_cost_minutes": query_cost,
        "action_exec_cost_minutes": max(0, end_progress - after_query_progress),
        "position_before": {"lat": float(before_status["current_lat"]), "lng": float(before_status["current_lng"])},
        "position_after": {"lat": float(after_status["current_lat"]), "lng": float(after_status["current_lng"])},
        "simulation_end_time": _format_sim_clock(end_progress),
        "action": action,
        "token_usage": _zero_usage(),
        "result": result,
    }


def _write_candidate_run(
    out_dir: Path,
    driver_id: str,
    node: BeamNode,
    settings: Any,
    *,
    simulate_time_seconds: float,
) -> None:
    action_path = out_dir / f"actions_202603_{driver_id}_beam.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in node.history:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "simulate_time_seconds": simulate_time_seconds,
        "completed_steps": len(node.history),
        "remaining_cargo_count": node.repo.size,
        "simulation_progress_minutes": node.progress(),
        "simulation_wall_time": _format_sim_clock(node.progress()) + ":00",
        "driver_completed_steps": {driver_id: len(node.history)},
        "driver_result_files": {driver_id: str(action_path.resolve())},
        "simulation_duration_days": int(settings.simulation_duration_days),
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _score_candidate(run_dir: Path) -> dict[str, Any] | None:
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


def _make_root_node(settings: Any, driver_id: str) -> BeamNode:
    repo = CargoRepository(settings.cargo_dataset_path)
    repo.load()
    manager = DriverStateManager(settings.drivers_path)
    manager.load()
    manager.start_simulation(driver_id=driver_id, progress_minutes=0)
    repo.sync_time_minutes(0)
    return BeamNode(repo=repo, manager=manager)


def _clone_repo(repo: CargoRepository) -> CargoRepository:
    """Fast clone for search branches.

    The cargo dataset records are immutable during simulation.  Branches only
    mutate queue cursors, online dictionaries, heaps, and cache flags, so we can
    safely share the large pending list instead of deepcopying 500k records.
    """
    cloned = CargoRepository(getattr(repo, "_path"), earth_radius_km=float(getattr(repo, "_earth_radius_km", 6371.0)))
    cloned._pending = getattr(repo, "_pending")
    cloned._pending_cursor = int(getattr(repo, "_pending_cursor", 0))
    cloned._online = dict(getattr(repo, "_online"))
    cloned._online_expire_heap = list(getattr(repo, "_online_expire_heap"))
    cloned._online_ids = list(getattr(repo, "_online_ids"))
    cloned._online_lat = getattr(repo, "_online_lat").copy()
    cloned._online_lng = getattr(repo, "_online_lng").copy()
    cloned._online_dirty = bool(getattr(repo, "_online_dirty", True))
    cloned._simulation_start_dt = getattr(repo, "_simulation_start_dt")
    cloned._current_time_minutes = int(getattr(repo, "_current_time_minutes", 0))
    return cloned


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


def _load_driver_cost_map(path: Path) -> dict[str, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["driver_id"]).upper(): float(item.get("cost_per_km", 1.5)) for item in raw if isinstance(item, dict)}


def _load_cargo_price_map(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            out[str(item.get("cargo_id", "")).strip()] = float(item.get("price", 0.0)) / 100.0
    return out


def _proxy_delta(action: dict[str, Any], result: dict[str, Any], *, cargo_price: dict[str, float], cost_per_km: float) -> float:
    name = _action_name(action)
    if name == "take_order" and bool(result.get("accepted", False)):
        cargo_id = str(result.get("cargo_id") or (action.get("params") or {}).get("cargo_id") or "")
        pickup = float(result.get("pickup_deadhead_km", 0.0) or 0.0)
        haul = float(result.get("haul_distance_km", 0.0) or 0.0)
        price = cargo_price.get(cargo_id, 0.0) if bool(result.get("income_eligible", True)) else 0.0
        return price - (pickup + haul) * cost_per_km
    if name == "reposition":
        return -float(result.get("distance_km", 0.0) or 0.0) * cost_per_km
    if name == "wait":
        minutes = max(0, _int((action.get("params") or {}).get("duration_minutes")))
        # Waiting has opportunity cost in search. Rest-credit can compensate
        # intentional legal-rest branches, but blind long waits should not win ties.
        return -0.02 * minutes
    return 0.0


def _rank_score(node: BeamNode, horizon_minutes: int) -> float:
    # Do not reward time passage: otherwise long waits dominate early search.
    return node.proxy_score


def _event_wait_minutes(repo: CargoRepository, current_minutes: int, horizon_minutes: int, *, min_event_wait: int) -> list[int]:
    waits: set[int] = set()
    cursor = int(getattr(repo, "_pending_cursor", 0))
    pending = getattr(repo, "_pending", [])
    if 0 <= cursor < len(pending):
        next_create = int(pending[cursor][0])
        if current_minutes + min_event_wait <= next_create <= horizon_minutes:
            waits.add(next_create - current_minutes)

    minute = current_minutes % 1440
    for target in (6 * 60, 8 * 60, 10 * 60, 12 * 60, 14 * 60, 18 * 60, 20 * 60, 22 * 60):
        wait = target - minute if minute < target else 1440 - minute + target
        if min_event_wait <= wait <= 12 * 60 and current_minutes + wait <= horizon_minutes:
            waits.add(wait)

    return sorted(wait for wait in waits if min_event_wait <= wait <= 12 * 60)


def _top_diagnostic_score(diagnostics: dict[str, Any]) -> float:
    selectable = diagnostics.get("selectable_features")
    if not isinstance(selectable, list) or not selectable:
        return -1e9
    return max(float((item or {}).get("score", 0.0) or 0.0) for item in selectable if isinstance(item, dict))


def _find_driver_income(payload: dict[str, Any], driver_id: str) -> dict[str, Any]:
    for item in payload.get("drivers", []) or []:
        if str(item.get("driver_id", "")).upper() == driver_id.upper():
            income = item.get("income")
            return income if isinstance(income, dict) else {}
    return {}


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for action in actions:
        key = json.dumps({k: v for k, v in action.items() if not k.startswith("_")}, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


def _driver_limit_env() -> dict[str, int]:
    limits: dict[str, int] = {}
    for idx in range(1, 11):
        driver_id = f"D{idx:03d}"
        value = os.getenv(f"AGENT_{driver_id}_NEAREST_CARGO_LIMIT")
        if value is not None:
            limits[driver_id] = max(1, _int(value))
    return limits


def _parse_int_list(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(max(1, _int(part)))
    return out


def _write_markdown(path: Path, driver_id: str, preset: str, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Offline Beam Planner Summary",
        "",
        f"- driver: `{driver_id}`",
        f"- preset: `{preset}`",
        "",
        "| rank | exact_net | exact_penalty | proxy | steps | progress | run_dir |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | {_fmt(row.get('exact_net_income'))} | {_fmt(row.get('exact_penalty'))} | "
            f"{_fmt(row.get('proxy_score'))} | {row.get('steps')} | {row.get('progress_minutes')} | `{row.get('run_dir')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_out_dir(driver_id: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEMO_ROOT / "results" / "beam_planner" / f"{ts}_{driver_id}"


def _format_sim_clock(minutes: int) -> str:
    return (SIM_EPOCH + timedelta(minutes=int(minutes))).strftime("%Y-%m-%d %H:%M")


def _action_name(action: dict[str, Any]) -> str:
    return str(action.get("action", "")).strip().lower()


def _action_label(action: dict[str, Any]) -> str:
    name = _action_name(action)
    params = action.get("params") or {}
    if name == "take_order":
        return f"take:{params.get('cargo_id')}"
    if name == "wait":
        return f"wait{params.get('duration_minutes')}"
    if name == "reposition":
        return f"reposition:{params.get('latitude')},{params.get('longitude')}"
    return name


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
