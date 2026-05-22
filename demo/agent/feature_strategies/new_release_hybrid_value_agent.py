"""Hybrid value strategy for the 2026-05-08 release.

Use marginal-value scoring only for drivers where the 30-day experiment showed
positive net lift, and keep the profit-guarded policy for drivers it hurt.
"""

from __future__ import annotations

from typing import Any

from .common import BaseFeatureStrategy
from .new_release_marginal_value_agent import NewReleaseMarginalValueAgent
from .new_release_preference_agent import _driver_id
from .new_release_profit_guarded_agent import NewReleaseProfitGuardedAgent


_MARGINAL_VALUE_DRIVERS = {"D002", "D004", "D005", "D006", "D010"}


class NewReleaseHybridValueAgent(NewReleaseMarginalValueAgent):
    name = "new_release_hybrid_value_agent"

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        if _driver_id(status) in _MARGINAL_VALUE_DRIVERS:
            return NewReleaseMarginalValueAgent.score(self, feature, status)
        return NewReleaseProfitGuardedAgent.score(self, feature, status)


def build_strategy() -> BaseFeatureStrategy:
    return NewReleaseHybridValueAgent()
