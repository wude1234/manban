"""Exact-net short-tail enumerator for high-score trajectory search.

This is an offline exploration harness, not an online submission agent.  It
keeps a proven trajectory prefix, then searches the remaining short tail using
actual incremental order net as the beam objective.  The purpose is to avoid
proxy-score pruning errors in `oracle_route_miner.py` when the remaining month
is short enough that exact tail net is the right objective.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

DEMO_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = DEMO_ROOT / "server"
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from calc_monthly_income import load_driver_cost_map
from oracle_route_miner import (
    HORIZON_MINUTES,
    Candidate,
    CargoTable,
    RouteNode,
    _clock,
    _find_driver_income,
    _generate_candidates,
    _load_cargo_table,
    _load_drivers,
    _load_seed_prefix,
    _score_candidate,
    _take_candidate,
    _write_run,
)
from server.bench.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Search a short route tail with exact incremental net ranking.")
    parser.add_argument("--driver", required=True)
    parser.add_argument("--seed-actions", required=True)
    parser.add_argument("--seed-prefix-orders", type=int, required=True)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--beam-width", type=int, default=500)
    parser.add_argument("--branch-top-n", type=int, default=160)
    parser.add_argument("--candidate-pool", type=int, default=2600)
    parser.add_argument("--max-tail-orders", type=int, default=6)
    parser.add_argument("--future-window", type=int, default=1320)
    parser.add_argument("--max-pickup-km", type=float, default=260.0)
    parser.add_argument("--min-net", type=float, default=-800.0)
    parser.add_argument("--preference-mode", default="d007_hard")
    parser.add_argument(
        "--rank-objective",
        choices=["net", "score", "nph"],
        default="net",
        help="Tail branch ranking. score uses oracle candidate score, which includes preference proxy.",
    )
    parser.add_argument("--diverse-per-bucket", type=int, default=3)
    parser.add_argument("--time-bucket-minutes", type=int, default=60)
    parser.add_argument("--region-cell-deg", type=float, default=0.08)
    parser.add_argument("--score-final-top", type=int, default=40)
    args = parser.parse_args()

    settings = load_settings()
    driver_id = args.driver.strip().upper()
    drivers = _load_drivers(settings.drivers_path)
    if driver_id not in drivers:
        raise KeyError(f"unknown driver: {driver_id}")
    cost_map = load_driver_cost_map(settings.drivers_path)
    cost_per_km = float(cost_map.get(driver_id, 1.5))
    speed = float(settings.reposition_speed_km_per_hour)
    cargo = _load_cargo_table(settings.cargo_dataset_path, cost_per_km=cost_per_km)
    fallback = RouteNode(
        progress=0,
        lat=float(drivers[driver_id].get("current_lat", 0.0)),
        lng=float(drivers[driver_id].get("current_lng", 0.0)),
    )
    root = _load_seed_prefix(
        Path(args.seed_actions),
        driver_id=driver_id,
        prefix_orders=max(0, int(args.seed_prefix_orders)),
        fallback=fallback,
    )
    tag = args.tag.strip() or f"{driver_id.lower()}_p{args.seed_prefix_orders}_exact_tail"
    out_dir = Path(args.out_dir) if args.out_dir else DEMO_ROOT / "results" / "exact_tail_enumerator" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")

    started = time.perf_counter()
    frontier = [root]
    finals: list[RouteNode] = []
    print(
        f"seed: driver={driver_id} prefix_orders={root.accepted_orders} "
        f"steps={len(root.history)} t={_clock(root.progress)}",
        flush=True,
    )
    for depth in range(max(1, int(args.max_tail_orders))):
        expanded: list[RouteNode] = []
        for node in frontier:
            finals.append(node)
            branches = _expand_exact_tail(
                node,
                cargo,
                driver_id=driver_id,
                speed_km_per_hour=speed,
                cost_per_km=cost_per_km,
                future_window=max(0, int(args.future_window)),
                max_pickup_km=max(1.0, float(args.max_pickup_km)),
                min_net=float(args.min_net),
                candidate_pool=max(1, int(args.candidate_pool)),
                branch_top_n=max(1, int(args.branch_top_n)),
                preference_mode=str(args.preference_mode),
                rank_objective=str(args.rank_objective),
            )
            if branches:
                expanded.extend(branches)
            else:
                finals.append(node)
        if not expanded:
            break
        expanded.sort(key=_tail_rank, reverse=True)
        frontier = _select_diverse_exact(
            expanded,
            beam_width=max(1, int(args.beam_width)),
            per_bucket=max(1, int(args.diverse_per_bucket)),
            time_bucket=max(1, int(args.time_bucket_minutes)),
            region_cell=max(0.01, float(args.region_cell_deg)),
        )
        best = frontier[0]
        print(
            f"depth={depth + 1} frontier={len(frontier)} "
            f"best_tail_net={best.proxy_score:.2f} orders={best.accepted_orders} "
            f"t={_clock(best.progress)} label={best.label.rsplit('>', 3)[-1]}",
            flush=True,
        )
    finals.extend(frontier)
    finals.sort(key=_tail_rank, reverse=True)

    rows: list[dict[str, Any]] = []
    top_n = max(1, int(args.score_final_top))
    for rank, node in enumerate(finals[:top_n], start=1):
        cand_dir = out_dir / f"candidate_{rank:03d}"
        cand_dir.mkdir(parents=True, exist_ok=True)
        _write_run(cand_dir, node, driver_id=driver_id, settings=settings, elapsed=round(time.perf_counter() - started, 2))
        score_payload = _score_candidate(cand_dir)
        income = _find_driver_income(score_payload or {}, driver_id) if score_payload else {}
        row = {
            "candidate": rank,
            "tail_net": round(node.proxy_score, 2),
            "orders": node.accepted_orders,
            "steps": len(node.history),
            "progress_minutes": node.progress,
            "wall_time": _clock(node.progress),
            "label": node.label,
            "run_dir": str(cand_dir),
            "exact_net_income": income.get("net_income"),
            "exact_gross_income": income.get("gross_income"),
            "exact_distance_km": income.get("distance_km"),
            "exact_preference_penalty": income.get("preference_penalty"),
        }
        rows.append(row)
    rows.sort(key=lambda item: float(item.get("exact_net_income") or -1e18), reverse=True)
    (out_dir / "exact_tail_summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "exact_tail_summary.md", driver_id, rows)
    print(f"written: {out_dir / 'exact_tail_summary.md'}")
    print(json.dumps(rows[: min(5, len(rows))], ensure_ascii=False, indent=2))
    return 0


def _expand_exact_tail(
    node: RouteNode,
    cargo: CargoTable,
    *,
    driver_id: str,
    speed_km_per_hour: float,
    cost_per_km: float,
    future_window: int,
    max_pickup_km: float,
    min_net: float,
    candidate_pool: int,
    branch_top_n: int,
    preference_mode: str,
    rank_objective: str,
) -> list[RouteNode]:
    candidates = _generate_candidates(
        node,
        cargo,
        value_index={},
        speed_km_per_hour=speed_km_per_hour,
        cost_per_km=cost_per_km,
        action_start_floor=node.progress,
        future_window=future_window,
        max_pickup_km=max_pickup_km,
        min_net=min_net,
        candidate_pool=max(candidate_pool, branch_top_n),
        nph_weight=0.0,
        future_weight=0.0,
        wait_penalty=0.0,
        pickup_penalty=0.0,
        preference_mode=preference_mode,
        driver_id=driver_id,
    )
    # `_generate_candidates` may still have used an internal rough top slice.
    # Re-rank the returned pool by actual accepted-order net, then expand.
    candidates.sort(key=lambda cand: _candidate_rank(cand, rank_objective), reverse=True)
    out: list[RouteNode] = []
    for cand in candidates[:branch_top_n]:
        rec = cargo.records[cand.cargo_index]
        child = _take_candidate(node, rec, cand, driver_id=driver_id, query_cost=0)
        child.proxy_score = node.proxy_score + float(cand.net)
        out.append(child)
    return out


def _candidate_exact_rank(cand: Candidate) -> tuple[float, float, float]:
    nph = float(cand.net) / max(1.0, float(cand.elapsed_minutes) / 60.0)
    return (float(cand.net), nph, -float(cand.pickup_km))


def _candidate_rank(cand: Candidate, objective: str) -> tuple[float, float, float]:
    nph = float(cand.net) / max(1.0, float(cand.elapsed_minutes) / 60.0)
    if objective == "score":
        return (float(cand.score), float(cand.net), -float(cand.pickup_km))
    if objective == "nph":
        return (nph, float(cand.net), -float(cand.pickup_km))
    return (float(cand.net), nph, -float(cand.pickup_km))


def _tail_rank(node: RouteNode) -> tuple[float, int, int]:
    return (float(node.proxy_score), int(node.accepted_orders), -int(node.progress))


def _select_diverse_exact(
    nodes: list[RouteNode],
    *,
    beam_width: int,
    per_bucket: int,
    time_bucket: int,
    region_cell: float,
) -> list[RouteNode]:
    selected: list[RouteNode] = []
    seen_labels: set[str] = set()
    bucket_count: dict[tuple[Any, ...], int] = {}
    for node in nodes:
        if node.label in seen_labels:
            continue
        bucket = (
            int(node.accepted_orders),
            int(node.progress // time_bucket),
            math.floor(float(node.lat) / region_cell),
            math.floor(float(node.lng) / region_cell),
        )
        if bucket_count.get(bucket, 0) >= per_bucket and len(selected) >= max(1, beam_width // 4):
            continue
        selected.append(node)
        seen_labels.add(node.label)
        bucket_count[bucket] = bucket_count.get(bucket, 0) + 1
        if len(selected) >= beam_width:
            break
    if len(selected) < beam_width:
        for node in nodes:
            if node.label in seen_labels:
                continue
            selected.append(node)
            seen_labels.add(node.label)
            if len(selected) >= beam_width:
                break
    return selected


def _write_markdown(path: Path, driver_id: str, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Exact Tail Enumerator",
        "",
        f"- driver: `{driver_id}`",
        "",
        "| rank | exact_net | gross | distance | penalty | tail_net | orders | steps | wall_time | run_dir |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for rank, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {net} | {gross} | {dist} | {pen} | {tail} | {orders} | {steps} | {time} | `{run}` |".format(
                rank=rank,
                net=row.get("exact_net_income"),
                gross=row.get("exact_gross_income"),
                dist=row.get("exact_distance_km"),
                pen=row.get("exact_preference_penalty"),
                tail=row.get("tail_net"),
                orders=row.get("orders"),
                steps=row.get("steps"),
                time=row.get("wall_time"),
                run=row.get("run_dir"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
