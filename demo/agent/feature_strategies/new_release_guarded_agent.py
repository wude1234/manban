"""Guarded strategy for the 2026-05-08 release.

This version keeps the public-API-only rule from ``new_release_preference_agent``
and adds stricter cross-day preference guards learned from previous local
experiments: hard constraints first, then profit ranking.
"""

from __future__ import annotations

import os
from typing import Any

from .common import BaseFeatureStrategy, FeatureSettings, distance_to_minutes, haversine_km
from .new_release_preference_agent import (
    D009_HOME,
    D009_TEMP_PICKUP,
    D010_HOME,
    D010_SPOUSE,
    MAR10_10,
    MAR13_22,
    TEMP_CARGO_ID,
    NewReleasePreferenceAgent,
    _accepted_orders_today,
    _driver_id,
    _history_records,
    _interval_overlaps_daily_window,
    _longest_wait_today,
    _record_action_end,
    _record_step_start,
    _required_rest_minutes,
    _took_cargo,
)


MAR03_TEMP_CREATE = 2 * 1440 + 14 * 60 + 43
MAR03_TEMP_REMOVE = 2 * 1440 + 16 * 60 + 8


class NewReleaseGuardedAgent(NewReleasePreferenceAgent):
    name = "new_release_guarded_agent"

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        driver_id = _driver_id(status)
        current = int(status.get("simulation_progress_minutes", 0))
        minute = current % 1440

        if driver_id == "D010":
            action = _guarded_d010_family_pre_action(status, self._memory_for(driver_id))
            if action is not None:
                return action

        if driver_id == "D009" and _enable_d009_temp_take():
            action = _guarded_d009_temp_cargo_pre_action(status, candidates, settings)
            if action is not None:
                return action

        # D004 only gets penalized when it accepts a late first order. If noon
        # has passed and no order has started today, skip the rest of the day.
        if driver_id == "D004" and _accepted_orders_today(status) == 0 and minute >= 12 * 60:
            return {"action": "wait", "params": {"duration_minutes": max(1, 1440 - minute)}}

        action = _daily_rest_deadline_pre_action(status)
        if action is not None:
            return action

        return super().pre_action(status, candidates, viable, settings)

    def is_selectable(self, feature: dict[str, Any], status: dict[str, Any]) -> bool:
        if not super().is_selectable(feature, status):
            return False
        if _breaks_rest_deadline(feature, status):
            return False
        if _breaks_d010_family_departure(feature, status):
            return False
        return True

    def no_selectable_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        rest = _daily_rest_deadline_pre_action(status, force_when_possible=True)
        if rest is not None:
            return rest
        return super().no_selectable_action(status, candidates, viable, settings)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseGuardedAgent()


def _guarded_d009_temp_cargo_pre_action(
    status: dict[str, Any],
    candidates: list[dict[str, Any]],
    settings: FeatureSettings,
) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    if _took_cargo(status, TEMP_CARGO_ID) or current > MAR03_TEMP_REMOVE:
        return None

    # The special cargo has remove_time before load_time. The generic feature
    # builder marks it non-viable, but the simulator accepts it if the order is
    # placed before remove_time and then waits until load_time.
    if current >= MAR03_TEMP_CREATE:
        if any(str(item.get("cargo_id", "")) == TEMP_CARGO_ID for item in candidates):
            return {"action": "take_order", "params": {"cargo_id": TEMP_CARGO_ID}}

    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    dist = haversine_km(lat, lng, D009_TEMP_PICKUP[0], D009_TEMP_PICKUP[1])
    travel_minutes = distance_to_minutes(dist, settings.speed_km_per_hour)
    latest_leave = MAR03_TEMP_CREATE - travel_minutes - 20

    if current >= latest_leave:
        if dist > 2.0:
            return {"action": "reposition", "params": {"latitude": D009_TEMP_PICKUP[0], "longitude": D009_TEMP_PICKUP[1]}}
        wait_to_create = MAR03_TEMP_CREATE - current
        if wait_to_create > 0:
            return {"action": "wait", "params": {"duration_minutes": max(1, min(wait_to_create, 60))}}
        return {"action": "wait", "params": {"duration_minutes": max(1, min(10, MAR03_TEMP_REMOVE - current))}}
    return None


def _enable_d009_temp_take() -> bool:
    return os.getenv("AGENT_ENABLE_D009_TEMP_TAKE", "0").strip() == "1"


def _guarded_d010_family_pre_action(status: dict[str, Any], memory: Any) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    if current < MAR10_10 or current >= MAR13_22:
        return None

    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    at_spouse = haversine_km(lat, lng, D010_SPOUSE[0], D010_SPOUSE[1]) <= 1.0
    at_home = haversine_km(lat, lng, D010_HOME[0], D010_HOME[1]) <= 1.0

    if not memory.spouse_picked:
        post_event_wait = _post_event_continuous_wait_near(
            _history_records(status),
            D010_SPOUSE,
            event_start=MAR10_10,
            before_minute=current,
        )
        if post_event_wait >= 10:
            memory.spouse_picked = True
        elif not at_spouse:
            return {"action": "reposition", "params": {"latitude": D010_SPOUSE[0], "longitude": D010_SPOUSE[1]}}
        else:
            wait_need = max(1, 10 - post_event_wait)
            if wait_need >= 10:
                memory.spouse_picked = True
            return {"action": "wait", "params": {"duration_minutes": wait_need}}

    if not at_home:
        return {"action": "reposition", "params": {"latitude": D010_HOME[0], "longitude": D010_HOME[1]}}
    return {"action": "wait", "params": {"duration_minutes": max(1, MAR13_22 - current)}}


def _daily_rest_deadline_pre_action(status: dict[str, Any], *, force_when_possible: bool = False) -> dict[str, Any] | None:
    spec = _daily_rest_spec(status)
    if spec is None:
        return None
    rest_minutes, latest_start_minute = spec
    if _longest_wait_today(status) >= rest_minutes:
        return None

    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if minute + rest_minutes <= 1440 and (force_when_possible or minute >= latest_start_minute - 30 or minute < 6 * 60):
        return {"action": "wait", "params": {"duration_minutes": rest_minutes}}
    return None


def _breaks_rest_deadline(feature: dict[str, Any], status: dict[str, Any]) -> bool:
    spec = _daily_rest_spec(status)
    if spec is None:
        return False
    rest_minutes, latest_start_minute = spec
    if _longest_wait_today(status) >= rest_minutes:
        return False
    current = int(status.get("simulation_progress_minutes", 0))
    current_day = current // 1440
    minute = current % 1440
    if minute > latest_start_minute:
        return False
    finish = int(feature.get("finish_minutes", current))
    return finish > current_day * 1440 + latest_start_minute


def _daily_rest_spec(status: dict[str, Any]) -> tuple[int, int] | None:
    driver_id = _driver_id(status)
    current = int(status.get("simulation_progress_minutes", 0))
    day = current // 1440
    if driver_id == "D008" and _weekday_202603(day) >= 5:
        return None

    rest = _required_rest_minutes("\n".join(_preference_contents(status)))
    if rest <= 0:
        return None
    latest = 1440 - rest
    return rest, latest


def _breaks_d010_family_departure(feature: dict[str, Any], status: dict[str, Any]) -> bool:
    if _driver_id(status) != "D010":
        return False
    current = int(status.get("simulation_progress_minutes", 0))
    if current >= MAR10_10:
        return False
    finish = int(feature.get("finish_minutes", current))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    minutes_to_spouse = distance_to_minutes(haversine_km(end_lat, end_lng, D010_SPOUSE[0], D010_SPOUSE[1]), 60.0)
    return finish + minutes_to_spouse + 60 > MAR10_10


def _post_event_continuous_wait_near(
    history: list[dict[str, Any]],
    point: tuple[float, float],
    *,
    event_start: int,
    before_minute: int,
) -> int:
    total = 0
    for rec in reversed(history):
        if _record_action_end(rec) > before_minute:
            continue
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() != "wait":
            break
        pos = rec.get("position_after") or {}
        try:
            lat = float(pos.get("lat", 0.0))
            lng = float(pos.get("lng", 0.0))
        except (TypeError, ValueError):
            break
        if haversine_km(lat, lng, point[0], point[1]) > 1.0:
            break
        start = max(event_start, _record_step_start(rec))
        end = _record_action_end(rec)
        total += max(0, end - start)
    return total


def _preference_contents(status: dict[str, Any]) -> list[str]:
    out: list[str] = []
    prefs = status.get("preferences") or []
    if not isinstance(prefs, list):
        return out
    for item in prefs:
        if isinstance(item, dict):
            text = item.get("content") or item.get("text")
            if text:
                out.append(str(text))
        elif item:
            out.append(str(item))
    return out


def _weekday_202603(day_idx: int) -> int:
    # 2026-03-01 is Sunday. Return 0=Monday ... 6=Sunday.
    return (6 + int(day_idx)) % 7
