"""Deterministic calculator skill for LLM-assisted reranking.

The LLM is only allowed to interpret these precomputed numbers.  All arithmetic
that affects candidate comparison should live here instead of in prompts.
"""

from __future__ import annotations

from typing import Any


def build_rerank_calculation(
    *,
    candidates: list[dict[str, Any]],
    rule_feature: dict[str, Any],
    max_score_drop: float,
    max_net_drop: float,
    min_score_improvement: float,
    min_net_improvement: float,
) -> dict[str, Any]:
    """Return precomputed deltas, guard decisions, and deterministic rankings."""

    rule_id = _cargo_id(rule_feature)
    rule_score = _num(rule_feature.get("score"))
    rule_net = _num(rule_feature.get("estimated_net"))
    rule_nph = _num(rule_feature.get("net_per_hour"))
    rows = [
        _candidate_row(
            item,
            rule_id=rule_id,
            rule_score=rule_score,
            rule_net=rule_net,
            rule_nph=rule_nph,
            max_score_drop=max_score_drop,
            max_net_drop=max_net_drop,
            min_score_improvement=min_score_improvement,
            min_net_improvement=min_net_improvement,
        )
        for item in candidates
        if _cargo_id(item)
    ]
    rows.sort(
        key=lambda row: (
            row["guard_pass"],
            row["score"],
            row["estimated_net"],
            row["net_per_hour"],
        ),
        reverse=True,
    )
    allowed = [row["cargo_id"] for row in rows if row["guard_pass"]]
    best_guarded = rows[0]["cargo_id"] if rows and rows[0]["guard_pass"] else rule_id
    best_score = max(rows, key=lambda row: row["score"], default=None)
    best_net = max(rows, key=lambda row: row["estimated_net"], default=None)
    return {
        "skill": "calculator",
        "instruction": "All numeric comparisons in this object were computed by Python. Do not recompute them.",
        "rule_cargo_id": rule_id,
        "rule_score": _round(rule_score),
        "rule_estimated_net": _round(rule_net),
        "rule_net_per_hour": _round(rule_nph),
        "guard": {
            "max_score_drop": _round(max_score_drop),
            "max_net_drop": _round(max_net_drop),
            "min_score_improvement": _round(min_score_improvement),
            "min_net_improvement": _round(min_net_improvement),
            "allowed_cargo_ids": allowed,
        },
        "recommendation": {
            "cargo_id": best_guarded,
            "reason": "highest guarded Python score; keep rule choice if no guarded alternative is better",
        },
        "best_by_score": None if best_score is None else best_score["cargo_id"],
        "best_by_estimated_net": None if best_net is None else best_net["cargo_id"],
        "candidate_rows": rows,
    }


def _candidate_row(
    feature: dict[str, Any],
    *,
    rule_id: str,
    rule_score: float,
    rule_net: float,
    rule_nph: float,
    max_score_drop: float,
    max_net_drop: float,
    min_score_improvement: float,
    min_net_improvement: float,
) -> dict[str, Any]:
    cargo_id = _cargo_id(feature)
    score = _num(feature.get("score"))
    net = _num(feature.get("estimated_net"))
    nph = _num(feature.get("net_per_hour"))
    pickup_km = _num(feature.get("pickup_km"))
    haul_km = _num(feature.get("haul_km"))
    score_delta = score - rule_score
    net_delta = net - rule_net
    nph_delta = nph - rule_nph
    guard_reasons: list[str] = []
    if score < rule_score - max_score_drop:
        guard_reasons.append("score_drop")
    if net < rule_net - max_net_drop:
        guard_reasons.append("net_drop")
    if cargo_id != rule_id and score < rule_score + min_score_improvement:
        guard_reasons.append("insufficient_score_improvement")
    if cargo_id != rule_id and net < rule_net + min_net_improvement:
        guard_reasons.append("insufficient_net_improvement")

    return {
        "cargo_id": cargo_id,
        "score": _round(score),
        "estimated_net": _round(net),
        "net_per_hour": _round(nph),
        "pickup_km": _round(pickup_km),
        "haul_km": _round(haul_km),
        "total_distance_km": _round(pickup_km + haul_km),
        "wait_minutes": _int(feature.get("wait_minutes")),
        "total_exec_minutes": _int(feature.get("total_exec_minutes")),
        "finish_minutes": _int(feature.get("finish_minutes")),
        "score_delta_vs_rule": _round(score_delta),
        "net_delta_vs_rule": _round(net_delta),
        "nph_delta_vs_rule": _round(nph_delta),
        "guard_pass": not guard_reasons,
        "guard_reasons": guard_reasons,
    }


def _cargo_id(feature: dict[str, Any]) -> str:
    return str(feature.get("cargo_id", "")).strip()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _round(value: float) -> float:
    return round(float(value), 4)
