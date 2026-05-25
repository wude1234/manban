"""D009 daily-home constrained oracle route miner.

This is a high-score exploration harness, not an online submission agent.  It
uses the full cargo table to search D009 daytime route chains while preserving
the important D009 preference structure:

- normal work should fit between 08:00 and 23:00 and still allow returning home;
- the special cargo 240646 is allowed as the one known night-violating exception;
- express/moving cargo is penalized but not hard-forbidden, because exact scoring
  decides whether the tradeoff is worth it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
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
from oracle_route_miner import (
    HORIZON_MINUTES,
    CargoTable,
    _clock,
    _distance_to_minutes,
    _find_driver_income,
    _haversine_array,
    _load_cargo_table,
    _score_candidate,
    _zero_usage,
)
from server.bench.settings import load_settings


HOME_LAT = 23.12
HOME_LNG = 113.28
SPECIAL_CARGO_ID = "240646"
DAY_START = 8 * 60
DAY_END = 23 * 60


@dataclass
class Node:
    progress: int
    lat: float
    lng: float
    history: list[dict[str, Any]] = field(default_factory=list)
    used_ids: frozenset[str] = frozenset()
    proxy_score: float = 0.0
    orders: int = 0
    label: str = "root"


@dataclass(frozen=True)
class Candidate:
    cargo_index: int
    accept: int
    finish: int
    pickup_km: float
    pickup_minutes: int
    load_wait: int
    elapsed: int
    net: float
    nph: float
    return_home_km: float
    return_home_minutes: int
    score: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine D009 routes with daily home-return constraints.")
    parser.add_argument("--beam-width", type=int, default=24)
    parser.add_argument("--branch-top-n", type=int, default=12)
    parser.add_argument("--candidate-pool", type=int, default=480)
    parser.add_argument("--max-steps", type=int, default=260)
    parser.add_argument("--future-window", type=int, default=12 * 60)
    parser.add_argument("--max-pickup-km", type=float, default=160.0)
    parser.add_argument("--min-net", type=float, default=-250.0)
    parser.add_argument("--nph-weight", type=float, default=1.6)
    parser.add_argument("--return-weight", type=float, default=1.0)
    parser.add_argument("--pickup-penalty", type=float, default=0.12)
    parser.add_argument("--express-penalty", type=float, default=350.0)
    parser.add_argument("--home-margin-minutes", type=int, default=0)
    parser.add_argument("--out-dir", default="results/oracle_route_miner/d009_daily_home_oracle")
    parser.add_argument("--score-final", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    settings = load_settings()
    cost_per_km = float(load_driver_cost_map(settings.drivers_path).get("D009", 1.5))
    speed = float(settings.reposition_speed_km_per_hour)
    cargo = _load_cargo_table(settings.cargo_dataset_path, cost_per_km=cost_per_km)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "daily_home_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    beam = [Node(progress=0, lat=HOME_LAT, lng=HOME_LNG)]
    finals: list[Node] = []
    for depth in range(max(1, args.max_steps)):
        expanded: list[Node] = []
        for node in beam:
            if node.progress >= HORIZON_MINUTES:
                finals.append(node)
                continue
            expanded.extend(
                _expand_node(
                    node,
                    cargo,
                    speed_km_per_hour=speed,
                    cost_per_km=cost_per_km,
                    future_window=max(0, int(args.future_window)),
                    max_pickup_km=max(1.0, float(args.max_pickup_km)),
                    min_net=float(args.min_net),
                    candidate_pool=max(1, int(args.candidate_pool)),
                    branch_top_n=max(1, int(args.branch_top_n)),
                    nph_weight=float(args.nph_weight),
                    return_weight=float(args.return_weight),
                    pickup_penalty=float(args.pickup_penalty),
                    express_penalty=float(args.express_penalty),
                    home_margin_minutes=max(0, int(args.home_margin_minutes)),
                )
            )
        if not expanded:
            break
        expanded.sort(key=_rank_node, reverse=True)
        beam = expanded[: max(1, int(args.beam_width))]
        if depth % 10 == 0:
            print(
                f"depth={depth + 1} "
                + ", ".join(f"{n.label}:proxy={n.proxy_score:.1f}:t={_clock(n.progress)}:orders={n.orders}" for n in beam[:3]),
                flush=True,
            )

    finals.extend(beam)
    finals = [_complete_to_horizon(n, speed_km_per_hour=speed, cost_per_km=cost_per_km) for n in finals]
    finals.sort(key=_rank_node, reverse=True)
    finals = finals[: max(1, int(args.beam_width))]

    rows: list[dict[str, Any]] = []
    for idx, node in enumerate(finals, start=1):
        cand_dir = out_dir / f"candidate_{idx:02d}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        _write_run(cand_dir, node, elapsed=round(time.perf_counter() - started, 2))
        score_payload = _score_candidate(cand_dir) if args.score_final else None
        row: dict[str, Any] = {
            "candidate": idx,
            "proxy_score": round(node.proxy_score, 2),
            "orders": node.orders,
            "steps": len(node.history),
            "progress_minutes": node.progress,
            "wall_time": _clock(node.progress),
            "label": node.label,
            "run_dir": str(cand_dir),
        }
        if score_payload:
            income = _find_driver_income(score_payload, "D009")
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
    (out_dir / "daily_home_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "daily_home_summary.md", rows)
    print(f"written: {out_dir / 'daily_home_summary.md'}")
    print(json.dumps(rows[: min(5, len(rows))], ensure_ascii=False, indent=2))
    return 0


def _expand_node(
    node: Node,
    cargo: CargoTable,
    *,
    speed_km_per_hour: float,
    cost_per_km: float,
    future_window: int,
    max_pickup_km: float,
    min_net: float,
    candidate_pool: int,
    branch_top_n: int,
    nph_weight: float,
    return_weight: float,
    pickup_penalty: float,
    express_penalty: float,
    home_margin_minutes: int,
) -> list[Node]:
    if node.progress >= HORIZON_MINUTES:
        return []
    minute = node.progress % 1440
    day = node.progress // 1440
    if minute < DAY_START and _near_home(node):
        return [_wait_node(node, DAY_START - minute, label="nightwait")]
    if minute >= DAY_END and _near_home(node):
        return [_wait_node(node, (day + 1) * 1440 + DAY_START - node.progress, label="nightwait")]
    if minute >= DAY_END and not _near_home(node):
        return [_home_node(node, speed_km_per_hour=speed_km_per_hour, cost_per_km=cost_per_km, label="latehome")]

    candidates = _generate_candidates(
        node,
        cargo,
        speed_km_per_hour=speed_km_per_hour,
        cost_per_km=cost_per_km,
        future_window=future_window,
        max_pickup_km=max_pickup_km,
        min_net=min_net,
        candidate_pool=candidate_pool,
        nph_weight=nph_weight,
        return_weight=return_weight,
        pickup_penalty=pickup_penalty,
        express_penalty=express_penalty,
        home_margin_minutes=home_margin_minutes,
    )
    out = [_take_candidate(node, cargo, cand) for cand in candidates[:branch_top_n]]
    if not _near_home(node):
        home = _home_node(node, speed_km_per_hour=speed_km_per_hour, cost_per_km=cost_per_km, label="home")
        if home is not None:
            out.append(home)
    for minutes in _wait_options(node, cargo, future_window=future_window):
        out.append(_wait_node(node, minutes, label=f"wait{minutes}"))
    return out


def _generate_candidates(
    node: Node,
    cargo: CargoTable,
    *,
    speed_km_per_hour: float,
    cost_per_km: float,
    future_window: int,
    max_pickup_km: float,
    min_net: float,
    candidate_pool: int,
    nph_weight: float,
    return_weight: float,
    pickup_penalty: float,
    express_penalty: float,
    home_margin_minutes: int,
) -> list[Candidate]:
    pickup_km = _haversine_array(node.lat, node.lng, cargo.start_lat, cargo.start_lng)
    pickup_minutes = np.ceil((pickup_km / speed_km_per_hour) * 60.0).astype(np.int32)
    pickup_minutes = np.where(pickup_km <= 1e-6, 0, np.maximum(1, pickup_minutes))
    accept = np.maximum(node.progress, cargo.create)
    has_window = cargo.load_end >= 0
    just_in_time = cargo.load_start - pickup_minutes
    accept = np.where(has_window, np.maximum(accept, just_in_time), accept)
    arrival = accept + pickup_minutes
    load_wait = np.where(has_window, np.maximum(0, cargo.load_start - arrival), 0)
    finish = arrival + load_wait + cargo.duration
    latest_accept = np.minimum(cargo.remove, np.where(has_window, cargo.load_end - pickup_minutes, cargo.remove))
    wait_to_accept = accept - node.progress
    elapsed = finish - node.progress
    net = cargo.price - cost_per_km * (pickup_km + cargo.haul_km)
    return_home_km = _haversine_array(HOME_LAT, HOME_LNG, cargo.end_lat, cargo.end_lng)
    return_home_minutes = np.ceil((return_home_km / speed_km_per_hour) * 60.0).astype(np.int32)
    return_home_minutes = np.where(return_home_km <= 1e-6, 0, np.maximum(1, return_home_minutes))
    day_end = (node.progress // 1440) * 1440 + DAY_END - home_margin_minutes
    ids = cargo.ids.astype(str)
    is_special = ids == SPECIAL_CARGO_ID
    normal_home_safe = finish + return_home_minutes <= day_end
    valid = (
        (accept >= node.progress)
        & (accept <= latest_accept)
        & (accept <= cargo.remove)
        & (finish <= HORIZON_MINUTES)
        & (wait_to_accept <= future_window)
        & (pickup_km <= max_pickup_km)
        & (net >= min_net)
        & (elapsed > 0)
        & ((normal_home_safe) | is_special)
    )
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return []
    nph = np.zeros_like(net)
    nph[idx] = net[idx] / np.maximum(1.0, elapsed[idx].astype(np.float64) / 60.0)
    rough = net + nph_weight * nph - return_weight * cost_per_km * return_home_km - pickup_penalty * pickup_km
    rough_idx = idx[np.argpartition(rough[idx], -min(candidate_pool * 3, idx.size))[-min(candidate_pool * 3, idx.size):]]
    scored: list[Candidate] = []
    for raw_i in rough_idx:
        i = int(raw_i)
        cid = str(cargo.ids[i])
        if cid in node.used_ids:
            continue
        name = cargo.records[i].cargo_name
        pref = express_penalty if name == "快递快运搬家" else 0.0
        special_bonus = 12000.0 if cid == SPECIAL_CARGO_ID and SPECIAL_CARGO_ID not in node.used_ids else 0.0
        score = (
            float(net[i])
            + nph_weight * float(nph[i])
            - return_weight * cost_per_km * float(return_home_km[i])
            - pickup_penalty * float(pickup_km[i])
            - pref
            + special_bonus
        )
        scored.append(
            Candidate(
                cargo_index=i,
                accept=int(accept[i]),
                finish=int(finish[i]),
                pickup_km=float(pickup_km[i]),
                pickup_minutes=int(pickup_minutes[i]),
                load_wait=int(load_wait[i]),
                elapsed=int(elapsed[i]),
                net=float(net[i]),
                nph=float(nph[i]),
                return_home_km=float(return_home_km[i]),
                return_home_minutes=int(return_home_minutes[i]),
                score=float(score),
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:candidate_pool]


def _take_candidate(node: Node, cargo: CargoTable, cand: Candidate) -> Node:
    rec = cargo.records[cand.cargo_index]
    history = list(node.history)
    progress = node.progress
    if cand.accept > progress:
        wait_node = _wait_node(node, cand.accept - progress, label=f"prewait{cand.accept - progress}")
        history = list(wait_node.history)
        progress = wait_node.progress
    step_start = progress
    exec_minutes = cand.pickup_minutes + cand.load_wait + rec.cost_time_minutes
    end_progress = step_start + exec_minutes
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": "D009",
            "step_elapsed_minutes": exec_minutes,
            "query_scan_cost_minutes": 0,
            "action_exec_cost_minutes": exec_minutes,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": round(rec.end_lat, 6), "lng": round(rec.end_lng, 6)},
            "simulation_end_time": _clock(end_progress),
            "action": {"action": "take_order", "params": {"cargo_id": rec.cargo_id}, "model_usage": _zero_usage()},
            "token_usage": _zero_usage(),
            "result": {
                "accepted": True,
                "detail": "d009 daily-home oracle accepted cargo",
                "driver_id": "D009",
                "cargo_id": rec.cargo_id,
                "simulation_progress_minutes": end_progress,
                "simulation_wall_time": _clock(end_progress) + ":00",
                "pickup_deadhead_km": round(cand.pickup_km, 2),
                "haul_distance_km": round(rec.haul_km, 2),
                "income_eligible": end_progress <= HORIZON_MINUTES,
            },
        }
    )
    return Node(
        progress=end_progress,
        lat=rec.end_lat,
        lng=rec.end_lng,
        history=history,
        used_ids=node.used_ids | {rec.cargo_id},
        proxy_score=node.proxy_score + cand.score,
        orders=node.orders + 1,
        label=f"{node.label}>take:{rec.cargo_id}",
    )


def _wait_node(node: Node, minutes: int, *, label: str) -> Node:
    minutes = max(1, min(int(minutes), HORIZON_MINUTES - node.progress))
    end_progress = node.progress + minutes
    history = list(node.history)
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": "D009",
            "step_elapsed_minutes": minutes,
            "query_scan_cost_minutes": 0,
            "action_exec_cost_minutes": minutes,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "simulation_end_time": _clock(end_progress),
            "action": {"action": "wait", "params": {"duration_minutes": minutes}, "model_usage": _zero_usage()},
            "token_usage": _zero_usage(),
            "result": {"simulation_progress_minutes": end_progress, "simulation_wall_time": _clock(end_progress) + ":00"},
        }
    )
    return Node(
        progress=end_progress,
        lat=node.lat,
        lng=node.lng,
        history=history,
        used_ids=node.used_ids,
        proxy_score=node.proxy_score - 0.01 * minutes,
        orders=node.orders,
        label=f"{node.label}>{label}",
    )


def _home_node(node: Node, *, speed_km_per_hour: float, cost_per_km: float, label: str) -> Node | None:
    distance_km = haversine_km(node.lat, node.lng, HOME_LAT, HOME_LNG)
    move_minutes = _distance_to_minutes(distance_km, speed_km_per_hour) if distance_km > 1e-6 else 1
    if node.progress + move_minutes > HORIZON_MINUTES:
        return None
    history = list(node.history)
    end_progress = node.progress + move_minutes
    history.append(
        {
            "step": len(history) + 1,
            "driver_id": "D009",
            "step_elapsed_minutes": move_minutes,
            "query_scan_cost_minutes": 0,
            "action_exec_cost_minutes": move_minutes,
            "position_before": {"lat": round(node.lat, 6), "lng": round(node.lng, 6)},
            "position_after": {"lat": HOME_LAT, "lng": HOME_LNG},
            "simulation_end_time": _clock(end_progress),
            "action": {"action": "reposition", "params": {"latitude": HOME_LAT, "longitude": HOME_LNG}, "model_usage": _zero_usage()},
            "token_usage": _zero_usage(),
            "result": {
                "current_lat": HOME_LAT,
                "current_lng": HOME_LNG,
                "simulation_progress_minutes": end_progress,
                "simulation_wall_time": _clock(end_progress) + ":00",
                "distance_km": round(distance_km, 2),
            },
        }
    )
    return Node(
        progress=end_progress,
        lat=HOME_LAT,
        lng=HOME_LNG,
        history=history,
        used_ids=node.used_ids,
        proxy_score=node.proxy_score - cost_per_km * distance_km,
        orders=node.orders,
        label=f"{node.label}>{label}",
    )


def _wait_options(node: Node, cargo: CargoTable, *, future_window: int) -> list[int]:
    minute = node.progress % 1440
    out = []
    if DAY_START <= minute < DAY_END:
        for minutes in (30, 60, 120):
            if node.progress + minutes < (node.progress // 1440) * 1440 + DAY_END:
                out.append(minutes)
        future = cargo.create[cargo.create > node.progress]
        if future.size:
            wait = int(np.min(future)) - node.progress
            if 5 <= wait <= min(future_window, 240):
                out.append(wait)
    return sorted(set(out))


def _complete_to_horizon(node: Node, *, speed_km_per_hour: float, cost_per_km: float) -> Node:
    cur = node
    if not _near_home(cur):
        home = _home_node(cur, speed_km_per_hour=speed_km_per_hour, cost_per_km=cost_per_km, label="finalhome")
        if home is not None:
            cur = home
    if cur.progress < HORIZON_MINUTES:
        cur = _wait_node(cur, HORIZON_MINUTES - cur.progress, label="finalwait")
    return cur


def _near_home(node: Node) -> bool:
    return haversine_km(node.lat, node.lng, HOME_LAT, HOME_LNG) <= 1.0


def _rank_node(node: Node) -> float:
    progress_credit = 0.002 * node.progress
    home_credit = 250.0 if _near_home(node) else 0.0
    special_credit = 8000.0 if SPECIAL_CARGO_ID in node.used_ids else -8000.0
    return node.proxy_score + progress_credit + home_credit + special_credit + 0.05 * node.orders


def _write_run(out_dir: Path, node: Node, *, elapsed: float) -> None:
    action_path = out_dir / "actions_202603_D009_daily_home_oracle.jsonl"
    with action_path.open("w", encoding="utf-8") as f:
        for rec in node.history:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "simulate_time_seconds": elapsed,
        "completed_steps": len(node.history),
        "remaining_cargo_count": 0,
        "simulation_progress_minutes": node.progress,
        "simulation_wall_time": _clock(node.progress) + ":00",
        "driver_completed_steps": {"D009": len(node.history)},
        "driver_result_files": {"D009": str(action_path.resolve())},
        "simulation_duration_days": 30,
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# D009 Daily Home Oracle",
        "",
        "| rank | exact_net | gross | distance | penalty | proxy | orders | steps | wall_time | run_dir |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for i, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {net} | {gross} | {dist} | {pen} | {proxy:.2f} | {orders} | {steps} | {wall} | `{run}` |".format(
                rank=i,
                net=_fmt(row.get("exact_net_income")),
                gross=_fmt(row.get("exact_gross_income")),
                dist=_fmt(row.get("exact_distance_km")),
                pen=_fmt(row.get("exact_preference_penalty")),
                proxy=float(row.get("proxy_score", 0.0) or 0.0),
                orders=row.get("orders"),
                steps=row.get("steps"),
                wall=row.get("wall_time"),
                run=row.get("run_dir"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
