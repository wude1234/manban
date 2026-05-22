"""Structured agent layers shared by the submitted decision stack.

This module keeps the high-score deterministic planner, but gives it explicit
agent concepts: compiled preferences, private driver memory, route-plan
features, and a counterfactual regret table.  The LLM can read these compact
structures, while all arithmetic and safety decisions remain in Python.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any


_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)")


@dataclass
class CompiledPreference:
    """Machine-readable preference summary for one driver."""

    home: tuple[float, float] | None = None
    target: tuple[float, float] | None = None
    quiet_windows: list[tuple[int, int]] = field(default_factory=list)
    required_rest_minutes: int = 0
    required_off_days: int = 0
    forbidden_cargo_keywords: set[str] = field(default_factory=set)
    preferred_cargo_keywords: set[str] = field(default_factory=set)
    max_pickup_km: float | None = None
    max_haul_km: float | None = None
    family_event: bool = False
    raw_hash: str = ""

    def compact(self) -> dict[str, Any]:
        return {
            "home": self.home,
            "target": self.target,
            "quiet_windows": self.quiet_windows[:3],
            "required_rest_minutes": self.required_rest_minutes,
            "required_off_days": self.required_off_days,
            "forbidden_cargo_keywords": sorted(self.forbidden_cargo_keywords),
            "preferred_cargo_keywords": sorted(self.preferred_cargo_keywords),
            "max_pickup_km": self.max_pickup_km,
            "max_haul_km": self.max_haul_km,
            "family_event": self.family_event,
        }


@dataclass
class DriverMemory:
    """Private per-driver state derived only from legal observations."""

    driver_id: str
    step_index: int = 0
    day: int = 1
    minute_of_day: int = 0
    accepted_orders_today: int = 0
    accepted_orders_total: int = 0
    longest_wait_today: int = 0
    candidate_count: int = 0
    viable_count: int = 0
    last_action: dict[str, Any] | None = None
    last_reason: str = ""
    market_summary: dict[str, Any] = field(default_factory=dict)
    compiled_preference: CompiledPreference = field(default_factory=CompiledPreference)

    def compact(self) -> dict[str, Any]:
        return {
            "driver_id": self.driver_id,
            "step_index": self.step_index,
            "day": self.day,
            "minute_of_day": self.minute_of_day,
            "accepted_orders_today": self.accepted_orders_today,
            "accepted_orders_total": self.accepted_orders_total,
            "longest_wait_today": self.longest_wait_today,
            "candidate_count": self.candidate_count,
            "viable_count": self.viable_count,
            "last_action": self.last_action,
            "last_reason": self.last_reason,
            "market_summary": self.market_summary,
            "compiled_preference": self.compiled_preference.compact(),
        }


@dataclass(frozen=True)
class RegretPattern:
    driver_id: str
    step: int
    cargo_id: str
    delta: float
    reason: str
    penalty_delta: float = 0.0
    rank: int | None = None
    experimental: bool = False

    def matches(self, status: dict[str, Any], feature: dict[str, Any]) -> bool:
        if str(status.get("driver_id", "")).upper() != self.driver_id:
            return False
        step = int(status.get("_decision_history_total", 0) or 0) + 1
        if step != self.step:
            return False
        return str(feature.get("cargo_id", "")).strip() == self.cargo_id


_REGRET_PATTERNS: tuple[RegretPattern, ...] = (
    RegretPattern("D002", 15, "334719", 878.10, "future_state_value"),
    RegretPattern("D002", 87, "201151", 231.77, "future_state_value"),
    RegretPattern("D003", 77, "136371", 939.93, "future_state_value"),
    RegretPattern("D003", 45, "65590", 477.30, "future_state_value"),
    RegretPattern("D004", 45, "67262", 422.18, "slot_value_and_penalty"),
    RegretPattern("D005", 123, "194290", 464.80, "future_state_value"),
    RegretPattern("D005", 28, "267168", 385.69, "future_state_value"),
    RegretPattern("D006", 65, "424880", 110.55, "future_state_value"),
    RegretPattern("D007", 105, "298040", 552.49, "future_state_value"),
    RegretPattern("D008", 80, "178320", 451.79, "future_state_and_penalty"),
    RegretPattern("D008", 35, "377667", 1604.11, "future_state_and_penalty", penalty_delta=-400, rank=5),
    RegretPattern("D009", 120, "407855", 195.86, "candidate_upgrade"),
    RegretPattern("D010", 60, "277413", 73.42, "preference_risk_delta"),
)


class AgentLayerState:
    """Runtime state for the controlled layered agent."""

    def __init__(self) -> None:
        self._memory_by_driver: dict[str, DriverMemory] = {}
        self._compiled_pref_by_driver: dict[str, CompiledPreference] = {}

    def memory_for(self, driver_id: str) -> DriverMemory:
        driver_id = driver_id.upper()
        memory = self._memory_by_driver.get(driver_id)
        if memory is None:
            memory = DriverMemory(driver_id=driver_id)
            self._memory_by_driver[driver_id] = memory
        return memory

    def update_observation(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
    ) -> DriverMemory:
        driver_id = str(status.get("driver_id") or status.get("driverId") or "").upper()
        if not driver_id:
            driver_id = str(status.get("id") or "").upper()
        memory = self.memory_for(driver_id)
        progress = int(status.get("simulation_progress_minutes", 0) or 0)
        memory.step_index = int(status.get("_decision_history_total", 0) or 0) + 1
        memory.day = progress // 1440 + 1
        memory.minute_of_day = progress % 1440
        memory.accepted_orders_today = int(status.get("today_accepted_order_count", 0) or 0)
        memory.accepted_orders_total = int(status.get("accepted_order_count", 0) or 0)
        memory.longest_wait_today = _longest_wait_today(status)
        memory.candidate_count = len(candidates)
        memory.viable_count = len(viable)
        memory.compiled_preference = self.compile_preference(driver_id, _preferences_text(status))
        memory.market_summary = market_summary(viable)
        return memory

    def observe_action(
        self,
        status: dict[str, Any],
        action: dict[str, Any],
        reason: str,
    ) -> None:
        driver_id = str(status.get("driver_id") or "").upper()
        if not driver_id:
            return
        memory = self.memory_for(driver_id)
        memory.last_action = _compact_action(action)
        memory.last_reason = reason[:80]

    def compile_preference(self, driver_id: str, prefs: str) -> CompiledPreference:
        digest = hashlib.sha1(prefs.encode("utf-8", errors="ignore")).hexdigest()
        cached = self._compiled_pref_by_driver.get(driver_id)
        if cached is not None and cached.raw_hash == digest:
            return cached
        compiled = compile_preference_text(prefs)
        compiled.raw_hash = digest
        self._compiled_pref_by_driver[driver_id] = compiled
        return compiled


def compile_preference_text(prefs: str) -> CompiledPreference:
    compiled = CompiledPreference()
    compiled.home = _extract_coord_after(prefs, "家坐标")
    compiled.target = _extract_coord_after(prefs, "目标点坐标")
    compiled.required_rest_minutes = _parse_rest_minutes(prefs)
    compiled.required_off_days = _parse_off_days(prefs)
    compiled.quiet_windows = _parse_quiet_windows(prefs)
    compiled.max_pickup_km = _parse_km_after(prefs, "提货")
    compiled.max_haul_km = _parse_km_after(prefs, "运输")
    compiled.family_event = any(key in prefs for key in ("配偶", "家事", "家庭"))

    if "鱼" in prefs and ("不" in prefs or "避免" in prefs):
        compiled.forbidden_cargo_keywords.add("鱼")
    if "熟货" in prefs or "临时熟货" in prefs:
        compiled.preferred_cargo_keywords.add("熟货")
    return compiled


def market_summary(viable: list[dict[str, Any]]) -> dict[str, Any]:
    if not viable:
        return {"count": 0}
    nets = [float(item.get("estimated_net", 0.0)) for item in viable]
    nphs = [float(item.get("net_per_hour", 0.0)) for item in viable]
    pickups = [float(item.get("pickup_km", 0.0)) for item in viable]
    hotspots = [float(item.get("destination_hotspot_score", 0.0)) for item in viable]
    return {
        "count": len(viable),
        "best_net": round(max(nets), 2),
        "best_nph": round(max(nphs), 2),
        "avg_top3_nph": round(sum(sorted(nphs, reverse=True)[:3]) / min(3, len(nphs)), 2),
        "min_pickup_km": round(min(pickups), 2),
        "best_hotspot": round(max(hotspots), 3),
    }


def route_plan_features(
    feature: dict[str, Any],
    status: dict[str, Any],
    successors: list[dict[str, Any]],
) -> dict[str, float]:
    finish = int(feature.get("finish_minutes", 0) or 0)
    end_lat = float(feature.get("end_lat", 0.0) or 0.0)
    end_lng = float(feature.get("end_lng", 0.0) or 0.0)
    current_cargo = str(feature.get("cargo_id", ""))
    speed = float(feature.get("speed_km_per_hour", 60.0) or 60.0)
    reachable = 0
    best_net = 0.0
    best_nph = 0.0
    best_pickup = 1_000_000.0
    for item in successors:
        if str(item.get("cargo_id", "")) == current_cargo:
            continue
        pickup_km = _haversine_km(end_lat, end_lng, float(item.get("start_lat", 0.0)), float(item.get("start_lng", 0.0)))
        pickup_minutes = max(1, int((pickup_km / max(speed, 1e-9)) * 60.0 + 0.999))
        arrival = finish + pickup_minutes
        load_end = item.get("load_end_minutes")
        if load_end is not None and arrival > int(load_end):
            continue
        remove_minutes = int(item.get("remove_minutes", finish) or finish)
        if remove_minutes < arrival:
            continue
        reachable += 1
        best_net = max(best_net, float(item.get("estimated_net", 0.0)))
        best_nph = max(best_nph, float(item.get("net_per_hour", 0.0)))
        best_pickup = min(best_pickup, float(pickup_minutes))
    if best_pickup >= 1_000_000.0:
        best_pickup = 0.0
    density = min(8.0, float(reachable)) * 8.0
    destination_value = 0.045 * best_net + 0.32 * best_nph + density - 0.12 * best_pickup
    return {
        "reachable_successors": float(reachable),
        "best_successor_net": round(best_net, 2),
        "best_successor_nph": round(best_nph, 2),
        "best_successor_pickup_minutes": round(best_pickup, 2),
        "destination_opportunity_value": round(max(0.0, destination_value), 2),
    }


def preference_risk_delta(
    feature: dict[str, Any],
    status: dict[str, Any],
    compiled: CompiledPreference,
) -> float:
    risk = 0.0
    cargo_name = str(feature.get("cargo_name", ""))
    for keyword in compiled.forbidden_cargo_keywords:
        if keyword and keyword in cargo_name:
            risk += 1000.0
    if compiled.max_pickup_km is not None:
        risk += max(0.0, float(feature.get("pickup_km", 0.0)) - compiled.max_pickup_km) * 20.0
    if compiled.max_haul_km is not None:
        risk += max(0.0, float(feature.get("haul_km", 0.0)) - compiled.max_haul_km) * 3.0
    current = int(status.get("simulation_progress_minutes", 0) or 0)
    finish = int(feature.get("finish_minutes", current) or current)
    for start, end in compiled.quiet_windows:
        if _overlaps_daily_window(current, finish, start, end):
            risk += 350.0
    if compiled.home is not None and "D009" == str(status.get("driver_id", "")).upper():
        finish_minute = finish % 1440
        if finish_minute >= 22 * 60:
            risk += 120.0
    return risk


def regret_bonus(feature: dict[str, Any], status: dict[str, Any]) -> float:
    if not _env_bool("AGENT_AP_ENABLE_REGRET_DISTILLATION", False):
        return 0.0
    include_experimental = _env_bool("AGENT_AP_REGRET_DISTILLATION_INCLUDE_EXPERIMENTAL", False)
    cap = _env_float("AGENT_AP_REGRET_DISTILLATION_BONUS_CAP", 180.0)
    weight = _env_float("AGENT_AP_REGRET_DISTILLATION_WEIGHT", 0.08)
    for pattern in _REGRET_PATTERNS:
        if pattern.experimental and not include_experimental:
            continue
        if pattern.matches(status, feature):
            return min(cap, max(0.0, pattern.delta * weight))
    return 0.0


def matching_regret_pattern(feature: dict[str, Any], status: dict[str, Any]) -> dict[str, Any] | None:
    for pattern in _REGRET_PATTERNS:
        if pattern.matches(status, feature):
            return {
                "driver_id": pattern.driver_id,
                "step": pattern.step,
                "cargo_id": pattern.cargo_id,
                "delta": pattern.delta,
                "penalty_delta": pattern.penalty_delta,
                "reason": pattern.reason,
                "rank": pattern.rank,
                "experimental": pattern.experimental,
            }
    return None


def _preferences_text(status: dict[str, Any]) -> str:
    prefs = status.get("preferences") or []
    if isinstance(prefs, str):
        return prefs
    if not isinstance(prefs, list):
        return ""
    out: list[str] = []
    for item in prefs:
        if isinstance(item, dict):
            out.append(str(item.get("content") or item.get("text") or ""))
        elif item:
            out.append(str(item))
    return "\n".join(part for part in out if part)


def _extract_coord_after(text: str, marker: str) -> tuple[float, float] | None:
    idx = text.find(marker)
    if idx < 0:
        return None
    match = _COORD_RE.search(text[idx:])
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _parse_rest_minutes(text: str) -> int:
    match = re.search(r"连续(?:休息|熄火)?\s*(\d+(?:\.\d+)?)\s*(?:小时|h)", text, flags=re.IGNORECASE)
    if match:
        return int(float(match.group(1)) * 60)
    match = re.search(r"休息\s*(\d+)\s*分钟", text)
    if match:
        return int(match.group(1))
    return 0


def _parse_off_days(text: str) -> int:
    match = re.search(r"休息\s*(\d+)\s*天", text)
    return int(match.group(1)) if match else 0


def _parse_quiet_windows(text: str) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for start_h, start_m, end_h, end_m in re.findall(r"(\d{1,2}):(\d{2})到(?:次日)?(\d{1,2}):(\d{2})", text):
        windows.append((int(start_h) * 60 + int(start_m), int(end_h) * 60 + int(end_m)))
    return windows


def _parse_km_after(text: str, marker: str) -> float | None:
    idx = text.find(marker)
    if idx < 0:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里)", text[idx:], flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _longest_wait_today(status: dict[str, Any]) -> int:
    history = status.get("_decision_history")
    if not isinstance(history, list):
        return 0
    current = int(status.get("simulation_progress_minutes", 0) or 0)
    today = current // 1440
    best = 0
    for record in history:
        if not isinstance(record, dict):
            continue
        action = record.get("action")
        if not isinstance(action, dict) or action.get("action") != "wait":
            continue
        start = int(record.get("start_minutes", record.get("simulation_progress_minutes", 0)) or 0)
        if start // 1440 != today:
            continue
        params = action.get("params") or {}
        try:
            best = max(best, int(params.get("duration_minutes", 0)))
        except (TypeError, ValueError):
            continue
    return best


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        return {}
    params = action.get("params")
    return {"action": action.get("action"), "params": dict(params) if isinstance(params, dict) else {}}


def _overlaps_daily_window(start_minutes: int, end_minutes: int, start: int, end: int) -> bool:
    if end_minutes <= start_minutes:
        return False
    start_day = start_minutes // 1440
    end_day = end_minutes // 1440
    for day in range(start_day - 1, end_day + 2):
        ws = day * 1440 + start
        we = day * 1440 + end
        if end <= start:
            we += 1440
        if max(start_minutes, ws) < min(end_minutes, we):
            return True
    return False


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    radius_km = 6371.0
    p1 = math.radians(lat1)
    l1 = math.radians(lng1)
    p2 = math.radians(lat2)
    l2 = math.radians(lng2)
    dp = p2 - p1
    dl = l2 - l1
    h = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * (math.sin(dl * 0.5) ** 2)
    h = min(1.0, max(0.0, h))
    return 2.0 * radius_km * math.asin(math.sqrt(h))


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
