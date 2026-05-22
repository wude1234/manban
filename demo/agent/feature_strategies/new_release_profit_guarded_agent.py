"""Profit-first guarded strategy for the 2026-05-08 release.

This strategy keeps only guards that have shown positive net impact on the
new data. It deliberately relaxes the over-conservative D001/D004 guards from
``new_release_guarded_agent``, adds a targeted D002/D008 rest deadline, and
uses small D003/D004/D005 net-profit tie breakers verified on 30-day runs.
"""

from __future__ import annotations

import os
from typing import Any

from .common import BaseFeatureStrategy, FeatureSettings, preferences_text
from .new_release_guarded_agent import (
    _breaks_d010_family_departure,
    _guarded_d009_temp_cargo_pre_action,
    _guarded_d010_family_pre_action,
    _weekday_202603,
)
from .new_release_preference_agent import (
    TEMP_CARGO_ID,
    NewReleasePreferenceAgent,
    _cargo_name_rules,
    _driver_id,
    _in_shenzhen,
    _longest_wait_today,
    _max_haul_km,
    _max_pickup_km,
    _took_cargo,
)


class NewReleaseProfitGuardedAgent(NewReleasePreferenceAgent):
    name = "new_release_profit_guarded_agent"

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        driver_id = _driver_id(status)

        if driver_id == "D010":
            action = _guarded_d010_family_pre_action(status, self._memory_for(driver_id))
            if action is not None:
                return action

        if driver_id == "D009" and _profit_enable_d009_temp_take():
            action = _guarded_d009_temp_cargo_pre_action(status, candidates, settings)
            if action is not None:
                return action

        action = _profit_rest_deadline_pre_action(status)
        if action is not None:
            return action

        if driver_id == "D009" and _d009_relax_home_after_temp(status):
            return None

        return NewReleasePreferenceAgent.pre_action(self, status, candidates, viable, settings)

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        score = NewReleasePreferenceAgent.score(self, feature, status)
        driver_id = _driver_id(status)
        score += _driver_score_net_weight(driver_id) * float(feature.get("estimated_net", 0.0))
        if driver_id == "D003":
            score -= _env_float("AGENT_D003_PICKUP_PENALTY_PER_KM", 0.0) * float(feature.get("pickup_km", 0.0))
        return score

    def is_selectable(self, feature: dict[str, Any], status: dict[str, Any]) -> bool:
        if _driver_id(status) == "D009" and _d009_relax_home_after_temp(status):
            if _profit_d009_hard_filter_penalty_without_home(feature, status) > 0:
                return False
        elif not NewReleasePreferenceAgent.is_selectable(self, feature, status):
            return False
        if _breaks_profit_rest_deadline(feature, status):
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
        rest = _profit_rest_deadline_pre_action(status, force_when_possible=True)
        if rest is not None:
            return rest
        return NewReleasePreferenceAgent.no_selectable_action(self, status, candidates, viable, settings)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseProfitGuardedAgent()


def _profit_enable_d009_temp_take() -> bool:
    return os.getenv("AGENT_ENABLE_D009_TEMP_TAKE", "1").strip() != "0"


def _d009_relax_home_after_temp(status: dict[str, Any]) -> bool:
    if os.getenv("AGENT_D009_RELAX_HOME_AFTER_TEMP", "0").strip() != "1":
        return False
    return _took_cargo(status, TEMP_CARGO_ID)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _driver_env_float(driver_id: str, suffix: str, default: float) -> float:
    return _env_float(f"AGENT_{driver_id}_{suffix}", default)


def _driver_score_net_weight(driver_id: str) -> float:
    driver_env = f"AGENT_{driver_id}_SCORE_NET_WEIGHT"
    if driver_env in os.environ:
        return _env_float(driver_env, 0.0)
    if "AGENT_SCORE_NET_WEIGHT" in os.environ:
        return _env_float("AGENT_SCORE_NET_WEIGHT", 0.0)
    if driver_id == "D005":
        return 0.03
    if driver_id in {"D003", "D004"}:
        return 0.02
    return 0.0


def _profit_rest_deadline_pre_action(
    status: dict[str, Any],
    *,
    force_when_possible: bool = False,
) -> dict[str, Any] | None:
    spec = _profit_rest_spec(status)
    if spec is None:
        return None
    rest_minutes, latest_start_minute = spec
    if _longest_wait_today(status) >= rest_minutes:
        return None

    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    low_opportunity = minute < 6 * 60
    close_to_deadline = minute >= latest_start_minute - 30
    if minute + rest_minutes <= 1440 and (force_when_possible or low_opportunity or close_to_deadline):
        return {"action": "wait", "params": {"duration_minutes": rest_minutes}}
    return None


def _breaks_profit_rest_deadline(feature: dict[str, Any], status: dict[str, Any]) -> bool:
    spec = _profit_rest_spec(status)
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


def _profit_rest_spec(status: dict[str, Any]) -> tuple[int, int] | None:
    driver_id = _driver_id(status)
    current = int(status.get("simulation_progress_minutes", 0))
    day = current // 1440

    if driver_id == "D002":
        rest_minutes = 4 * 60
    elif driver_id == "D008" and _weekday_202603(day) < 5:
        rest_minutes = 4 * 60
    elif driver_id == "D006" and os.getenv("AGENT_ENABLE_D006_REST_DEADLINE", "0").strip() == "1":
        rest_minutes = 5 * 60
    elif driver_id == "D010" and os.getenv("AGENT_ENABLE_D010_REST_DEADLINE", "0").strip() == "1":
        rest_minutes = 3 * 60
    else:
        return None
    return rest_minutes, 1440 - rest_minutes


def _profit_d009_hard_filter_penalty_without_home(feature: dict[str, Any], status: dict[str, Any]) -> float:
    """Keep D009 hard cargo bans, but deliberately price home/night as a daily soft penalty."""
    prefs = preferences_text(status)
    penalty = 0.0
    cargo_name = str(feature.get("cargo_name", "") or "")
    pickup_km = float(feature.get("pickup_km", 0.0))
    haul_km = float(feature.get("haul_km", 0.0))
    start_lat = float(feature.get("start_lat", 0.0))
    start_lng = float(feature.get("start_lng", 0.0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))

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

    return penalty
