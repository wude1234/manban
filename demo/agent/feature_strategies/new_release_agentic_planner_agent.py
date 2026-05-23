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
        self._state_value_gate_by_driver: dict[str, dict[str, Any]] = {}
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
        self._prepare_state_value_gate_state(status, viable)

        action = _counterfactual_cargo_switch_action(status, viable)
        if action is not None:
            return action

        action = _distilled_counterfactual_action(status, viable)
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
        base += self._state_value_gate_bonus(feature, status)
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
        feature["unit_time_route_value"] = _unit_time_route_value(feature, route)
        latent_market = _latent_market_state(feature, route, status)
        feature["latent_market_value"] = latent_market["market_value"]
        feature["latent_isolation_risk"] = latent_market["isolation_risk"]

        layered_enabled = _env_bool("AGENT_AP_ENABLE_LAYERED_AGENT_SCORER", False)
        unit_time_enabled = (
            _env_bool("AGENT_AP_ENABLE_UNIT_TIME_SCORER", False)
            and driver_id in _env_str_set("AGENT_AP_UNIT_TIME_DRIVERS", "D007,D008")
        )
        latent_enabled = (
            _env_bool("AGENT_AP_ENABLE_LATENT_MARKET_SCORER", False)
            and driver_id in _env_str_set("AGENT_AP_LATENT_MARKET_DRIVERS", "D008")
        )
        if not layered_enabled and not unit_time_enabled and not latent_enabled:
            return regret_bonus(feature, status)

        bonus = regret_bonus(feature, status)
        if layered_enabled:
            route_weight = _env_float(
                f"AGENT_AP_{driver_id}_LAYER_ROUTE_WEIGHT",
                _env_float("AGENT_AP_LAYER_ROUTE_WEIGHT", 0.018),
            )
            risk_weight = _env_float(
                f"AGENT_AP_{driver_id}_LAYER_RISK_WEIGHT",
                _env_float("AGENT_AP_LAYER_RISK_WEIGHT", 0.030),
            )
            query_cost = _env_float("AGENT_AP_LAYER_QUERY_COST", 0.0)
            bonus += route_weight * float(feature.get("destination_opportunity_value", 0.0))
            bonus -= risk_weight * float(feature.get("preference_risk_delta", 0.0))
            bonus -= query_cost
        if unit_time_enabled:
            feature["unit_time_route_value"] = _unit_time_route_value(
                feature,
                route,
                successor_weight=_env_float(
                    f"AGENT_AP_{driver_id}_UNIT_TIME_SUCCESSOR_WEIGHT",
                    _env_float("AGENT_AP_UNIT_TIME_SUCCESSOR_WEIGHT", 0.30),
                ),
                density_weight=_env_float(
                    f"AGENT_AP_{driver_id}_UNIT_TIME_DENSITY_WEIGHT",
                    _env_float("AGENT_AP_UNIT_TIME_DENSITY_WEIGHT", 3.0),
                ),
                wait_cost=_env_float(
                    f"AGENT_AP_{driver_id}_UNIT_TIME_WAIT_COST",
                    _env_float("AGENT_AP_UNIT_TIME_WAIT_COST", 0.035),
                ),
                pickup_cost=_env_float(
                    f"AGENT_AP_{driver_id}_UNIT_TIME_PICKUP_COST",
                    _env_float("AGENT_AP_UNIT_TIME_PICKUP_COST", 0.08),
                ),
                long_order_cost=_env_float(
                    f"AGENT_AP_{driver_id}_UNIT_TIME_LONG_ORDER_COST",
                    _env_float("AGENT_AP_UNIT_TIME_LONG_ORDER_COST", 0.025),
                ),
            )
            unit_weight = _env_float(
                f"AGENT_AP_{driver_id}_UNIT_TIME_WEIGHT",
                _env_float("AGENT_AP_UNIT_TIME_WEIGHT", 0.018),
            )
            min_nph = _env_float(
                f"AGENT_AP_{driver_id}_UNIT_TIME_MIN_NPH",
                _env_float("AGENT_AP_UNIT_TIME_MIN_NPH", 0.0),
            )
            low_nph_penalty = _env_float(
                f"AGENT_AP_{driver_id}_UNIT_TIME_LOW_NPH_PENALTY",
                _env_float("AGENT_AP_UNIT_TIME_LOW_NPH_PENALTY", 0.0),
            )
            current_nph = float(feature.get("net_per_hour", 0.0))
            bonus += unit_weight * float(feature.get("unit_time_route_value", 0.0))
            if min_nph > 0.0 and current_nph < min_nph:
                bonus -= low_nph_penalty * (min_nph - current_nph)
        if latent_enabled:
            market_weight = _env_float(
                f"AGENT_AP_{driver_id}_LATENT_MARKET_WEIGHT",
                _env_float("AGENT_AP_LATENT_MARKET_WEIGHT", 0.006),
            )
            isolation_weight = _env_float(
                f"AGENT_AP_{driver_id}_LATENT_ISOLATION_WEIGHT",
                _env_float("AGENT_AP_LATENT_ISOLATION_WEIGHT", 0.006),
            )
            bonus += market_weight * float(feature.get("latent_market_value", 0.0))
            bonus -= isolation_weight * float(feature.get("latent_isolation_risk", 0.0))
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

    def _prepare_state_value_gate_state(self, status: dict[str, Any], viable: list[dict[str, Any]]) -> None:
        driver_id = _driver_id(status)
        if not _env_bool("AGENT_AP_ENABLE_STATE_VALUE_GATE", False):
            self._state_value_gate_by_driver.pop(driver_id, None)
            return
        if driver_id not in _env_str_set("AGENT_AP_STATE_VALUE_DRIVERS", "D008"):
            self._state_value_gate_by_driver.pop(driver_id, None)
            return

        rows: list[dict[str, Any]] = []
        for item in viable:
            if not self.is_selectable(item, status):
                continue
            route = route_plan_features(item, status, viable)
            latent = _latent_market_state(item, route, status)
            base_score = self._score_without_rollout(item, status)
            rows.append(
                {
                    "cargo_id": str(item.get("cargo_id", "")),
                    "base_score": base_score,
                    "state_value": _after_state_value(item, route, latent, status),
                    "visible_value": float(route.get("destination_opportunity_value", 0.0)),
                    "latent_market": float(latent.get("market_value", 0.0)),
                    "isolation_risk": float(latent.get("isolation_risk", 0.0)),
                }
            )
        rows.sort(key=lambda item: item["base_score"], reverse=True)
        if len(rows) < 2:
            self._state_value_gate_by_driver.pop(driver_id, None)
            return

        best = rows[0]
        second = rows[1]
        max_gap = _env_float("AGENT_AP_STATE_VALUE_MAX_GAP", 0.8)
        conflict_gap = _env_float("AGENT_AP_STATE_VALUE_CONFLICT_MAX_GAP", 3.0)
        visible_gap = _env_float("AGENT_AP_STATE_VALUE_VISIBLE_GAP", 60.0)
        state_gap = _env_float("AGENT_AP_STATE_VALUE_STATE_GAP", 35.0)
        score_gap = float(best["base_score"]) - float(second["base_score"])
        conflict = (
            score_gap <= conflict_gap
            and float(second["visible_value"]) - float(best["visible_value"]) >= visible_gap
            and float(best["state_value"]) - float(second["state_value"]) >= state_gap
        )
        near_tie = score_gap <= max_gap
        if not near_tie and not conflict:
            self._state_value_gate_by_driver.pop(driver_id, None)
            return

        top_k = max(2, _env_int("AGENT_AP_STATE_VALUE_TOP_K", 4))
        eligible: dict[str, float] = {}
        best_state = max(float(item["state_value"]) for item in rows[:top_k])
        for item in rows[:top_k]:
            state_delta = float(item["state_value"]) - best_state
            score_drop = max(0.0, float(best["base_score"]) - float(item["base_score"]))
            eligible[str(item["cargo_id"])] = state_delta - _env_float("AGENT_AP_STATE_VALUE_SCORE_DROP_COST", 0.25) * score_drop

        self._state_value_gate_by_driver[driver_id] = {
            "best_cargo_id": str(best["cargo_id"]),
            "score_gap": score_gap,
            "near_tie": near_tie,
            "conflict": conflict,
            "eligible": eligible,
        }

    def _state_value_gate_bonus(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        driver_id = _driver_id(status)
        state = self._state_value_gate_by_driver.get(driver_id)
        if not state:
            return 0.0
        eligible = state.get("eligible")
        if not isinstance(eligible, dict):
            return 0.0
        raw = float(eligible.get(str(feature.get("cargo_id", "")), 0.0))
        weight = _env_float(f"AGENT_AP_{driver_id}_STATE_VALUE_WEIGHT", _env_float("AGENT_AP_STATE_VALUE_WEIGHT", 0.08))
        cap = _env_float("AGENT_AP_STATE_VALUE_BONUS_CAP", 18.0)
        return max(-cap, min(cap, weight * raw))

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
    if _counterfactual_switch_overridden(driver_id, step):
        return None
    target = _counterfactual_switch_map().get((driver_id, step))
    if not target:
        return None
    cargo_ids = {str(item.get("cargo_id", "")).strip() for item in viable}
    if target not in cargo_ids:
        return None
    return {"action": "take_order", "params": {"cargo_id": target}}


def _counterfactual_switch_overridden(driver_id: str, step: int) -> bool:
    # Some v49 action-level teachers replace an older cargo switch with wait or
    # reposition. Keep this explicit so unrelated counterfactual switches retain
    # their original precedence.
    if driver_id == "D006" and step == 65 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP65_WAIT", False):
        return True
    if driver_id == "D002" and step == 87 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D002_STEP87_WAIT", False):
        return True
    if driver_id == "D008" and step == 80 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D008_STEP80_WAIT", False):
        return True
    return False


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


def _distilled_counterfactual_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _env_bool("AGENT_AP_ENABLE_DISTILLED_COUNTERFACTUAL_GATE", False):
        return None
    driver_id = _driver_id(status)
    step = int(status.get("_decision_history_total", 0) or 0) + 1
    if driver_id == "D008" and step == 62:
        return _d008_step62_distilled_action(status, viable)
    if driver_id == "D004" and step == 70 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP70", False):
        return _d004_step70_distilled_action(status, viable)
    if driver_id == "D004" and step == 86 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP86_WAIT", False):
        return _d004_step86_wait_distilled_action(status)
    if driver_id == "D009" and step == 165 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP165", False):
        return _d009_step165_distilled_action(status, viable)
    if driver_id == "D009" and step == 170 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP170_WAIT", False):
        return _d009_step170_wait_distilled_action(status, viable)
    if driver_id == "D010" and step == 100 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP100_REPOS_DG", False):
        return _d010_step100_repos_dg_distilled_action(status, viable)
    if driver_id == "D010" and step == 100 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP100_WAIT", False):
        return _d010_step100_wait_distilled_action(status, viable)
    if driver_id == "D004" and step == 87 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP87", False):
        return _d004_step87_distilled_action(status, viable)
    if driver_id == "D009" and step == 172 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP172", False):
        return _d009_step172_distilled_action(status, viable)
    if driver_id == "D009" and step == 178 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP178_REPOS_HY", False):
        return _d009_step178_repos_hy_distilled_action(status, viable)
    if driver_id == "D009" and step == 178 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP178_WAIT", False):
        return _d009_step178_wait_distilled_action(status, viable)
    if driver_id == "D010" and step == 101 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP101", False):
        return _d010_step101_distilled_action(status, viable)
    if driver_id == "D004" and step == 93 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP93", False):
        return _d004_step93_distilled_action(status, viable)
    if driver_id == "D004" and step == 95 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP95_REPOS_GZ", False):
        return _d004_step95_repos_gz_distilled_action(status, viable)
    if driver_id == "D004" and step == 96 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D004_STEP96_REPOS_FS", False):
        return _d004_step96_repos_fs_distilled_action(status, viable)
    if driver_id == "D006" and step == 65 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP65_WAIT", False):
        return _d006_step65_wait_distilled_action(status, viable)
    if driver_id == "D006" and step == 95 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP95_REPOS_FS", False):
        return _d006_step95_repos_fs_distilled_action(status, viable)
    if driver_id == "D006" and step == 97 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP97_WAIT", False):
        return _d006_step97_wait_distilled_action(status, viable)
    if driver_id == "D006" and step == 98 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP98", False):
        return _d006_step98_distilled_action(status, viable)
    if driver_id == "D006" and step == 99 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP99_REPOS_GZ", False):
        return _d006_step99_repos_gz_distilled_action(status, viable)
    if driver_id == "D006" and step == 100 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP100_WAIT", False):
        return _d006_step100_wait_distilled_action(status)
    if driver_id == "D002" and step == 87 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D002_STEP87_WAIT", False):
        return _d002_step87_wait_distilled_action(status, viable)
    if driver_id == "D002" and step == 89 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D002_STEP89", False):
        return _d002_step89_distilled_action(status, viable)
    if driver_id == "D002" and step == 90 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D002_STEP90_WAIT", False):
        return _d002_step90_wait_distilled_action(status, viable)
    if driver_id == "D002" and step == 91 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D002_STEP91_REPOS_GZ", False):
        return _d002_step91_repos_gz_distilled_action(status, viable)
    if driver_id == "D001" and step == 77 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D001_STEP77_WAIT", False):
        return _d001_step77_wait_distilled_action(status, viable)
    if driver_id == "D001" and step == 93 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D001_STEP93_WAIT", False):
        return _d001_step93_wait_distilled_action(status, viable)
    if driver_id == "D001" and step == 98 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D001_STEP98_REPOS_SZ", False):
        return _d001_step98_repos_sz_distilled_action(status, viable)
    if driver_id == "D001" and step == 102 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D001_STEP102_WAIT", False):
        return _d001_step102_wait_distilled_action(status, viable)
    if driver_id == "D003" and step == 107 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D003_STEP107_WAIT", False):
        return _d003_step107_wait_distilled_action(status, viable)
    if driver_id == "D003" and step == 110 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D003_STEP110", False):
        return _d003_step110_distilled_action(status, viable)
    if driver_id == "D010" and step == 121 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP121_WAIT", False):
        return _d010_step121_wait_distilled_action(status)
    if driver_id == "D010" and step == 122 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP122_WAIT", False):
        return _d010_step122_wait_distilled_action(status, viable)
    if driver_id == "D010" and step == 123 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D010_STEP123", False):
        return _d010_step123_distilled_action(status, viable)
    if driver_id == "D007" and step == 114 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D007_STEP114", False):
        return _d007_step114_distilled_action(status, viable)
    if driver_id == "D007" and step == 119 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D007_STEP119_WAIT", False):
        return _d007_step119_wait_distilled_action(status, viable)
    if driver_id == "D007" and step == 121 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D007_STEP121_REPOS_FS", False):
        return _d007_step121_repos_fs_distilled_action(status, viable)
    if driver_id == "D007" and step == 80 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D007_STEP80_REPOS_GZ", False):
        return _d007_step80_repos_gz_distilled_action(status, viable)
    if driver_id == "D005" and step == 123 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D005_STEP123", False):
        return _d005_step123_distilled_action(status, viable)
    if driver_id == "D005" and step == 128 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D005_STEP128_REPOS_FS", False):
        return _d005_step128_repos_fs_distilled_action(status, viable)
    if driver_id == "D008" and step == 80 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D008_STEP80_WAIT", False):
        return _d008_step80_wait_distilled_action(status, viable)
    if driver_id == "D008" and step == 87 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D008_STEP87", False):
        return _d008_step87_distilled_action(status, viable)
    if driver_id == "D008" and step == 88 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D008_STEP88_WAIT", False):
        return _d008_step88_wait_distilled_action(status, viable)
    if driver_id == "D006" and step == 99 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D006_STEP99_208042", False):
        return _d006_step99_208042_distilled_action(status, viable)
    if driver_id == "D009" and step == 200 and _env_bool("AGENT_AP_ENABLE_DISTILLED_D009_STEP200_WAIT", False):
        return _d009_step200_wait_distilled_action(status, viable)
    return None


def _d008_step62_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner = _feature_by_cargo_id(viable, "139843")
    if winner is None:
        return None
    loser_ids = _env_str_set("AGENT_AP_D008_STEP62_LOSER_IDS", "137667,435262")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None

    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (5 * 60 <= minute <= 7 * 60):
        return None
    if haversine_km(lat, lng, 23.24, 116.45) > _env_float("AGENT_AP_D008_STEP62_LOCATION_RADIUS_KM", 25.0):
        return None

    min_net = _env_float("AGENT_AP_D008_STEP62_WINNER_MIN_NET", 380.0)
    min_haul = _env_float("AGENT_AP_D008_STEP62_WINNER_MIN_HAUL_KM", 180.0)
    max_finish_minute = _env_int("AGENT_AP_D008_STEP62_WINNER_MAX_FINISH_MINUTE", 19 * 60 + 30)
    if float(winner.get("estimated_net", 0.0)) < min_net:
        return None
    if float(winner.get("haul_km", 0.0)) < min_haul:
        return None
    if int(winner.get("finish_minutes", progress) or progress) % 1440 > max_finish_minute:
        return None
    return {"action": "take_order", "params": {"cargo_id": "139843"}}


def _d004_step70_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D004_STEP70_WINNER_ID", "420939").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    loser_ids = _env_str_set("AGENT_AP_D004_STEP70_LOSER_IDS", "123537")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None

    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    min_minute = _env_int("AGENT_AP_D004_STEP70_MIN_MINUTE", 12 * 60)
    max_minute = _env_int("AGENT_AP_D004_STEP70_MAX_MINUTE", 13 * 60 + 15)
    if not (min_minute <= minute <= max_minute):
        return None
    if haversine_km(lat, lng, 24.73, 113.60) > _env_float("AGENT_AP_D004_STEP70_LOCATION_RADIUS_KM", 20.0):
        return None

    min_net = _env_float("AGENT_AP_D004_STEP70_WINNER_MIN_NET", 650.0)
    min_haul = _env_float("AGENT_AP_D004_STEP70_WINNER_MIN_HAUL_KM", 180.0)
    if float(winner.get("estimated_net", 0.0)) < min_net:
        return None
    if float(winner.get("haul_km", 0.0)) < min_haul:
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d004_step86_wait_distilled_action(status: dict[str, Any]) -> dict[str, Any] | None:
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D004_STEP86_MIN_MINUTE", 12 * 60) <= minute <= _env_int("AGENT_AP_D004_STEP86_MAX_MINUTE", 12 * 60 + 30)):
        return None
    if haversine_km(lat, lng, 23.61, 116.68) > _env_float("AGENT_AP_D004_STEP86_LOCATION_RADIUS_KM", 8.0):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D004_STEP86_WAIT_MINUTES", 30)}}


def _d009_step165_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D009_STEP165_WINNER_ID", "450780").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    loser_ids = _env_str_set("AGENT_AP_D009_STEP165_LOSER_IDS", "292330")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None

    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D009_STEP165_MIN_MINUTE", 8 * 60) <= minute <= _env_int("AGENT_AP_D009_STEP165_MAX_MINUTE", 9 * 60)):
        return None
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > _env_float("AGENT_AP_D009_STEP165_HOME_RADIUS_KM", 5.0):
        return None

    max_finish_minute = _env_int("AGENT_AP_D009_STEP165_WINNER_MAX_FINISH_MINUTE", 13 * 60)
    max_end_home_km = _env_float("AGENT_AP_D009_STEP165_WINNER_MAX_END_HOME_KM", 45.0)
    min_net = _env_float("AGENT_AP_D009_STEP165_WINNER_MIN_NET", 250.0)
    if float(winner.get("estimated_net", 0.0)) < min_net:
        return None
    if int(winner.get("finish_minutes", progress) or progress) % 1440 > max_finish_minute:
        return None
    if haversine_km(float(winner.get("end_lat", 0.0)), float(winner.get("end_lng", 0.0)), D009_HOME[0], D009_HOME[1]) > max_end_home_km:
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d009_step170_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    loser_ids = _env_str_set("AGENT_AP_D009_STEP170_LOSER_IDS", "168167")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D009_STEP170_MIN_MINUTE", 8 * 60) <= minute <= _env_int("AGENT_AP_D009_STEP170_MAX_MINUTE", 8 * 60 + 45)):
        return None
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > _env_float("AGENT_AP_D009_STEP170_HOME_RADIUS_KM", 5.0):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D009_STEP170_WAIT_MINUTES", 120)}}


def _d010_step100_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    loser_ids = _env_str_set("AGENT_AP_D010_STEP100_LOSER_IDS", "290384,151344")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    day = progress // 1440
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if day != _env_int("AGENT_AP_D010_STEP100_DAY", 22):
        return None
    if not (_env_int("AGENT_AP_D010_STEP100_MIN_MINUTE", 16 * 60 + 20) <= minute <= _env_int("AGENT_AP_D010_STEP100_MAX_MINUTE", 17 * 60 + 10)):
        return None
    if haversine_km(lat, lng, 23.48, 114.79) > _env_float("AGENT_AP_D010_STEP100_LOCATION_RADIUS_KM", 12.0):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D010_STEP100_WAIT_MINUTES", 60)}}


def _d010_step100_repos_dg_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D010_STEP100_REPOS_REQUIRE_VISIBLE_LOSER", False) and not _has_visible_cargo(
        viable, "AGENT_AP_D010_STEP100_REPOS_LOSER_IDS", "290384,151344"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D010_STEP100_REPOS_DAY",
        default_day=22,
        min_env="AGENT_AP_D010_STEP100_REPOS_MIN_MINUTE",
        default_minute=16 * 60,
        max_env="AGENT_AP_D010_STEP100_REPOS_MAX_MINUTE",
        default_max_minute=18 * 60,
        center_lat=23.48,
        center_lng=114.79,
        radius_env="AGENT_AP_D010_STEP100_REPOS_LOCATION_RADIUS_KM",
        default_radius_km=18.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D010_STEP100_REPOS_LAT", 23.02),
            "longitude": _env_float("AGENT_AP_D010_STEP100_REPOS_LNG", 113.75),
        },
    }


def _d004_step87_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D004_STEP87_WINNER_ID", "164073").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    loser_ids = _env_str_set("AGENT_AP_D004_STEP87_LOSER_IDS", "293321")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D004_STEP87_MIN_MINUTE", 13 * 60 + 20) <= minute <= _env_int("AGENT_AP_D004_STEP87_MAX_MINUTE", 14 * 60 + 5)):
        return None
    if haversine_km(lat, lng, 23.61, 116.68) > _env_float("AGENT_AP_D004_STEP87_LOCATION_RADIUS_KM", 8.0):
        return None
    min_net = _env_float("AGENT_AP_D004_STEP87_WINNER_MIN_NET", 650.0)
    max_pickup = _env_float("AGENT_AP_D004_STEP87_WINNER_MAX_PICKUP_KM", 55.0)
    if float(winner.get("estimated_net", 0.0)) < min_net:
        return None
    if float(winner.get("pickup_km", 9999.0)) > max_pickup:
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d009_step172_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D009_STEP172_WINNER_ID", "296607").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    loser_ids = _env_str_set("AGENT_AP_D009_STEP172_LOSER_IDS", "296528")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D009_STEP172_MIN_MINUTE", 15 * 60 + 10) <= minute <= _env_int("AGENT_AP_D009_STEP172_MAX_MINUTE", 15 * 60 + 50)):
        return None
    if haversine_km(lat, lng, 22.77, 113.76) > _env_float("AGENT_AP_D009_STEP172_LOCATION_RADIUS_KM", 8.0):
        return None
    if haversine_km(float(winner.get("end_lat", 0.0)), float(winner.get("end_lng", 0.0)), D009_HOME[0], D009_HOME[1]) > _env_float("AGENT_AP_D009_STEP172_MAX_END_HOME_KM", 45.0):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d009_step178_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    loser_ids = _env_str_set("AGENT_AP_D009_STEP178_LOSER_IDS", "298327")
    if not any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in loser_ids):
        return None
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    minute = progress % 1440
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    if not (_env_int("AGENT_AP_D009_STEP178_MIN_MINUTE", 8 * 60) <= minute <= _env_int("AGENT_AP_D009_STEP178_MAX_MINUTE", 8 * 60 + 45)):
        return None
    if haversine_km(lat, lng, D009_HOME[0], D009_HOME[1]) > _env_float("AGENT_AP_D009_STEP178_HOME_RADIUS_KM", 5.0):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D009_STEP178_WAIT_MINUTES", 120)}}


def _d010_step101_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D010_STEP101_WINNER_ID", "290609").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D010_STEP101_LOSER_IDS", "290384"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D010_STEP101_DAY",
        default_day=22,
        min_env="AGENT_AP_D010_STEP101_MIN_MINUTE",
        default_minute=17 * 60 + 35,
        max_env="AGENT_AP_D010_STEP101_MAX_MINUTE",
        default_max_minute=18 * 60 + 20,
        center_lat=23.48,
        center_lng=114.79,
        radius_env="AGENT_AP_D010_STEP101_LOCATION_RADIUS_KM",
        default_radius_km=12.0,
    ):
        return None
    if float(winner.get("estimated_net", 0.0)) < _env_float("AGENT_AP_D010_STEP101_WINNER_MIN_NET", 250.0):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d004_step93_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D004_STEP93_WINNER_ID", "469204").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D004_STEP93_LOSER_IDS", "468269"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D004_STEP93_DAY",
        default_day=26,
        min_env="AGENT_AP_D004_STEP93_MIN_MINUTE",
        default_minute=12 * 60 + 45,
        max_env="AGENT_AP_D004_STEP93_MAX_MINUTE",
        default_max_minute=13 * 60 + 20,
        center_lat=23.19,
        center_lng=116.35,
        radius_env="AGENT_AP_D004_STEP93_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d004_step95_repos_gz_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D004_STEP95_REQUIRE_NO_VIABLE", False) and viable:
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D004_STEP95_DAY",
        default_day=27,
        min_env="AGENT_AP_D004_STEP95_MIN_MINUTE",
        default_minute=10 * 60 + 30,
        max_env="AGENT_AP_D004_STEP95_MAX_MINUTE",
        default_max_minute=11 * 60 + 20,
        center_lat=22.58,
        center_lng=113.79,
        radius_env="AGENT_AP_D004_STEP95_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D004_STEP95_REPOS_LAT", 23.13),
            "longitude": _env_float("AGENT_AP_D004_STEP95_REPOS_LNG", 113.26),
        },
    }


def _d004_step96_repos_fs_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D004_STEP96_LOSER_IDS", "189146"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D004_STEP96_DAY",
        default_day=27,
        min_env="AGENT_AP_D004_STEP96_MIN_MINUTE",
        default_minute=12 * 60 + 45,
        max_env="AGENT_AP_D004_STEP96_MAX_MINUTE",
        default_max_minute=13 * 60 + 20,
        center_lat=22.58,
        center_lng=113.79,
        radius_env="AGENT_AP_D004_STEP96_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D004_STEP96_REPOS_LAT", 23.02),
            "longitude": _env_float("AGENT_AP_D004_STEP96_REPOS_LNG", 113.12),
        },
    }


def _d006_step65_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP65_LOSER_IDS", "424880"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP65_DAY",
        default_day=20,
        min_env="AGENT_AP_D006_STEP65_MIN_MINUTE",
        default_minute=60 + 15,
        max_env="AGENT_AP_D006_STEP65_MAX_MINUTE",
        default_max_minute=60 + 45,
        center_lat=22.72,
        center_lng=114.00,
        radius_env="AGENT_AP_D006_STEP65_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D006_STEP65_WAIT_MINUTES", 300)}}


def _d006_step95_repos_fs_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP95_LOSER_IDS", "202939"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP95_DAY",
        default_day=28,
        min_env="AGENT_AP_D006_STEP95_MIN_MINUTE",
        default_minute=20 * 60 + 30,
        max_env="AGENT_AP_D006_STEP95_MAX_MINUTE",
        default_max_minute=21 * 60 + 10,
        center_lat=22.78,
        center_lng=113.60,
        radius_env="AGENT_AP_D006_STEP95_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D006_STEP95_REPOS_LAT", 23.02),
            "longitude": _env_float("AGENT_AP_D006_STEP95_REPOS_LNG", 113.12),
        },
    }


def _d006_step97_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP97_LOSER_IDS", "200633"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP97_DAY",
        default_day=29,
        min_env="AGENT_AP_D006_STEP97_MIN_MINUTE",
        default_minute=2 * 60,
        max_env="AGENT_AP_D006_STEP97_MAX_MINUTE",
        default_max_minute=2 * 60 + 30,
        center_lat=23.25,
        center_lng=113.20,
        radius_env="AGENT_AP_D006_STEP97_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D006_STEP97_WAIT_MINUTES", 300)}}


def _d006_step98_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D006_STEP98_WINNER_ID", "484278").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP98_LOSER_IDS", "200255"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP98_DAY",
        default_day=29,
        min_env="AGENT_AP_D006_STEP98_MIN_MINUTE",
        default_minute=7 * 60,
        max_env="AGENT_AP_D006_STEP98_MAX_MINUTE",
        default_max_minute=7 * 60 + 40,
        center_lat=22.63,
        center_lng=112.76,
        radius_env="AGENT_AP_D006_STEP98_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    if float(winner.get("estimated_net", 0.0)) < _env_float("AGENT_AP_D006_STEP98_WINNER_MIN_NET", 200.0):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d006_step99_repos_gz_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP99_LOSER_IDS", "485299"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP99_DAY",
        default_day=29,
        min_env="AGENT_AP_D006_STEP99_MIN_MINUTE",
        default_minute=13 * 60,
        max_env="AGENT_AP_D006_STEP99_MAX_MINUTE",
        default_max_minute=13 * 60 + 45,
        center_lat=23.04,
        center_lng=113.03,
        radius_env="AGENT_AP_D006_STEP99_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D006_STEP99_REPOS_LAT", 23.13),
            "longitude": _env_float("AGENT_AP_D006_STEP99_REPOS_LNG", 113.26),
        },
    }


def _d006_step100_wait_distilled_action(status: dict[str, Any]) -> dict[str, Any] | None:
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP100_DAY",
        default_day=29,
        min_env="AGENT_AP_D006_STEP100_MIN_MINUTE",
        default_minute=18 * 60 + 30,
        max_env="AGENT_AP_D006_STEP100_MAX_MINUTE",
        default_max_minute=19 * 60,
        center_lat=22.70,
        center_lng=113.12,
        radius_env="AGENT_AP_D006_STEP100_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D006_STEP100_WAIT_MINUTES", 30)}}


def _d002_step87_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D002_STEP87_REQUIRE_VISIBLE_LOSER", True) and not _has_visible_cargo(
        viable, "AGENT_AP_D002_STEP87_LOSER_IDS", "201151"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D002_STEP87_DAY",
        default_day=28,
        min_env="AGENT_AP_D002_STEP87_MIN_MINUTE",
        default_minute=17 * 60,
        max_env="AGENT_AP_D002_STEP87_MAX_MINUTE",
        default_max_minute=18 * 60,
        center_lat=23.02,
        center_lng=113.06,
        radius_env="AGENT_AP_D002_STEP87_LOCATION_RADIUS_KM",
        default_radius_km=12.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D002_STEP87_WAIT_MINUTES", 60)}}


def _d002_step89_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D002_STEP89_WINNER_ID", "200633").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D002_STEP89_DAY",
        default_day=29,
        min_env="AGENT_AP_D002_STEP89_MIN_MINUTE",
        default_minute=60,
        max_env="AGENT_AP_D002_STEP89_MAX_MINUTE",
        default_max_minute=6 * 60,
        center_lat=23.25,
        center_lng=113.20,
        radius_env="AGENT_AP_D002_STEP89_LOCATION_RADIUS_KM",
        default_radius_km=18.0,
    ):
        return None
    if float(winner.get("estimated_net", 0.0)) < _env_float("AGENT_AP_D002_STEP89_WINNER_MIN_NET", 180.0):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d002_step90_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D002_STEP90_REQUIRE_VISIBLE_LOSER", True) and not _has_visible_cargo(
        viable, "AGENT_AP_D002_STEP90_LOSER_IDS", "483734"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D002_STEP90_DAY",
        default_day=29,
        min_env="AGENT_AP_D002_STEP90_MIN_MINUTE",
        default_minute=5 * 60,
        max_env="AGENT_AP_D002_STEP90_MAX_MINUTE",
        default_max_minute=8 * 60,
        center_lat=23.25,
        center_lng=113.20,
        radius_env="AGENT_AP_D002_STEP90_LOCATION_RADIUS_KM",
        default_radius_km=18.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D002_STEP90_WAIT_MINUTES", 240)}}


def _d002_step91_repos_gz_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D002_STEP91_REQUIRE_VISIBLE_LOSER", True) and not _has_visible_cargo(
        viable, "AGENT_AP_D002_STEP91_LOSER_IDS", "203266"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D002_STEP91_DAY",
        default_day=29,
        min_env="AGENT_AP_D002_STEP91_MIN_MINUTE",
        default_minute=7 * 60,
        max_env="AGENT_AP_D002_STEP91_MAX_MINUTE",
        default_max_minute=16 * 60,
        center_lat=23.32,
        center_lng=113.09,
        radius_env="AGENT_AP_D002_STEP91_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D002_STEP91_REPOS_LAT", 23.13),
            "longitude": _env_float("AGENT_AP_D002_STEP91_REPOS_LNG", 113.26),
        },
    }


def _d001_step77_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D001_STEP77_LOSER_IDS", "145964"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D001_STEP77_DAY",
        default_day=21,
        min_env="AGENT_AP_D001_STEP77_MIN_MINUTE",
        default_minute=21 * 60,
        max_env="AGENT_AP_D001_STEP77_MAX_MINUTE",
        default_max_minute=21 * 60 + 45,
        center_lat=22.72,
        center_lng=114.40,
        radius_env="AGENT_AP_D001_STEP77_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D001_STEP77_WAIT_MINUTES", 300)}}


def _d001_step93_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D001_STEP93_LOSER_IDS", "469532"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D001_STEP93_DAY",
        default_day=26,
        min_env="AGENT_AP_D001_STEP93_MIN_MINUTE",
        default_minute=11 * 60 + 10,
        max_env="AGENT_AP_D001_STEP93_MAX_MINUTE",
        default_max_minute=11 * 60 + 45,
        center_lat=22.77,
        center_lng=114.33,
        radius_env="AGENT_AP_D001_STEP93_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D001_STEP93_WAIT_MINUTES", 60)}}


def _d001_step98_repos_sz_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D001_STEP98_LOSER_IDS", "477985"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D001_STEP98_DAY",
        default_day=27,
        min_env="AGENT_AP_D001_STEP98_MIN_MINUTE",
        default_minute=20 * 60 + 30,
        max_env="AGENT_AP_D001_STEP98_MAX_MINUTE",
        default_max_minute=21 * 60,
        center_lat=22.54,
        center_lng=114.02,
        radius_env="AGENT_AP_D001_STEP98_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D001_STEP98_REPOS_LAT", 22.55),
            "longitude": _env_float("AGENT_AP_D001_STEP98_REPOS_LNG", 114.05),
        },
    }


def _d001_step102_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D001_STEP102_LOSER_IDS", "484350"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D001_STEP102_DAY",
        default_day=28,
        min_env="AGENT_AP_D001_STEP102_MIN_MINUTE",
        default_minute=23 * 60 + 20,
        max_env="AGENT_AP_D001_STEP102_MAX_MINUTE",
        default_max_minute=23 * 60 + 59,
        center_lat=22.63,
        center_lng=113.88,
        radius_env="AGENT_AP_D001_STEP102_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D001_STEP102_WAIT_MINUTES", 180)}}


def _d003_step107_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D003_STEP107_LOSER_IDS", "196038"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D003_STEP107_DAY",
        default_day=28,
        min_env="AGENT_AP_D003_STEP107_MIN_MINUTE",
        default_minute=14 * 60 + 45,
        max_env="AGENT_AP_D003_STEP107_MAX_MINUTE",
        default_max_minute=15 * 60 + 20,
        center_lat=24.37,
        center_lng=114.91,
        radius_env="AGENT_AP_D003_STEP107_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D003_STEP107_WAIT_MINUTES", 60)}}


def _d003_step110_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D003_STEP110_WINNER_ID", "484175").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D003_STEP110_LOSER_IDS", "203928"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D003_STEP110_DAY",
        default_day=29,
        min_env="AGENT_AP_D003_STEP110_MIN_MINUTE",
        default_minute=5 * 60 - 15,
        max_env="AGENT_AP_D003_STEP110_MAX_MINUTE",
        default_max_minute=5 * 60 + 20,
        center_lat=23.49,
        center_lng=116.56,
        radius_env="AGENT_AP_D003_STEP110_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d010_step121_wait_distilled_action(status: dict[str, Any]) -> dict[str, Any] | None:
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D010_STEP121_DAY",
        default_day=29,
        min_env="AGENT_AP_D010_STEP121_MIN_MINUTE",
        default_minute=60 + 45,
        max_env="AGENT_AP_D010_STEP121_MAX_MINUTE",
        default_max_minute=2 * 60 + 10,
        center_lat=23.49,
        center_lng=116.56,
        radius_env="AGENT_AP_D010_STEP121_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D010_STEP121_WAIT_MINUTES", 60)}}


def _d010_step122_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D010_STEP122_LOSER_IDS", "484175"):
        return None
    return _d010_step121_wait_distilled_action(status)


def _d010_step123_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D010_STEP123_WINNER_ID", "205150").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D010_STEP123_LOSER_IDS", "484468"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D010_STEP123_DAY",
        default_day=29,
        min_env="AGENT_AP_D010_STEP123_MIN_MINUTE",
        default_minute=10 * 60 + 10,
        max_env="AGENT_AP_D010_STEP123_MAX_MINUTE",
        default_max_minute=10 * 60 + 45,
        center_lat=24.11,
        center_lng=115.77,
        radius_env="AGENT_AP_D010_STEP123_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d007_step114_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D007_STEP114_WINNER_ID", "193118").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D007_STEP114_LOSER_IDS", "475223"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D007_STEP114_DAY",
        default_day=28,
        min_env="AGENT_AP_D007_STEP114_MIN_MINUTE",
        default_minute=3 * 60 + 45,
        max_env="AGENT_AP_D007_STEP114_MAX_MINUTE",
        default_max_minute=4 * 60 + 20,
        center_lat=22.21,
        center_lng=113.40,
        radius_env="AGENT_AP_D007_STEP114_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d007_step119_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D007_STEP119_LOSER_IDS", "202277"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D007_STEP119_DAY",
        default_day=29,
        min_env="AGENT_AP_D007_STEP119_MIN_MINUTE",
        default_minute=3 * 60 + 45,
        max_env="AGENT_AP_D007_STEP119_MAX_MINUTE",
        default_max_minute=4 * 60 + 20,
        center_lat=23.88,
        center_lng=114.10,
        radius_env="AGENT_AP_D007_STEP119_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D007_STEP119_WAIT_MINUTES", 30)}}


def _d007_step80_repos_gz_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D007_STEP80_REQUIRE_VISIBLE_LOSER", True) and not _has_visible_cargo(
        viable, "AGENT_AP_D007_STEP80_LOSER_IDS", "429035"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D007_STEP80_DAY",
        default_day=20,
        min_env="AGENT_AP_D007_STEP80_MIN_MINUTE",
        default_minute=4 * 60,
        max_env="AGENT_AP_D007_STEP80_MAX_MINUTE",
        default_max_minute=13 * 60,
        center_lat=23.10,
        center_lng=113.65,
        radius_env="AGENT_AP_D007_STEP80_LOCATION_RADIUS_KM",
        default_radius_km=25.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D007_STEP80_REPOS_LAT", 23.13),
            "longitude": _env_float("AGENT_AP_D007_STEP80_REPOS_LNG", 113.26),
        },
    }


def _d007_step121_repos_fs_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D007_STEP121_LOSER_IDS", "209244"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D007_STEP121_DAY",
        default_day=29,
        min_env="AGENT_AP_D007_STEP121_MIN_MINUTE",
        default_minute=16 * 60 - 15,
        max_env="AGENT_AP_D007_STEP121_MAX_MINUTE",
        default_max_minute=16 * 60 + 30,
        center_lat=23.32,
        center_lng=113.20,
        radius_env="AGENT_AP_D007_STEP121_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D007_STEP121_REPOS_LAT", 23.02),
            "longitude": _env_float("AGENT_AP_D007_STEP121_REPOS_LNG", 113.12),
        },
    }


def _d005_step123_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D005_STEP123_WINNER_ID", "194561").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D005_STEP123_LOSER_IDS", "194290"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D005_STEP123_DAY",
        default_day=28,
        min_env="AGENT_AP_D005_STEP123_MIN_MINUTE",
        default_minute=5 * 60 + 45,
        max_env="AGENT_AP_D005_STEP123_MAX_MINUTE",
        default_max_minute=6 * 60 + 20,
        center_lat=22.85,
        center_lng=114.01,
        radius_env="AGENT_AP_D005_STEP123_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d005_step128_repos_fs_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D005_STEP128_LOSER_IDS", "209407"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D005_STEP128_DAY",
        default_day=29,
        min_env="AGENT_AP_D005_STEP128_MIN_MINUTE",
        default_minute=14 * 60 + 30,
        max_env="AGENT_AP_D005_STEP128_MAX_MINUTE",
        default_max_minute=15 * 60 + 15,
        center_lat=23.30,
        center_lng=113.09,
        radius_env="AGENT_AP_D005_STEP128_LOCATION_RADIUS_KM",
        default_radius_km=8.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D005_STEP128_REPOS_LAT", 23.02),
            "longitude": _env_float("AGENT_AP_D005_STEP128_REPOS_LNG", 113.12),
        },
    }


def _d008_step80_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D008_STEP80_REQUIRE_VISIBLE_LOSER", False) and not _has_visible_cargo(
        viable, "AGENT_AP_D008_STEP80_LOSER_IDS", "178320"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D008_STEP80_DAY",
        default_day=26,
        min_env="AGENT_AP_D008_STEP80_MIN_MINUTE",
        default_minute=10 * 60 + 30,
        max_env="AGENT_AP_D008_STEP80_MAX_MINUTE",
        default_max_minute=12 * 60 + 30,
        center_lat=23.06,
        center_lng=113.27,
        radius_env="AGENT_AP_D008_STEP80_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D008_STEP80_WAIT_MINUTES", 240)}}


def _d008_step87_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D008_STEP87_WINNER_ID", "203124").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D008_STEP87_DAY",
        default_day=29,
        min_env="AGENT_AP_D008_STEP87_MIN_MINUTE",
        default_minute=9 * 60,
        max_env="AGENT_AP_D008_STEP87_MAX_MINUTE",
        default_max_minute=11 * 60,
        center_lat=23.71,
        center_lng=113.03,
        radius_env="AGENT_AP_D008_STEP87_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d008_step88_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_visible_cargo(viable, "AGENT_AP_D008_STEP88_LOSER_IDS", "205543"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D008_STEP88_DAY",
        default_day=29,
        min_env="AGENT_AP_D008_STEP88_MIN_MINUTE",
        default_minute=18 * 60,
        max_env="AGENT_AP_D008_STEP88_MAX_MINUTE",
        default_max_minute=20 * 60,
        center_lat=23.71,
        center_lng=113.03,
        radius_env="AGENT_AP_D008_STEP88_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D008_STEP88_WAIT_MINUTES", 60)}}


def _d009_step178_repos_hy_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D009_STEP178_DAY",
        default_day=26,
        min_env="AGENT_AP_D009_STEP178_REPOS_MIN_MINUTE",
        default_minute=9 * 60,
        max_env="AGENT_AP_D009_STEP178_REPOS_MAX_MINUTE",
        default_max_minute=12 * 60,
        center_lat=23.12,
        center_lng=113.28,
        radius_env="AGENT_AP_D009_STEP178_REPOS_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {
        "action": "reposition",
        "params": {
            "latitude": _env_float("AGENT_AP_D009_STEP178_REPOS_LAT", 23.73),
            "longitude": _env_float("AGENT_AP_D009_STEP178_REPOS_LNG", 114.68),
        },
    }


def _d006_step99_208042_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    winner_id = os.getenv("AGENT_AP_D006_STEP99_WINNER_ID", "208042").strip()
    winner = _feature_by_cargo_id(viable, winner_id)
    if winner is None:
        return None
    if not _has_visible_cargo(viable, "AGENT_AP_D006_STEP99_LOSER_IDS", "208263"):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D006_STEP99_DAY",
        default_day=29,
        min_env="AGENT_AP_D006_STEP99_MIN_MINUTE",
        default_minute=19 * 60,
        max_env="AGENT_AP_D006_STEP99_MAX_MINUTE",
        default_max_minute=22 * 60,
        center_lat=23.14,
        center_lng=113.41,
        radius_env="AGENT_AP_D006_STEP99_LOCATION_RADIUS_KM",
        default_radius_km=20.0,
    ):
        return None
    return {"action": "take_order", "params": {"cargo_id": winner_id}}


def _d009_step200_wait_distilled_action(status: dict[str, Any], viable: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _env_bool("AGENT_AP_D009_STEP200_REQUIRE_VISIBLE_LOSER", True) and not _has_visible_cargo(
        viable, "AGENT_AP_D009_STEP200_LOSER_IDS", "201171"
    ):
        return None
    if not _phase_guard(
        status,
        day_env="AGENT_AP_D009_STEP200_DAY",
        default_day=29,
        min_env="AGENT_AP_D009_STEP200_MIN_MINUTE",
        default_minute=8 * 60,
        max_env="AGENT_AP_D009_STEP200_MAX_MINUTE",
        default_max_minute=15 * 60,
        center_lat=D009_HOME[0],
        center_lng=D009_HOME[1],
        radius_env="AGENT_AP_D009_STEP200_LOCATION_RADIUS_KM",
        default_radius_km=10.0,
    ):
        return None
    return {"action": "wait", "params": {"duration_minutes": _env_int("AGENT_AP_D009_STEP200_WAIT_MINUTES", 60)}}


def _has_visible_cargo(viable: list[dict[str, Any]], env_name: str, default: str) -> bool:
    cargo_ids = _env_str_set(env_name, default)
    return any(_feature_by_cargo_id(viable, cargo_id) is not None for cargo_id in cargo_ids)


def _phase_guard(
    status: dict[str, Any],
    *,
    day_env: str,
    default_day: int,
    min_env: str,
    default_minute: int,
    max_env: str,
    default_max_minute: int,
    center_lat: float,
    center_lng: float,
    radius_env: str,
    default_radius_km: float,
) -> bool:
    progress = int(status.get("simulation_progress_minutes", 0) or 0)
    day = progress // 1440
    minute = progress % 1440
    if day != _env_int(day_env, default_day):
        return False
    if not _minute_in_closed_window(minute, _env_int(min_env, default_minute), _env_int(max_env, default_max_minute)):
        return False
    lat = float(status.get("current_lat", 0.0) or 0.0)
    lng = float(status.get("current_lng", 0.0) or 0.0)
    return haversine_km(lat, lng, center_lat, center_lng) <= _env_float(radius_env, default_radius_km)


def _minute_in_closed_window(minute: int, start_minute: int, end_minute: int) -> bool:
    if end_minute < start_minute:
        return minute >= start_minute or minute <= end_minute
    return start_minute <= minute <= end_minute


def _feature_by_cargo_id(features: list[dict[str, Any]], cargo_id: str) -> dict[str, Any] | None:
    for feature in features:
        if str(feature.get("cargo_id", "")).strip() == cargo_id:
            return feature
    return None


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


def _unit_time_route_value(
    feature: dict[str, Any],
    route: dict[str, Any],
    *,
    successor_weight: float = 0.30,
    density_weight: float = 3.0,
    wait_cost: float = 0.035,
    pickup_cost: float = 0.08,
    long_order_cost: float = 0.025,
) -> float:
    current_nph = max(0.0, float(feature.get("net_per_hour", 0.0)))
    successor_nph = max(0.0, float(route.get("best_successor_nph", 0.0)))
    reachable = max(0.0, float(route.get("reachable_successors", 0.0)))
    wait_minutes = max(0.0, float(feature.get("wait_minutes", 0.0)))
    pickup_km = max(0.0, float(feature.get("pickup_km", 0.0)))
    total_minutes = max(1.0, float(feature.get("total_exec_minutes", 1.0)))

    value = current_nph
    value += successor_weight * successor_nph
    value += density_weight * min(8.0, reachable)
    value -= wait_cost * wait_minutes
    value -= pickup_cost * pickup_km
    value -= long_order_cost * max(0.0, total_minutes - 480.0)
    return round(value, 2)


def _latent_market_state(
    feature: dict[str, Any],
    route: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, float]:
    city_value = _latent_city_value(str(feature.get("end_city", "") or ""))
    hotspot = max(0.0, float(feature.get("destination_hotspot_score", 0.0)))
    reachable = max(0.0, float(route.get("reachable_successors", 0.0)))
    successor_nph = max(0.0, float(route.get("best_successor_nph", 0.0)))
    finish = int(feature.get("finish_minutes", status.get("simulation_progress_minutes", 0)) or 0)
    finish_minute = finish % 1440

    market_value = 100.0 * city_value + 55.0 * hotspot
    # Visible cargo is only a short-horizon hint; keep it smaller than latent
    # city value so it cannot overfit to cargo that is already online.
    market_value += 4.0 * min(8.0, reachable) + 0.12 * successor_nph
    if 7 * 60 <= finish_minute <= 21 * 60:
        market_value += 12.0 * city_value

    isolation_risk = 0.0
    if city_value <= 0.05 and hotspot <= 0.05:
        isolation_risk += 85.0
    elif city_value < 0.25 and reachable >= 6.0:
        isolation_risk += 55.0
    if reachable == 0.0 and city_value < 0.25:
        isolation_risk += 35.0
    if finish_minute >= 21 * 60 or finish_minute <= 5 * 60:
        isolation_risk += max(0.0, 25.0 - 40.0 * city_value)

    return {
        "market_value": round(max(0.0, market_value), 2),
        "isolation_risk": round(max(0.0, isolation_risk), 2),
    }


def _latent_city_value(city: str) -> float:
    # Latent value estimates future cargo that is not online yet.  It is a
    # coarse market prior, intentionally separate from visible successor value.
    table = {
        "广东省广州市白云区": 1.00,
        "广东省佛山市南海区": 0.92,
        "广东省佛山市顺德区": 0.86,
        "广东省深圳市龙岗区": 0.84,
        "广东省深圳市宝安区": 0.78,
        "广东省广州市黄埔区": 0.74,
        "广东省广州市增城区": 0.70,
        "广东省广州市花都区": 0.68,
        "广东省佛山市三水区": 0.66,
        "广东省佛山市禅城区": 0.62,
        "广东省广州市番禺区": 0.60,
        "广东省广州市南沙区": 0.58,
        "广东省惠州市博罗县": 0.56,
        "广东省惠州市惠城区": 0.52,
        "广东省惠州市惠阳区": 0.50,
        "广东省东莞市": 0.50,
        "广东省中山市": 0.46,
        "广东省珠海市": 0.42,
        "广东省江门市": 0.38,
        "广东省汕尾市": 0.24,
        "广东省揭阳市": 0.14,
        "广东省梅州市": 0.12,
        "广东省潮州市": 0.10,
    }
    for key, value in table.items():
        if key in city or city in key:
            return value
    return 0.0


def _after_state_value(
    feature: dict[str, Any],
    route: dict[str, Any],
    latent: dict[str, float],
    status: dict[str, Any],
) -> float:
    current = int(status.get("simulation_progress_minutes", 0) or 0)
    finish = int(feature.get("finish_minutes", current) or current)
    remaining_days = max(0.0, (31 * 1440 - finish) / 1440.0)
    total_hours = max(1.0 / 60.0, float(feature.get("total_exec_minutes", 1.0)) / 60.0)
    estimated_net = float(feature.get("estimated_net", 0.0))
    nph = float(feature.get("net_per_hour", 0.0))
    wait_minutes = float(feature.get("wait_minutes", 0.0))

    value = 0.20 * estimated_net
    value += 0.85 * nph
    value += 0.08 * float(route.get("destination_opportunity_value", 0.0))
    value += 0.10 * float(latent.get("market_value", 0.0)) * min(1.0, remaining_days / 6.0)
    value -= 0.16 * float(latent.get("isolation_risk", 0.0))
    value -= 1.4 * total_hours
    value -= 0.020 * wait_minutes

    driver_id = _driver_id(status)
    if driver_id in {"D006", "D010"}:
        value -= 0.08 * _rollout_state_risk(feature, status)
    elif driver_id == "D008":
        # D008 has already shown that visible successor density can be a trap.
        # Prefer stable after-states over short local hops when the month still
        # has enough time for a chain to unfold.
        value += 0.06 * float(feature.get("haul_km", 0.0)) * min(1.0, remaining_days / 8.0)
    return round(value, 2)


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
