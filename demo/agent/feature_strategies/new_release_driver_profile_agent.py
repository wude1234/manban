"""Per-driver profile strategy for the 2026-05-08 release.

This is an experimental layer on top of the current hybrid-value strategy.  It
keeps the proven guards, but changes the objective by driver:

* high-query-value drivers can opt into visible-candidate chaining;
* D004 is treated as a daily quota problem, not a pure per-order greedy task;
* D009 is scored by home-return safety rather than generic expansion.
"""

from __future__ import annotations

import os
from typing import Any

from .common import BaseFeatureStrategy, FeatureSettings, distance_to_minutes, haversine_km
from .new_release_hybrid_value_agent import NewReleaseHybridValueAgent
from .new_release_preference_agent import (
    D009_HOME,
    _accepted_orders_today,
    _driver_id,
    _interval_overlaps_daily_window,
)


class NewReleaseDriverProfileAgent(NewReleaseHybridValueAgent):
    name = "new_release_driver_profile_agent"

    def __init__(self) -> None:
        super().__init__()
        self._visible_chain_value_by_driver: dict[str, dict[str, float]] = {}

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        self._visible_chain_value_by_driver[_driver_id(status)] = _build_visible_chain_value(viable)
        return super().pre_action(status, candidates, viable, settings)

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        base = super().score(feature, status)
        chain_value = self._chain_value(feature, driver_id)
        estimated_net = float(feature.get("estimated_net", 0.0))
        total_hours = max(1.0 / 60.0, float(feature.get("total_exec_minutes", 1.0)) / 60.0)
        minute = int(status.get("simulation_progress_minutes", 0)) % 1440

        if driver_id == "D001":
            return base + _env_float("AGENT_PROFILE_D001_CHAIN_WEIGHT", 0.0) * chain_value

        if driver_id == "D003":
            # Deadhead is already capped in good runs; after that, prioritize bigger net chains.
            return base + _env_float("AGENT_PROFILE_D003_CHAIN_WEIGHT", 0.0) * chain_value

        if driver_id == "D004":
            orders_today = _accepted_orders_today(status)
            score = base + _env_float("AGENT_PROFILE_D004_CHAIN_WEIGHT", 0.0) * chain_value
            score += _env_float("AGENT_PROFILE_D004_NET_WEIGHT", 0.0) * estimated_net
            if orders_today >= 2:
                score += _env_float("AGENT_PROFILE_D004_LATE_QUOTA_NET_WEIGHT", 0.0) * estimated_net
                score -= _env_float("AGENT_PROFILE_D004_SHORT_JOB_PENALTY", 0.0) / max(total_hours, 0.25)
            if orders_today >= 3:
                # The fourth daily order has an uncapped 200 yuan penalty. Only
                # exceptional net/hour jobs should survive this drag.
                score -= _env_float("AGENT_PROFILE_D004_OVER_QUOTA_SCORE_COST", 0.0)
            if 11 * 60 <= minute < 13 * 60:
                score -= _env_float("AGENT_PROFILE_D004_LUNCH_EDGE_COST", 0.0)
            return score

        if driver_id == "D005":
            score = base + _env_float("AGENT_PROFILE_D005_CHAIN_WEIGHT", 0.0) * chain_value
            score += _env_float("AGENT_PROFILE_D005_NET_WEIGHT", 0.0) * estimated_net
            score -= _env_float("AGENT_PROFILE_D005_WAIT_COST_PER_HOUR", 3.0) * (
                float(feature.get("wait_minutes", 0.0)) / 60.0
            )
            # Short-haul hard filters already apply; within them, slightly
            # prefer using the available distance budget instead of tiny jobs.
            score += min(float(feature.get("haul_km", 0.0)), 100.0) * _env_float("AGENT_PROFILE_D005_HAUL_WEIGHT", 0.0)
            return score

        if driver_id == "D006":
            return base + _env_float("AGENT_PROFILE_D006_CHAIN_WEIGHT", 0.0) * chain_value

        if driver_id == "D007":
            score = base + _env_float("AGENT_PROFILE_D007_CHAIN_WEIGHT", 0.0) * chain_value
            score += _env_float("AGENT_PROFILE_D007_NET_WEIGHT", 0.0) * estimated_net
            score -= _env_float("AGENT_PROFILE_D007_WAIT_COST_PER_HOUR", 2.5) * (
                float(feature.get("wait_minutes", 0.0)) / 60.0
            )
            return score

        if driver_id == "D008":
            return base + _env_float("AGENT_PROFILE_D008_CHAIN_WEIGHT", 0.0) * chain_value

        if driver_id == "D009":
            return base + _env_float("AGENT_PROFILE_D009_HOME_WEIGHT", 0.0) * _d009_home_safety_bonus(feature, status)

        if driver_id == "D010":
            return base + _env_float("AGENT_PROFILE_D010_CHAIN_WEIGHT", 0.0) * chain_value

        return base

    def _chain_value(self, feature: dict[str, Any], driver_id: str) -> float:
        key = _coord_bucket(float(feature.get("end_lat", 0.0)), float(feature.get("end_lng", 0.0)))
        return self._visible_chain_value_by_driver.get(driver_id, {}).get(key, 0.0)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseDriverProfileAgent()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _coord_bucket(lat: float, lng: float) -> str:
    # About 10-12 km buckets in Guangdong; coarse enough to avoid overfitting.
    return f"{round(lat, 1):.1f},{round(lng, 1):.1f}"


def _build_visible_chain_value(viable: list[dict[str, Any]]) -> dict[str, float]:
    by_bucket: dict[str, float] = {}
    for item in viable:
        start_key = _coord_bucket(float(item.get("start_lat", 0.0)), float(item.get("start_lng", 0.0)))
        net = max(0.0, float(item.get("estimated_net", 0.0)))
        nph = max(0.0, float(item.get("net_per_hour", 0.0)))
        # Saturated value: reward both density and quality, but avoid one
        # extreme visible order dominating all decisions.
        value = min(140.0, 0.08 * net + 0.25 * nph)
        if value > by_bucket.get(start_key, 0.0):
            by_bucket[start_key] = value
    return by_bucket


def _d009_home_safety_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    if _interval_overlaps_daily_window(current, finish, 23, 8):
        return -1000.0

    dist_home = haversine_km(
        float(feature.get("end_lat", 0.0)),
        float(feature.get("end_lng", 0.0)),
        D009_HOME[0],
        D009_HOME[1],
    )
    minutes_home = distance_to_minutes(dist_home, float(feature.get("speed_km_per_hour", 60.0)))
    finish_minute = finish % 1440
    latest_return = finish_minute + minutes_home
    if latest_return > 23 * 60:
        return -900.0 - max(0, latest_return - 23 * 60) * 4.0
    if 16 * 60 <= finish_minute <= 22 * 60:
        return max(0.0, 180.0 - 2.5 * dist_home)
    return max(0.0, 60.0 - 0.8 * dist_home)
