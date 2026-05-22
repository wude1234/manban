"""Rule-aware baseline for the 2026-05-08 release.

This strategy intentionally uses only runtime API observations:
driver status, visible cargo candidates, and in-session decision history.
It does not read the original cargo or driver data files.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .common import BaseFeatureStrategy, FeatureSettings, distance_to_minutes, haversine_km, hour_of_day, preferences_text


SHENZHEN_LAT_MIN = 22.42
SHENZHEN_LAT_MAX = 22.89
SHENZHEN_LNG_MIN = 113.74
SHENZHEN_LNG_MAX = 114.66
D003_FORBIDDEN = (23.30, 113.52, 20.0)
D009_HOME = (23.12, 113.28)
D009_TEMP_PICKUP = (24.81, 113.58)
D010_TARGET = (23.13, 113.26)
D010_SPOUSE = (23.21, 113.37)
D010_HOME = (23.19, 113.36)

MAR10_10 = 9 * 1440 + 10 * 60
MAR13_22 = 12 * 1440 + 22 * 60
MAR03_10 = 2 * 1440 + 10 * 60
MAR03_16 = 2 * 1440 + 16 * 60
TEMP_CARGO_ID = "240646"


@dataclass
class DriverMemory:
    target_days: set[int] = field(default_factory=set)
    spouse_wait_done: bool = False
    spouse_wait_minutes: int = 0
    spouse_picked: bool = False
    family_home_arrived: bool = False


class NewReleasePreferenceAgent(BaseFeatureStrategy):
    name = "new_release_preference_agent"

    def __init__(self) -> None:
        self._memory_by_driver: dict[str, DriverMemory] = {}

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        driver_id = _driver_id(status)
        memory = self._memory_for(driver_id)
        current_minutes = int(status.get("simulation_progress_minutes", 0))
        day = current_minutes // 1440
        minute = current_minutes % 1440
        lat = float(status.get("current_lat", 0.0))
        lng = float(status.get("current_lng", 0.0))
        prefs = preferences_text(status)
        history = _history_records(status)

        if haversine_km(lat, lng, D010_TARGET[0], D010_TARGET[1]) <= 1.0:
            memory.target_days.add(day)
        memory.target_days.update(_visited_target_days(history, D010_TARGET))
        if driver_id == "D010" and haversine_km(lat, lng, D010_HOME[0], D010_HOME[1]) <= 1.0:
            memory.family_home_arrived = True
        if driver_id == "D010":
            memory.spouse_wait_minutes = max(
                memory.spouse_wait_minutes,
                _continuous_wait_near_after(
                    history,
                    D010_SPOUSE,
                    start_minute=MAR10_10,
                    before_minute=current_minutes,
                ),
            )
            if current_minutes >= MAR10_10 and memory.spouse_wait_minutes >= 10:
                memory.spouse_picked = True

        # D010 family event is the largest hard constraint in the new release.
        if driver_id == "D010":
            action = _d010_family_pre_action(status, memory, settings)
            if action is not None:
                return action
            action = _d010_target_visit_pre_action(status, memory, settings)
            if action is not None:
                return action
            if _env_bool("AGENT_AP_D010_ENABLE_OPPORTUNITY_REST", False):
                action = _driver_opportunity_rest_action(status, viable, prefs, driver_id)
                if action is not None:
                    return action

        if driver_id != "D010" and _env_bool(f"AGENT_AP_{driver_id}_ENABLE_OPPORTUNITY_REST", False):
            action = _driver_opportunity_rest_action(status, viable, prefs, driver_id)
            if action is not None:
                return action

        # D009 temporary known cargo: if it is visible and feasible, take it.
        if driver_id == "D009":
            action = _d009_temp_cargo_pre_action(status, viable, settings)
            if action is not None:
                return action

        # Home-by-night. This is expensive in the new release, so treat it as hard.
        if driver_id == "D009":
            action = _home_by_night_pre_action(status, viable, settings, home=D009_HOME, quiet_end_hour=8)
            if action is not None:
                return action

        # Generic no-active windows from text preferences.
        quiet_action = _quiet_window_pre_action(status, settings, prefs)
        if quiet_action is not None:
            return quiet_action

        # D004 is evaluated by accepted orders whose action_start is in the
        # same natural day. After 3 orders, only take clearly exceptional jobs.
        if driver_id == "D004" and _accepted_orders_today(status) >= 3:
            best_nph = max((float(item.get("net_per_hour", 0.0)) for item in viable), default=0.0)
            if best_nph < 85.0:
                wait_to_next_day = 1440 - minute
                return {"action": "wait", "params": {"duration_minutes": max(1, wait_to_next_day)}}

        # Long daily rest: use low-opportunity windows first.
        rest_minutes = _required_rest_minutes(prefs)
        if rest_minutes > 0:
            longest_rest_today = _longest_wait_today(status)
            if longest_rest_today < rest_minutes and _should_take_rest_now(status, viable, rest_minutes):
                return {"action": "wait", "params": {"duration_minutes": rest_minutes}}

        # Month off-days: reserve early low-value full days for high fixed penalties.
        off_days_needed = _required_off_days(prefs)
        if off_days_needed > 0:
            off_days_done = _off_days_count(status, settings)
            days_remaining = max(0, settings.simulation_horizon_minutes // 1440 - day)
            must_reserve = off_days_done + days_remaining <= off_days_needed
            early_reserve = off_days_done < off_days_needed and day < off_days_needed and minute < 6 * 60
            if (must_reserve or early_reserve) and _active_minutes_today(status) == 0:
                return {"action": "wait", "params": {"duration_minutes": max(1, 1440 - minute)}}

        return None

    def pre_query_action(
        self,
        status: dict[str, Any],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        if not _env_bool("AGENT_AP_D010_FAMILY_PRE_QUERY", False):
            return None
        if _driver_id(status) != "D010":
            return None

        memory = self._memory_for("D010")
        current_minutes = int(status.get("simulation_progress_minutes", 0))
        lat = float(status.get("current_lat", 0.0))
        lng = float(status.get("current_lng", 0.0))
        history = _history_records(status)
        if haversine_km(lat, lng, D010_HOME[0], D010_HOME[1]) <= 1.0:
            memory.family_home_arrived = True
        memory.spouse_wait_minutes = max(
            memory.spouse_wait_minutes,
            _continuous_wait_near_after(
                history,
                D010_SPOUSE,
                start_minute=MAR10_10,
                before_minute=current_minutes,
            ),
        )
        if current_minutes >= MAR10_10 and memory.spouse_wait_minutes >= 10:
            memory.spouse_picked = True

        return _d010_family_pre_action(status, memory, settings)

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        score = float(feature["net_per_hour"])
        prefs = preferences_text(status)
        driver_id = _driver_id(status)
        score -= _quantified_preference_cost(feature, status, prefs)
        score -= _soft_preference_cost(feature, prefs)

        # New release net/hour distribution is lower than the old one, so keep
        # bonuses modest and mostly use them as tie breakers.
        score += 8.0 * float(feature.get("destination_hotspot_score", 0.0))

        if driver_id == "D010":
            score += _d010_target_bonus(feature, status)

        if driver_id == "D004":
            # D004 has a no-cap "more than 3 orders/day" penalty. Prefer fewer,
            # better orders after the third visible accepted order.
            orders_today = _accepted_orders_today(status)
            if orders_today >= 3:
                score -= 80.0

        return score

    def is_selectable(self, feature: dict[str, Any], status: dict[str, Any]) -> bool:
        return _hard_filter_penalty(feature, status, preferences_text(status)) <= 0

    def no_selectable_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        prefs = preferences_text(status)
        quiet = _quiet_window_pre_action(status, settings, prefs)
        if quiet is not None:
            return quiet
        near_quiet = _next_quiet_window_wait(status, prefs)
        if near_quiet is not None:
            return near_quiet
        rest_minutes = _required_rest_minutes(prefs)
        if rest_minutes > 0 and _longest_wait_today(status) < rest_minutes:
            return {"action": "wait", "params": {"duration_minutes": rest_minutes}}
        current = int(status.get("simulation_progress_minutes", 0))
        minute = current % 1440
        if minute >= 20 * 60 or minute < 6 * 60:
            wait_to_morning = (24 * 60 - minute) + 6 * 60 if minute >= 20 * 60 else 6 * 60 - minute
            return {"action": "wait", "params": {"duration_minutes": max(1, wait_to_morning)}}
        return {"action": "wait", "params": {"duration_minutes": 60}}

    def _memory_for(self, driver_id: str) -> DriverMemory:
        memory = self._memory_by_driver.get(driver_id)
        if memory is None:
            memory = DriverMemory()
            self._memory_by_driver[driver_id] = memory
        return memory


def build_strategy() -> BaseFeatureStrategy:
    return NewReleasePreferenceAgent()


def _hard_filter_penalty(feature: dict[str, Any], status: dict[str, Any], prefs: str) -> float:
    penalty = 0.0
    cargo_name = str(feature.get("cargo_name", "") or "")
    pickup_km = float(feature.get("pickup_km", 0.0))
    haul_km = float(feature.get("haul_km", 0.0))
    start_lat = float(feature.get("start_lat", 0.0))
    start_lng = float(feature.get("start_lng", 0.0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    start_minutes = int(status.get("simulation_progress_minutes", 0))
    finish_minutes = int(feature.get("finish_minutes", start_minutes))
    driver_id = _driver_id(status)

    hard_forbidden, _soft_forbidden = _cargo_name_rules(prefs)
    if cargo_name in hard_forbidden:
        penalty += 10000.0

    max_haul = _max_haul_km(prefs)
    if max_haul is not None and haul_km > max_haul:
        penalty += 10000.0 + haul_km - max_haul

    max_pickup = _max_pickup_km(prefs)
    if max_pickup is not None and pickup_km > max_pickup:
        penalty += 10000.0 + pickup_km - max_pickup

    if "深圳市范围内" in prefs:
        if not (_in_shenzhen(start_lat, start_lng) and _in_shenzhen(end_lat, end_lng)):
            penalty += 10000.0

    if driver_id == "D003":
        center_lat, center_lng, radius = D003_FORBIDDEN
        if (
            haversine_km(start_lat, start_lng, center_lat, center_lng) <= radius
            or haversine_km(end_lat, end_lng, center_lat, center_lng) <= radius
        ):
            penalty += 10000.0

    if _violates_quiet_windows(start_minutes, finish_minutes, prefs):
        penalty += 10000.0

    if driver_id == "D009" and _d009_cannot_get_home(feature, status):
        penalty += 10000.0

    return penalty


def _quantified_preference_cost(feature: dict[str, Any], status: dict[str, Any], prefs: str) -> float:
    driver_id = _driver_id(status)
    if driver_id == "D003":
        pickup_km = float(feature.get("pickup_km", 0.0))
        over = max(0.0, _deadhead_km(status) + pickup_km - 100.0)
        return min(2000.0, over * 10.0) / 20.0
    return 0.0


def _soft_preference_cost(feature: dict[str, Any], prefs: str) -> float:
    cargo_name = str(feature.get("cargo_name", "") or "")
    _hard, soft = _cargo_name_rules(prefs)
    if cargo_name in soft:
        return 14.0
    return 0.0


def _d010_family_pre_action(status: dict[str, Any], memory: DriverMemory, settings: FeatureSettings) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    if current < MAR10_10:
        # On Mar 10 morning, move close to spouse pickup point before the event.
        if current >= MAR10_10 - 15 * 60:
            if haversine_km(lat, lng, D010_SPOUSE[0], D010_SPOUSE[1]) > 1.0:
                return {"action": "reposition", "params": {"latitude": D010_SPOUSE[0], "longitude": D010_SPOUSE[1]}}
            return {"action": "wait", "params": {"duration_minutes": max(1, MAR10_10 - current)}}
        return None

    if MAR10_10 <= current < MAR13_22:
        at_spouse = haversine_km(lat, lng, D010_SPOUSE[0], D010_SPOUSE[1]) <= 1.0
        at_home = haversine_km(lat, lng, D010_HOME[0], D010_HOME[1]) <= 1.0
        if not memory.spouse_picked:
            if not at_spouse:
                return {"action": "reposition", "params": {"latitude": D010_SPOUSE[0], "longitude": D010_SPOUSE[1]}}
            wait_need = max(1, 10 - memory.spouse_wait_minutes)
            memory.spouse_wait_minutes += wait_need
            if memory.spouse_wait_minutes >= 10:
                memory.spouse_picked = True
            return {"action": "wait", "params": {"duration_minutes": wait_need}}
        if not at_home:
            return {"action": "reposition", "params": {"latitude": D010_HOME[0], "longitude": D010_HOME[1]}}
        return {"action": "wait", "params": {"duration_minutes": max(1, MAR13_22 - current)}}
    return None


def _d010_target_visit_pre_action(status: dict[str, Any], memory: DriverMemory, settings: FeatureSettings) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    if current >= MAR10_10:
        return None
    day = current // 1440
    minute = current % 1440
    if len(memory.target_days) >= 5 or day >= 9:
        return None
    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    if haversine_km(lat, lng, D010_TARGET[0], D010_TARGET[1]) <= 1.0:
        memory.target_days.add(day)
        if 6 * 60 <= minute < 22 * 60:
            return {"action": "wait", "params": {"duration_minutes": 60}}
        return None
    visits_needed = 5 - len(memory.target_days)
    days_left = max(1, 9 - day)
    if visits_needed >= days_left or (8 * 60 <= minute <= 10 * 60 and visits_needed > 0):
        return {"action": "reposition", "params": {"latitude": D010_TARGET[0], "longitude": D010_TARGET[1]}}
    return None


def _driver_opportunity_rest_action(
    status: dict[str, Any],
    viable: list[dict[str, Any]],
    prefs: str,
    driver_id: str,
) -> dict[str, Any] | None:
    rest_minutes = _required_rest_minutes(prefs)
    if rest_minutes <= 0 or _longest_wait_today(status) >= rest_minutes:
        return None

    current = int(status.get("simulation_progress_minutes", 0))
    day_one_based = current // 1440 + 1
    minute = current % 1440
    prefix = f"AGENT_AP_{driver_id}_OPPORTUNITY_REST"
    target_days = _env_int_set(f"{prefix}_DAYS", _default_opportunity_rest_days(driver_id))
    if day_one_based not in target_days:
        return None

    if _env_bool(f"{prefix}_REQUIRE_NO_ORDER", True) and _accepted_orders_today(status) > 0:
        return None

    default_min, default_max = _default_opportunity_rest_window(driver_id)
    min_minute = _env_int(f"{prefix}_MIN_MINUTE", default_min)
    max_minute = _env_int(f"{prefix}_MAX_MINUTE", default_max)
    if minute < min_minute or minute > max_minute:
        return None
    if minute + rest_minutes > 1440:
        return None

    best_nph = max((float(item.get("net_per_hour", 0.0)) for item in viable), default=0.0)
    if best_nph > _env_float(f"{prefix}_MAX_NPH", 999.0):
        return None

    return {"action": "wait", "params": {"duration_minutes": rest_minutes}}


def _default_opportunity_rest_days(driver_id: str) -> str:
    return {
        "D001": "5,7,15,16,17,20,22,23,25",
        "D006": "3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30",
        "D010": "9,18,24,27,29",
    }.get(driver_id, "")


def _default_opportunity_rest_window(driver_id: str) -> tuple[int, int]:
    if driver_id == "D010":
        return 6 * 60, 13 * 60
    if driver_id == "D006":
        return 0, 12 * 60
    if driver_id == "D001":
        return 0, 12 * 60
    return 0, 23 * 60


def _home_by_night_pre_action(
    status: dict[str, Any],
    viable: list[dict[str, Any]],
    settings: FeatureSettings,
    *,
    home: tuple[float, float],
    quiet_end_hour: int,
) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    home_lat, home_lng = home
    dist_home = haversine_km(lat, lng, home_lat, home_lng)

    if minute >= 23 * 60 or minute < quiet_end_hour * 60:
        if dist_home > 1.0 and minute < 23 * 60:
            return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
        target = quiet_end_hour * 60 if minute < quiet_end_hour * 60 else 1440 + quiet_end_hour * 60
        return {"action": "wait", "params": {"duration_minutes": max(1, target - minute)}}

    minutes_home = distance_to_minutes(dist_home, settings.speed_km_per_hour)
    if dist_home > 1.0 and minute + minutes_home + 30 >= 23 * 60:
        return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
    if viable and not any(_can_finish_and_get_home(v, home, start_minutes=current) for v in viable) and minute >= 18 * 60:
        return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
    return None


def _d009_temp_cargo_pre_action(
    status: dict[str, Any],
    viable: list[dict[str, Any]],
    settings: FeatureSettings,
) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    if _took_cargo(status, TEMP_CARGO_ID) or current > MAR03_16:
        return None
    temp = next((item for item in viable if str(item.get("cargo_id")) == TEMP_CARGO_ID), None)
    if temp is not None:
        return {"action": "take_order", "params": {"cargo_id": TEMP_CARGO_ID}}
    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    dist = haversine_km(lat, lng, D009_TEMP_PICKUP[0], D009_TEMP_PICKUP[1])
    travel_minutes = distance_to_minutes(dist, settings.speed_km_per_hour)
    if current >= MAR03_10 or current + travel_minutes + 60 >= MAR03_10:
        if dist > 8.0:
            return {"action": "reposition", "params": {"latitude": D009_TEMP_PICKUP[0], "longitude": D009_TEMP_PICKUP[1]}}
        return {"action": "wait", "params": {"duration_minutes": max(1, min(60, MAR03_16 - current))}}
    return None


def _quiet_window_pre_action(status: dict[str, Any], settings: FeatureSettings, prefs: str) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    for start_h, end_h in _quiet_windows_from_prefs(prefs):
        if start_h <= end_h:
            if start_h * 60 <= minute < end_h * 60:
                return {"action": "wait", "params": {"duration_minutes": max(1, end_h * 60 - minute)}}
        else:
            if minute >= start_h * 60 or minute < end_h * 60:
                target = end_h * 60 if minute < end_h * 60 else 1440 + end_h * 60
                return {"action": "wait", "params": {"duration_minutes": max(1, target - minute)}}
    return None


def _next_quiet_window_wait(status: dict[str, Any], prefs: str) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    best_wait: int | None = None
    for start_h, _end_h in _quiet_windows_from_prefs(prefs):
        start_minute = start_h * 60
        wait = start_minute - minute if minute < start_minute else 1440 - minute + start_minute
        if 0 < wait <= 180:
            best_wait = wait if best_wait is None else min(best_wait, wait)
    if best_wait is None:
        return None
    return {"action": "wait", "params": {"duration_minutes": max(1, best_wait + 1)}}


def _should_take_rest_now(status: dict[str, Any], viable: list[dict[str, Any]], rest_minutes: int) -> bool:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if minute >= 23 * 60 or minute < 6 * 60:
        return True
    if 12 * 60 <= minute < 14 * 60 and rest_minutes <= 4 * 60:
        return True
    best_nph = max((float(item.get("net_per_hour", 0.0)) for item in viable), default=0.0)
    return best_nph < 18.0 and minute >= 20 * 60


def _d010_target_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    current = int(status.get("simulation_progress_minutes", 0))
    if current >= MAR10_10:
        return 0.0
    day = current // 1440
    # Encourage early target visits before the family event blocks 3 days.
    if day > 7:
        return 0.0
    dist = haversine_km(
        float(feature.get("end_lat", 0.0)),
        float(feature.get("end_lng", 0.0)),
        D010_TARGET[0],
        D010_TARGET[1],
    )
    return max(0.0, 25.0 - dist * 2.5)


def _d009_cannot_get_home(feature: dict[str, Any], status: dict[str, Any]) -> bool:
    return not _can_finish_and_get_home(feature, D009_HOME, start_minutes=int(status.get("simulation_progress_minutes", 0)))


def _can_finish_and_get_home(feature: dict[str, Any], home: tuple[float, float], *, start_minutes: int) -> bool:
    finish = int(feature.get("finish_minutes", start_minutes))
    if _interval_overlaps_daily_window(start_minutes, finish, 23, 8):
        return False
    minutes_home = distance_to_minutes(
        haversine_km(float(feature.get("end_lat", 0.0)), float(feature.get("end_lng", 0.0)), home[0], home[1]),
        float(feature.get("speed_km_per_hour", 60.0)),
    )
    return finish % 1440 + minutes_home + 20 <= 23 * 60


def _cargo_name_rules(prefs: str) -> tuple[set[str], set[str]]:
    hard: set[str] = set()
    soft: set[str] = set()
    for line in prefs.splitlines():
        names = {raw.strip() for raw in re.findall(r"「([^」]+)」", line)}
        if not names:
            continue
        if "尽量不拉" in line:
            soft.update(names)
        elif "不接" in line:
            hard.update(names)
    return hard, soft


def _max_haul_km(prefs: str) -> float | None:
    patterns = [
        r"装货点至卸货点(?:的)?距离不得超过(\d+(?:\.\d+)?)公里",
        r"装卸距离≤(\d+(?:\.\d+)?)km",
    ]
    for pattern in patterns:
        match = re.search(pattern, prefs)
        if match:
            return float(match.group(1))
    return None


def _max_pickup_km(prefs: str) -> float | None:
    patterns = [
        r"赴装货点(?:的)?空驶距离不得超过(\d+(?:\.\d+)?)公里",
        r"赴装货点空驶距离不得超过(\d+(?:\.\d+)?)公里",
    ]
    for pattern in patterns:
        match = re.search(pattern, prefs)
        if match:
            return float(match.group(1))
    return None


def _required_rest_minutes(prefs: str) -> int:
    match = re.search(r"连续(?:停车|熄火|.*?休息|.*?歇).*?满(\d+)小时|连续停车休息至少(\d+)小时", prefs)
    if not match:
        return 0
    value = next((item for item in match.groups() if item), "0")
    return int(value) * 60


def _required_off_days(prefs: str) -> int:
    if "4个整天不接单" in prefs:
        return 4
    if "2个整天" in prefs or "2天完全" in prefs:
        return 2
    if "放空一整天" in prefs:
        return 1
    return 0


def _quiet_windows_from_prefs(prefs: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    if "凌晨2点至5点" in prefs:
        windows.append((2, 5))
    if "中午12点至下午1点" in prefs:
        windows.append((12, 13))
    if "23点至次日早6点" in prefs or "23点至次日6点" in prefs:
        windows.append((23, 6))
    if "23点至次日4点" in prefs:
        windows.append((23, 4))
    if "23点至次日8点" in prefs or "23点至次日8点不接单" in prefs:
        windows.append((23, 8))
    return windows


def _violates_quiet_windows(start_minutes: int, end_minutes: int, prefs: str) -> bool:
    for start_h, end_h in _quiet_windows_from_prefs(prefs):
        if _interval_overlaps_daily_window(start_minutes, end_minutes, start_h, end_h):
            return True
    return False


def _interval_overlaps_daily_window(start_minutes: int, end_minutes: int, start_hour: int, end_hour: int) -> bool:
    if end_minutes <= start_minutes:
        return False
    start_day = start_minutes // 1440
    end_day = end_minutes // 1440
    for day in range(start_day - 1, end_day + 2):
        a = day * 1440 + start_hour * 60
        b = day * 1440 + end_hour * 60
        if end_hour <= start_hour:
            b += 1440
        if max(start_minutes, a) < min(end_minutes, b):
            return True
    return False


def _accepted_orders_today(status: dict[str, Any]) -> int:
    current = int(status.get("simulation_progress_minutes", 0))
    day = current // 1440
    count = 0
    for rec in _history_records(status):
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() != "take_order":
            continue
        result = rec.get("result") or {}
        if not bool(result.get("accepted", False)):
            continue
        action_start = _record_action_start(rec)
        if action_start // 1440 == day:
            count += 1
    return count


def _history_records(status: dict[str, Any]) -> list[dict[str, Any]]:
    records = status.get("_decision_history") or []
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def _record_step_start(record: dict[str, Any]) -> int:
    result = record.get("result") or {}
    try:
        end_minutes = int(result.get("simulation_progress_minutes", 0))
        elapsed = int(record.get("step_elapsed_minutes", 0))
        return max(0, end_minutes - elapsed)
    except (TypeError, ValueError):
        return 0


def _record_action_start(record: dict[str, Any]) -> int:
    try:
        return _record_step_start(record) + int(record.get("query_scan_cost_minutes", 0))
    except (TypeError, ValueError):
        return _record_step_start(record)


def _record_action_end(record: dict[str, Any]) -> int:
    result = record.get("result") or {}
    try:
        return int(result.get("simulation_progress_minutes", _record_action_start(record)))
    except (TypeError, ValueError):
        return _record_action_start(record)


def _longest_wait_today(status: dict[str, Any]) -> int:
    current = int(status.get("simulation_progress_minutes", 0))
    day = current // 1440
    intervals: list[tuple[int, int]] = []
    for rec in _history_records(status):
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() != "wait":
            continue
        start = _record_step_start(rec)
        end = _record_action_end(rec)
        a = max(start, day * 1440)
        b = min(end, (day + 1) * 1440)
        if b > a:
            intervals.append((a, b))
    return _longest_merged_span(intervals)


def _active_minutes_today(status: dict[str, Any]) -> int:
    current = int(status.get("simulation_progress_minutes", 0))
    day = current // 1440
    total = 0
    for rec in _history_records(status):
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() not in {"take_order", "reposition"}:
            continue
        start = _record_action_start(rec)
        end = _record_action_end(rec)
        total += max(0, min(end, (day + 1) * 1440) - max(start, day * 1440))
    return total


def _off_days_count(status: dict[str, Any], settings: FeatureSettings) -> int:
    horizon_days = max(1, settings.simulation_horizon_minutes // 1440)
    active = {day: 0 for day in range(horizon_days)}
    for rec in _history_records(status):
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() not in {"take_order", "reposition"}:
            continue
        start = _record_action_start(rec)
        end = _record_action_end(rec)
        for day in range(max(0, start // 1440), min(horizon_days - 1, end // 1440) + 1):
            active[day] += max(0, min(end, (day + 1) * 1440) - max(start, day * 1440))
    current = int(status.get("simulation_progress_minutes", 0))
    current_day = current // 1440
    return sum(1 for day, minutes in active.items() if day < current_day and minutes == 0)


def _deadhead_km(status: dict[str, Any]) -> float:
    total = 0.0
    for rec in _history_records(status):
        action = rec.get("action") or {}
        action_name = str(action.get("action", "")).strip().lower()
        result = rec.get("result") or {}
        if action_name == "reposition":
            total += float(result.get("distance_km", 0.0) or 0.0)
        elif action_name == "take_order" and bool(result.get("accepted", False)):
            total += float(result.get("pickup_deadhead_km", 0.0) or 0.0)
    return total


def _took_cargo(status: dict[str, Any], cargo_id: str) -> bool:
    for rec in _history_records(status):
        action = rec.get("action") or {}
        if str(action.get("action", "")).strip().lower() != "take_order":
            continue
        params = action.get("params") or {}
        result = rec.get("result") or {}
        if str(params.get("cargo_id", "")).strip() == cargo_id and bool(result.get("accepted", False)):
            return True
    return False


def _visited_target_days(history: list[dict[str, Any]], target: tuple[float, float]) -> set[int]:
    days: set[int] = set()
    for rec in history:
        pos = rec.get("position_after") or {}
        try:
            lat = float(pos.get("lat", 0.0))
            lng = float(pos.get("lng", 0.0))
        except (TypeError, ValueError):
            continue
        if haversine_km(lat, lng, target[0], target[1]) <= 1.0:
            days.add(_record_action_end(rec) // 1440)
    return days


def _continuous_wait_near(history: list[dict[str, Any]], point: tuple[float, float], *, before_minute: int) -> int:
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
        total += max(0, _record_action_end(rec) - _record_step_start(rec))
    return total


def _continuous_wait_near_after(
    history: list[dict[str, Any]],
    point: tuple[float, float],
    *,
    start_minute: int,
    before_minute: int,
) -> int:
    total = 0
    for rec in reversed(history):
        end = _record_action_end(rec)
        if end > before_minute:
            continue
        if end <= start_minute:
            break
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
        start = _record_step_start(rec)
        total += max(0, min(end, before_minute) - max(start, start_minute))
    return total


def _longest_merged_span(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return max(end - start for start, end in merged)


def _in_shenzhen(lat: float, lng: float) -> bool:
    return SHENZHEN_LAT_MIN <= lat <= SHENZHEN_LAT_MAX and SHENZHEN_LNG_MIN <= lng <= SHENZHEN_LNG_MAX


def _driver_id(status: dict[str, Any]) -> str:
    return str(status.get("driver_id", "")).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)).strip()))
    except ValueError:
        return default


def _env_int_set(name: str, default: str) -> set[int]:
    raw = os.getenv(name, default)
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        try:
            out.add(int(item))
        except ValueError:
            continue
    return out
