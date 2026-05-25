"""Offline oracle route miner for high-yield trajectory discovery.

This is not a submission agent.  It deliberately uses the full cargo table to
search for profitable route skeletons, then writes normal action JSONL files so
the official income calculator can score the result.  The goal is to discover
large route-level gaps that can later be distilled into online agent rules or a
pre-recorded trajectory submission.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

DEMO_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = DEMO_ROOT / "server"
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from calc_monthly_income import haversine_km, load_driver_cost_map
from server.bench.settings import load_settings


SIM_EPOCH = datetime(2026, 3, 1, 0, 0, 0)
HORIZON_MINUTES = 30 * 1440


@dataclass(frozen=True)
class CargoRecord:
    cargo_id: str
    cargo_name: str
    price: float
    create_minutes: int
    remove_minutes: int
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    load_start_minutes: int | None
    load_end_minutes: int | None
    cost_time_minutes: int
    haul_km: float


@dataclass
class CargoTable:
    records: list[CargoRecord]
    ids: np.ndarray
    create: np.ndarray
    remove: np.ndarray
    start_lat: np.ndarray
    start_lng: np.ndarray
    end_lat: np.ndarray
    end_lng: np.ndarray
    load_start: np.ndarray
    load_end: np.ndarray
    duration: np.ndarray
    price: np.ndarray
    haul_km: np.ndarray
    gross_margin: np.ndarray


@dataclass
class RouteNode:
    progress: int
    lat: float
    lng: float
    history: list[dict[str, Any]] = field(default_factory=list)
    used_ids: frozenset[str] = frozenset()
    proxy_score: float = 0.0
    accepted_orders: int = 0
    label: str = "root"


@dataclass(frozen=True)
class Candidate:
    cargo_index: int
    accept_minutes: int
    finish_minutes: int
    pickup_km: float
    pickup_minutes: int
    load_wait_minutes: int
    haul_km: float
    gross: float
    net: float
    elapsed_minutes: int
    score: float
    destination_value: float


@dataclass(frozen=True)
class TargetPoint:
    label: str
    lat: float
    lng: float
    bonus: float = 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine high-yield full-month routes with global cargo visibility.")
    parser.add_argument("--driver", required=True, help="Driver id, e.g. D009.")
    parser.add_argument("--beam-width", type=int, default=10)
    parser.add_argument("--branch-top-n", type=int, default=14)
    parser.add_argument("--candidate-pool", type=int, default=220)
    parser.add_argument("--max-steps", type=int, default=180)
    parser.add_argument("--future-window", type=int, default=18 * 60)
    parser.add_argument("--max-pickup-km", type=float, default=180.0)
    parser.add_argument("--min-net", type=float, default=-400.0)
    parser.add_argument("--score-nph-weight", type=float, default=1.8)
    parser.add_argument("--score-future-weight", type=float, default=0.55)
    parser.add_argument("--score-wait-penalty", type=float, default=0.015)
    parser.add_argument("--score-pickup-penalty", type=float, default=0.2)
    parser.add_argument("--rest-waits", default="", help="Optional explicit wait branches, comma-separated minutes.")
    parser.add_argument("--query-cost", type=int, default=0, help="Synthetic query cost minutes per decision.")
    parser.add_argument(
        "--seed-actions",
        default="",
        help="Optional existing actions JSONL used as a fixed route prefix before mining the remaining tail.",
    )
    parser.add_argument(
        "--seed-prefix-orders",
        type=int,
        default=0,
        help="Number of take_order actions to keep from --seed-actions before tail mining.",
    )
    parser.add_argument(
        "--preference-mode",
        choices=["ignore", "soft", "d001_capsoft", "d006_semisoft"],
        default="soft",
        help="Preference proxy. d001_capsoft treats D001 rest/Shenzhen penalties as capped fixed costs. d006_semisoft keeps the high-gross route search but avoids the expensive D006 fish/long-haul caps.",
    )
    parser.add_argument(
        "--reposition-targets",
        default="",
        help="Optional target reposition branches: label:lat,lng[:bonus];label2:lat,lng[:bonus].",
    )
    parser.add_argument(
        "--reposition-daily-window",
        default="",
        help="Optional daily action window for target reposition, e.g. 16:00-23:00 or 960-1380.",
    )
    parser.add_argument("--reposition-min-km", type=float, default=5.0)
    parser.add_argument("--reposition-max-km", type=float, default=260.0)
    parser.add_argument("--reposition-value-weight", type=float, default=0.35)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--score-final", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    driver_id = args.driver.strip().upper()
    drivers = _load_drivers(settings.drivers_path)
    if driver_id not in drivers:
        raise KeyError(f"unknown driver: {driver_id}")
    cost_map = load_driver_cost_map(settings.drivers_path)
    cost_per_km = float(cost_map.get(driver_id, 1.5))
    speed = float(settings.reposition_speed_km_per_hour)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir(driver_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "oracle_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    cargo = _load_cargo_table(settings.cargo_dataset_path, cost_per_km=cost_per_km)
    value_index = _build_value_index(cargo)
    driver = drivers[driver_id]
    root = RouteNode(
        progress=0,
        lat=float(driver.get("current_lat", 0.0)),
        lng=float(driver.get("current_lng", 0.0)),
    )
    if args.seed_actions:
        root = _load_seed_prefix(
            Path(args.seed_actions),
            driver_id=driver_id,
            prefix_orders=max(0, int(args.seed_prefix_orders)),
            fallback=root,
        )
        print(
            f"seed prefix: orders={root.accepted_orders} steps={len(root.history)} "
            f"t={_clock(root.progress)} used={len(root.used_ids)}",
            flush=True,
        )

    wait_branches = _parse_int_list(args.rest_waits)
    reposition_targets = _parse_target_points(args.reposition_targets)
    reposition_daily_window = _parse_daily_window(args.reposition_daily_window)
    beam = [root]
    finals: list[RouteNode] = []
    for depth in range(max(1, int(args.max_steps))):
        expanded: list[RouteNode] = []
        for node in beam:
            if node.progress >= HORIZON_MINUTES:
                finals.append(node)
                continue
            expanded.extend(
                _expand_node(
                    node,
                    cargo,
                    value_index=value_index,
                    driver_id=driver_id,
                    speed_km_per_hour=speed,
                    cost_per_km=cost_per_km,
                    query_cost=max(0, int(args.query_cost)),
                    future_window=max(0, int(args.future_window)),
                    max_pickup_km=max(1.0, float(args.max_pickup_km)),
                    min_net=float(args.min_net),
                    branch_top_n=max(1, int(args.branch_top_n)),
                    candidate_pool=max(1, int(args.candidate_pool)),
                    nph_weight=float(args.score_nph_weight),
                    future_weight=float(args.score_future_weight),
                    wait_penalty=float(args.score_wait_penalty),
                    pickup_penalty=float(args.score_pickup_penalty),
                    preference_mode=str(args.preference_mode),
                    wait_branches=wait_branches,
                    reposition_targets=reposition_targets,
                    reposition_daily_window=reposition_daily_window,
                    reposition_min_km=max(0.0, float(args.reposition_min_km)),
                    reposition_max_km=max(1.0, float(args.reposition_max_km)),
                    reposition_value_weight=float(args.reposition_value_weight),
                )
            )
        if not expanded:
            break
        expanded.sort(key=_rank_node, reverse=True)
        beam = expanded[: max(1, int(args.beam_width))]
        if depth % 10 == 0:
            print(
                f"depth={depth + 1} "
                + ", ".join(
                    f"{n.label}:proxy={n.proxy_score:.1f}:t={_clock(n.progress)}:orders={n.accepted_orders}"
                    for n in beam[:3]
                ),
                flush=True,
            )

    finals.extend(beam)
    finals.sort(key=_rank_node, reverse=True)
    finals = finals[: max(1, int(args.beam_width))]
    rows: list[dict[str, Any]] = []
    for idx, node in enumerate(finals, start=1):
        cand_dir = out_dir / f"candidate_{idx:02d}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        _write_run(cand_dir, node, driver_id=driver_id, settings=settings, elapsed=round(time.perf_counter() - started, 2))
        score_payload = _score_candidate(cand_dir) if args.score_final else None
        row = {
            "candidate": idx,
            "proxy_score": round(node.proxy_score, 2),
            "orders": node.accepted_orders,
            "steps": len(node.history),
            "progress_minutes": node.progress,
            "wall_time": _clock(node.progress),
            "label": node.label,
            "run_dir": str(cand_dir),
        }
        if score_payload:
            income = _find_driver_income(score_payload, driver_id)
            row.update(
                {
                    "exact_net_income": income.get("net_income"),
                    "exact_gross_income": income.get("gross_income"),
                    "exact_distance_km": income.get("distance_km"),
                    "exact_preference_penalty": income.get("preference_penalty"),
                }
            )
        rows.append(row)
    rows.sort(key=lambda item: float(item.get("exact_net_income", item.get("proxy_score", 0.0)) or 0.0), reverse=True)
    (out_dir / "oracle_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "oracle_summary.md", driver_id, rows)
    print(f"written: {out_dir / 'oracle_summary.md'}")
    print(json.dumps(rows[: min(5, len(rows))], ensure_ascii=False, indent=2))
    return 0


def _expand_node(
    node: RouteNode,
    cargo: CargoTable,
    *,
    value_index: dict[tuple[int, int, int], float],
    driver_id: str,
    speed_km_per_hour: float,
    cost_per_km: float,
    query_cost: int,
    future_window: int,
    max_pickup_km: float,
    min_net: float,
    branch_top_n: int,
    candidate_pool: int,
    nph_weight: float,
    future_weight: float,
    wait_penalty: float,
    pickup_penalty: float,
    preference_mode: str,
    wait_branches: list[int],
    reposition_targets: list[TargetPoint],
    reposition_daily_window: tuple[int, int] | None,
    reposition_min_km: float,
    reposition_max_km: float,
    reposition_value_weight: float,
) -> list[RouteNode]:
    action_start_floor = node.progress + query_cost
    candidates = _generate_candidates(
        node,
        cargo,
        value_index=value_index,
        speed_km_per_hour=speed_km_per_hour,
        cost_per_km=cost_per_km,
        action_start_floor=action_start_floor,
        future_window=future_window,
        max_pickup_km=max_pickup_km,
        min_net=min_net,
        candidate_pool=candidate_pool,
        nph_weight=nph_weight,
        future_weight=future_weight,
        wait_penalty=wait_penalty,
        pickup_penalty=pickup_penalty,
        preference_mode=preference_mode,
        driver_id=driver_id,
    )
    out: list[RouteNode] = []
    for cand in candidates[:branch_top_n]:
        out.append(_take_candidate(node, cargo.records[cand.cargo_index], cand, driver_id=driver_id, query_cost=query_cost))
    for minutes in wait_branches:
        if minutes <= 0 or node.progress + minutes > HORIZON_MINUTES:
            continue
        out.append(_wait_node(node, minutes, driver_id=driver_id, label=f"wait:{minutes}"))
    for target in reposition_targets:
        if reposition_daily_window is not None and not _minute_in_daily_window(node.progress, reposition_daily_window):
            continue
        moved = _reposition_node(
            node,
            target,
            driver_id=driver_id,
            speed_km_per_hour=speed_km_per_hour,
            cost_per_km=cost_per_km,
            query_cost=query_cost,
            value_index=value_index,
            min_km=reposition_min_km,
            max_km=reposition_max_km,
            future_weight=future_weight * reposition_value_weight,
            wait_penalty=wait_penalty,
        )
        if moved is not None:
            out.append(moved)
    if not out:
        # Move time to the next likely release instead of dying at an empty/low-value state.
        next_wait = _next_release_wait(cargo, node.progress, max_wait=max(60, future_window))
        if next_wait > 0:
            out.append(_wait_node(node, next_wait, driver_id=driver_id, label=f"eventwait:{next_wait}"))
    return out


def _generate_candidates(
    node: RouteNode,
    cargo: CargoTable,
    *,
    value_index: dict[tuple[int, int, int], float],
    speed_km_per_hour: float,
    cost_per_km: float,
    action_start_floor: int,
    future_window: int,
    max_pickup_km: float,
    min_net: float,
    candidate_pool: int,
    nph_weight: float,
    future_weight: float,
    wait_penalty: float,
    pickup_penalty: float,
    preference_mode: str,
    driver_id: str,
) -> list[Candidate]:
    used = node.used_ids
    pickup_km = _haversine_array(node.lat, node.lng, cargo.start_lat, cargo.start_lng)
    pickup_minutes = np.ceil((pickup_km / speed_km_per_hour) * 60.0).astype(np.int32)
    pickup_minutes = np.where(pickup_km <= 1e-6, 0, np.maximum(1, pickup_minutes))
    accept = np.maximum(action_start_floor, cargo.create)
    has_window = cargo.load_end >= 0
    just_in_time = cargo.load_start - pickup_minutes
    accept = np.where(has_window, np.maximum(accept, just_in_time), accept)
    arrival = accept + pickup_minutes
    load_wait = np.where(has_window, np.maximum(0, cargo.load_start - arrival), 0)
    finish = arrival + load_wait + cargo.duration
    latest_accept = np.minimum(cargo.remove, np.where(has_window, cargo.load_end - pickup_minutes, cargo.remove))
    wait_to_accept = accept - action_start_floor
    elapsed = finish - node.progress
    net = cargo.price - cost_per_km * (pickup_km + cargo.haul_km)
    valid = (
        (accept >= action_start_floor)
        & (accept <= latest_accept)
        & (accept <= cargo.remove)
        & (finish <= HORIZON_MINUTES)
        & (wait_to_accept <= future_window)
        & (pickup_km <= max_pickup_km)
        & (net >= min_net)
        & (elapsed > 0)
    )
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return []
    nph = np.zeros_like(net)
    nph[idx] = net[idx] / np.maximum(1.0, elapsed[idx].astype(np.float64) / 60.0)
    rough = net + nph_weight * nph - wait_penalty * wait_to_accept - pickup_penalty * pickup_km
    rough_idx = idx[np.argpartition(rough[idx], -min(candidate_pool * 4, idx.size))[-min(candidate_pool * 4, idx.size):]]
    scored: list[Candidate] = []
    heap: list[tuple[float, int]] = []
    for raw_i in rough_idx:
        i = int(raw_i)
        cargo_id = str(cargo.ids[i])
        if cargo_id in used:
            continue
        pref = _preference_proxy(
            driver_id,
            cargo.records[i],
            node_progress=node.progress,
            action_start=int(accept[i]),
            finish=int(finish[i]),
            pickup_km=float(pickup_km[i]),
            preference_mode=preference_mode,
        )
        dest = _lookup_destination_value(value_index, int(finish[i]), float(cargo.end_lat[i]), float(cargo.end_lng[i]))
        score = (
            float(net[i])
            + nph_weight * float(nph[i])
            + future_weight * dest
            - wait_penalty * float(wait_to_accept[i])
            - pickup_penalty * float(pickup_km[i])
            - pref
        )
        if len(heap) < candidate_pool:
            heapq.heappush(heap, (score, i))
        elif score > heap[0][0]:
            heapq.heapreplace(heap, (score, i))
    for score, i in sorted(heap, reverse=True):
        elapsed_i = int(finish[i]) - node.progress
        scored.append(
            Candidate(
                cargo_index=i,
                accept_minutes=int(accept[i]),
                finish_minutes=int(finish[i]),
                pickup_km=float(pickup_km[i]),
                pickup_minutes=int(pickup_minutes[i]),
                load_wait_minutes=int(load_wait[i]),
                haul_km=float(cargo.haul_km[i]),
                gross=float(cargo.price[i]),
                net=float(net[i]),
                elapsed_minutes=elapsed_i,
                score=float(score),
                destination_value=_lookup_destination_value(value_index, int(finish[i]), float(cargo.end_lat[i]), float(cargo.end_lng[i])),
            )
        )
    return scored


def _take_candidate(node: RouteNode, rec: CargoRecord, cand: Candidate, *, driver_id: str, query_cost: int) -> RouteNode:
    history = list(node.history)
    progress = node.progress
    if cand.accept_minutes > progress + query_cost:
        wait_minutes = cand.accept_minutes - progress - query_cost
        if wait_minutes > 0:
            wait_node = _wait_node(node, wait_minutes, driver_id=driver_id, label=f"prewait:{wait_minutes}", query_cost=query_cost)
            history = list(wait_node.history)
            progress = wait_node.progress
            query_cost = 0
    step_start = progress
    action_start = step_start + query_cost
    exec_minutes = cand.pickup_minutes + cand.load_wait_minutes + rec.cost_time_minutes
    end_progress = action_start + exec_minutes
    action = {"action": "take_order", "params": {"cargo_id": rec.cargo_id}, "model_usage": _zero_usage()}
    result = {
        "accepted": True,
        "detail": "oracle route miner accepted cargo",
        "driver_id": driver_id,
        "cargo_id": rec.cargo_id,
        "simulation_progress_minutes": end_progress,
        "simulation_wall_time": _clock(end_progress) + ":00",
        "pickup_deadhead_km": round(cand.pickup_km, 2),
        "haul_distance_km": round(rec.haul_km, 2),
        "income_eligible": end_progress <= HORIZON_MINUTES,
    }
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": driver_id,
            "step_elapsed_minutes": query_cost + exec_minutes,
            "query_scan_cost_minutes": query_cost,
            "action_exec_cost_minutes": exec_minutes,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": round(rec.end_lat, 6), "lng": round(rec.end_lng, 6)},
            "simulation_end_time": _clock(end_progress),
            "action": action,
            "token_usage": _zero_usage(),
            "result": result,
        }
    )
    return RouteNode(
        progress=end_progress,
        lat=rec.end_lat,
        lng=rec.end_lng,
        history=history,
        used_ids=node.used_ids | {rec.cargo_id},
        proxy_score=node.proxy_score + cand.score,
        accepted_orders=node.accepted_orders + 1,
        label=f"{node.label}>take:{rec.cargo_id}",
    )


def _wait_node(node: RouteNode, minutes: int, *, driver_id: str, label: str, query_cost: int = 0) -> RouteNode:
    end_progress = min(HORIZON_MINUTES, node.progress + query_cost + minutes)
    actual_wait = max(0, end_progress - node.progress - query_cost)
    history = list(node.history)
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": driver_id,
            "step_elapsed_minutes": query_cost + actual_wait,
            "query_scan_cost_minutes": query_cost,
            "action_exec_cost_minutes": actual_wait,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "simulation_end_time": _clock(end_progress),
            "action": {"action": "wait", "params": {"duration_minutes": actual_wait}, "model_usage": _zero_usage()},
            "token_usage": _zero_usage(),
            "result": {
                "simulation_progress_minutes": end_progress,
                "simulation_wall_time": _clock(end_progress) + ":00",
            },
        }
    )
    return RouteNode(
        progress=end_progress,
        lat=node.lat,
        lng=node.lng,
        history=history,
        used_ids=node.used_ids,
        proxy_score=node.proxy_score - 0.02 * actual_wait,
        accepted_orders=node.accepted_orders,
        label=f"{node.label}>{label}",
    )


def _reposition_node(
    node: RouteNode,
    target: TargetPoint,
    *,
    driver_id: str,
    speed_km_per_hour: float,
    cost_per_km: float,
    query_cost: int,
    value_index: dict[tuple[int, int, int], float],
    min_km: float,
    max_km: float,
    future_weight: float,
    wait_penalty: float,
) -> RouteNode | None:
    distance_km = haversine_km(node.lat, node.lng, target.lat, target.lng)
    if distance_km < min_km or distance_km > max_km:
        return None
    move_minutes = _distance_to_minutes(distance_km, speed_km_per_hour)
    end_progress = node.progress + query_cost + move_minutes
    if end_progress > HORIZON_MINUTES:
        return None
    dest_value = _lookup_destination_value(value_index, end_progress, target.lat, target.lng)
    proxy_delta = target.bonus + future_weight * dest_value - cost_per_km * distance_km - wait_penalty * move_minutes
    history = list(node.history)
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": driver_id,
            "step_elapsed_minutes": query_cost + move_minutes,
            "query_scan_cost_minutes": query_cost,
            "action_exec_cost_minutes": move_minutes,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": round(target.lat, 6), "lng": round(target.lng, 6)},
            "simulation_end_time": _clock(end_progress),
            "action": {
                "action": "reposition",
                "params": {"latitude": round(target.lat, 6), "longitude": round(target.lng, 6)},
                "model_usage": _zero_usage(),
            },
            "token_usage": _zero_usage(),
            "result": {
                "current_lat": round(target.lat, 6),
                "current_lng": round(target.lng, 6),
                "simulation_progress_minutes": end_progress,
                "simulation_wall_time": _clock(end_progress) + ":00",
                "distance_km": round(distance_km, 2),
            },
        }
    )
    return RouteNode(
        progress=end_progress,
        lat=target.lat,
        lng=target.lng,
        history=history,
        used_ids=node.used_ids,
        proxy_score=node.proxy_score + proxy_delta,
        accepted_orders=node.accepted_orders,
        label=f"{node.label}>repos:{target.label}",
    )


def _preference_proxy(
    driver_id: str,
    rec: CargoRecord,
    *,
    node_progress: int,
    action_start: int,
    finish: int,
    pickup_km: float,
    preference_mode: str,
) -> float:
    if preference_mode == "ignore":
        return 0.0
    name = rec.cargo_name
    penalty = 0.0
    if driver_id == "D001":
        if name in {"化工塑料", "煤炭矿产"}:
            penalty += 500.0
        if preference_mode == "d001_capsoft":
            return penalty
        if not (_in_shenzhen(rec.start_lat, rec.start_lng) and _in_shenzhen(rec.end_lat, rec.end_lng)):
            penalty += 120.0
    elif driver_id == "D002":
        if name == "蔬菜":
            penalty += 350.0
    elif driver_id == "D003":
        penalty += max(0.0, pickup_km - 100.0) * 4.0
        if _near(rec.start_lat, rec.start_lng, 23.30, 113.52, 20.0) or _near(rec.end_lat, rec.end_lng, 23.30, 113.52, 20.0):
            penalty += 500.0
        if _overlaps_daily(action_start, finish, 2 * 60, 5 * 60):
            penalty += 100.0
    elif driver_id == "D004":
        if _overlaps_daily(action_start, finish, 12 * 60, 13 * 60):
            penalty += 60.0
    elif driver_id == "D005":
        if rec.haul_km > 100.0:
            penalty += 100.0
        if pickup_km > 90.0:
            penalty += 100.0
        if _overlaps_night(action_start, finish, 23 * 60, 6 * 60):
            penalty += 120.0
    elif driver_id == "D006":
        if preference_mode == "d006_semisoft":
            # D006's rest/off-day penalties cap out, but fish and long-haul caps
            # explain most of the gap between the high-gross chain and the best
            # exact monthly score. Use a light proxy so gross can still win.
            if name == "鲜活水产品":
                penalty += 650.0
            if rec.haul_km > 150.0:
                penalty += 260.0
            return penalty
        if name == "鲜活水产品":
            penalty += 300.0
        if rec.haul_km > 150.0:
            penalty += 150.0
    elif driver_id == "D007":
        if name == "机械设备":
            penalty += 220.0
        if rec.haul_km > 180.0:
            penalty += 100.0
        if _overlaps_night(action_start, finish, 23 * 60, 4 * 60):
            penalty += 200.0
    elif driver_id == "D008":
        if name == "食品饮料":
            penalty += 120.0
        if pickup_km > 50.0:
            penalty += 100.0
    elif driver_id == "D009":
        if name == "快递快运搬家":
            penalty += 350.0
        if _overlaps_night(action_start, finish, 23 * 60, 8 * 60):
            penalty += 160.0
    elif driver_id == "D010":
        if name == "服饰纺织皮革":
            penalty += 120.0
        if _overlaps_daily(action_start, finish, 0, 3 * 60):
            penalty += 80.0
    return penalty


def _build_value_index(cargo: CargoTable) -> dict[tuple[int, int, int], float]:
    value: dict[tuple[int, int, int], list[float]] = {}
    base = cargo.gross_margin + 0.08 * cargo.price
    buckets = np.maximum(0, cargo.create // 360)
    lat_cell = np.floor(cargo.start_lat * 10).astype(np.int32)
    lng_cell = np.floor(cargo.start_lng * 10).astype(np.int32)
    order = np.argpartition(base, -min(50000, len(base)))[-min(50000, len(base)):]
    for i in order:
        key = (int(buckets[i]), int(lat_cell[i]), int(lng_cell[i]))
        value.setdefault(key, []).append(float(base[i]))
    out: dict[tuple[int, int, int], float] = {}
    for key, vals in value.items():
        vals.sort(reverse=True)
        out[key] = vals[0] + 0.35 * sum(vals[1:4])
    return out


def _lookup_destination_value(index: dict[tuple[int, int, int], float], minute: int, lat: float, lng: float) -> float:
    bucket = max(0, minute // 360)
    lat_cell = math.floor(lat * 10)
    lng_cell = math.floor(lng * 10)
    best = 0.0
    for db in range(0, 5):
        for da in (-1, 0, 1):
            for dg in (-1, 0, 1):
                best = max(best, index.get((bucket + db, lat_cell + da, lng_cell + dg), 0.0))
    return best


def _load_cargo_table(path: Path, *, cost_per_km: float) -> CargoTable:
    records: list[CargoRecord] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            start = item.get("start", {}) or {}
            end = item.get("end", {}) or {}
            start_lat = float(start["lat"])
            start_lng = float(start["lng"])
            end_lat = float(end["lat"])
            end_lng = float(end["lng"])
            load_window = item.get("load_time")
            load_start = None
            load_end = None
            if isinstance(load_window, list) and len(load_window) == 2:
                load_start = _parse_minutes(str(load_window[0]))
                load_end = _parse_minutes(str(load_window[1]))
                if load_end < load_start:
                    load_start = None
                    load_end = None
            haul = haversine_km(start_lat, start_lng, end_lat, end_lng)
            records.append(
                CargoRecord(
                    cargo_id=str(item["cargo_id"]),
                    cargo_name=str(item.get("cargo_name", "") or ""),
                    price=float(item.get("price", 0.0)) / 100.0,
                    create_minutes=_parse_minutes(str(item["create_time"])),
                    remove_minutes=_parse_minutes(str(item["remove_time"])),
                    start_lat=start_lat,
                    start_lng=start_lng,
                    end_lat=end_lat,
                    end_lng=end_lng,
                    load_start_minutes=load_start,
                    load_end_minutes=load_end,
                    cost_time_minutes=int(item.get("cost_time_minutes", 0) or 0),
                    haul_km=haul,
                )
            )
    ids = np.asarray([r.cargo_id for r in records], dtype=object)
    create = np.asarray([r.create_minutes for r in records], dtype=np.int32)
    remove = np.asarray([r.remove_minutes for r in records], dtype=np.int32)
    start_lat = np.asarray([r.start_lat for r in records], dtype=np.float64)
    start_lng = np.asarray([r.start_lng for r in records], dtype=np.float64)
    end_lat = np.asarray([r.end_lat for r in records], dtype=np.float64)
    end_lng = np.asarray([r.end_lng for r in records], dtype=np.float64)
    load_start = np.asarray([r.load_start_minutes if r.load_start_minutes is not None else -1 for r in records], dtype=np.int32)
    load_end = np.asarray([r.load_end_minutes if r.load_end_minutes is not None else -1 for r in records], dtype=np.int32)
    duration = np.asarray([r.cost_time_minutes for r in records], dtype=np.int32)
    price = np.asarray([r.price for r in records], dtype=np.float64)
    haul_km = np.asarray([r.haul_km for r in records], dtype=np.float64)
    gross_margin = price - cost_per_km * haul_km
    return CargoTable(
        records=records,
        ids=ids,
        create=create,
        remove=remove,
        start_lat=start_lat,
        start_lng=start_lng,
        end_lat=end_lat,
        end_lng=end_lng,
        load_start=load_start,
        load_end=load_end,
        duration=duration,
        price=price,
        haul_km=haul_km,
        gross_margin=gross_margin,
    )


def _load_drivers(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["driver_id"]).upper(): item for item in raw if isinstance(item, dict)}


def _load_seed_prefix(path: Path, *, driver_id: str, prefix_orders: int, fallback: RouteNode) -> RouteNode:
    if prefix_orders <= 0:
        return fallback
    if not path.is_file():
        raise FileNotFoundError(f"missing --seed-actions file: {path}")
    history: list[dict[str, Any]] = []
    used: set[str] = set()
    progress = fallback.progress
    lat = fallback.lat
    lng = fallback.lng
    accepted = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            action = rec.get("action") if isinstance(rec, dict) else None
            params = action.get("params", {}) if isinstance(action, dict) else {}
            action_name = str(action.get("action", "") if isinstance(action, dict) else "")
            history.append(rec)
            result = rec.get("result", {}) if isinstance(rec.get("result"), dict) else {}
            pos_after = rec.get("position_after", {}) if isinstance(rec.get("position_after"), dict) else {}
            progress = int(result.get("simulation_progress_minutes") or progress)
            lat = float(pos_after.get("lat", lat))
            lng = float(pos_after.get("lng", lng))
            if action_name == "take_order":
                cargo_id = str(params.get("cargo_id", "")).strip()
                if cargo_id:
                    used.add(cargo_id)
                accepted += 1
                if accepted >= prefix_orders:
                    break
    if accepted < prefix_orders:
        raise ValueError(f"{path} contains only {accepted} take_order actions, requested prefix {prefix_orders}")
    return RouteNode(
        progress=progress,
        lat=lat,
        lng=lng,
        history=history,
        used_ids=frozenset(used),
        proxy_score=0.0,
        accepted_orders=accepted,
        label=f"seed:{driver_id}:{prefix_orders}",
    )


def _write_run(out_dir: Path, node: RouteNode, *, driver_id: str, settings: Any, elapsed: float) -> None:
    action_path = out_dir / f"actions_202603_{driver_id}_oracle.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in node.history:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "simulate_time_seconds": elapsed,
        "completed_steps": len(node.history),
        "remaining_cargo_count": 0,
        "simulation_progress_minutes": node.progress,
        "simulation_wall_time": _clock(node.progress) + ":00",
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


def _find_driver_income(payload: dict[str, Any], driver_id: str) -> dict[str, Any]:
    for item in payload.get("drivers", []) or []:
        if str(item.get("driver_id", "")).upper() == driver_id.upper():
            income = item.get("income")
            return income if isinstance(income, dict) else item
    return {}


def _next_release_wait(cargo: CargoTable, progress: int, *, max_wait: int) -> int:
    future = cargo.create[cargo.create > progress]
    if future.size == 0:
        return 0
    wait = int(np.min(future)) - progress
    return wait if 0 < wait <= max_wait else 0


def _haversine_array(lat: float, lng: float, lat_arr: np.ndarray, lng_arr: np.ndarray) -> np.ndarray:
    radius_km = 6371.0
    p1 = math.radians(lat)
    l1 = math.radians(lng)
    p2 = np.radians(lat_arr)
    l2 = np.radians(lng_arr)
    dp = p2 - p1
    dl = l2 - l1
    h = np.sin(dp * 0.5) ** 2 + np.cos(p1) * np.cos(p2) * (np.sin(dl * 0.5) ** 2)
    h = np.minimum(1.0, np.maximum(0.0, h))
    return 2.0 * radius_km * np.arcsin(np.sqrt(h))


def _parse_minutes(text: str) -> int:
    return int((datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S") - SIM_EPOCH).total_seconds() // 60)


def _clock(minutes: int) -> str:
    return (SIM_EPOCH + timedelta(minutes=int(minutes))).strftime("%Y-%m-%d %H:%M:%S")


def _distance_to_minutes(distance_km: float, speed_km_per_hour: float) -> int:
    if distance_km <= 0:
        return 1
    return max(1, int(math.ceil((distance_km / speed_km_per_hour) * 60.0)))


def _rank_node(node: RouteNode) -> float:
    return node.proxy_score + 0.015 * node.accepted_orders - 0.0002 * max(0, HORIZON_MINUTES - node.progress)


def _zero_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}


def _parse_int_list(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def _parse_target_points(text: str) -> list[TargetPoint]:
    out: list[TargetPoint] = []
    for raw in str(text or "").split(";"):
        item = raw.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"invalid target point, expected label:lat,lng[:bonus], got {item!r}")
        label, rest = item.split(":", 1)
        parts = [p.strip() for p in rest.split(":")]
        coord = parts[0]
        if "," not in coord:
            raise ValueError(f"invalid target coordinates: {item!r}")
        lat_s, lng_s = coord.split(",", 1)
        bonus = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
        out.append(TargetPoint(label=label.strip() or f"target{len(out) + 1}", lat=float(lat_s), lng=float(lng_s), bonus=bonus))
    return out


def _parse_daily_window(text: str) -> tuple[int, int] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if "-" not in raw:
        raise ValueError(f"invalid daily window: {raw!r}")
    start_s, end_s = raw.split("-", 1)
    return (_parse_day_minute(start_s.strip()), _parse_day_minute(end_s.strip()))


def _parse_day_minute(text: str) -> int:
    if ":" in text:
        hour_s, minute_s = text.split(":", 1)
        return int(hour_s) * 60 + int(minute_s)
    return int(text)


def _minute_in_daily_window(minute: int, window: tuple[int, int]) -> bool:
    start, end = window
    day_minute = int(minute) % 1440
    if start <= end:
        return start <= day_minute <= end
    return day_minute >= start or day_minute <= end


def _in_shenzhen(lat: float, lng: float) -> bool:
    return 22.42 <= lat <= 22.89 and 113.74 <= lng <= 114.66


def _near(lat: float, lng: float, center_lat: float, center_lng: float, radius_km: float) -> bool:
    return haversine_km(lat, lng, center_lat, center_lng) <= radius_km


def _overlaps_daily(start: int, end: int, window_start: int, window_end: int) -> bool:
    if end <= start:
        return False
    for day in range(start // 1440, end // 1440 + 1):
        ws = day * 1440 + window_start
        we = day * 1440 + window_end
        if max(start, ws) < min(end, we):
            return True
    return False


def _overlaps_night(start: int, end: int, night_start: int, morning_end: int) -> bool:
    if end <= start:
        return False
    for day in range(start // 1440 - 1, end // 1440 + 1):
        w1s = day * 1440 + night_start
        w1e = (day + 1) * 1440
        w2s = (day + 1) * 1440
        w2e = (day + 1) * 1440 + morning_end
        if max(start, w1s) < min(end, w1e) or max(start, w2s) < min(end, w2e):
            return True
    return False


def _write_markdown(path: Path, driver_id: str, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Oracle Route Miner",
        "",
        f"- driver: `{driver_id}`",
        "",
        "| rank | exact_net | gross | distance | penalty | proxy | orders | steps | wall_time | run_dir |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for rank, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {net} | {gross} | {dist} | {pen} | {proxy:.2f} | {orders} | {steps} | {wall} | `{run}` |".format(
                rank=rank,
                net=_fmt(row.get("exact_net_income")),
                gross=_fmt(row.get("exact_gross_income")),
                dist=_fmt(row.get("exact_distance_km")),
                pen=_fmt(row.get("exact_preference_penalty")),
                proxy=float(row.get("proxy_score") or 0.0),
                orders=row.get("orders", ""),
                steps=row.get("steps", ""),
                wall=row.get("wall_time", ""),
                run=row.get("run_dir", ""),
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
    return DEMO_ROOT / "results" / "oracle_route_miner" / f"{stamp}_{driver_id}"


if __name__ == "__main__":
    raise SystemExit(main())
