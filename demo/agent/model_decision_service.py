"""Decision service used by the embedded evaluator.

The official template calls an LLM on every step.  Our experiments use a
deterministic strategy engine by default and reserve LLM calls for optional
reranking windows.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agent.calculator_skill import build_rerank_calculation
from agent.feature_strategies import available_strategy_names, load_strategy
from agent.feature_strategies.common import FeatureDecisionEngine
from agent.submission_defaults import SUBMISSION_PROFILE, apply_submission_defaults
from simkit.ports import SimulationApiPort


apply_submission_defaults()


class ModelDecisionService:
    """Route decisions to the selected rule/agent strategy."""

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.decision_service")
        strategy_name = os.getenv("AGENT_STRATEGY", "new_release_agentic_planner_agent").strip()
        self._strategy_name = strategy_name

        if strategy_name.lower() == "llm_rerank_agent":
            base_name = os.getenv("AGENT_LLM_RERANK_BASE_STRATEGY", "new_release_agentic_planner_agent").strip()
            self._strategy = load_strategy(base_name)
            self._engine = FeatureDecisionEngine(api, self._strategy)
            self._llm_rerank_enabled = True
            self._logger.info(
                "submission profile=%s strategy=llm_rerank_agent base_strategy=%s",
                SUBMISSION_PROFILE,
                base_name,
            )
            return

        try:
            self._strategy = load_strategy(strategy_name)
        except ValueError as exc:
            known = ", ".join(available_strategy_names())
            raise ValueError(f"{exc}; AGENT_STRATEGY may also be llm_rerank_agent; known={known}") from exc
        self._engine = FeatureDecisionEngine(api, self._strategy)
        self._llm_rerank_enabled = False
        self._logger.info(
            "submission profile=%s strategy=%s",
            SUBMISSION_PROFILE,
            getattr(self._strategy, "name", strategy_name),
        )

    def decide(self, driver_id: str) -> dict[str, Any]:
        action, diagnostics = self._engine.decide(driver_id)
        rule_action = action
        if self._llm_rerank_enabled:
            action = self._maybe_llm_rerank(driver_id, action, diagnostics)

        self._write_decision_trace(driver_id, rule_action, action, diagnostics)
        self._logger.info(
            "decision output driver_id=%s strategy=%s action=%s params=%s candidates=%s viable=%s",
            driver_id,
            self._strategy_name,
            action.get("action"),
            action.get("params"),
            diagnostics.get("candidate_count"),
            diagnostics.get("viable_count"),
        )
        return _normalize_action(action)

    def _write_decision_trace(
        self,
        driver_id: str,
        rule_action: dict[str, Any],
        final_action: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> None:
        trace_path = os.getenv("AGENT_DECISION_TRACE_PATH", "").strip()
        trace_dir = os.getenv("AGENT_DECISION_TRACE_DIR", "").strip()
        if not trace_path and trace_dir:
            trace_path = str(Path(trace_dir) / f"decision_trace_{driver_id}.jsonl")
        if not trace_path:
            return

        status = diagnostics.get("status")
        if not isinstance(status, dict):
            status = {}
        selectable = diagnostics.get("selectable_features")
        if not isinstance(selectable, list):
            selectable = []
        compact_candidates = [_compact_feature(item) for item in sorted(
            [item for item in selectable if isinstance(item, dict)],
            key=lambda item: float(item.get("score", 0.0)),
            reverse=True,
        )[: _env_int("AGENT_DECISION_TRACE_TOP_K", 8)]]
        row = {
            "driver_id": driver_id,
            "strategy": diagnostics.get("strategy"),
            "step_index": int(status.get("_decision_history_total", 0) or 0),
            "time_min": status.get("simulation_progress_minutes"),
            "day": (int(status.get("simulation_progress_minutes", 0) or 0) // 1440) + 1,
            "minute_of_day": int(status.get("simulation_progress_minutes", 0) or 0) % 1440,
            "location": {
                "lat": status.get("current_lat"),
                "lng": status.get("current_lng"),
            },
            "accepted_order_count": status.get("accepted_order_count"),
            "today_accepted_order_count": status.get("today_accepted_order_count"),
            "net_income": status.get("net_income"),
            "candidate_count": diagnostics.get("candidate_count"),
            "viable_count": diagnostics.get("viable_count"),
            "selectable_count": diagnostics.get("selectable_count"),
            "rule_action": _compact_action(rule_action),
            "final_action": _compact_action(final_action),
            "chosen": _compact_feature(diagnostics.get("chosen")) if isinstance(diagnostics.get("chosen"), dict) else None,
            "chosen_without_pre_action": _compact_feature(diagnostics.get("chosen_without_pre_action"))
            if isinstance(diagnostics.get("chosen_without_pre_action"), dict)
            else None,
            "planned_action": diagnostics.get("planned_action"),
            "fallback": diagnostics.get("fallback"),
            "top_candidates": compact_candidates,
        }
        try:
            path = Path(trace_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            self._logger.warning("decision_trace write failed driver_id=%s reason=%s", driver_id, exc)

    def _maybe_llm_rerank(
        self,
        driver_id: str,
        rule_action: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if not _driver_enabled(driver_id, os.getenv("AGENT_LLM_RERANK_DRIVERS", "D004,D009,D010")):
            return rule_action
        if rule_action.get("action") != "take_order":
            return rule_action

        selectable = diagnostics.get("selectable_features")
        if not isinstance(selectable, list) or len(selectable) < 2:
            return rule_action

        top_k = max(2, _env_int("AGENT_LLM_RERANK_TOP_K", 5))
        candidates = sorted(selectable, key=lambda item: float(item.get("score", 0.0)), reverse=True)[:top_k]
        rule_cargo_id = str(rule_action.get("params", {}).get("cargo_id", ""))
        rule_feature = _find_feature(candidates, rule_cargo_id) or diagnostics.get("chosen")
        if not isinstance(rule_feature, dict):
            return rule_action

        if not _should_rerank_window(driver_id, candidates, rule_feature, diagnostics):
            return rule_action

        try:
            picked = self._call_llm_reranker(driver_id, candidates, rule_feature, diagnostics)
        except Exception as exc:  # LLM is optional; failed rerank must not kill evaluation.
            self._logger.warning("llm_rerank fallback driver_id=%s reason=%s", driver_id, exc)
            return rule_action

        selected = _find_feature(candidates, picked)
        if selected is None:
            self._logger.info("llm_rerank ignored unknown cargo_id=%s driver_id=%s", picked, driver_id)
            return rule_action
        if not _passes_numeric_guard(selected, rule_feature):
            self._logger.info("llm_rerank rejected by guard driver_id=%s cargo_id=%s", driver_id, picked)
            return rule_action

        self._logger.info(
            "llm_rerank accepted driver_id=%s from=%s to=%s rule_score=%.4f llm_score=%.4f",
            driver_id,
            rule_cargo_id,
            picked,
            float(rule_feature.get("score", 0.0)),
            float(selected.get("score", 0.0)),
        )
        return {"action": "take_order", "params": {"cargo_id": str(selected["cargo_id"])}}

    def _call_llm_reranker(
        self,
        driver_id: str,
        candidates: list[dict[str, Any]],
        rule_feature: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> str:
        if _env_bool("AGENT_LLM_SKILL_CRITIC", False):
            return self._call_llm_skill_critic(driver_id, candidates, rule_feature, diagnostics)

        status = diagnostics.get("status")
        if not isinstance(status, dict):
            status = {}
        calculator_summary = _calculator_summary(candidates, rule_feature)
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a truck-dispatch reranker. Return only JSON. "
                        "Choose one cargo_id from candidates. Prioritize total net score, "
                        "avoid preference penalties, and never choose a cargo outside candidates. "
                        "Use calculator_summary for all arithmetic. Do not calculate score, net, "
                        "net_per_hour, deltas, distances, or guards yourself."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "driver_id": driver_id,
                            "time_min": status.get("simulation_progress_minutes"),
                            "agent_memory": _agent_memory_snapshot(self._strategy, driver_id),
                            "rule_choice": _compact_feature(rule_feature),
                            "candidates": [_compact_feature(item) for item in candidates],
                            "calculator_summary": calculator_summary,
                            "output_schema": {"cargo_id": "string"},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": _env_float("AGENT_LLM_TEMPERATURE", 0.0),
            "max_tokens": _env_int("AGENT_LLM_MAX_TOKENS", 64),
        }
        model_name = os.getenv("AGENT_LLM_MODEL", "").strip()
        if model_name:
            payload["model"] = model_name
        if os.getenv("AGENT_LLM_ENABLE_THINKING", "").strip() in {"0", "false", "False"}:
            payload["enable_thinking"] = False

        model_resp = self._api.model_chat_completion(payload)
        content = _extract_message_content(model_resp)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM rerank response is not an object")
        return str(parsed.get("cargo_id") or parsed.get("CargoID") or "").strip()

    def _call_llm_skill_critic(
        self,
        driver_id: str,
        candidates: list[dict[str, Any]],
        rule_feature: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> str:
        status = diagnostics.get("status")
        if not isinstance(status, dict):
            status = {}
        calculator_summary = _calculator_summary(candidates, rule_feature)
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a truck-driver agent skill critic. Return only JSON. "
                        "Pick a skill and one cargo_id from candidates, or keep the rule_choice. "
                        "Do not invent cargo IDs. Prefer monthly net profit after preference penalties. "
                        "Use conservative changes: switch only when the candidate is clearly safer or better. "
                        "Use calculator_summary for all arithmetic. Do not calculate score, net, "
                        "net_per_hour, deltas, distances, or guards yourself. If calculator_summary "
                        "marks a candidate guard_pass=false, treat it as ineligible."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "driver_id": driver_id,
                            "status": _compact_status(status),
                            "agent_memory": _agent_memory_snapshot(self._strategy, driver_id),
                            "driver_skills": _driver_skill_cards(driver_id),
                            "rule_choice": _compact_feature(rule_feature),
                            "candidates": [_compact_feature(item) for item in candidates],
                            "calculator_summary": calculator_summary,
                            "output_schema": {
                                "skill": "base|chain_rollout|opportunity_rest|quota_guard|home_return|profit_priority|risk_guard",
                                "decision": "keep|switch",
                                "cargo_id": "string from candidates",
                                "risk": "none|preference|deadline|low_profit|unknown",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": _env_float("AGENT_LLM_TEMPERATURE", 0.0),
            "max_tokens": _env_int("AGENT_LLM_MAX_TOKENS", 96),
        }
        model_name = os.getenv("AGENT_LLM_MODEL", "").strip()
        if model_name:
            payload["model"] = model_name
        if os.getenv("AGENT_LLM_ENABLE_THINKING", "").strip() in {"0", "false", "False"}:
            payload["enable_thinking"] = False

        model_resp = self._api.model_chat_completion(payload)
        content = _extract_message_content(model_resp)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM skill critic response is not an object")

        cargo_id = str(parsed.get("cargo_id") or parsed.get("CargoID") or "").strip()
        decision = str(parsed.get("decision") or "").strip().lower()
        risk = str(parsed.get("risk") or "").strip().lower()
        if _risk_rejected(risk):
            return str(rule_feature.get("cargo_id", "")).strip()
        if decision == "keep" and not _env_bool("AGENT_LLM_SKILL_CRITIC_ALLOW_KEEP_SWITCH", False):
            return str(rule_feature.get("cargo_id", "")).strip()
        return cargo_id


def _normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    action_name = str(action.get("action", "")).strip().lower()
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}
    if action_name == "take_order":
        return {"action": "take_order", "params": {"cargo_id": str(params.get("cargo_id", "")).strip()}}
    if action_name == "reposition":
        return {
            "action": "reposition",
            "params": {"latitude": float(params["latitude"]), "longitude": float(params["longitude"])},
        }
    if action_name == "wait":
        return {"action": "wait", "params": {"duration_minutes": max(1, int(params["duration_minutes"]))}}
    return {"action": "wait", "params": {"duration_minutes": max(1, _env_int("AGENT_FALLBACK_WAIT_MINUTES", 60))}}


def _should_rerank_window(
    driver_id: str,
    candidates: list[dict[str, Any]],
    rule_feature: dict[str, Any],
    diagnostics: dict[str, Any],
) -> bool:
    if _env_bool("AGENT_LLM_RERANK_ALWAYS", False):
        return True
    if not _env_bool("AGENT_LLM_RERANK_NEAR_TIE_ONLY", False) and driver_id in {"D004", "D009", "D010"}:
        return True
    if len(candidates) < 2:
        return False
    score_gap = abs(float(candidates[0].get("score", 0.0)) - float(candidates[1].get("score", 0.0)))
    if score_gap <= _env_float("AGENT_LLM_RERANK_MAX_SCORE_GAP", 80.0):
        return True
    if not _env_bool("AGENT_LLM_RERANK_ON_CONFLICT", True):
        return False

    rule_score = float(rule_feature.get("score", 0.0) or 0.0)
    rule_risk = float(rule_feature.get("preference_risk_delta", 0.0) or 0.0)
    rule_route = float(rule_feature.get("destination_opportunity_value", 0.0) or 0.0)
    max_score_drop = _env_float("AGENT_LLM_CONFLICT_MAX_SCORE_DROP", 12.0)
    min_risk_gain = _env_float("AGENT_LLM_CONFLICT_MIN_RISK_GAIN", 120.0)
    min_route_gain = _env_float("AGENT_LLM_CONFLICT_MIN_ROUTE_GAIN", 35.0)
    for item in candidates[1:]:
        score = float(item.get("score", 0.0) or 0.0)
        if score < rule_score - max_score_drop:
            continue
        risk_gain = rule_risk - float(item.get("preference_risk_delta", 0.0) or 0.0)
        route_gain = float(item.get("destination_opportunity_value", 0.0) or 0.0) - rule_route
        if risk_gain >= min_risk_gain or route_gain >= min_route_gain:
            return True
    return False


def _passes_numeric_guard(selected: dict[str, Any], rule_feature: dict[str, Any]) -> bool:
    max_score_drop = _env_float("AGENT_LLM_MAX_SCORE_DROP", 40.0)
    max_net_drop = _env_float("AGENT_LLM_MAX_NET_DROP", 120.0)
    selected_score = float(selected.get("score", 0.0))
    rule_score = float(rule_feature.get("score", 0.0))
    selected_net = float(selected.get("estimated_net", 0.0))
    rule_net = float(rule_feature.get("estimated_net", 0.0))
    if selected_score < rule_score - max_score_drop:
        return False
    if selected_net < rule_net - max_net_drop:
        return False

    selected_id = str(selected.get("cargo_id", "")).strip()
    rule_id = str(rule_feature.get("cargo_id", "")).strip()
    if selected_id != rule_id:
        min_improvement = _env_float("AGENT_LLM_MIN_SCORE_IMPROVEMENT", 0.0)
        if selected_score < rule_score + min_improvement:
            return False
        min_net_improvement = _env_float("AGENT_LLM_MIN_NET_IMPROVEMENT", 0.0)
        if selected_net < rule_net + min_net_improvement:
            return False

    if _env_bool("AGENT_LLM_OBSERVE_ONLY", False) and selected_id != rule_id:
        return False
    return True


def _calculator_summary(candidates: list[dict[str, Any]], rule_feature: dict[str, Any]) -> dict[str, Any]:
    return build_rerank_calculation(
        candidates=candidates,
        rule_feature=rule_feature,
        max_score_drop=_env_float("AGENT_LLM_MAX_SCORE_DROP", 40.0),
        max_net_drop=_env_float("AGENT_LLM_MAX_NET_DROP", 120.0),
        min_score_improvement=_env_float("AGENT_LLM_MIN_SCORE_IMPROVEMENT", 0.0),
        min_net_improvement=_env_float("AGENT_LLM_MIN_NET_IMPROVEMENT", 0.0),
    )


def _compact_feature(feature: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "cargo_id",
        "score",
        "estimated_net",
        "net_per_hour",
        "destination_hotspot_score",
        "destination_opportunity_value",
        "preference_risk_delta",
        "route_plan",
        "pickup_km",
        "haul_km",
        "wait_minutes",
        "total_exec_minutes",
        "finish_minutes",
        "end_address",
        "start_city",
        "end_city",
        "cargo_type",
        "cargo_name",
    ]
    return {key: feature.get(key) for key in keys if key in feature}


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        return {}
    action_name = str(action.get("action", "")).strip()
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}
    return {"action": action_name, "params": dict(params)}


def _compact_status(status: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "driver_id",
        "simulation_progress_minutes",
        "current_lat",
        "current_lng",
        "total_income",
        "total_cost",
        "net_income",
        "accepted_order_count",
        "today_accepted_order_count",
        "rest_violations",
        "preferences",
    ]
    compact = {key: status.get(key) for key in keys if key in status}
    prefs = compact.get("preferences")
    if isinstance(prefs, list):
        compact["preferences"] = [str(item)[:140] for item in prefs[:6]]
    elif isinstance(prefs, str):
        compact["preferences"] = prefs[:500]
    history_total = status.get("_decision_history_total")
    if history_total is not None:
        compact["history_count"] = history_total
    return compact


def _driver_skill_cards(driver_id: str) -> list[str]:
    cards = {
        "D001": [
            "opportunity_rest: daily 8h continuous rest matters; rest in low net_per_hour windows.",
            "chain_rollout: visible successor value can justify finishing near better future cargo.",
        ],
        "D004": [
            "quota_guard: daily first-order and max-three-orders constraints are important.",
            "risk_guard: lunch/noon timing can trade 100 lunch cost against 200 late-first-order cost.",
        ],
        "D006": [
            "profit_priority: high-density short-haul profit usually beats forcing daily rest.",
            "risk_guard: avoid fish cargo and overlong pickup/haul, but do not over-rest.",
        ],
        "D007": [
            "chain_rollout: near-tie choices should preserve next high NPH cargo.",
            "risk_guard: night quiet window and haul limit must remain feasible.",
        ],
        "D009": [
            "home_return: evening actions must preserve 23:00 home arrival.",
            "risk_guard: temporary familiar cargo has very high penalty if missed.",
        ],
        "D010": [
            "chain_rollout: near-tie choices should preserve high next NPH and target visits.",
            "home_return: family event and home stay dominate normal cargo profit around Mar 10-13.",
        ],
    }
    return cards.get(driver_id, ["base: choose the best guarded monthly net candidate."])


def _agent_memory_snapshot(strategy: Any, driver_id: str) -> dict[str, Any]:
    getter = getattr(strategy, "agent_memory_snapshot", None)
    if not callable(getter):
        return {}
    try:
        snapshot = getter(driver_id)
    except Exception:
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def _risk_rejected(risk: str) -> bool:
    rejected = {item.strip().lower() for item in os.getenv("AGENT_LLM_SKILL_CRITIC_REJECT_RISKS", "").split(",") if item.strip()}
    return bool(risk and risk in rejected)


def _find_feature(candidates: list[dict[str, Any]], cargo_id: str) -> dict[str, Any] | None:
    target = str(cargo_id).strip()
    for item in candidates:
        if str(item.get("cargo_id", "")).strip() == target:
            return item
    return None


def _extract_message_content(model_resp: dict[str, Any]) -> str:
    choices = model_resp.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("LLM response missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response content is empty")
    return content.strip()


def _driver_enabled(driver_id: str, raw: str) -> bool:
    enabled = {item.strip().upper() for item in raw.split(",") if item.strip()}
    return driver_id.strip().upper() in enabled


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


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
