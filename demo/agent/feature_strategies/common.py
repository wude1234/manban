"""Shared feature construction and action selection for rule-based strategies."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from simkit.ports import SimulationApiPort


_SIMULATION_EPOCH = datetime(2026, 3, 1, 0, 0, 0)
_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)")

HOTSPOT_CITY_SCORE = {
    "广东省广州市白云区": 1.00,
    "广东省佛山市南海区": 0.90,
    "广东省佛山市顺德区": 0.78,
    "广东省深圳市龙岗区": 0.62,
    "广东省惠州市博罗县": 0.62,
    "广东省广州市花都区": 0.55,
    "广东省佛山市三水区": 0.55,
    "广东省广州市黄埔区": 0.52,
    "广东省广州市增城区": 0.50,
    "广东省惠州市惠城区": 0.48,
    "广东省深圳市宝安区": 0.48,
    "广东省惠州市惠阳区": 0.47,
    "广东省广州市番禺区": 0.46,
    "广东省广州市南沙区": 0.44,
    "广东省佛山市禅城区": 0.42,
}


@dataclass(frozen=True)
class FeatureSettings:
    speed_km_per_hour: float
    simulation_horizon_minutes: int
    fallback_wait_minutes: int

    @classmethod
    def from_env_and_config(cls) -> "FeatureSettings":
        simulation_days = _load_float_setting(
            env_name="AGENT_SIMULATION_DAYS",
            config_key="simulation_duration_days",
            default=30.0,
        )
        return cls(
            speed_km_per_hour=_load_float_setting(
                env_name="AGENT_REPOSITION_SPEED_KMH",
                config_key="reposition_speed_km_per_hour",
                default=60.0,
            ),
            simulation_horizon_minutes=int(simulation_days * 24 * 60),
            fallback_wait_minutes=max(1, int(os.getenv("AGENT_FALLBACK_WAIT_MINUTES", "60"))),
        )


class BaseFeatureStrategy:
    name = "base"

    def pre_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        return None

    def pre_query_action(
        self,
        status: dict[str, Any],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        return None

    def score(self, feature: dict[str, Any], status: dict[str, Any]) -> float:
        raise NotImplementedError

    def is_selectable(self, feature: dict[str, Any], status: dict[str, Any]) -> bool:
        return True

    def no_selectable_action(
        self,
        status: dict[str, Any],
        candidates: list[dict[str, Any]],
        viable: list[dict[str, Any]],
        settings: FeatureSettings,
    ) -> dict[str, Any] | None:
        return None


class FeatureDecisionEngine:
    """Build candidate features, delegate scoring to one strategy, and emit actions."""

    def __init__(self, api: SimulationApiPort, strategy: BaseFeatureStrategy, settings: FeatureSettings | None = None) -> None:
        self._api = api
        self.strategy = strategy
        self.settings = settings or FeatureSettings.from_env_and_config()

    def decide(self, driver_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        status = self._api.get_driver_status(driver_id)
        pre_status = dict(status)
        history = self._query_history(driver_id)
        pre_status["_decision_history"] = history
        pre_status["_decision_history_total"] = len(history)
        pre_query = getattr(self.strategy, "pre_query_action", None)
        if callable(pre_query):
            planned_action = pre_query(pre_status, self.settings)
            if planned_action is not None:
                diagnostics = {
                    "strategy": self.strategy.name,
                    "status": pre_status,
                    "candidate_count": 0,
                    "viable_count": 0,
                    "planned_action": planned_action,
                    "pre_query_action": True,
                }
                return planned_action, diagnostics

        lat = float(status["current_lat"])
        lng = float(status["current_lng"])
        cargo_resp = self._api.query_cargo(driver_id=driver_id, latitude=lat, longitude=lng)
        items = cargo_resp.get("items", [])
        if not isinstance(items, list):
            items = []

        action_status = self._api.get_driver_status(driver_id)
        action_status = dict(action_status)
        history = self._query_history(driver_id)
        action_status["_decision_history"] = history
        action_status["_decision_history_total"] = len(history)
        action_start_minutes = int(action_status.get("simulation_progress_minutes", 0))
        candidates = [
            feature
            for item in items
            if (feature := self._build_candidate_features(action_status, item, action_start_minutes)) is not None
        ]
        viable = [feature for feature in candidates if feature["feasible"]]

        planned_action = self.strategy.pre_action(action_status, candidates, viable, self.settings)
        if planned_action is not None:
            for feature in viable:
                feature["score"] = self.strategy.score(feature, action_status)
            selectable = [feature for feature in viable if self.strategy.is_selectable(feature, action_status)]
            diagnostics = {
                "strategy": self.strategy.name,
                "status": action_status,
                "candidate_count": len(candidates),
                "viable_count": len(viable),
                "planned_action": planned_action,
                "selectable_count": len(selectable),
                "selectable_features": selectable,
            }
            if selectable:
                diagnostics["chosen_without_pre_action"] = max(selectable, key=lambda x: float(x["score"]))
            return planned_action, diagnostics

        if viable:
            for feature in viable:
                feature["score"] = self.strategy.score(feature, action_status)
            selectable = [feature for feature in viable if self.strategy.is_selectable(feature, action_status)]
            if not selectable:
                fallback = self.strategy.no_selectable_action(action_status, candidates, viable, self.settings)
                if fallback is None:
                    fallback = self._build_fallback_action(action_status)
                observer = getattr(self.strategy, "observe_selected_action", None)
                if callable(observer):
                    observer(action_status, candidates, viable, fallback)
                diagnostics = {
                    "strategy": self.strategy.name,
                    "status": action_status,
                    "candidate_count": len(candidates),
                    "viable_count": len(viable),
                    "selectable_count": 0,
                    "fallback": fallback,
                }
                return fallback, diagnostics

            best = max(selectable, key=lambda x: float(x["score"]))
            action = {"action": "take_order", "params": {"cargo_id": str(best["cargo_id"])}}
            observer = getattr(self.strategy, "observe_selected_action", None)
            if callable(observer):
                observer(action_status, candidates, viable, action)
            diagnostics = {
                "strategy": self.strategy.name,
                "status": action_status,
                "candidate_count": len(candidates),
                "viable_count": len(viable),
                "selectable_count": len(selectable),
                "selectable_features": selectable,
                "chosen": best,
            }
            return action, diagnostics

        fallback = self._build_fallback_action(action_status)
        observer = getattr(self.strategy, "observe_selected_action", None)
        if callable(observer):
            observer(action_status, candidates, viable, fallback)
        diagnostics = {
            "strategy": self.strategy.name,
            "status": action_status,
            "candidate_count": len(candidates),
            "viable_count": 0,
            "fallback": fallback,
        }
        return fallback, diagnostics

    def _query_history(self, driver_id: str) -> list[dict[str, Any]]:
        try:
            resp = self._api.query_decision_history(driver_id, -1)
        except Exception:
            return []
        records = resp.get("records") if isinstance(resp, dict) else None
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def _build_candidate_features(
        self,
        status: dict[str, Any],
        item: dict[str, Any],
        action_start_minutes: int,
    ) -> dict[str, Any] | None:
        cargo = item.get("cargo")
        if not isinstance(cargo, dict):
            return None
        cargo_id = str(cargo.get("cargo_id", "")).strip()
        if not cargo_id:
            return None

        try:
            start = cargo.get("start") or {}
            end = cargo.get("end") or {}
            start_lat = float(start["lat"])
            start_lng = float(start["lng"])
            end_lat = float(end["lat"])
            end_lng = float(end["lng"])
            pickup_km = float(item.get("distance_km"))
            haul_km = haversine_km(start_lat, start_lng, end_lat, end_lng)
            price_yuan = float(cargo.get("price", 0.0))
            cost_time_minutes = int(cargo.get("cost_time_minutes", 0) or 0)
            create_minutes = wall_time_to_minutes(str(cargo["create_time"]))
            remove_minutes = wall_time_to_minutes(str(cargo["remove_time"]))
        except (KeyError, TypeError, ValueError):
            return None

        if cost_time_minutes <= 0:
            return None
        if remove_minutes < create_minutes:
            remove_minutes = create_minutes

        pickup_minutes = distance_to_minutes(pickup_km, self.settings.speed_km_per_hour)
        if pickup_km <= 1e-6:
            pickup_minutes = 0
        arrival_minutes = action_start_minutes + pickup_minutes

        feasible = True
        reject_reasons: list[str] = []
        wait_minutes = 0
        load_start_minutes: int | None = None
        load_end_minutes: int | None = None
        try:
            load_window = parse_load_window(cargo.get("load_time"))
        except ValueError:
            load_window = None
            feasible = False
            reject_reasons.append("bad_load_window")
        if load_window is not None:
            load_start_minutes, load_end_minutes = load_window
            if arrival_minutes > load_end_minutes:
                feasible = False
                reject_reasons.append("miss_load_window")
            wait_minutes = max(0, load_start_minutes - arrival_minutes)

        ready_minutes = arrival_minutes + wait_minutes
        finish_minutes = ready_minutes + cost_time_minutes
        if create_minutes > action_start_minutes:
            feasible = False
            reject_reasons.append("not_created_yet")
        if remove_minutes < action_start_minutes:
            feasible = False
            reject_reasons.append("expired_after_query_scan")
        elif remove_minutes < ready_minutes:
            feasible = False
            reject_reasons.append("expires_before_pickup_ready")
        if finish_minutes > self.settings.simulation_horizon_minutes:
            feasible = False
            reject_reasons.append("horizon_exceeded")

        truck_lengths = cargo.get("truck_length") or []
        driver_truck_length = str(status.get("truck_length", "")).strip()
        if isinstance(truck_lengths, list) and truck_lengths and driver_truck_length not in truck_lengths:
            feasible = False
            reject_reasons.append("truck_mismatch")

        cost_per_km = get_cost_per_km(status)
        estimated_net = price_yuan - (pickup_km + haul_km) * cost_per_km
        total_exec_minutes = pickup_minutes + wait_minutes + cost_time_minutes
        net_per_hour = estimated_net / max(total_exec_minutes / 60.0, 1e-9)
        price_per_hour = price_yuan / max(cost_time_minutes / 60.0, 1e-9)
        destination_hotspot_score = destination_hotspot_score_for_cargo(cargo)
        if estimated_net <= 0:
            feasible = False
            reject_reasons.append("non_positive_net")

        return {
            "cargo_id": cargo_id,
            "feasible": feasible,
            "reject_reasons": reject_reasons,
            "price_yuan": price_yuan,
            "start_lat": start_lat,
            "start_lng": start_lng,
            "end_lat": end_lat,
            "end_lng": end_lng,
            "pickup_km": pickup_km,
            "pickup_minutes": pickup_minutes,
            "haul_km": haul_km,
            "wait_minutes": wait_minutes,
            "cost_time_minutes": cost_time_minutes,
            "total_exec_minutes": total_exec_minutes,
            "arrival_minutes": arrival_minutes,
            "load_start_minutes": load_start_minutes,
            "load_end_minutes": load_end_minutes,
            "finish_minutes": finish_minutes,
            "create_minutes": create_minutes,
            "remove_minutes": remove_minutes,
            "lifecycle_slack_minutes": remove_minutes - ready_minutes,
            "estimated_net": estimated_net,
            "net_per_hour": net_per_hour,
            "price_per_hour": price_per_hour,
            "destination_hotspot_score": destination_hotspot_score,
            "cargo_name": str(cargo.get("cargo_name", "") or "").strip(),
            "start_city": str(start.get("city", "") or "").strip(),
            "end_city": str(end.get("city", "") or "").strip(),
            "raw_cargo": cargo,
            "speed_km_per_hour": self.settings.speed_km_per_hour,
            "score": 0.0,
        }

    def _build_fallback_action(self, status: dict[str, Any]) -> dict[str, Any]:
        current_minutes = int(status.get("simulation_progress_minutes", 0))
        hour = hour_of_day(current_minutes)
        if hour >= 23:
            duration = (24 * 60 - (current_minutes % 1440)) + 6 * 60
        elif hour < 6:
            duration = 6 * 60 - (current_minutes % 1440)
        else:
            duration = self.settings.fallback_wait_minutes
        remaining = self.settings.simulation_horizon_minutes - current_minutes
        duration = max(1, min(int(duration), int(remaining) if remaining > 0 else 1))
        return {"action": "wait", "params": {"duration_minutes": duration}}


def destination_hotspot_score_for_cargo(cargo: dict[str, Any]) -> float:
    end = cargo.get("end") or {}
    city = str(end.get("city", "")).strip()
    if city in HOTSPOT_CITY_SCORE:
        return HOTSPOT_CITY_SCORE[city]
    for key, score in HOTSPOT_CITY_SCORE.items():
        if key in city or city in key:
            return score
    return 0.0


def parse_load_window(raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("load_time 格式无效")
    start = wall_time_to_minutes(str(raw[0]))
    end = wall_time_to_minutes(str(raw[1]))
    if end < start:
        raise ValueError("load_time 结束早于开始")
    return start, end


def wall_time_to_minutes(text: str) -> int:
    dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")
    return int((dt - _SIMULATION_EPOCH).total_seconds() // 60)


def distance_to_minutes(distance_km: float, speed_km_per_hour: float) -> int:
    if distance_km <= 0:
        return 1
    return max(1, math.ceil((distance_km / speed_km_per_hour) * 60.0))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
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


def hour_of_day(simulation_minutes: int) -> int:
    return (int(simulation_minutes) // 60) % 24


def preferences_text(status: dict[str, Any]) -> str:
    prefs = status.get("preferences") or []
    if not isinstance(prefs, list):
        return ""
    out: list[str] = []
    for item in prefs:
        if isinstance(item, dict):
            content = item.get("content")
            if content is None:
                content = item.get("text")
            if content:
                out.append(str(content))
        elif item:
            out.append(str(item))
    return "\n".join(out)


def extract_home_coordinate(text: str) -> tuple[float, float] | None:
    idx = text.find("家坐标")
    if idx >= 0:
        match = _COORD_RE.search(text[idx:])
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def extract_target_coordinate(text: str) -> tuple[float, float] | None:
    idx = text.find("目标点坐标")
    if idx >= 0:
        match = _COORD_RE.search(text[idx:])
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def extract_forbidden_zone(text: str) -> tuple[float, float, float] | None:
    idx = text.find("不想进入的区域")
    if idx < 0:
        idx = text.find("禁入")
    if idx < 0:
        return None
    sub = text[idx:]
    coord = _COORD_RE.search(sub)
    radius = re.search(r"半径\s*(\d+(?:\.\d+)?)\s*km", sub, flags=re.IGNORECASE)
    if coord and radius:
        return float(coord.group(1)), float(coord.group(2)), float(radius.group(1))
    return None


def overlaps_night_window(start_minutes: int, end_minutes: int, start_hour: int, end_hour: int) -> bool:
    if end_minutes <= start_minutes:
        return False
    start_day = start_minutes // 1440
    end_day = end_minutes // 1440
    for day in range(start_day - 1, end_day + 2):
        window_start = day * 1440 + start_hour * 60
        window_end = day * 1440 + end_hour * 60
        if end_hour <= start_hour:
            window_end += 1440
        if max(start_minutes, window_start) < min(end_minutes, window_end):
            return True
    return False


def get_cost_per_km(status: dict[str, Any]) -> float:
    try:
        value = float(status.get("cost_per_km", 1.5))
    except (TypeError, ValueError):
        value = 1.5
    return max(0.0, value)


def preference_reposition_or_wait(status: dict[str, Any], speed_km_per_hour: float) -> dict[str, Any] | None:
    prefs = preferences_text(status)
    current_minutes = int(status.get("simulation_progress_minutes", 0))
    minute_of_day = current_minutes % 1440
    current_lat = float(status.get("current_lat", 0.0))
    current_lng = float(status.get("current_lng", 0.0))

    if "23:00到次日04:00" in prefs and (minute_of_day >= 23 * 60 or minute_of_day < 4 * 60):
        target = 4 * 60 if minute_of_day < 4 * 60 else 24 * 60 + 4 * 60
        return {"action": "wait", "params": {"duration_minutes": max(1, target - minute_of_day)}}

    if "23:00前回到家" in prefs:
        home = extract_home_coordinate(prefs)
        if home is None:
            return None
        home_lat, home_lng = home
        dist_home = haversine_km(current_lat, current_lng, home_lat, home_lng)
        if minute_of_day >= 23 * 60 or minute_of_day < 8 * 60:
            target = 8 * 60 if minute_of_day < 8 * 60 else 24 * 60 + 8 * 60
            return {"action": "wait", "params": {"duration_minutes": max(1, target - minute_of_day)}}
        travel_home_minutes = distance_to_minutes(dist_home, speed_km_per_hour)
        if dist_home > 1.0 and minute_of_day + travel_home_minutes >= 23 * 60:
            return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
    return None


def preference_risk(
    *,
    status: dict[str, Any],
    action_start_minutes: int,
    finish_minutes: int,
    end_lat: float,
    end_lng: float,
    speed_km_per_hour: float,
) -> float:
    prefs = preferences_text(status)
    risk = 0.0
    if "23:00到次日04:00" in prefs and overlaps_night_window(action_start_minutes, finish_minutes, 23, 4):
        return 1_000_000.0

    if "23:00前回到家" in prefs:
        home = extract_home_coordinate(prefs)
        if home is not None:
            home_lat, home_lng = home
            finish_day_minute = finish_minutes % 1440
            if overlaps_night_window(action_start_minutes, finish_minutes, 23, 8):
                return 1_000_000.0
            minutes_to_home = distance_to_minutes(
                haversine_km(end_lat, end_lng, home_lat, home_lng),
                speed_km_per_hour,
            )
            if finish_day_minute < 23 * 60 and finish_day_minute + minutes_to_home > 23 * 60:
                risk += 5000.0

    if "不想进入的区域" in prefs or "禁入" in prefs:
        forbidden = extract_forbidden_zone(prefs)
        if forbidden is not None:
            center_lat, center_lng, radius_km = forbidden
            if haversine_km(end_lat, end_lng, center_lat, center_lng) <= radius_km:
                return 1_000_000.0
    return risk


def preference_bonus(*, status: dict[str, Any], end_lat: float, end_lng: float) -> float:
    prefs = preferences_text(status)
    if "目标点坐标" not in prefs:
        return 0.0
    target = extract_target_coordinate(prefs)
    if target is None:
        return 0.0
    target_lat, target_lng = target
    dist = haversine_km(end_lat, end_lng, target_lat, target_lng)
    return 300.0 if dist <= 1.0 else max(0.0, 80.0 - dist * 4.0)


def _load_float_setting(*, env_name: str, config_key: str, default: float) -> float:
    env_value = os.getenv(env_name)
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            return default
    demo_root = Path(__file__).resolve().parents[2]
    for path in (
        demo_root / "server" / "config" / "config.json",
        demo_root / "server" / "config" / "config.example.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get(config_key)
            if isinstance(value, (int, float)):
                return float(value)
        except Exception:
            continue
    return default
