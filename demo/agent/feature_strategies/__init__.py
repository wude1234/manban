"""Feature-engineering strategies for the 2026-05-08 release."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .common import BaseFeatureStrategy


STRATEGY_MODULES = {
    "new_release_preference_agent": "agent.feature_strategies.new_release_preference_agent",
    "new_release_guarded_agent": "agent.feature_strategies.new_release_guarded_agent",
    "new_release_profit_guarded_agent": "agent.feature_strategies.new_release_profit_guarded_agent",
    "new_release_marginal_value_agent": "agent.feature_strategies.new_release_marginal_value_agent",
    "new_release_hybrid_value_agent": "agent.feature_strategies.new_release_hybrid_value_agent",
    "new_release_driver_profile_agent": "agent.feature_strategies.new_release_driver_profile_agent",
    "new_release_agentic_planner_agent": "agent.feature_strategies.new_release_agentic_planner_agent",
}


def available_strategy_names() -> list[str]:
    return sorted(STRATEGY_MODULES)


def load_strategy(name: str) -> BaseFeatureStrategy:
    normalized = name.strip().lower()
    if normalized in {"new_release", "release_agent", "pref_agent", "hard_filter"}:
        normalized = "new_release_preference_agent"
    if normalized in {"guarded", "new_release_guarded", "pref_guarded", "cross_day_guarded"}:
        normalized = "new_release_guarded_agent"
    if normalized in {"profit_guarded", "new_release_profit_guarded", "high_profit", "收益优先"}:
        normalized = "new_release_profit_guarded_agent"
    if normalized in {"marginal_value", "shadow_price", "mv_agent", "边际价值"}:
        normalized = "new_release_marginal_value_agent"
    if normalized in {"hybrid_value", "hybrid_mv", "value_hybrid", "混合价值"}:
        normalized = "new_release_hybrid_value_agent"
    if normalized in {"driver_profile", "profile_agent", "profile_search", "司机画像"}:
        normalized = "new_release_driver_profile_agent"
    if normalized in {"agentic_planner", "planner_agent", "agentic_agent", "agent算法", "规划agent"}:
        normalized = "new_release_agentic_planner_agent"
    module_path = STRATEGY_MODULES.get(normalized)
    if module_path is None:
        known = ", ".join(available_strategy_names())
        raise ValueError(f"unknown AGENT_STRATEGY={name!r}; available: {known}, llm")
    module = import_module(module_path)
    strategy_factory: Any = getattr(module, "build_strategy")
    strategy = strategy_factory()
    if not isinstance(strategy, BaseFeatureStrategy):
        raise TypeError(f"{module_path}.build_strategy() did not return BaseFeatureStrategy")
    return strategy
