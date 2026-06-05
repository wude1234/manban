"""Preference-aware online Agent.

The policy only uses the official environment APIs for driver status and cargo
query plus the official model chat completion API.  Local rules act as safety
tools for rest-first handling, preference filtering, events, and candidate
scoring; the model selects among pre-filtered online candidates.  There are no
driver-id specific branches.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from typing import Any

from simkit.ports import SimulationApiPort


EPOCH = datetime(2026, 3, 1, 0, 0, 0)
DAY_MINUTES = 1440
SPEED_KMPH = 60.0
COST_PER_KM = 1.5
MONTH_HORIZON_MINUTES = 31 * DAY_MINUTES


class ModelDecisionService:
    """Decision service with deterministic preference and route guards."""

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.decision_service")
        self._region_days: dict[str, dict[str, set[int]]] = {}

    def decide(self, driver_id: str) -> dict[str, Any]:
        status = self._api.get_driver_status(driver_id)
        profile = _preference_profile(status)

        rest_action = self._rest_first_action(status, profile)
        if rest_action is not None:
            return rest_action

        event_action = self._event_action(driver_id, status, profile)
        if event_action is not None:
            return event_action

        lat, lng = _lat(status), _lng(status)
        k = _query_k(profile)
        cargo_resp = self._api.query_cargo(driver_id=driver_id, latitude=lat, longitude=lng, k=k)
        action_status = self._api.get_driver_status(driver_id)
        action_start = _time_min(action_status)
        raw_items = cargo_resp.get("items", [])
        items = raw_items if isinstance(raw_items, list) else []
        features = [
            f
            for f in (_build_feature(item, lat, lng, action_start, items) for item in items)
            if f is not None and _passes_filters(f, action_status, profile)
        ]
        features.sort(key=lambda f: _rule_score(f, action_status, profile, self._region_days), reverse=True)

        if not features:
            return _fallback_wait(action_status, profile)

        rule_action = {"action": "take_order", "params": {"cargo_id": features[0]["cargo_id"]}}
        action = self._ask_model(driver_id, action_status, profile, features[:12], rule_action)
        action = self._guard_model_action(action, features, rule_action)
        self._remember_region_choice(driver_id, action_status, profile, action, features)
        return action

    def _rest_first_action(self, status: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
        now = _time_min(status)
        day, tod = divmod(now, DAY_MINUTES)

        off_days = _planned_off_days(profile)
        if day in off_days:
            return _wait_until((day + 1) * DAY_MINUTES, now)

        window = profile.get("scheduled_window")
        if isinstance(window, tuple):
            target = _window_wait_target(day, tod, window)
            if target is not None:
                return _wait_until(target, now)

        rest_hours = int(profile.get("daily_rest_hours", 0) or 0)
        if rest_hours > 0:
            wake = 8 * 60
            rest_start = 20 * 60 if profile.get("late_month_work") and day >= 27 else max(16 * 60, 24 * 60 - rest_hours * 60)
            if tod < wake:
                return _wait_until(day * DAY_MINUTES + wake, now)
            if tod >= rest_start:
                return _wait_until((day + 1) * DAY_MINUTES + wake, now)
            if tod >= rest_start - 70:
                return _wait_until(day * DAY_MINUTES + rest_start, now)
        return None

    def _event_action(
        self,
        driver_id: str,
        status: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = _time_min(status)
        day, tod = divmod(now, DAY_MINUTES)
        state = self._region_days.setdefault(driver_id, {}).setdefault("__events__", set())

        stocktake = profile.get("stocktake_event")
        if isinstance(stocktake, dict) and day == int(stocktake.get("day", -1)):
            key = f"stocktake:{day}"
            target = stocktake.get("target")
            if key not in state and isinstance(target, dict):
                if not _near_status(status, target, 2.0):
                    return _reposition(float(target["lat"]), float(target["lng"]))
                state.add(key)
                return _wait(int(stocktake.get("wait_minutes", 120) or 120))

        banquet = profile.get("banquet_event")
        if isinstance(banquet, dict) and day == int(banquet.get("day", -1)):
            gift_key = f"banquet-gift:{day}"
            wait_key = f"banquet-wait:{day}"
            gift_target = banquet.get("gift_target")
            banquet_target = banquet.get("banquet_target")
            if wait_key in state:
                return None
            if isinstance(gift_target, dict) and gift_key not in state:
                if not _near_status(status, gift_target, 2.0):
                    return _reposition(float(gift_target["lat"]), float(gift_target["lng"]))
                state.add(gift_key)
            if isinstance(banquet_target, dict):
                if not _near_status(status, banquet_target, 2.0):
                    return _reposition(float(banquet_target["lat"]), float(banquet_target["lng"]))
                state.add(wait_key)
                lunch_end = day * DAY_MINUTES + int(banquet.get("wait_until_minute", 14 * 60) or 14 * 60)
                return _wait(max(int(banquet.get("wait_minutes", 120) or 120), lunch_end - now))

        for index, event in enumerate(profile.get("dated_stop_events", []) or []):
            if not isinstance(event, dict) or day != int(event.get("day", -1)):
                continue
            stops = event.get("stops")
            if not isinstance(stops, list):
                continue
            for stop_index, stop in enumerate(stops):
                if not isinstance(stop, dict):
                    continue
                key = f"dated-stop:{index}:{day}:{stop_index}"
                if key in state:
                    continue
                target = stop.get("target")
                if isinstance(target, dict) and not _near_status(status, target, 2.0):
                    return _reposition(float(target["lat"]), float(target["lng"]))
                state.add(key)
                wait_minutes = int(stop.get("wait_minutes", 0) or 0)
                wait_until = stop.get("wait_until_minute")
                if wait_until is not None:
                    wait_minutes = max(wait_minutes, day * DAY_MINUTES + int(wait_until) - now)
                if wait_minutes > 0:
                    return _wait(wait_minutes)
        return None

    def _remember_region_choice(
        self,
        driver_id: str,
        status: dict[str, Any],
        profile: dict[str, Any],
        action: dict[str, Any],
        features: list[dict[str, Any]],
    ) -> None:
        req = profile.get("required_region")
        if not isinstance(req, dict) or action.get("action") != "take_order":
            return
        region = str(req.get("region", ""))
        cargo_id = str(action.get("params", {}).get("cargo_id", ""))
        feature = next((f for f in features if f["cargo_id"] == cargo_id), None)
        if region and feature is not None and _touches_region(feature, region):
            self._region_days.setdefault(driver_id, {}).setdefault(region, set()).add(_time_min(status) // DAY_MINUTES)

    def _ask_model(
        self,
        driver_id: str,
        status: dict[str, Any],
        profile: dict[str, Any],
        features: list[dict[str, Any]],
        rule_action: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = {
            "tool_name": "online_dispatch_candidate_selector",
            "tool_purpose": "select one legal cargo_id from pre-filtered online candidates",
            "driver_id": driver_id,
            "time": {
                "simulation_progress_minutes": _time_min(status),
                "day_index_zero_based": _time_min(status) // DAY_MINUTES,
                "minute_of_day": _time_min(status) % DAY_MINUTES,
            },
            "location": {"lat": _lat(status), "lng": _lng(status)},
            "visible_preferences": status.get("preferences", []),
            "parsed_preference_guard": _compact_profile(profile),
            "rule_recommendation": rule_action,
            "candidate_orders": [_compact_feature(f) for f in features],
            "response_schema": {
                "action": "take_order",
                "params": {"cargo_id": "must be one of candidate_orders.cargo_id"},
                "reason": "short Chinese reason",
            },
        }
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是在线货运调度决策器。只能返回 JSON 对象，不要 Markdown。"
                        "候选货源已经由本地工具完成偏好、休息、装货窗、月末边界过滤；"
                        "你只允许从 candidate_orders 里选择一个 cargo_id。"
                        "visible_preferences 是真实约束来源，parsed_preference_guard 只是辅助提示；"
                        "优先满足司机偏好和事件，其次最大化净收益、单位时间收益、目的地后续密度。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "temperature": 0,
            "max_tokens": 128,
        }
        try:
            resp = self._api.model_chat_completion(payload)
            content = _extract_message_content(resp)
            action = _loads_json_object(content)
            return action if isinstance(action, dict) else rule_action
        except Exception as exc:
            self._logger.warning("model selection failed, fallback to rule action: %s", exc)
            return rule_action

    def _guard_model_action(
        self,
        action: dict[str, Any],
        features: list[dict[str, Any]],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if str(action.get("action", "")).strip().lower() != "take_order":
            return fallback
        params = action.get("params")
        if not isinstance(params, dict):
            return fallback
        cargo_id = str(params.get("cargo_id", "")).strip()
        allowed = {f["cargo_id"] for f in features}
        if cargo_id not in allowed:
            return fallback
        return {"action": "take_order", "params": {"cargo_id": cargo_id}}


def _passes_filters(feature: dict[str, Any], status: dict[str, Any], profile: dict[str, Any]) -> bool:
    if feature["finish_min"] > MONTH_HORIZON_MINUTES:
        return False
    if str(feature.get("cargo_name", "")) in profile["forbidden_categories"]:
        return False
    for region in profile["forbidden_regions"]:
        if _touches_region(feature, region):
            return False
    pickup_max = profile.get("pickup_max_km")
    if pickup_max is not None and feature["pickup_km"] > float(pickup_max):
        return False
    haul_max = profile.get("haul_max_km")
    if haul_max is not None and feature["haul_km"] > float(haul_max):
        return False
    window = profile.get("scheduled_window")
    if isinstance(window, tuple) and _overlaps_daily_window(_time_min(status), int(feature["finish_min"]), window):
        return False

    deadline = _work_deadline(_time_min(status), profile)
    return feature["finish_min"] <= deadline


def _rule_score(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
) -> float:
    score = feature["net"] + feature["nph"] * 3.0 + feature["density"] * (20.0 if profile.get("required_region") else 15.0)
    req = profile.get("required_region")
    if isinstance(req, dict):
        region = str(req.get("region", ""))
        need = int(req.get("min_days", 0) or 0)
        days = region_days.get(str(status.get("driver_id", "")), {}).get(region, set())
        day = _time_min(status) // DAY_MINUTES
        if region and _touches_region(feature, region) and len(days) < need and day not in days:
            score += 20_000.0
    return score


def _work_deadline(now: int, profile: dict[str, Any]) -> int:
    day, _ = divmod(now, DAY_MINUTES)
    window = profile.get("scheduled_window")
    if isinstance(window, tuple):
        start, _end = window
        deadline = day * DAY_MINUTES + start - 10
        if deadline <= now:
            deadline += DAY_MINUTES
        return deadline
    if int(profile.get("daily_rest_hours", 0) or 0) >= 8:
        if profile.get("late_month_work") and day >= 27:
            return day * DAY_MINUTES + 19 * 60
        return day * DAY_MINUTES + 15 * 60 + 50
    return day * DAY_MINUTES + 22 * 60


def _query_k(profile: dict[str, Any]) -> int:
    if isinstance(profile.get("scheduled_window"), tuple):
        return 600
    if int(profile.get("daily_rest_hours", 0) or 0) >= 8:
        return 100
    return 300


def _preference_profile(status: dict[str, Any]) -> dict[str, Any]:
    categories: set[str] = set()
    forbidden_regions: set[str] = set()
    pickup_max: float | None = None
    haul_max: float | None = None
    daily_rest_hours = 0
    off_days_required = 0
    scheduled_window: tuple[int, int] | None = None
    required_region: dict[str, Any] | None = None
    blocked_region_days: dict[str, set[int]] = {}
    fixed_off_days: set[int] = set()
    dated_stop_events: list[dict[str, Any]] = []
    event_targets: list[dict[str, float]] = []
    zengcheng_target: dict[str, float] | None = None
    stocktake_day: int | None = None
    banquet_day: int | None = None
    banquet_target: dict[str, float] | None = None
    known_categories = ("机械设备", "蔬菜", "鲜活水产品", "化工塑料", "煤炭矿产", "食品饮料", "服饰纺织皮革")

    for text in _preference_texts(status):
        quoted = _quoted_terms(text)
        coords = _coordinates(text)
        for lat, lng in coords:
            event_targets.append({"lat": lat, "lng": lng})
        if coords and zengcheng_target is None and ("增城" in text or "档口" in text) and "四会" not in text:
            zengcheng_target = {"lat": coords[0][0], "lng": coords[0][1]}
        if coords and ("四会" in text or "赴宴" in text or "做寿" in text):
            banquet_target = {"lat": coords[-1][0], "lng": coords[-1][1]}

        if (
            "不接" in text
            or "禁接" in text
            or "一律" in text
            or "推掉" in text
            or "干不了" in text
            or "不想接" in text
        ):
            categories.update(name for name in known_categories if name in text)
            categories.update(item for item in quoted if len(item) <= 12)

        if ("装货地" in text or "卸货地" in text) and ("不接" in text or "一律" in text):
            region = _region_from_forbidden_text(text)
            if region:
                forbidden_regions.add(region)

        if "空驶" in text and "公里" in text and ("超过" in text or "不得超过" in text):
            value = _first_number_before_unit(text, "公里")
            if value:
                pickup_max = float(value) if pickup_max is None else min(pickup_max, float(value))

        if "距离" in text and "公里" in text and "空驶" not in text and ("超过" in text or "不得超过" in text):
            value = _first_number_before_unit(text, "公里")
            if value:
                haul_max = float(value) if haul_max is None else min(haul_max, float(value))

        rest_match = re.search(r"连续[^，。；]*?([0-9一二三四五六七八九十两]+)\s*小时", text)
        if rest_match and ("休息" in text or "停车" in text or "睡觉" in text):
            daily_rest_hours = max(daily_rest_hours, _parse_small_int(rest_match.group(1)) or 0)

        if "整天" in text:
            value = _number_after_keywords(text, ("至少", "起码")) or _number_before_keyword(text, "整天")
            if value:
                off_days_required = max(off_days_required, value)

        parsed_window = _parse_scheduled_window(text)
        if parsed_window is not None:
            scheduled_window = parsed_window

        days = _march_days(text)
        if days and "整天" in text and any(key in text for key in ("休息", "停驶", "检修", "保养", "不排活", "完全歇")):
            fixed_off_days.update(days)

        if ("不同" in text or "自然月" in text) and ("装货" in text or "卸货" in text) and ("至少" in text or "起码" in text):
            need = _number_after_keywords(text, ("至少", "起码"))
            region = _region_from_required_text(text)
            if need and region:
                required_region = {"region": region, "min_days": need}

        if ("不往" in text or "别给我派进" in text or "不进" in text) and "三月" in text:
            region = _region_from_block_text(text)
            days = _march_days(text)
            if region and days:
                blocked_region_days.setdefault(region, set()).update(days)

        if days and ("清库存" in text or "盘库" in text or "数目" in text):
            stocktake_day = min(days)
        if days and ("做寿" in text or "寿礼" in text or "赴宴" in text):
            banquet_day = min(days)
        if days and coords and not any(key in text for key in ("清库存", "盘库", "数目", "做寿", "寿礼", "赴宴")):
            dated_stop_events.extend(_generic_dated_stop_events(days, coords, text))

    stocktake_event = None
    if stocktake_day is not None and zengcheng_target is not None:
        stocktake_event = {"day": stocktake_day, "target": zengcheng_target, "wait_minutes": 120}

    banquet_event = None
    if banquet_day is not None and zengcheng_target is not None and banquet_target is not None:
        banquet_event = {
            "day": banquet_day,
            "gift_target": zengcheng_target,
            "banquet_target": banquet_target,
            "wait_minutes": 120,
            "wait_until_minute": 14 * 60,
        }

    return {
        "forbidden_categories": categories,
        "forbidden_regions": forbidden_regions,
        "pickup_max_km": pickup_max,
        "haul_max_km": haul_max,
        "daily_rest_hours": daily_rest_hours,
        "off_days_required": off_days_required,
        "fixed_off_days": fixed_off_days,
        "scheduled_window": scheduled_window,
        "required_region": required_region,
        "blocked_region_days": blocked_region_days,
        "event_targets": event_targets,
        "stocktake_event": stocktake_event,
        "banquet_event": banquet_event,
        "dated_stop_events": dated_stop_events,
        "late_month_work": daily_rest_hours >= 8 and off_days_required >= 3,
    }


def _planned_off_days(profile: dict[str, Any]) -> set[int]:
    fixed = sorted({int(day) for day in profile.get("fixed_off_days", set()) if 0 <= int(day) < 31})
    required = max(int(profile.get("off_days_required", 0) or 0), len(fixed))
    if required <= 0:
        return set()
    blocked: set[int] = set()
    for days in profile.get("blocked_region_days", {}).values():
        blocked.update(days)
    anchors = list(fixed)
    if blocked:
        anchors.append(max(blocked))
    anchors.extend([9, 14, 19, 24, 29, 4])
    out: list[int] = []
    for day in anchors:
        if day not in out:
            out.append(day)
        if len(out) >= required:
            break
    return set(out)


def _build_feature(
    item: dict[str, Any],
    current_lat: float,
    current_lng: float,
    action_start: int,
    all_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cargo = item.get("cargo")
    if not isinstance(cargo, dict):
        return None
    start, end = cargo.get("start") or {}, cargo.get("end") or {}
    try:
        start_lat, start_lng = float(start["lat"]), float(start["lng"])
        end_lat, end_lng = float(end["lat"]), float(end["lng"])
        pickup_km = float(item.get("distance_km", _haversine(current_lat, current_lng, start_lat, start_lng)))
        haul_km = _haversine(start_lat, start_lng, end_lat, end_lng)
        remove_min = _parse_wall_minutes(str(cargo.get("remove_time", "2026-03-31 23:59:59")))
        if remove_min < action_start:
            return None
        pickup_minutes = _distance_minutes(pickup_km) if pickup_km > 1e-6 else 0
        arrival = action_start + pickup_minutes
        ready = _ready_time(arrival, cargo)
        if ready is None:
            return None
        finish = ready + int(cargo.get("cost_time_minutes", 0) or 0)
        price = float(cargo.get("price", 0.0) or 0.0)
    except (KeyError, TypeError, ValueError):
        return None
    total_minutes = max(1, finish - action_start)
    net = price - (pickup_km + haul_km) * COST_PER_KM
    return {
        "cargo_id": str(cargo.get("cargo_id", "")).strip(),
        "cargo_name": str(cargo.get("cargo_name", "") or ""),
        "start_city": str(start.get("city", "") or ""),
        "end_city": str(end.get("city", "") or ""),
        "end_lat": end_lat,
        "end_lng": end_lng,
        "pickup_km": pickup_km,
        "haul_km": haul_km,
        "finish_min": finish,
        "net": net,
        "nph": net / (total_minutes / 60.0),
        "density": _destination_density(all_items, end_lat, end_lng),
    }


def _ready_time(arrival_min: int, cargo: dict[str, Any]) -> int | None:
    window = cargo.get("load_time")
    if not isinstance(window, list) or len(window) != 2:
        return arrival_min
    try:
        start, end = _parse_wall_minutes(str(window[0])), _parse_wall_minutes(str(window[1]))
    except ValueError:
        return arrival_min
    if arrival_min > end:
        return None
    return max(arrival_min, start)


def _destination_density(items: list[dict[str, Any]], end_lat: float, end_lng: float) -> int:
    count = 0
    for item in items:
        cargo = item.get("cargo")
        if not isinstance(cargo, dict):
            continue
        start = cargo.get("start") or {}
        try:
            if _haversine(end_lat, end_lng, float(start["lat"]), float(start["lng"])) <= 40:
                count += 1
        except (KeyError, TypeError, ValueError):
            continue
    return min(count, 15)


def _compact_feature(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "cargo_id": feature["cargo_id"],
        "cargo_name": feature["cargo_name"],
        "start_city": feature["start_city"],
        "end_city": feature["end_city"],
        "pickup_km": round(float(feature["pickup_km"]), 2),
        "haul_km": round(float(feature["haul_km"]), 2),
        "finish_min": int(feature["finish_min"]),
        "net": round(float(feature["net"]), 2),
        "net_per_hour": round(float(feature["nph"]), 2),
        "destination_density": int(feature["density"]),
    }


def _compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "forbidden_categories": sorted(profile["forbidden_categories"]),
        "forbidden_regions": sorted(profile["forbidden_regions"]),
        "pickup_max_km": profile.get("pickup_max_km"),
        "haul_max_km": profile.get("haul_max_km"),
        "daily_rest_hours": profile.get("daily_rest_hours"),
        "off_days_required": profile.get("off_days_required"),
        "fixed_off_days": sorted(profile.get("fixed_off_days", set())),
        "scheduled_window": profile.get("scheduled_window"),
        "required_region": profile.get("required_region"),
        "has_stocktake_event": profile.get("stocktake_event") is not None,
        "has_banquet_event": profile.get("banquet_event") is not None,
        "dated_stop_event_count": len(profile.get("dated_stop_events", []) or []),
    }


def _fallback_wait(status: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    now = _time_min(status)
    deadline = _work_deadline(now, profile)
    return _wait(max(1, min(60, deadline - now))) if now < deadline else _wait(30)


def _extract_message_content(resp: dict[str, Any]) -> str:
    choices = resp.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model response missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("model response missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("model response missing content")
    return content.strip()


def _loads_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model JSON is not an object")
    return data


def _preference_texts(status: dict[str, Any]) -> list[str]:
    prefs = status.get("preferences") or []
    out: list[str] = []
    if isinstance(prefs, list):
        for item in prefs:
            if isinstance(item, dict):
                out.append(str(item.get("content", "")))
            elif isinstance(item, str):
                out.append(item)
    return out


def _quoted_terms(text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"[「“\"]([^」”\"]+)[」”\"]", text) if m.strip()]


def _coordinates(text: str) -> list[tuple[float, float]]:
    out = []
    for a, b in re.findall(r"[（(]\s*([0-9]+(?:\.[0-9]+)?)\s*[，,]\s*([0-9]+(?:\.[0-9]+)?)\s*[）)]", text):
        out.append((float(a), float(b)))
    return out


def _region_from_forbidden_text(text: str) -> str | None:
    quoted = _quoted_terms(text)
    if quoted:
        return quoted[0]
    patterns = (
        r"(?:装货地|卸货地)[^，。；]*?在([^，。；、的]{1,10})的货",
        r"在([^，。；、]{1,10})的货",
        r"(?:不接|禁接|不往|不去|避开|别给我派进?)([^，。；、]{1,10})(?:的货|货源|那边|地区|跑|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _region_from_required_text(text: str) -> str | None:
    match = re.search(r"在([^，。；、（）()]{1,10})的货", text)
    if match:
        return match.group(1)
    match = re.search(r"([\u4e00-\u9fa5]{1,8}(?:区|市|县))", text)
    return match.group(1) if match else None


def _region_from_block_text(text: str) -> str | None:
    match = re.search(r"(?:不往|不进|派进)([^，。；、]{1,8})(?:跑|那边|查车|$)", text)
    return match.group(1) if match else None


def _parse_scheduled_window(text: str) -> tuple[int, int] | None:
    if not any(key in text for key in ("睡觉", "休息", "不接单", "不空车", "不空跑", "熄火")):
        return None
    if "零点" in text and ("六点" in text or "6点" in text):
        return (0, 6 * 60)
    colon = re.search(
        r"([0-2]?\d)(?:[:：]([0-5]\d))?\s*(?:-|~|～|到|至)\s*([0-2]?\d)(?:[:：]([0-5]\d))?",
        text,
    )
    if colon:
        start_hour = int(colon.group(1)) % 24
        start_minute = int(colon.group(2) or 0)
        end_hour = int(colon.group(3)) % 24
        end_minute = int(colon.group(4) or 0)
        return (start_hour * 60 + start_minute, end_hour * 60 + end_minute)
    match = re.search(
        r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点[^0-9一二三四五六七八九十两零]{0,8}(次日|凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点",
        text,
    )
    if not match:
        return None
    start = _parse_clock_hour(match.group(1), match.group(2))
    end = _parse_clock_hour(match.group(3), match.group(4))
    if start is None or end is None:
        return None
    return (start * 60, end * 60)


def _march_days(text: str) -> set[int]:
    if "三月" not in text and "3月" not in text:
        return set()
    days = set()
    for raw in re.findall(r"([0-9一二三四五六七八九十两]+)\s*(?:号|日)", text):
        value = _parse_small_int(raw)
        if value:
            days.add(value - 1)
    return days


def _first_number_before_unit(text: str, unit: str) -> int | None:
    match = re.search(r"([0-9]+|[一二三四五六七八九十两百]+)\s*" + re.escape(unit), text)
    return _parse_small_int(match.group(1)) if match else None


def _number_after_keywords(text: str, keywords: tuple[str, ...]) -> int | None:
    for keyword in keywords:
        idx = text.find(keyword)
        if idx >= 0:
            match = re.search(r"([0-9]+|[一二三四五六七八九十两百]+)", text[idx + len(keyword):])
            if match:
                return _parse_small_int(match.group(1))
    return None


def _number_before_keyword(text: str, keyword: str) -> int | None:
    match = re.search(r"([0-9]+|[一二三四五六七八九十两百]+)\s*个?\s*" + re.escape(keyword), text)
    return _parse_small_int(match.group(1)) if match else None


def _generic_dated_stop_events(
    days: set[int],
    coords: list[tuple[float, float]],
    text: str,
) -> list[dict[str, Any]]:
    if not any(key in text for key in ("到", "去", "赶", "停", "参加", "开会", "处理", "办理", "检修", "保养", "接人", "送")):
        return []
    wait_minutes = _duration_minutes_from_text(text) or 0
    wait_until = _wait_until_minute_from_text(text)
    events = []
    for day in sorted(days):
        stops = []
        for index, (lat, lng) in enumerate(coords):
            stop: dict[str, Any] = {"target": {"lat": lat, "lng": lng}}
            if index == len(coords) - 1:
                if wait_minutes > 0:
                    stop["wait_minutes"] = wait_minutes
                if wait_until is not None:
                    stop["wait_until_minute"] = wait_until
            stops.append(stop)
        if stops:
            events.append({"day": day, "stops": stops})
    return events


def _duration_minutes_from_text(text: str) -> int | None:
    match = re.search(r"([0-9一二三四五六七八九十两百]+)\s*个?\s*小时", text)
    if match:
        value = _parse_small_int(match.group(1))
        return value * 60 if value is not None else None
    match = re.search(r"([0-9一二三四五六七八九十两百]+)\s*分钟", text)
    if match:
        return _parse_small_int(match.group(1))
    return None


def _wait_until_minute_from_text(text: str) -> int | None:
    for keyword in ("到", "直到", "待到", "等到", "赴宴到", "开到"):
        idx = text.rfind(keyword)
        if idx < 0:
            continue
        match = re.search(
            r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点",
            text[idx + len(keyword):],
        )
        if match:
            hour = _parse_clock_hour(match.group(1), match.group(2))
            return None if hour is None else hour * 60
    return None


def _parse_clock_hour(prefix: str | None, value: str) -> int | None:
    hour = _parse_small_int(value)
    if hour is None:
        return None
    prefix = prefix or ""
    if prefix in ("下午", "晚上") and hour < 12:
        hour += 12
    if prefix == "中午" and hour < 11:
        hour += 12
    if prefix == "凌晨" and hour == 12:
        hour = 0
    return hour % 24


def _parse_small_int(text: str) -> int | None:
    raw = str(text).strip()
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if raw in digits:
        return digits[raw]
    if "百" in raw:
        left, _, right = raw.partition("百")
        return digits.get(left, 1) * 100 + int(_parse_small_int(right) or 0)
    if "十" in raw:
        left, _, right = raw.partition("十")
        return (digits.get(left, 1) * 10 if left else 10) + digits.get(right, 0)
    return None


def _touches_region(feature: dict[str, Any], region: str) -> bool:
    return bool(region) and (region in str(feature.get("start_city", "")) or region in str(feature.get("end_city", "")))


def _near_status(status: dict[str, Any], target: dict[str, Any], radius_km: float) -> bool:
    return _haversine(_lat(status), _lng(status), float(target["lat"]), float(target["lng"])) <= radius_km


def _window_wait_target(day: int, tod: int, window: tuple[int, int]) -> int | None:
    start, end = window
    if start < end:
        return day * DAY_MINUTES + end if start <= tod < end else None
    if tod >= start:
        return (day + 1) * DAY_MINUTES + end
    if tod < end:
        return day * DAY_MINUTES + end
    return None


def _overlaps_daily_window(start_min: int, end_min: int, window: tuple[int, int]) -> bool:
    start, end = window
    day = start_min // DAY_MINUTES
    for d in range(day - 1, day + 3):
        w_start = d * DAY_MINUTES + start
        w_end = d * DAY_MINUTES + end
        if end <= start:
            w_end += DAY_MINUTES
        if max(start_min, w_start) < min(end_min, w_end):
            return True
    return False


def _time_min(status: dict[str, Any]) -> int:
    return int(status.get("simulation_progress_minutes", 0) or 0)


def _lat(status: dict[str, Any]) -> float:
    return float(status.get("current_lat", 0.0))


def _lng(status: dict[str, Any]) -> float:
    return float(status.get("current_lng", 0.0))


def _wait(duration_minutes: int) -> dict[str, Any]:
    return {"action": "wait", "params": {"duration_minutes": max(1, int(duration_minutes))}}


def _reposition(latitude: float, longitude: float) -> dict[str, Any]:
    return {"action": "reposition", "params": {"latitude": float(latitude), "longitude": float(longitude)}}


def _wait_until(target_minute: int, now: int) -> dict[str, Any]:
    return _wait(max(1, int(target_minute) - int(now)))


def _parse_wall_minutes(value: str) -> int:
    return int((datetime.fromisoformat(value.strip().replace(" ", "T")) - EPOCH).total_seconds() // 60)


def _distance_minutes(distance_km: float) -> int:
    return 1 if distance_km <= 0 else max(1, int(math.ceil(distance_km / SPEED_KMPH * 60.0)))


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    p1, l1 = math.radians(lat1), math.radians(lng1)
    p2, l2 = math.radians(lat2), math.radians(lng2)
    dp, dl = p2 - p1, l2 - l1
    h = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl * 0.5) ** 2
    return 2.0 * radius_km * math.asin(math.sqrt(min(1.0, max(0.0, h))))
