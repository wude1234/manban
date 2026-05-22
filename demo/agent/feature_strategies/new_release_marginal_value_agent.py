"""Marginal-value strategy for the 2026-05-08 release.

This strategy keeps the proven cross-day guards from the profit strategy, but
scores orders with an explicit marginal objective:

    immediate net + future location value - time opportunity cost - marginal penalties

The goal is to compare money earned against the incremental preference cost,
instead of tuning isolated weights by hand.
"""

from __future__ import annotations

import os
from typing import Any

from .common import BaseFeatureStrategy, FeatureSettings, haversine_km
from .new_release_preference_agent import (
    D009_HOME,
    D010_TARGET,
    _accepted_orders_today,
    _deadhead_km,
    _driver_id,
    _interval_overlaps_daily_window,
    _longest_wait_today,
)
from .new_release_profit_guarded_agent import NewReleaseProfitGuardedAgent


class NewReleaseMarginalValueAgent(NewReleaseProfitGuardedAgent):
    name = "new_release_marginal_value_agent"

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        current = int(status.get("simulation_progress_minutes", 0))
        total_minutes = max(1.0, float(feature.get("total_exec_minutes", 1.0)))
        estimated_net = float(feature.get("estimated_net", 0.0))

        value = estimated_net
        value += _future_location_value(feature, status)
        value -= _time_opportunity_cost(feature, status)
        value -= _marginal_penalty_cost(feature, status)

        # Keep the proven D003/D004/D005 profit tie-breaker as a small residual.
        if driver_id == "D003":
            value += 0.02 * estimated_net
        elif driver_id == "D004":
            value += 0.02 * estimated_net
        elif driver_id == "D005":
            value += 0.03 * estimated_net

        # Prefer orders that finish cleanly before known low-activity windows.
        if current % 1440 < 6 * 60 and total_minutes > 10 * 60:
            value -= 80.0

        return value / (total_minutes / 60.0)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseMarginalValueAgent()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _future_location_value(feature: dict[str, Any], status: dict[str, Any]) -> float:
    driver_id = _driver_id(status)
    value = _env_float("AGENT_MV_HOTSPOT_VALUE", 70.0) * float(feature.get("destination_hotspot_score", 0.0))

    if driver_id == "D009":
        finish = int(feature.get("finish_minutes", status.get("simulation_progress_minutes", 0)))
        minute = finish % 1440
        if 16 * 60 <= minute <= 22 * 60:
            dist_home = haversine_km(
                float(feature.get("end_lat", 0.0)),
                float(feature.get("end_lng", 0.0)),
                D009_HOME[0],
                D009_HOME[1],
            )
            value += max(0.0, 120.0 - dist_home * 3.0)

    if driver_id == "D010" and int(status.get("simulation_progress_minutes", 0)) < 9 * 1440:
        dist_target = haversine_km(
            float(feature.get("end_lat", 0.0)),
            float(feature.get("end_lng", 0.0)),
            D010_TARGET[0],
            D010_TARGET[1],
        )
        value += max(0.0, 90.0 - dist_target * 4.0)

    return value


def _time_opportunity_cost(feature: dict[str, Any], status: dict[str, Any]) -> float:
    driver_id = _driver_id(status)
    total_hours = max(1.0 / 60.0, float(feature.get("total_exec_minutes", 1.0)) / 60.0)
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    base = _driver_hour_shadow_price(driver_id, minute)

    # Waiting for far-future load windows consumes scarce daytime search time.
    wait_minutes = float(feature.get("wait_minutes", 0.0))
    wait_cost = _env_float("AGENT_MV_WAIT_COST_PER_HOUR", 8.0) * (wait_minutes / 60.0)
    return base * total_hours + wait_cost


def _driver_hour_shadow_price(driver_id: str, minute: int) -> float:
    if 8 * 60 <= minute <= 18 * 60:
        default = {
            "D003": 18.0,
            "D004": 20.0,
            "D005": 16.0,
            "D006": 24.0,
            "D008": 20.0,
            "D010": 18.0,
        }.get(driver_id, 14.0)
    elif 18 * 60 < minute <= 23 * 60:
        default = {
            "D004": 10.0,
            "D006": 18.0,
            "D009": 28.0,
            "D010": 16.0,
        }.get(driver_id, 8.0)
    else:
        default = {
            "D001": 6.0,
            "D006": 14.0,
            "D009": 45.0,
            "D010": 12.0,
        }.get(driver_id, 5.0)
    return _env_float(f"AGENT_MV_{driver_id}_HOUR_COST", default)


def _marginal_penalty_cost(feature: dict[str, Any], status: dict[str, Any]) -> float:
    driver_id = _driver_id(status)
    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    cost = 0.0

    if driver_id == "D003":
        pickup_km = float(feature.get("pickup_km", 0.0))
        current_deadhead = _deadhead_km(status)
        before = min(2000.0, max(0.0, current_deadhead - 100.0) * 10.0)
        after = min(2000.0, max(0.0, current_deadhead + pickup_km - 100.0) * 10.0)
        cost += max(0.0, after - before)
        if _interval_overlaps_daily_window(current, finish, 2, 5):
            cost += 200.0

    elif driver_id == "D004":
        minute = current % 1440
        orders_today = _accepted_orders_today(status)
        if orders_today == 0 and minute >= 12 * 60:
            cost += 200.0
        if orders_today >= 3:
            cost += 200.0
        if _interval_overlaps_daily_window(current, finish, 12, 13):
            cost += 100.0

    elif driver_id == "D005":
        if float(feature.get("haul_km", 0.0)) > 100.0:
            cost += 100.0
        if float(feature.get("pickup_km", 0.0)) > 90.0:
            cost += 100.0
        if _interval_overlaps_daily_window(current, finish, 23, 6):
            cost += 200.0

    elif driver_id == "D006":
        if float(feature.get("haul_km", 0.0)) > 150.0:
            cost += 250.0

    elif driver_id == "D008":
        cargo_name = str(feature.get("cargo_name", "") or "")
        if cargo_name == "食品饮料":
            cost += 200.0
        if float(feature.get("pickup_km", 0.0)) > 50.0:
            cost += 100.0

    elif driver_id == "D009":
        if _interval_overlaps_daily_window(current, finish, 23, 8):
            cost += 900.0
        end_home_km = haversine_km(
            float(feature.get("end_lat", 0.0)),
            float(feature.get("end_lng", 0.0)),
            D009_HOME[0],
            D009_HOME[1],
        )
        if finish % 1440 >= 18 * 60 and end_home_km > 80.0:
            cost += 450.0

    elif driver_id == "D010":
        if str(feature.get("cargo_name", "") or "") == "服饰纺织皮革":
            cost += 240.0
        if _longest_wait_today(status) < 3 * 60 and finish % 1440 > 21 * 60:
            cost += 150.0

    return cost
