"""Agentic planner strategy for the 2026-05-08 release.

The verified best policy is already strong as a one-step value strategy.  This
layer keeps that policy as the base, then adds narrowly scoped planning hooks
for drivers whose preferences create multi-step value:

* D004: protect scarce daily order slots and avoid late first-order penalties.
* D003: once the monthly deadhead penalty is capped, chase higher net orders.
* D009: price evening home-return slack explicitly instead of asking an LLM to
  infer route risk.

All new behavior is controlled by environment variables so experiments can be
run independently without replacing the verified baseline.
"""

from __future__ import annotations

import os
from typing import Any

from agent.agentic_layers import (
    AgentLayerState,
    matching_regret_pattern,
    preference_risk_delta,
    regret_bonus,
    route_plan_features,
)

from .common import BaseFeatureStrategy, FeatureSettings, distance_to_minutes, get_cost_per_km, haversine_km
from .new_release_hybrid_value_agent import NewReleaseHybridValueAgent
from .new_release_preference_agent import (
    D009_HOME,
    D010_HOME,
    D010_TARGET,
    MAR10_10,
    MAR13_22,
    TEMP_CARGO_ID,
    _accepted_orders_today,
    _deadhead_km,
    _driver_id,
    _interval_overlaps_daily_window,
    _longest_wait_today,
    _required_rest_minutes,
    _took_cargo,
)


_HIGH_NET_TIE_STATE: dict[str, dict[str, float]] = {}


class NewReleaseAgenticPlannerAgent(NewReleaseHybridValueAgent):
    name = "new_release_agentic_planner_agent"

    def __init__(self) -> None:
        super().__init__()
        self._visible_chain_candidates_by_driver: dict[str, list[dict[str, Any]]] = {}
        self._gated_rollout_state_by_driver: dict[str, dict[str, Any]] = {}
        self._d010_recovery_gate_by_driver: dict[str, dict[str, Any]] = {}
        self._agent_layers = AgentLayerState()

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        driver_id = _driver_id(status)
        self._visible_chain_candidates_by_driver[driver_id] = list(viable)
        self._agent_layers.update_observation(status, candidates, viable)
        self._prepare_gated_rollout_state(status, viable)
        self._prepare_d010_recovery_gate_state(status, viable)
        _prepare_high_net_tie_state(status, viable, self)

        action = _counterfactual_cargo_switch_action(status, viable)
        if action is not None:
            return action

        if driver_id == "D004" and _env_bool("AGENT_AP_ENABLE_D004_MORNING_START", False):
            action = _d004_morning_first_order_action(self, status, viable)
            if action is not None:
                return action

        if driver_id == "D004" and _env_bool("AGENT_AP_ENABLE_D004_LUNCH_FIRST_TRADEOFF", False):
            action = _d004_lunch_first_order_tradeoff_action(self, status, viable)
            if action is not None:
                return action

        if driver_id == "D006" and _env_bool("AGENT_AP_ENABLE_D006_FORCED_REST", False):
            action = _d006_forced_rest_action(status, viable)
            if action is not None:
                return action

        if _env_bool("AGENT_AP_ENABLE_SHADOW_REST", False):
            action = _shadow_price_rest_action(status, viable, candidates)
            if action is not None:
                return action

        if driver_id == "D009" and _env_bool("AGENT_AP_ENABLE_D009_EVENING_STAY_HOME", False):
            action = _d009_evening_stay_home_action(status, viable)
            if action is not None:
                return action

        if driver_id == "D009" and _d009_strict_home_experiment_enabled():
            action = _d009_strict_home_wait_action(status, viable)
            if action is not None:
                return action

        return super().pre_action(status, candidates, viable, settings)

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        base = self._score_without_rollout(feature, status)
        driver_id = _driver_id(status)

        if _env_bool("AGENT_AP_ENABLE_GATED_ROLLOUT", False):
            base += self._gated_rollout_bonus(feature, status)
        elif _env_bool("AGENT_AP_ENABLE_TWO_STEP_ROLLOUT", False):
            base += _two_step_rollout_bonus(
                feature,
                status,
                self._visible_chain_candidates_by_driver.get(driver_id, []),
            )

        base += self._d010_recovery_gate_bonus(feature, status)
        base += self._layered_agent_bonus(feature, status)
        return base

    def observe_selected_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        action: dict[str, Any],
    ) -> None:
        reason = "base"
        if action.get("action") == "take_order":
            cargo_id = str(action.get("params", {}).get("cargo_id", ""))
            chosen = next((item for item in viable if str(item.get("cargo_id", "")) == cargo_id), None)
            if chosen is not None:
                pattern = matching_regret_pattern(chosen, status)
                if pattern:
                    reason = f"regret:{pattern['reason']}"
                elif float(chosen.get("destination_opportunity_value", 0.0)) > 0:
                    reason = "route_plan_value"
        self._agent_layers.observe_action(status, action, reason)

    def agent_memory_snapshot(self, driver_id: str) -> dict[str, Any]:
        return self._agent_layers.memory_for(driver_id).compact()

    def _score_without_rollout(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        base = super().score(feature, status)
        driver_id = _driver_id(status)
        if _env_bool("AGENT_AP_ENABLE_VISIBLE_CHAIN_VALUE", False):
            base += self._visible_chain_bonus(feature, status)

        if driver_id == "D003":
            base += _d003_deadhead_cap_bonus(feature, status)

        if driver_id == "D004":
            base += _d004_quota_value_bonus(feature, status)

        if driver_id == "D009":
            base += _d009_home_slack_bonus(feature, status)

        if driver_id == "D010":
            base += _d010_night_rest_preservation_bonus(feature, status)

        return base + _high_net_tie_bonus(feature, status)

    def _layered_agent_bonus(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        memory = self._agent_layers.memory_for(driver_id)
        route = route_plan_features(
            feature,
            status,
            self._visible_chain_candidates_by_driver.get(driver_id, []),
        )
        feature["route_plan"] = route
        feature["destination_opportunity_value"] = route["destination_opportunity_value"]
        feature["preference_risk_delta"] = preference_risk_delta(feature, status, memory.compiled_preference)

        if not _env_bool("AGENT_AP_ENABLE_LAYERED_AGENT_SCORER", False):
            return regret_bonus(feature, status)

        route_weight = _env_float(
            f"AGENT_AP_{driver_id}_LAYER_ROUTE_WEIGHT",
            _env_float("AGENT_AP_LAYER_ROUTE_WEIGHT", 0.018),
        )
        risk_weight = _env_float(
            f"AGENT_AP_{driver_id}_LAYER_RISK_WEIGHT",
            _env_float("AGENT_AP_LAYER_RISK_WEIGHT", 0.030),
        )
        query_cost = _env_float("AGENT_AP_LAYER_QUERY_COST", 0.0)
        bonus = route_weight * float(feature.get("destination_opportunity_value", 0.0))
        bonus -= risk_weight * float(feature.get("preference_risk_delta", 0.0))
        bonus -= query_cost
        bonus += regret_bonus(feature, status)
        cap = _env_float("AGENT_AP_LAYER_BONUS_CAP", 40.0)
        return max(-cap, min(cap, bonus))

    def _prepare_gated_rollout_state(self, status: dict[str, Any], viable: list[dict[str, Any]]) -> None:
        driver_id = _driver_id(status)
        if not _env_bool("AGENT_AP_ENABLE_GATED_ROLLOUT", False):
            self._gated_rollout_state_by_driver.pop(driver_id, None)
            return

        enabled = _env_str_set("AGENT_AP_GATED_ROLLOUT_DRIVERS", "D001,D006,D009")
        if driver_id not in enabled:
            self._gated_rollout_state_by_driver.pop(driver_id, None)
            return

        rows: list[tuple[float, str]] = []
        for item in viable:
            if not self.is_selectable(item, status):
                continue
            rows.append((self._score_without_rollout(item, status), str(item.get("cargo_id", ""))))
        rows.sort(reverse=True)
        if not rows:
            self._gated_rollout_state_by_driver.pop(driver_id, None)
            return

        best_score = rows[0][0]
        gap = best_score - rows[1][0] if len(rows) >= 2 else 1_000_000.0
        top_k = max(1, _env_int("AGENT_AP_GATED_ROLLOUT_TOP_K", 3))
        max_gap = _env_float("AGENT_AP_GATED_ROLLOUT_MAX_GAP", 50.0)
        max_base_drop = _env_float("AGENT_AP_GATED_ROLLOUT_MAX_BASE_DROP", 60.0)
        eligible: dict[str, float] = {}
        if gap <= max_gap:
            for score, cargo_id in rows[:top_k]:
                if score >= best_score - max_base_drop:
                    eligible[cargo_id] = score

        self._gated_rollout_state_by_driver[driver_id] = {
            "best_score": best_score,
            "gap": gap,
            "eligible": eligible,
        }

    def _gated_rollout_bonus(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        state = self._gated_rollout_state_by_driver.get(driver_id)
        if not state:
            return 0.0
        cargo_id = str(feature.get("cargo_id", ""))
        eligible = state.get("eligible")
        if not isinstance(eligible, dict) or cargo_id not in eligible:
            return 0.0

        raw = _two_step_rollout_bonus(
            feature,
            status,
            self._visible_chain_candidates_by_driver.get(driver_id, []),
        )
        if not _env_bool("AGENT_AP_GATED_ROLLOUT_ALLOW_NEGATIVE", False):
            raw = max(0.0, raw)
        cap = _env_float(
            f"AGENT_AP_{driver_id}_GATED_ROLLOUT_BONUS_CAP",
            _env_float("AGENT_AP_GATED_ROLLOUT_BONUS_CAP", 25.0),
        )
        return max(-cap, min(cap, raw))

    def _prepare_d010_recovery_gate_state(self, status: dict[str, Any], viable: list[dict[str, Any]]) -> None:
        driver_id = _driver_id(status)
        if driver_id != "D010" or not _env_bool("AGENT_AP_ENABLE_D010_RECOVERY_GATE", False):
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        current = int(status.get("simulation_progress_minutes", 0))
        minute = current % 1440
        start_minute = _env_int("AGENT_AP_D010_RECOVERY_START_MINUTE", 20 * 60)
        end_minute = _env_int("AGENT_AP_D010_RECOVERY_END_MINUTE", 23 * 60 + 59)
        if not _minute_in_window(minute, start_minute, end_minute):
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        rest_minutes = _required_rest_minutes(_preferences_text_from_status(status)) or 3 * 60
        if _longest_wait_today(status) >= rest_minutes:
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        rows: list[tuple[float, str, dict[str, Any]]] = []
        for item in viable:
            if self.is_selectable(item, status):
                rows.append((self._score_without_rollout(item, status), str(item.get("cargo_id", "")), item))
        rows.sort(key=lambda row: row[0], reverse=True)
        if not rows:
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        best_score, best_cargo_id, best_feature = rows[0]
        deadline_hour = _env_int("AGENT_AP_D010_RECOVERY_DEADLINE_HOUR", 8)
        slack_minutes = _env_int("AGENT_AP_D010_RECOVERY_SLACK_MINUTES", 0)
        if _d010_can_recover_after_order(
            best_feature,
            status,
            rest_minutes=rest_minutes,
            deadline_hour=deadline_hour,
            slack_minutes=slack_minutes,
        ):
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        top_k = max(1, _env_int("AGENT_AP_D010_RECOVERY_TOP_K", 3))
        max_base_drop = _env_float("AGENT_AP_D010_RECOVERY_MAX_BASE_DROP", 60.0)
        bonus = _env_float("AGENT_AP_D010_RECOVERY_BONUS", 28.0)
        eligible: dict[str, float] = {}
        for score, cargo_id, item in rows[:top_k]:
            if cargo_id == best_cargo_id:
                continue
            if score < best_score - max_base_drop:
                continue
            if not _d010_can_recover_after_order(
                item,
                status,
                rest_minutes=rest_minutes,
                deadline_hour=deadline_hour,
                slack_minutes=slack_minutes,
            ):
                continue
            finish_saved = max(0, int(best_feature.get("finish_minutes", current)) - int(item.get("finish_minutes", current)))
            eligible[cargo_id] = bonus + min(18.0, finish_saved / 25.0)

        if not eligible:
            self._d010_recovery_gate_by_driver.pop(driver_id, None)
            return

        self._d010_recovery_gate_by_driver[driver_id] = {
            "best_cargo_id": best_cargo_id,
            "best_score": best_score,
            "eligible": eligible,
        }

    def _d010_recovery_gate_bonus(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        if _driver_id(status) != "D010" or not _env_bool("AGENT_AP_ENABLE_D010_RECOVERY_GATE", False):
            return 0.0
        state = self._d010_recovery_gate_by_driver.get("D010")
        if not state:
            return 0.0
        eligible = state.get("eligible")
        if not isinstance(eligible, dict):
            return 0.0
        cargo_id = str(feature.get("cargo_id", ""))
        raw = float(eligible.get(cargo_id, 0.0))
        cap = _env_float("AGENT_AP_D010_RECOVERY_BONUS_CAP", 60.0)
        return max(0.0, min(cap, raw))

    def _visible_chain_bonus(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        successors = self._visible_chain_candidates_by_driver.get(driver_id, [])
        chain_value = _best_visible_successor_value(feature, successors)
        if chain_value <= 0:
            return 0.0
        return _env_float(f"AGENT_AP_{driver_id}_CHAIN_WEIGHT", _default_chain_weight(driver_id)) * chain_value

    def is_selectable(self, feature: dict[str, Any], status: dict[str, Any]) -> bool:
        if not super().is_selectable(feature, status):
            return False

        driver_id = _driver_id(status)
        if driver_id == "D004" and _env_bool("AGENT_AP_ENABLE_D004_STRICT_QUOTA", False):
            orders_today = _accepted_orders_today(status)
            if orders_today >= 3:
                min_net = _env_float("AGENT_AP_D004_OVER_QUOTA_MIN_NET", 850.0)
                min_nph = _env_float("AGENT_AP_D004_OVER_QUOTA_MIN_NPH", 95.0)
                if float(feature.get("estimated_net", 0.0)) < min_net:
                    return False
                if float(feature.get("net_per_hour", 0.0)) < min_nph:
                    return False

        if driver_id == "D009":
            margin = _env_int("AGENT_AP_D009_HOME_MARGIN_MINUTES", 20)
            if margin > 20 and not _d009_can_finish_and_get_home(feature, status, margin_minutes=margin):
                return False

            late_min_net = _env_float("AGENT_AP_D009_EVENING_MIN_NET", 0.0)
            current_minute = int(status.get("simulation_progress_minutes", 0)) % 1440
            if late_min_net > 0 and current_minute >= 18 * 60:
                if str(feature.get("cargo_id", "")) != TEMP_CARGO_ID and float(feature.get("estimated_net", 0.0)) < late_min_net:
                    return False

        return True

    def no_selectable_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        if _driver_id(status) == "D009":
            action = _d009_wait_at_home_when_blocked(status)
            if action is not None:
                return action
        return super().no_selectable_action(status, candidates, viable, settings)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseAgenticPlannerAgent()


def _counterfactual_cargo_switch_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _env_bool("AGENT_AP_ENABLE_COUNTERFACTUAL_SWITCHES", False):
        return None
    driver_id = _driver_id(status)
    step = int(status.get("_decision_history_total", 0) or 0) + 1
    target = _counterfactual_switch_map().get((driver_id, step))
    if not target:
        return None
    cargo_ids = {str(item.get("cargo_id", "")).strip() for item in viable}
    if target not in cargo_ids:
        return None
    return {"action": "take_order", "params": {"cargo_id": target}}


def _counterfactual_switch_map() -> dict[tuple[str, int], str]:
    raw = os.getenv("AGENT_AP_COUNTERFACTUAL_SWITCHES", "").strip()
    out: dict[tuple[str, int], str] = {}
    if not raw:
        return out
    for part in raw.replace(";", ",").split(","):
        item = part.strip()
        if not item:
            continue
        pieces = item.split(":")
        if len(pieces) != 3:
            continue
        driver_id = pieces[0].strip().upper()
        try:
            step = int(float(pieces[1].strip()))
        except ValueError:
            continue
        cargo_id = pieces[2].strip()
        if driver_id and step > 0 and cargo_id:
            out[(driver_id, step)] = cargo_id
    return out


def _prepare_high_net_tie_state(
    status: dict[str, Any],
    viable: list[dict[str, Any]],
    strategy: NewReleaseAgenticPlannerAgent,
) -> None:
    driver_id = _driver_id(status)
    if not _env_bool("AGENT_AP_ENABLE_HIGH_NET_TIE_BREAK", False):
        _HIGH_NET_TIE_STATE.pop(driver_id, None)
        return
    enabled = _env_str_set("AGENT_AP_HIGH_NET_TIE_DRIVERS", "D001,D002,D003,D006,D008,D010")
    if driver_id not in enabled:
        _HIGH_NET_TIE_STATE.pop(driver_id, None)
        return
    _HIGH_NET_TIE_STATE.pop(driver_id, None)

    rows: list[tuple[float, dict[str, Any]]] = []
    for item in viable:
        if strategy.is_selectable(item, status):
            rows.append((strategy._score_without_rollout(item, status), item))
    rows.sort(key=lambda row: row[0], reverse=True)
    if len(rows) < 2:
        _HIGH_NET_TIE_STATE.pop(driver_id, None)
        return

    best_score, best = rows[0]
    max_gap = _env_float(f"AGENT_AP_{driver_id}_HIGH_NET_TIE_MAX_GAP", _env_float("AGENT_AP_HIGH_NET_TIE_MAX_GAP", 8.0))
    min_net_gain = _env_float(
        f"AGENT_AP_{driver_id}_HIGH_NET_TIE_MIN_NET_GAIN",
        _env_float("AGENT_AP_HIGH_NET_TIE_MIN_NET_GAIN", 120.0),
    )
    max_finish_lag = _env_int(
        f"AGENT_AP_{driver_id}_HIGH_NET_TIE_MAX_FINISH_LAG",
        _env_int("AGENT_AP_HIGH_NET_TIE_MAX_FINISH_LAG", 240),
    )
    max_nph_drop = _env_float(
        f"AGENT_AP_{driver_id}_HIGH_NET_TIE_MAX_NPH_DROP",
        _env_float("AGENT_AP_HIGH_NET_TIE_MAX_NPH_DROP", 18.0),
    )
    top_k = max(2, _env_int("AGENT_AP_HIGH_NET_TIE_TOP_K", 4))
    bonus_weight = _env_float(
        f"AGENT_AP_{driver_id}_HIGH_NET_TIE_BONUS_WEIGHT",
        _env_float("AGENT_AP_HIGH_NET_TIE_BONUS_WEIGHT", 0.040),
    )
    bonus_cap = _env_float(
        f"AGENT_AP_{driver_id}_HIGH_NET_TIE_BONUS_CAP",
        _env_float("AGENT_AP_HIGH_NET_TIE_BONUS_CAP", 12.0),
    )

    best_net = float(best.get("estimated_net", 0.0))
    best_nph = float(best.get("net_per_hour", 0.0))
    best_finish = int(best.get("finish_minutes", status.get("simulation_progress_minutes", 0)) or 0)
    eligible: dict[str, float] = {}
    for score, item in rows[:top_k]:
        gap = best_score - score
        if gap > max_gap:
            continue
        net_gain = float(item.get("estimated_net", 0.0)) - best_net
        if net_gain < min_net_gain:
            continue
        finish_lag = int(item.get("finish_minutes", best_finish) or best_finish) - best_finish
        if finish_lag > max_finish_lag:
            continue
        nph_drop = best_nph - float(item.get("net_per_hour", 0.0))
        if nph_drop > max_nph_drop:
            continue
        bonus = min(bonus_cap, max(0.0, net_gain * bonus_weight))
        if bonus > gap:
            eligible[str(item.get("cargo_id", ""))] = bonus

    if eligible:
        _HIGH_NET_TIE_STATE[driver_id] = eligible
    else:
        _HIGH_NET_TIE_STATE.pop(driver_id, None)


def _high_net_tie_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    if not _env_bool("AGENT_AP_ENABLE_HIGH_NET_TIE_BREAK", False):
        return 0.0
    driver_id = _driver_id(status)
    return float(_HIGH_NET_TIE_STATE.get(driver_id, {}).get(str(feature.get("cargo_id", "")), 0.0))


def _d004_morning_first_order_action(
    strategy: NewReleaseAgenticPlannerAgent,
    status: dict[str, Any],
    viable: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if _accepted_orders_today(status) > 0:
        return None
    if not (_env_int("AGENT_AP_D004_MORNING_START_AFTER_MINUTE", 11 * 60 + 15) <= minute < 12 * 60):
        return None

    min_net = _env_float("AGENT_AP_D004_MORNING_MIN_NET", 260.0)
    min_nph = _env_float("AGENT_AP_D004_MORNING_MIN_NPH", 35.0)
    options = [
        item
        for item in viable
        if strategy.is_selectable(item, status)
        and float(item.get("estimated_net", 0.0)) >= min_net
        and float(item.get("net_per_hour", 0.0)) >= min_nph
    ]
    if not options:
        return None

    best = max(
        options,
        key=lambda item: (
            strategy.score(item, status),
            float(item.get("estimated_net", 0.0)),
            -float(item.get("total_exec_minutes", 0.0)),
        ),
    )
    return {"action": "take_order", "params": {"cargo_id": str(best["cargo_id"])}}


def _d004_lunch_first_order_tradeoff_action(
    strategy: NewReleaseAgenticPlannerAgent,
    status: dict[str, Any],
    viable: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if _accepted_orders_today(status) > 0:
        return None
    if not (11 * 60 <= minute < 12 * 60):
        return None

    # D004 pays 200 if the first accepted order starts after 12:00, but lunch
    # overlap only costs 100. This optional hook allows taking an exceptional
    # first order just before noon when the raw net is high enough.
    min_net = _env_float("AGENT_AP_D004_LUNCH_FIRST_MIN_NET", 760.0)
    min_nph = _env_float("AGENT_AP_D004_LUNCH_FIRST_MIN_NPH", 60.0)
    options = [
        item
        for item in viable
        if float(item.get("estimated_net", 0.0)) >= min_net
        and float(item.get("net_per_hour", 0.0)) >= min_nph
        and _interval_overlaps_daily_window(
            current,
            int(item.get("finish_minutes", current)),
            12,
            13,
        )
    ]
    if not options:
        return None
    best = max(
        options,
        key=lambda item: (
            float(item.get("estimated_net", 0.0)),
            strategy.score(item, status),
            float(item.get("net_per_hour", 0.0)),
        ),
    )
    return {"action": "take_order", "params": {"cargo_id": str(best["cargo_id"])}}


def _d009_evening_stay_home_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if not (20 * 60 <= minute < 23 * 60):
        return None
    if not _took_cargo(status, TEMP_CARGO_ID):
        return None

    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > 1.0:
        return None

    min_net = _env_float("AGENT_AP_D009_LEAVE_HOME_MIN_NET", 420.0)
    min_nph = _env_float("AGENT_AP_D009_LEAVE_HOME_MIN_NPH", 55.0)
    margin = _env_int("AGENT_AP_D009_HOME_MARGIN_MINUTES", 45)
    has_worth_leaving = any(
        float(item.get("estimated_net", 0.0)) >= min_net
        and float(item.get("net_per_hour", 0.0)) >= min_nph
        and _d009_can_finish_and_get_home(item, status, margin_minutes=margin)
        for item in viable
    )
    if has_worth_leaving:
        return None

    target = 1440 + 8 * 60
    return {"action": "wait", "params": {"duration_minutes": max(1, target - minute)}}


def _d009_strict_home_experiment_enabled() -> bool:
    return (
        _env_int("AGENT_AP_D009_HOME_MARGIN_MINUTES", 20) > 20
        or _env_float("AGENT_AP_D009_HOME_SLACK_WEIGHT", 0.0) != 0.0
        or _env_float("AGENT_AP_D009_EVENING_MIN_NET", 0.0) > 0.0
    )


def _d009_strict_home_wait_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if not (18 * 60 <= minute < 23 * 60):
        return None

    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > 1.0:
        return None

    margin = _env_int("AGENT_AP_D009_HOME_MARGIN_MINUTES", 45)
    min_net = _env_float("AGENT_AP_D009_EVENING_MIN_NET", 0.0)
    has_safe_order = any(
        float(item.get("estimated_net", 0.0)) >= min_net
        and _d009_can_finish_and_get_home(item, status, margin_minutes=margin)
        for item in viable
    )
    if has_safe_order:
        return None

    if minute >= 22 * 60:
        return {"action": "wait", "params": {"duration_minutes": max(1, 1440 + 8 * 60 - minute)}}
    return {"action": "wait", "params": {"duration_minutes": min(60, max(1, 23 * 60 - minute))}}


def _d009_wait_at_home_when_blocked(status: dict[str, Any]) -> dict[str, Any] | None:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if not (18 * 60 <= minute < 23 * 60):
        return None

    lat = float(status.get("current_lat", 0.0))
    lng = float(status.get("current_lng", 0.0))
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > 1.0:
        return None

    if minute >= 22 * 60:
        return {"action": "wait", "params": {"duration_minutes": max(1, 1440 + 8 * 60 - minute)}}
    return {"action": "wait", "params": {"duration_minutes": min(60, max(1, 23 * 60 - minute))}}


def _d006_forced_rest_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    rest_minutes = _env_int("AGENT_AP_D006_FORCED_REST_MINUTES", 5 * 60)
    if rest_minutes <= 0 or _longest_wait_today(status) >= rest_minutes:
        return None

    current = int(status.get("simulation_progress_minutes", 0))
    day_one_based = current // 1440 + 1
    days = _env_int_set("AGENT_AP_D006_FORCED_REST_DAYS", "")
    if days and day_one_based not in days:
        return None

    minute = current % 1440
    min_minute = _env_int("AGENT_AP_D006_FORCED_REST_MIN_MINUTE", 0)
    max_minute = _env_int("AGENT_AP_D006_FORCED_REST_MAX_MINUTE", 23 * 60)
    if minute < min_minute or minute > max_minute:
        return None
    if minute + rest_minutes > 1440:
        return None

    if _env_bool("AGENT_AP_D006_FORCED_REST_REQUIRE_NO_ORDER", False) and _accepted_orders_today(status) > 0:
        return None

    best_nph = max((float(item.get("net_per_hour", 0.0)) for item in viable), default=0.0)
    best_net = max((float(item.get("estimated_net", 0.0)) for item in viable), default=0.0)
    if best_nph > _env_float("AGENT_AP_D006_FORCED_REST_MAX_NPH", 999.0):
        return None
    if best_net > _env_float("AGENT_AP_D006_FORCED_REST_MAX_NET", 99999.0):
        return None

    min_orders_today = _env_int("AGENT_AP_D006_FORCED_REST_AFTER_ORDERS", -1)
    if min_orders_today >= 0 and _accepted_orders_today(status) < min_orders_today:
        return None

    return {"action": "wait", "params": {"duration_minutes": rest_minutes}}


def _shadow_price_rest_action(
    status: dict[str, Any],
    viable: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    driver_id = _driver_id(status)
    if driver_id not in _env_str_set("AGENT_AP_SHADOW_REST_DRIVERS", "D001,D006,D010"):
        return None

    rest_minutes = _required_rest_minutes(_preferences_text_from_status(status))
    if rest_minutes <= 0 or _longest_wait_today(status) >= rest_minutes:
        return None
    if _accepted_orders_today(status) > 0 and _env_bool("AGENT_AP_SHADOW_REST_REQUIRE_NO_ORDER", True):
        return None

    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    if driver_id == "D010" and MAR10_10 <= current < MAR13_22:
        return None
    min_minute = _env_int(f"AGENT_AP_{driver_id}_SHADOW_REST_MIN_MINUTE", _default_shadow_rest_window(driver_id)[0])
    max_minute = _env_int(f"AGENT_AP_{driver_id}_SHADOW_REST_MAX_MINUTE", _default_shadow_rest_window(driver_id)[1])
    if minute < min_minute or minute > max_minute:
        return None
    if minute + rest_minutes > 1440:
        return None

    if len(candidates) < _env_int(f"AGENT_AP_{driver_id}_SHADOW_REST_MIN_CANDIDATES", 0):
        return None

    best_nph = max((float(item.get("net_per_hour", 0.0)) for item in viable), default=0.0)
    best_net = max((float(item.get("estimated_net", 0.0)) for item in viable), default=0.0)
    if best_nph > _env_float(f"AGENT_AP_{driver_id}_SHADOW_REST_MAX_NPH", _default_shadow_rest_max_nph(driver_id)):
        return None
    if best_net > _env_float(f"AGENT_AP_{driver_id}_SHADOW_REST_MAX_NET", _default_shadow_rest_max_net(driver_id)):
        return None

    penalty_value = _env_float(f"AGENT_AP_{driver_id}_SHADOW_REST_PENALTY_VALUE", _default_rest_penalty_value(driver_id))
    opportunity = _shadow_rest_opportunity_cost(driver_id, best_nph, rest_minutes, minute)
    deadline_bonus = _rest_deadline_bonus(status, rest_minutes)
    if penalty_value + deadline_bonus < opportunity:
        return None

    return {"action": "wait", "params": {"duration_minutes": rest_minutes}}


def _shadow_rest_opportunity_cost(driver_id: str, best_nph: float, rest_minutes: int, minute: int) -> float:
    multiplier = _env_float(f"AGENT_AP_{driver_id}_SHADOW_REST_OPPORTUNITY_MULT", _default_shadow_rest_opportunity_mult(driver_id))
    opportunity = best_nph * (rest_minutes / 60.0) * multiplier
    if 0 <= minute < 6 * 60:
        opportunity *= _env_float(f"AGENT_AP_{driver_id}_SHADOW_REST_NIGHT_DISCOUNT", 0.65)
    return opportunity


def _rest_deadline_bonus(status: dict[str, Any], rest_minutes: int) -> float:
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    latest_start = max(0, 1440 - rest_minutes)
    if minute >= latest_start:
        return _env_float("AGENT_AP_SHADOW_REST_DEADLINE_BONUS", 300.0)
    if minute >= latest_start - 2 * 60:
        return _env_float("AGENT_AP_SHADOW_REST_NEAR_DEADLINE_BONUS", 120.0)
    return 0.0


def _preferences_text_from_status(status: dict[str, Any]) -> str:
    prefs = status.get("preferences") or []
    if isinstance(prefs, str):
        return prefs
    if not isinstance(prefs, list):
        return ""
    parts: list[str] = []
    for item in prefs:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(item.get("content") or item.get("text") or ""))
    return "\n".join(part for part in parts if part)


def _default_shadow_rest_window(driver_id: str) -> tuple[int, int]:
    if driver_id == "D001":
        return 6 * 60, 13 * 60
    if driver_id == "D006":
        return 0, 12 * 60
    if driver_id == "D010":
        return 6 * 60, 13 * 60
    return 0, 23 * 60


def _default_shadow_rest_max_nph(driver_id: str) -> float:
    return {
        "D001": 35.0,
        "D006": 35.0,
        "D010": 45.0,
    }.get(driver_id, 30.0)


def _default_shadow_rest_max_net(driver_id: str) -> float:
    return {
        "D001": 300.0,
        "D006": 520.0,
        "D010": 600.0,
    }.get(driver_id, 600.0)


def _default_shadow_rest_opportunity_mult(driver_id: str) -> float:
    return {
        "D001": 0.32,
        "D006": 0.85,
        "D010": 0.45,
    }.get(driver_id, 0.6)


def _default_rest_penalty_value(driver_id: str) -> float:
    return {
        "D001": 300.0,
        "D006": 200.0,
        "D010": 300.0,
    }.get(driver_id, 200.0)


def _best_visible_successor_value(feature: dict[str, Any], successors: list[dict[str, Any]]) -> float:
    finish = int(feature.get("finish_minutes", 0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    speed = float(feature.get("speed_km_per_hour", 60.0))
    cargo_id = str(feature.get("cargo_id", ""))
    best = 0.0
    for item in successors:
        if str(item.get("cargo_id", "")) == cargo_id:
            continue
        pickup_minutes = distance_to_minutes(
            haversine_km(end_lat, end_lng, float(item.get("start_lat", 0.0)), float(item.get("start_lng", 0.0))),
            speed,
        )
        arrival = finish + pickup_minutes
        load_end = item.get("load_end_minutes")
        if load_end is not None and arrival > int(load_end):
            continue
        remove_minutes = int(item.get("remove_minutes", finish))
        if remove_minutes < max(finish, arrival):
            continue
        load_start = item.get("load_start_minutes")
        wait_minutes = max(0, int(load_start) - arrival) if load_start is not None else 0
        net = max(0.0, float(item.get("estimated_net", 0.0)))
        nph = max(0.0, float(item.get("net_per_hour", 0.0)))
        value = 0.07 * net + 0.35 * nph
        value -= 0.18 * pickup_minutes
        value -= 2.5 * (wait_minutes / 60.0)
        best = max(best, min(160.0, value))
    return best


def _two_step_rollout_bonus(
    feature: dict[str, Any],
    status: dict[str, Any],
    successors: list[dict[str, Any]],
) -> float:
    driver_id = _driver_id(status)
    if driver_id not in _env_str_set("AGENT_AP_ROLLOUT_DRIVERS", "D001,D004,D006,D007,D009,D010"):
        return 0.0

    weight = _env_float(f"AGENT_AP_{driver_id}_ROLLOUT_WEIGHT", _default_rollout_weight(driver_id))
    if weight == 0.0:
        return 0.0

    successor = _rollout_successor_value(feature, status, successors)
    density = _rollout_successor_density(feature, status, successors)
    risk = _rollout_state_risk(feature, status)
    value = successor
    value += _env_float(f"AGENT_AP_{driver_id}_ROLLOUT_DENSITY_WEIGHT", _default_rollout_density_weight(driver_id)) * density
    value -= _env_float(f"AGENT_AP_{driver_id}_ROLLOUT_RISK_WEIGHT", _default_rollout_risk_weight(driver_id)) * risk
    cap = _env_float(f"AGENT_AP_{driver_id}_ROLLOUT_VALUE_CAP", _default_rollout_value_cap(driver_id))
    return weight * max(-cap, min(cap, value))


def _rollout_successor_value(
    feature: dict[str, Any],
    status: dict[str, Any],
    successors: list[dict[str, Any]],
) -> float:
    values = _reachable_successor_values(feature, status, successors)
    if not values:
        return 0.0
    top_n = max(1, _env_int("AGENT_AP_ROLLOUT_TOP_N", 2))
    top = sorted(values, reverse=True)[:top_n]
    best = top[0]
    if len(top) == 1:
        return best
    avg_rest = sum(top[1:]) / len(top[1:])
    return best + _env_float("AGENT_AP_ROLLOUT_AVG_NEXT_WEIGHT", 0.35) * avg_rest


def _rollout_successor_density(
    feature: dict[str, Any],
    status: dict[str, Any],
    successors: list[dict[str, Any]],
) -> float:
    min_value = _env_float("AGENT_AP_ROLLOUT_DENSITY_MIN_VALUE", 28.0)
    good = sum(1 for value in _reachable_successor_values(feature, status, successors) if value >= min_value)
    return min(8.0, float(good)) * 8.0


def _reachable_successor_values(
    feature: dict[str, Any],
    status: dict[str, Any],
    successors: list[dict[str, Any]],
) -> list[float]:
    finish = int(feature.get("finish_minutes", 0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    speed = float(feature.get("speed_km_per_hour", 60.0))
    cost_per_km = get_cost_per_km(status)
    current_cargo_id = str(feature.get("cargo_id", ""))
    max_pickup = _env_int("AGENT_AP_ROLLOUT_SUCCESSOR_MAX_PICKUP_MINUTES", 180)
    max_wait = _env_int("AGENT_AP_ROLLOUT_SUCCESSOR_MAX_WAIT_MINUTES", 180)
    net_weight = _env_float("AGENT_AP_ROLLOUT_NEXT_NET_WEIGHT", 0.055)
    nph_weight = _env_float("AGENT_AP_ROLLOUT_NEXT_NPH_WEIGHT", 0.42)
    pickup_cost = _env_float("AGENT_AP_ROLLOUT_NEXT_PICKUP_MINUTE_COST", 0.16)
    wait_cost = _env_float("AGENT_AP_ROLLOUT_NEXT_WAIT_HOUR_COST", 2.5)

    values: list[float] = []
    for item in successors:
        if str(item.get("cargo_id", "")) == current_cargo_id:
            continue
        pickup_km = haversine_km(
            end_lat,
            end_lng,
            float(item.get("start_lat", 0.0)),
            float(item.get("start_lng", 0.0)),
        )
        pickup_minutes = distance_to_minutes(pickup_km, speed)
        if pickup_minutes > max_pickup:
            continue
        arrival = finish + pickup_minutes
        load_end = item.get("load_end_minutes")
        if load_end is not None and arrival > int(load_end):
            continue
        remove_minutes = int(item.get("remove_minutes", finish))
        if remove_minutes < arrival:
            continue
        load_start = item.get("load_start_minutes")
        wait_minutes = max(0, int(load_start) - arrival) if load_start is not None else 0
        if wait_minutes > max_wait:
            continue

        future_net = float(item.get("price_yuan", 0.0)) - (pickup_km + float(item.get("haul_km", 0.0))) * cost_per_km
        if future_net <= 0:
            continue
        total_minutes = max(1, pickup_minutes + wait_minutes + int(item.get("cost_time_minutes", 0)))
        future_nph = future_net / max(total_minutes / 60.0, 1e-9)
        value = net_weight * future_net + nph_weight * future_nph
        value -= pickup_cost * pickup_minutes
        value -= wait_cost * (wait_minutes / 60.0)
        value += 10.0 * float(item.get("destination_hotspot_score", 0.0))
        values.append(value)
    return values


def _rollout_state_risk(feature: dict[str, Any], status: dict[str, Any]) -> float:
    driver_id = _driver_id(status)
    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    minute = current % 1440
    finish_minute = finish % 1440
    risk = 0.0

    rest_minutes = _required_rest_minutes(_preferences_text_from_status(status))
    if rest_minutes > 0 and _longest_wait_today(status) < rest_minutes:
        latest_start = max(0, 1440 - rest_minutes)
        if minute <= latest_start < finish_minute or finish_minute > latest_start:
            risk += _env_float(f"AGENT_AP_{driver_id}_ROLLOUT_REST_RISK", _default_rollout_rest_risk(driver_id))

    if driver_id == "D004":
        orders_today = _accepted_orders_today(status)
        estimated_net = float(feature.get("estimated_net", 0.0))
        nph = float(feature.get("net_per_hour", 0.0))
        if orders_today >= 2:
            risk += max(0.0, _env_float("AGENT_AP_D004_ROLLOUT_SLOT_MIN_NET", 680.0) - estimated_net) * 0.15
            risk += max(0.0, _env_float("AGENT_AP_D004_ROLLOUT_SLOT_MIN_NPH", 55.0) - nph) * 1.2
        if orders_today == 0 and minute >= 11 * 60 and finish_minute >= 12 * 60:
            risk += 80.0

    if driver_id == "D009":
        if not _d009_can_finish_and_get_home(feature, status, margin_minutes=_env_int("AGENT_AP_D009_ROLLOUT_HOME_MARGIN", 25)):
            risk += 900.0

    if driver_id == "D010" and _interval_overlaps_daily_window(current, finish, 21, 6):
        risk += 120.0

    return risk


def _default_rollout_weight(driver_id: str) -> float:
    return {
        "D001": 0.04,
        "D004": 0.03,
        "D006": 0.025,
        "D007": 0.04,
        "D009": 0.03,
        "D010": 0.035,
    }.get(driver_id, 0.0)


def _default_rollout_density_weight(driver_id: str) -> float:
    return {
        "D001": 0.45,
        "D004": 0.25,
        "D006": 0.20,
        "D007": 0.30,
        "D009": 0.35,
        "D010": 0.35,
    }.get(driver_id, 0.0)


def _default_rollout_risk_weight(driver_id: str) -> float:
    return {
        "D001": 0.20,
        "D004": 0.45,
        "D006": 0.25,
        "D007": 0.15,
        "D009": 0.50,
        "D010": 0.35,
    }.get(driver_id, 0.25)


def _default_rollout_value_cap(driver_id: str) -> float:
    return {
        "D001": 180.0,
        "D004": 160.0,
        "D006": 150.0,
        "D007": 160.0,
        "D009": 150.0,
        "D010": 170.0,
    }.get(driver_id, 150.0)


def _default_rollout_rest_risk(driver_id: str) -> float:
    return {
        "D001": 180.0,
        "D006": 120.0,
        "D010": 150.0,
    }.get(driver_id, 100.0)


def _default_chain_weight(driver_id: str) -> float:
    # Chain value is powerful and can easily reroute a profitable driver.
    # Keep it opt-in per driver; experiment presets set explicit weights.
    return 0.0


def _d003_deadhead_cap_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    deadhead = _deadhead_km(status)
    cap_trigger_km = _env_float("AGENT_AP_D003_DEADHEAD_CAP_TRIGGER_KM", 300.0)
    if deadhead < cap_trigger_km:
        return 0.0

    estimated_net = float(feature.get("estimated_net", 0.0))
    pickup_km = float(feature.get("pickup_km", 0.0))
    extra = _env_float("AGENT_AP_D003_AFTER_CAP_NET_WEIGHT", 0.0) * estimated_net
    extra -= _env_float("AGENT_AP_D003_AFTER_CAP_PICKUP_COST", 0.0) * pickup_km
    return extra


def _d004_quota_value_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    orders_today = _accepted_orders_today(status)
    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    estimated_net = float(feature.get("estimated_net", 0.0))
    total_hours = max(1.0 / 60.0, float(feature.get("total_exec_minutes", 1.0)) / 60.0)

    bonus = 0.0
    if orders_today == 0 and minute < 12 * 60:
        bonus += _env_float("AGENT_AP_D004_FIRST_ORDER_BEFORE_NOON_BONUS", 0.0)
    if orders_today >= 2:
        bonus += _env_float("AGENT_AP_D004_LATE_QUOTA_NET_WEIGHT", 0.0) * estimated_net
        bonus -= _env_float("AGENT_AP_D004_LOW_VALUE_SLOT_COST", 0.0) / max(total_hours, 0.25)
    return bonus


def _d009_home_slack_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    weight = _env_float("AGENT_AP_D009_HOME_SLACK_WEIGHT", 0.0)
    if weight == 0.0:
        return 0.0

    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    finish_minute = finish % 1440
    if finish_minute < 16 * 60 and current % 1440 < 16 * 60:
        return 0.0
    if _interval_overlaps_daily_window(current, finish, 23, 8):
        return -1000.0 * weight

    dist_home = haversine_km(
        float(feature.get("end_lat", 0.0)),
        float(feature.get("end_lng", 0.0)),
        D009_HOME[0],
        D009_HOME[1],
    )
    minutes_home = distance_to_minutes(dist_home, float(feature.get("speed_km_per_hour", 60.0)))
    slack = 23 * 60 - (finish_minute + minutes_home)
    if slack < 0:
        return weight * (-900.0 - abs(slack) * 4.0)
    return weight * min(140.0, max(0.0, 110.0 - dist_home * 2.2) + min(30.0, slack / 4.0))


def _d009_can_finish_and_get_home(
    feature: dict[str, Any],
    status: dict[str, Any],
    *,
    margin_minutes: int,
) -> bool:
    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    if _interval_overlaps_daily_window(current, finish, 23, 8):
        return False
    minutes_home = distance_to_minutes(
        haversine_km(
            float(feature.get("end_lat", 0.0)),
            float(feature.get("end_lng", 0.0)),
            D009_HOME[0],
            D009_HOME[1],
        ),
        float(feature.get("speed_km_per_hour", 60.0)),
    )
    return finish % 1440 + minutes_home + margin_minutes <= 23 * 60


def _d010_night_rest_preservation_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    if not _env_bool("AGENT_AP_ENABLE_D010_NIGHT_REST_PRESERVE", False):
        return 0.0

    current = int(status.get("simulation_progress_minutes", 0))
    minute = current % 1440
    start_minute = _env_int("AGENT_AP_D010_NIGHT_REST_START_MINUTE", 20 * 60)
    end_minute = _env_int("AGENT_AP_D010_NIGHT_REST_END_MINUTE", 4 * 60)
    if not _minute_in_window(minute, start_minute, end_minute):
        return 0.0

    rest_minutes = _required_rest_minutes(_preferences_text_from_status(status)) or 3 * 60
    if _longest_wait_today(status) >= rest_minutes:
        return 0.0

    finish = int(feature.get("finish_minutes", current))
    speed = float(feature.get("speed_km_per_hour", 60.0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    target_minutes = min(
        distance_to_minutes(haversine_km(end_lat, end_lng, D010_TARGET[0], D010_TARGET[1]), speed),
        distance_to_minutes(haversine_km(end_lat, end_lng, D010_HOME[0], D010_HOME[1]), speed),
    )
    deadline_hour = _env_int("AGENT_AP_D010_NIGHT_REST_DEADLINE_HOUR", 8)
    deadline = (current // 1440) * 1440 + deadline_hour * 60
    if deadline <= current:
        deadline += 1440
    can_recover = finish + target_minutes + rest_minutes <= deadline

    haul = float(feature.get("haul_km", 0.0))
    pickup = float(feature.get("pickup_km", 0.0))
    total_minutes = float(feature.get("total_exec_minutes", 0.0))
    max_haul = _env_float("AGENT_AP_D010_NIGHT_REST_MAX_HAUL_KM", 90.0)
    max_pickup = _env_float("AGENT_AP_D010_NIGHT_REST_MAX_PICKUP_KM", 30.0)
    max_total = _env_float("AGENT_AP_D010_NIGHT_REST_MAX_TOTAL_MINUTES", 420.0)

    if can_recover and haul <= max_haul and pickup <= max_pickup and total_minutes <= max_total:
        return _env_float("AGENT_AP_D010_NIGHT_REST_BONUS", 35.0)
    if not can_recover:
        return -_env_float("AGENT_AP_D010_NIGHT_REST_RISK_COST", 35.0)
    return 0.0


def _d010_can_recover_after_order(
    feature: dict[str, Any],
    status: dict[str, Any],
    *,
    rest_minutes: int,
    deadline_hour: int,
    slack_minutes: int,
) -> bool:
    current = int(status.get("simulation_progress_minutes", 0))
    finish = int(feature.get("finish_minutes", current))
    speed = float(feature.get("speed_km_per_hour", 60.0))
    end_lat = float(feature.get("end_lat", 0.0))
    end_lng = float(feature.get("end_lng", 0.0))
    return_minutes = min(
        distance_to_minutes(haversine_km(end_lat, end_lng, D010_TARGET[0], D010_TARGET[1]), speed),
        distance_to_minutes(haversine_km(end_lat, end_lng, D010_HOME[0], D010_HOME[1]), speed),
    )
    deadline = (current // 1440) * 1440 + deadline_hour * 60
    if deadline <= current:
        deadline += 1440
    return finish + return_minutes + rest_minutes + slack_minutes <= deadline


def _minute_in_window(minute: int, start_minute: int, end_minute: int) -> bool:
    if end_minute < start_minute:
        return minute >= start_minute or minute < end_minute
    return start_minute <= minute < end_minute


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


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
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.add(int(item))
        except ValueError:
            continue
    return out


def _env_str_set(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {item.strip().upper() for item in raw.split(",") if item.strip()}
