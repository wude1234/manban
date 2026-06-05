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
SOFT_PENALTY_RISK_FACTOR = 8.0
SOFT_PENALTY_EXCEPTION_MULTIPLIER = 12.0
SOFT_PENALTY_MIN_EXCEPTION_MARGIN = 500.0
SOFT_PENALTY_NPH_FLOOR_RATIO = 0.75
NET_PER_HOUR_SCORE_WEIGHT = 8.0
KNOWN_CARGO_CATEGORIES = ("机械设备", "蔬菜", "鲜活水产品", "化工塑料", "煤炭矿产", "食品饮料", "服饰纺织皮革")


class ModelDecisionService:
    """Decision service with deterministic preference and route guards."""

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.decision_service")
        self._region_days: dict[str, dict[str, set[int]]] = {}
        self._preference_memory = RuntimePreferenceMemory()
        self._compiled_profile_cache: dict[str, dict[str, Any]] = {}

    def decide(self, driver_id: str) -> dict[str, Any]:
        status = self._api.get_driver_status(driver_id)
        history = _decision_history(self._api, driver_id)
        remembered_preferences = self._preference_memory.update(driver_id, status, history)
        memory_context = self._preference_memory.context(driver_id)
        profile = self._compile_profile(driver_id, remembered_preferences)
        self._sync_requirement_progress_from_history(driver_id, profile, history)

        rest_action = self._rest_first_action(status, profile)
        if rest_action is not None:
            return rest_action

        event_action = self._event_action(driver_id, status, profile)
        if event_action is not None:
            return event_action

        schedule_action = self._schedule_guard_action(status, profile, history)
        if schedule_action is not None:
            return schedule_action

        lat, lng = _lat(status), _lng(status)
        k = _query_k(profile)
        pre_query_preferences = list(remembered_preferences)
        cargo_resp = self._api.query_cargo(driver_id=driver_id, latitude=lat, longitude=lng, k=k)
        action_status = self._api.get_driver_status(driver_id)
        remembered_preferences = self._preference_memory.update(driver_id, action_status, history)
        memory_context = self._preference_memory.context(driver_id)
        profile = self._compile_profile(driver_id, remembered_preferences)
        self._sync_requirement_progress_from_history(driver_id, profile, history)
        memory_context = _with_requirement_progress(
            memory_context,
            driver_id,
            action_status,
            profile,
            self._region_days,
            history,
        )

        if remembered_preferences != pre_query_preferences:
            post_query_guard = self._post_query_guard_action(driver_id, action_status, profile, history)
            if post_query_guard is not None:
                return post_query_guard

        action_start = _time_min(action_status)
        raw_items = cargo_resp.get("items", [])
        items = raw_items if isinstance(raw_items, list) else []
        features = [
            f
            for f in (_build_feature(item, lat, lng, action_start, items) for item in items)
            if f is not None and _passes_filters(f, action_status, profile, history)
        ]
        for feature in features:
            _annotate_soft_penalty(feature, action_status, profile, history)
        features = _gate_soft_penalty_candidates(features, action_status, profile, self._region_days, history)
        features.sort(key=lambda f: _rule_score(f, action_status, profile, self._region_days, history), reverse=True)

        if not features:
            return _fallback_wait(action_status, profile)

        rule_action = {"action": "take_order", "params": {"cargo_id": features[0]["cargo_id"]}}
        model_features = _model_candidate_pool(features, action_status, profile, self._region_days, history)
        if _should_ask_model(model_features, action_status, profile, self._region_days, history):
            action = self._ask_model(
                driver_id,
                action_status,
                profile,
                model_features,
                rule_action,
                memory_context,
                self._region_days,
                history,
            )
            action = self._guard_model_action(action, model_features, rule_action, action_status, profile, history)
        else:
            action = rule_action
        self._remember_region_choice(driver_id, action_status, profile, action, features)
        return action

    def _rest_first_action(self, status: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
        now = _time_min(status)
        day, tod = divmod(now, DAY_MINUTES)

        home_action = _home_deadline_action(status, profile)
        if home_action is not None:
            return home_action

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
            wake = 8 * 60 if rest_hours >= 8 else 6 * 60
            rest_start = 20 * 60 if rest_hours >= 8 else 23 * 60
            if tod < wake:
                return _wait_until(day * DAY_MINUTES + wake, now)
            if tod >= rest_start:
                return _wait_until((day + 1) * DAY_MINUTES + wake, now)
            if tod >= rest_start - 70:
                return _wait_until(day * DAY_MINUTES + rest_start, now)
        return None

    def _schedule_guard_action(
        self,
        status: dict[str, Any],
        profile: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        now = _time_min(status)
        day, tod = divmod(now, DAY_MINUTES)
        today_orders = _accepted_orders_on_day(history, day)

        max_daily = profile.get("max_daily_orders")
        if max_daily is not None and today_orders >= int(max_daily):
            return _wait_until((day + 1) * DAY_MINUTES, now)

        first_deadline = profile.get("first_order_deadline_minute")
        if first_deadline is not None and today_orders == 0 and tod >= int(first_deadline):
            return _wait_until((day + 1) * DAY_MINUTES, now)
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
        if action.get("action") != "take_order":
            return
        cargo_id = str(action.get("params", {}).get("cargo_id", ""))
        feature = next((f for f in features if f["cargo_id"] == cargo_id), None)
        if feature is None:
            return

        req = profile.get("required_region")
        if isinstance(req, dict):
            key = _region_requirement_key(req)
            if _feature_touches_region_requirement(feature, req):
                self._region_days.setdefault(driver_id, {}).setdefault(key, set()).add(_time_min(status) // DAY_MINUTES)

        loc_req = profile.get("required_location")
        if isinstance(loc_req, dict) and _feature_touches_location(feature, loc_req):
            key = str(loc_req.get("key", "required_location"))
            self._region_days.setdefault(driver_id, {}).setdefault(key, set()).add(_time_min(status) // DAY_MINUTES)

    def _sync_requirement_progress_from_history(
        self,
        driver_id: str,
        profile: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> None:
        state = self._region_days.setdefault(driver_id, {})
        req = profile.get("required_region")
        if isinstance(req, dict):
            key = _region_requirement_key(req)
            days = state.setdefault(key, set())
            for record in history:
                if _accepted_record_touches_region_requirement(record, req):
                    start, _ = _record_start_end(record)
                    days.add(start // DAY_MINUTES)

        loc_req = profile.get("required_location")
        if isinstance(loc_req, dict):
            key = str(loc_req.get("key", "required_location"))
            days = state.setdefault(key, set())
            for record in history:
                if _accepted_record_touches_location(record, loc_req):
                    start, _ = _record_start_end(record)
                    days.add(start // DAY_MINUTES)

    def _post_query_guard_action(
        self,
        driver_id: str,
        status: dict[str, Any],
        profile: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        rest_action = self._rest_first_action(status, profile)
        if rest_action is not None:
            return rest_action
        event_action = self._event_action(driver_id, status, profile)
        if event_action is not None:
            return event_action
        return self._schedule_guard_action(status, profile, history)

    def _compile_profile(self, driver_id: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        local_profile = _preference_profile_from_entries(entries)
        signature = _preference_entries_signature(entries)
        if not signature:
            self._compiled_profile_cache.pop(driver_id, None)
            return local_profile

        cached = self._compiled_profile_cache.get(driver_id)
        if isinstance(cached, dict) and cached.get("signature") == signature:
            model_profile = cached.get("model_profile")
            return _merge_profiles(local_profile, model_profile if isinstance(model_profile, dict) else None)

        model_profile = self._ask_model_for_preference_profile(driver_id, entries)
        self._compiled_profile_cache[driver_id] = {
            "signature": signature,
            "model_profile": model_profile if isinstance(model_profile, dict) else None,
        }
        return _merge_profiles(local_profile, model_profile if isinstance(model_profile, dict) else None)

    def _ask_model_for_preference_profile(
        self,
        driver_id: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        prompt = {
            "tool_name": "preference_profile_compiler",
            "driver_id": driver_id,
            "task": (
                "Compile legally observed driver preference text into a conservative executable profile. "
                "Use only the provided preference_entries. Do not infer cargo ids or future market data."
            ),
            "date_rule": "The simulation month is March 2026. Day indexes are zero-based: Mar 1 = 0, Mar 31 = 30.",
            "preference_entries": [
                _compact_preference_entry_for_model(index, entry)
                for index, entry in enumerate(entries[:80])
            ],
            "output_schema": {
                "forbidden_categories": ["hard cargo categories to reject"],
                "soft_forbidden_categories": [{"category": "name", "penalty": 0}],
                "preferred_categories": ["cargo categories to prefer"],
                "forbidden_regions": ["hard start/end city substrings to reject"],
                "soft_forbidden_regions": [{"region": "city_or_area", "penalty": 0}],
                "pickup_max_km": None,
                "soft_pickup_max_km": [{"max_km": 0, "penalty": 0}],
                "haul_max_km": None,
                "soft_haul_max_km": [{"max_km": 0, "penalty": 0}],
                "monthly_empty_km_limit": None,
                "soft_monthly_empty_km_limit": [{"max_km": 0, "penalty": 0}],
                "daily_rest_hours": None,
                "scheduled_window": {"start_minute": 0, "end_minute": 360},
                "off_days_required": None,
                "fixed_off_days": [0],
                "max_daily_orders": None,
                "first_order_deadline_minute": None,
                "blocked_region_days": [{"region": "name", "days": [0], "hard": True, "penalty": 0}],
                "required_region": {
                    "region": "name",
                    "min_days": 1,
                    "lat": None,
                    "lng": None,
                    "radius_km": 8.0,
                },
                "required_location": {"lat": 0, "lng": 0, "radius_km": 2.0, "min_days": 1},
                "home_deadline": {"lat": 0, "lng": 0, "radius_km": 1.0, "deadline_minute": 1320, "release_minute": 480},
                "allowed_box": {"lat_min": 0, "lat_max": 0, "lng_min": 0, "lng_max": 0},
                "forbidden_circles": [{"lat": 0, "lng": 0, "radius_km": 1}],
                "stocktake_event": {"day": 0, "target": {"lat": 0, "lng": 0}, "wait_minutes": 120},
                "banquet_event": {
                    "day": 0,
                    "gift_target": {"lat": 0, "lng": 0},
                    "banquet_target": {"lat": 0, "lng": 0},
                    "wait_minutes": 120,
                    "wait_until_minute": 840,
                },
                "dated_stop_events": [
                    {
                        "day": 0,
                        "stops": [
                            {"target": {"lat": 0, "lng": 0}, "wait_minutes": 0, "wait_until_minute": None}
                        ],
                    }
                ],
                "unknown_hard_rules": [
                    {"terms": ["text"], "days": [], "coords": [], "pickup_max_km": None, "haul_max_km": None}
                ],
                "soft_penalty_rules": [
                    {
                        "kind": "unknown_text",
                        "terms": ["text"],
                        "days": [],
                        "coords": [],
                        "pickup_max_km": None,
                        "haul_max_km": None,
                        "penalty": 0,
                    }
                ],
            },
            "response_contract": (
                "Return one JSON object only. Omit fields you cannot support. "
                "Use null instead of guessing numeric limits. For soft preferences, include the penalty amount."
            ),
        }
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是货运司机偏好编译器，只返回 JSON 对象。"
                        "硬禁忌只用于明确的一律、禁止、不得、不能、坚决不接等表达；"
                        "不想、尽量少、最好别、超一次扣、每次扣等表达应编译为软罚规则。"
                        "日期字段必须使用 0-based day index，三月一号是 0，三月三十一号是 30。"
                        "不要输出货源 id，不要使用未来市场信息，不要编造偏好文本没有说的条件。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "temperature": 0,
            "max_tokens": 1200,
        }
        try:
            resp = self._api.model_chat_completion(payload)
            content = _extract_message_content(resp)
            profile = _loads_json_object(content)
            return profile if isinstance(profile, dict) else None
        except Exception as exc:
            self._logger.warning("preference profile compiler failed, using local parser only: %s", exc)
            return None

    def _ask_model(
        self,
        driver_id: str,
        status: dict[str, Any],
        profile: dict[str, Any],
        features: list[dict[str, Any]],
        rule_action: dict[str, Any],
        memory_context: dict[str, Any],
        region_days: dict[str, dict[str, set[int]]],
        history: list[dict[str, Any]],
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
            "current_visible_preferences": status.get("preferences", []),
            "observed_preferences_in_session": memory_context.get("preferences", []),
            "session_progress_memory": memory_context.get("progress", {}),
            "parsed_preference_guard": _compact_profile(profile),
            "rule_recommendation": rule_action,
            "candidate_shortlist_policy": (
                "candidate_orders mixes rule-score, net-income, net-per-hour, requirement-progress, "
                "destination-density, and low-deadhead candidates; rule_recommendation is a safe baseline, "
                "not a mandatory choice."
            ),
            "candidate_orders": [
                _compact_feature(f, status, profile, region_days, history)
                for f in features
            ],
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
                        "候选货源已经由本地工具完成硬偏好、休息、装货窗、月末边界过滤，"
                        "并估算软偏好的罚分；"
                        "你只允许从 candidate_orders 里选择一个 cargo_id。"
                        "current_visible_preferences 是本步 get_driver_status 返回的偏好；"
                        "observed_preferences_in_session 是本会话此前通过 get_driver_status 合法看见的运行态记忆，"
                        "不是文件持久记忆。parsed_preference_guard 只是辅助提示；"
                        "candidate_orders 是多策略候选池，rule_recommendation 是安全基线而不是强制答案；"
                        "如果自然语言偏好里有 parsed_preference_guard 没覆盖的禁忌、偏好、时间或罚款，"
                        "必须按当前可见和本会话已观察偏好执行。"
                        "软偏好可比较收益与 estimated_preference_penalty，保守决策时参考 risk_adjusted_net_after_penalty。"
                        "优先满足司机偏好和事件，其次最大化净收益、单位时间收益、目的地后续密度。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "temperature": 0,
            "max_tokens": 192,
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
        status: dict[str, Any],
        profile: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if str(action.get("action", "")).strip().lower() != "take_order":
            return fallback
        params = action.get("params")
        if not isinstance(params, dict):
            return fallback
        cargo_id = str(params.get("cargo_id", "")).strip()
        feature_by_id = {f["cargo_id"]: f for f in features}
        selected = feature_by_id.get(cargo_id)
        if selected is None:
            return fallback
        fallback_id = str(fallback.get("params", {}).get("cargo_id", "")).strip()
        fallback_feature = feature_by_id.get(fallback_id)
        if fallback_feature is not None and _model_proposal_is_risky(
            selected,
            fallback_feature,
            features,
            status,
            profile,
            self._region_days,
            history,
        ):
            return fallback
        return {"action": "take_order", "params": {"cargo_id": cargo_id}}


class RuntimePreferenceMemory:
    """Per-run memory for legally observed driver preference text.

    The store is intentionally process-local.  It never reads or writes driver
    preference files, and it only accumulates text surfaced by get_driver_status
    during the current evaluation session.
    """

    def __init__(self, max_entries_per_driver: int = 80) -> None:
        self._max_entries_per_driver = max_entries_per_driver
        self._drivers: dict[str, dict[str, Any]] = {}

    def update(
        self,
        driver_id: str,
        status: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        state = self._drivers.setdefault(driver_id, {"entries": {}, "progress": {}})
        entries = state["entries"]
        if not isinstance(entries, dict):
            entries = {}
            state["entries"] = entries

        now = _time_min(status)
        visible_texts: set[str] = set()
        for pref in _preference_entries(status):
            text = _normalize_preference_text(pref.get("content", ""))
            if not text:
                continue
            visible_texts.add(text)
            stored = entries.get(text)
            if not isinstance(stored, dict):
                stored = {"content": text, "first_seen_min": now, "seen_count": 0}
                entries[text] = stored
            stored["content"] = text
            stored["last_seen_min"] = now
            stored["last_visible"] = True
            stored["seen_count"] = int(stored.get("seen_count", 0) or 0) + 1
            if isinstance(pref, dict) and pref.get("penalty_amount") is not None:
                stored["penalty_amount"] = pref.get("penalty_amount")
            if isinstance(pref, dict):
                for key in ("start_time", "end_time", "penalty_cap"):
                    if pref.get(key) is not None:
                        stored[key] = pref.get(key)

        for text, stored in list(entries.items()):
            if isinstance(stored, dict):
                stored["last_visible"] = text in visible_texts

        self._trim_entries(entries)
        state["progress"] = _history_progress_summary(history)
        return [self._parser_entry(item) for item in entries.values() if isinstance(item, dict)]

    def context(self, driver_id: str) -> dict[str, Any]:
        state = self._drivers.get(driver_id)
        if not isinstance(state, dict):
            return {"preferences": [], "progress": {}}
        entries = state.get("entries")
        if not isinstance(entries, dict):
            return {"preferences": [], "progress": state.get("progress", {}) if isinstance(state.get("progress"), dict) else {}}
        prefs = []
        for item in entries.values():
            if not isinstance(item, dict):
                continue
            text = str(item.get("content", "")).strip()
            if not text:
                continue
            prefs.append(
                {
                    "content": text,
                    "penalty_amount": item.get("penalty_amount"),
                    "penalty_cap": item.get("penalty_cap"),
                    "start_time": item.get("start_time"),
                    "end_time": item.get("end_time"),
                    "first_seen_min": int(item.get("first_seen_min", 0) or 0),
                    "last_seen_min": int(item.get("last_seen_min", 0) or 0),
                    "last_visible": bool(item.get("last_visible", False)),
                }
            )
        prefs.sort(key=lambda x: (not x["last_visible"], x["first_seen_min"]))
        progress = state.get("progress")
        return {"preferences": prefs[:20], "progress": progress if isinstance(progress, dict) else {}}

    def _trim_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        if len(entries) <= self._max_entries_per_driver:
            return
        removable = sorted(
            (
                (str(text), int(item.get("last_seen_min", 0) or 0))
                for text, item in entries.items()
                if isinstance(item, dict) and not bool(item.get("last_visible", False))
            ),
            key=lambda x: x[1],
        )
        for text, _ in removable:
            if len(entries) <= self._max_entries_per_driver:
                break
            entries.pop(text, None)

    @staticmethod
    def _parser_entry(item: dict[str, Any]) -> dict[str, Any]:
        out = {"content": str(item.get("content", "")).strip()}
        if item.get("penalty_amount") is not None:
            out["penalty_amount"] = item.get("penalty_amount")
        for key in ("penalty_cap", "start_time", "end_time"):
            if item.get(key) is not None:
                out[key] = item.get(key)
        for key in ("first_seen_min", "last_seen_min", "last_visible"):
            if item.get(key) is not None:
                out[key] = item.get(key)
        return out


def _passes_filters(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> bool:
    if feature["finish_min"] > MONTH_HORIZON_MINUTES:
        return False
    day = _time_min(status) // DAY_MINUTES
    today_orders = _accepted_orders_on_day(history, day)
    max_daily = profile.get("max_daily_orders")
    if max_daily is not None and today_orders >= int(max_daily):
        return False
    first_deadline = profile.get("first_order_deadline_minute")
    if first_deadline is not None and today_orders == 0 and _time_min(status) % DAY_MINUTES >= int(first_deadline):
        return False
    if str(feature.get("cargo_name", "")) in profile["forbidden_categories"]:
        return False
    for region in profile["forbidden_regions"]:
        if _touches_region(feature, region):
            return False
    if _touches_blocked_region_day(feature, status, profile):
        return False
    for rule in profile.get("unknown_hard_rules", []) or []:
        if isinstance(rule, dict) and _unknown_rule_matches(feature, status, rule, history):
            return False
    box = profile.get("allowed_box")
    if isinstance(box, dict) and not _feature_in_allowed_box(feature, box):
        return False
    for circle in profile.get("forbidden_circles", []) or []:
        if isinstance(circle, dict) and _feature_touches_circle(feature, circle):
            return False
    pickup_max = profile.get("pickup_max_km")
    if pickup_max is not None and feature["pickup_km"] > float(pickup_max):
        return False
    haul_max = profile.get("haul_max_km")
    if haul_max is not None and feature["haul_km"] > float(haul_max):
        return False
    empty_limit = profile.get("monthly_empty_km_limit")
    if empty_limit is not None and _monthly_empty_km(history) + float(feature["pickup_km"]) > float(empty_limit) + 10.0:
        return False
    home = profile.get("home_deadline")
    if isinstance(home, dict) and not _can_finish_and_reach_home(feature, home):
        return False
    if _feature_conflicts_pending_event(feature, status, profile, history):
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
    history: list[dict[str, Any]],
) -> float:
    score = (
        float(feature.get("score_net_after_penalty", feature.get("net_after_penalty", feature["net"])))
        + float(feature.get("score_nph_after_penalty", feature.get("nph_after_penalty", feature["nph"])))
        * NET_PER_HOUR_SCORE_WEIGHT
        + feature["density"] * (8.0 if profile.get("required_region") else 5.0)
    )
    if str(feature.get("cargo_name", "")) in profile.get("preferred_categories", set()):
        score += 80.0
    empty_limit = profile.get("monthly_empty_km_limit")
    if empty_limit is not None:
        remaining = max(0.0, float(empty_limit) - _monthly_empty_km(history))
        if feature["pickup_km"] > remaining:
            score -= (feature["pickup_km"] - remaining) * 60.0
    req = profile.get("required_region")
    if isinstance(req, dict):
        need = int(req.get("min_days", 0) or 0)
        days = region_days.get(str(status.get("driver_id", "")), {}).get(_region_requirement_key(req), set())
        day = _time_min(status) // DAY_MINUTES
        if _feature_touches_region_requirement(feature, req) and len(days) < need and day not in days:
            score += 1_200.0
    loc_req = profile.get("required_location")
    if isinstance(loc_req, dict):
        driver_id = str(status.get("driver_id", ""))
        key = str(loc_req.get("key", "required_location"))
        days = region_days.get(driver_id, {}).get(key, set())
        need = int(loc_req.get("min_days", 0) or 0)
        day = _time_min(status) // DAY_MINUTES
        if len(days) < need and day not in days and _feature_touches_location(feature, loc_req):
            score += 1_000.0
    return score


def _gate_soft_penalty_candidates(
    features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not features or not profile.get("soft_penalty_rules"):
        return features
    clean = [feature for feature in features if float(feature.get("estimated_penalty", 0.0) or 0.0) <= 0.0]
    if not clean:
        standalone = [feature for feature in features if _soft_penalty_standalone_allowed(feature)]
        if standalone:
            return standalone
        return sorted(
            features,
            key=lambda f: float(f.get("score_net_after_penalty", f.get("net_after_penalty", f.get("net", 0.0))) or 0.0),
            reverse=True,
        )[: min(3, len(features))]

    best_clean_net = max(float(feature.get("net_after_penalty", feature.get("net", 0.0)) or 0.0) for feature in clean)
    best_clean_nph = max(float(feature.get("nph_after_penalty", feature.get("nph", 0.0)) or 0.0) for feature in clean)
    best_clean_score = max(_rule_score(feature, status, profile, region_days, history) for feature in clean)
    allowed = list(clean)
    for feature in features:
        if float(feature.get("estimated_penalty", 0.0) or 0.0) <= 0.0:
            continue
        if _soft_penalty_exception_allowed(
            feature,
            best_clean_net,
            best_clean_nph,
            best_clean_score,
            status,
            profile,
            region_days,
            history,
        ):
            allowed.append(feature)
    return allowed


def _model_candidate_pool(
    features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    if len(features) <= limit:
        return features

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(feature: dict[str, Any]) -> None:
        if len(selected) >= limit:
            return
        cargo_id = str(feature.get("cargo_id", "")).strip()
        if not cargo_id or cargo_id in seen:
            return
        selected.append(feature)
        seen.add(cargo_id)

    # The first few preserve the deterministic rule baseline.
    for feature in features[:4]:
        add(feature)

    for feature in sorted(
        features,
        key=lambda f: float(f.get("net_after_penalty", f.get("net", 0.0)) or 0.0),
        reverse=True,
    )[:4]:
        add(feature)

    for feature in sorted(
        features,
        key=lambda f: float(f.get("nph_after_penalty", f.get("nph", 0.0)) or 0.0),
        reverse=True,
    )[:4]:
        add(feature)

    requirement_candidates = [
        feature
        for feature in features
        if _feature_advances_outstanding_requirement(feature, status, profile, region_days)
    ]
    for feature in sorted(
        requirement_candidates,
        key=lambda f: _rule_score(f, status, profile, region_days, history),
        reverse=True,
    )[:3]:
        add(feature)

    preferred = [
        feature
        for feature in features
        if str(feature.get("cargo_name", "")) in profile.get("preferred_categories", set())
    ]
    for feature in sorted(
        preferred,
        key=lambda f: _rule_score(f, status, profile, region_days, history),
        reverse=True,
    )[:2]:
        add(feature)

    for feature in sorted(features, key=lambda f: int(f.get("density", 0) or 0), reverse=True)[:3]:
        add(feature)

    for feature in sorted(features, key=lambda f: float(f.get("pickup_km", 0.0) or 0.0))[:3]:
        add(feature)

    for feature in features:
        add(feature)
        if len(selected) >= limit:
            break
    return selected


def _should_ask_model(
    features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> bool:
    if len(features) <= 1:
        return False
    if _profile_has_open_text_rules(profile):
        return True
    if any(feature.get("soft_penalty_triggers") for feature in features):
        return True
    fallback_id = str(features[0].get("cargo_id", "")).strip()
    if any(
        str(feature.get("cargo_id", "")).strip() != fallback_id
        and _feature_advances_outstanding_requirement(feature, status, profile, region_days)
        for feature in features
    ):
        return True
    return _candidate_pool_has_rank_disagreement(features, status, profile, region_days, history)


def _profile_has_open_text_rules(profile: dict[str, Any]) -> bool:
    if profile.get("unknown_hard_rules"):
        return True
    for rule in profile.get("soft_penalty_rules", []) or []:
        if isinstance(rule, dict) and str(rule.get("kind", "")) == "unknown_text":
            return True
    return False


def _candidate_pool_has_rank_disagreement(
    features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> bool:
    fallback_id = str(features[0].get("cargo_id", "")).strip()
    if not fallback_id:
        return False
    score_ranks = _candidate_ranks(
        features,
        lambda f: _rule_score(f, status, profile, region_days, history),
    )
    net_ranks = _candidate_ranks(
        features,
        lambda f: float(f.get("net_after_penalty", f.get("net", 0.0)) or 0.0),
    )
    nph_ranks = _candidate_ranks(
        features,
        lambda f: float(f.get("nph_after_penalty", f.get("nph", 0.0)) or 0.0),
    )
    top_score_band = max(1, int(math.sqrt(len(features))))
    for feature in features:
        cargo_id = str(feature.get("cargo_id", "")).strip()
        if cargo_id == fallback_id:
            continue
        if score_ranks.get(cargo_id, len(features)) >= top_score_band:
            continue
        if net_ranks.get(cargo_id, len(features)) == 0 or nph_ranks.get(cargo_id, len(features)) == 0:
            return True
    return False


def _soft_penalty_standalone_allowed(feature: dict[str, Any]) -> bool:
    penalty = float(feature.get("estimated_penalty", 0.0) or 0.0)
    if penalty <= 0.0:
        return True
    return (
        float(feature.get("net_after_penalty", feature["net"])) >= _soft_exception_margin(feature)
        and float(feature.get("nph_after_penalty", feature["nph"])) > 0.0
    )


def _soft_penalty_exception_allowed(
    feature: dict[str, Any],
    best_clean_net: float,
    best_clean_nph: float,
    best_clean_score: float,
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> bool:
    margin = _soft_exception_margin(feature)
    net_after = float(feature.get("net_after_penalty", feature["net"]))
    nph_after = float(feature.get("nph_after_penalty", feature["nph"]))
    score = _rule_score(feature, status, profile, region_days, history)

    if net_after < best_clean_net + margin:
        return False
    if nph_after >= max(0.0, best_clean_nph * SOFT_PENALTY_NPH_FLOOR_RATIO):
        return True
    return score >= best_clean_score + margin * 0.5


def _soft_exception_margin(feature: dict[str, Any]) -> float:
    penalty = float(feature.get("estimated_penalty", 0.0) or 0.0)
    margin = max(SOFT_PENALTY_MIN_EXCEPTION_MARGIN, penalty * SOFT_PENALTY_EXCEPTION_MULTIPLIER)
    for trigger in feature.get("soft_penalty_triggers", []) or []:
        if not isinstance(trigger, dict):
            continue
        kind = str(trigger.get("kind", ""))
        if kind in {"pickup_max_km", "haul_max_km", "monthly_empty_km_limit"}:
            margin += max(0.0, float(trigger.get("excess_km", 0.0) or 0.0)) * COST_PER_KM * 4.0
    return margin


def _work_deadline(now: int, profile: dict[str, Any]) -> int:
    day, _ = divmod(now, DAY_MINUTES)
    window = profile.get("scheduled_window")
    if isinstance(window, tuple):
        start, _end = window
        deadline = day * DAY_MINUTES + start - 10
        if deadline <= now:
            deadline += DAY_MINUTES
        return deadline
    rest_hours = int(profile.get("daily_rest_hours", 0) or 0)
    if rest_hours > 0:
        rest_start = 20 * 60 if rest_hours >= 8 else 23 * 60
        return day * DAY_MINUTES + rest_start - 10
    return day * DAY_MINUTES + 22 * 60


def _query_k(profile: dict[str, Any]) -> int:
    if isinstance(profile.get("scheduled_window"), tuple):
        return 600
    if profile.get("pickup_max_km") is not None or profile.get("haul_max_km") is not None or profile.get("required_region"):
        return 400
    if (
        profile.get("forbidden_categories")
        or profile.get("forbidden_regions")
        or profile.get("preferred_categories")
    ):
        return 300
    return 300


def _preference_profile(status: dict[str, Any]) -> dict[str, Any]:
    return _preference_profile_from_entries(_preference_entries(status))


def _preference_entries_signature(entries: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    parts: list[tuple[Any, ...]] = []
    for entry in entries:
        text = _normalize_preference_text(entry.get("content", ""))
        if not text:
            continue
        first_seen_min = _int_or_none(entry.get("first_seen_min"))
        first_seen_day = None if first_seen_min is None else max(0, min(30, first_seen_min // DAY_MINUTES))
        parts.append(
            (
                text,
                round(_preference_penalty_amount(entry), 2),
                first_seen_day,
                str(entry.get("start_time", "") or ""),
                str(entry.get("end_time", "") or ""),
            )
        )
    return tuple(sorted(parts))


def _compact_preference_entry_for_model(index: int, entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "index": index,
        "content": _normalize_preference_text(entry.get("content", "")),
        "penalty_amount": _preference_penalty_amount(entry),
    }
    first_seen_min = _int_or_none(entry.get("first_seen_min"))
    if first_seen_min is not None:
        out["first_seen_min"] = first_seen_min
        out["first_seen_day_zero_based"] = max(0, min(30, first_seen_min // DAY_MINUTES))
    last_seen_min = _int_or_none(entry.get("last_seen_min"))
    if last_seen_min is not None:
        out["last_seen_min"] = last_seen_min
        out["last_seen_day_zero_based"] = max(0, min(30, last_seen_min // DAY_MINUTES))
    if entry.get("last_visible") is not None:
        out["last_visible"] = bool(entry.get("last_visible"))
    for key in ("start_time", "end_time", "penalty_cap"):
        if entry.get(key) is not None:
            out[key] = entry.get(key)
    return out


def _merge_profiles(local_profile: dict[str, Any], model_profile: dict[str, Any] | None) -> dict[str, Any]:
    out = _copy_preference_profile(local_profile)
    if not isinstance(model_profile, dict) or not model_profile:
        return out

    for key in ("forbidden_categories", "hard_forbidden_categories"):
        out["forbidden_categories"].update(_as_text_list(model_profile.get(key)))
    for key in ("preferred_categories", "prefer_categories", "preferred_cargo_categories"):
        out["preferred_categories"].update(_as_text_list(model_profile.get(key)))
    for key in ("forbidden_regions", "hard_forbidden_regions"):
        out["forbidden_regions"].update(_as_text_list(model_profile.get(key)))

    for item in _as_list(model_profile.get("soft_forbidden_categories")):
        name, penalty = _model_named_penalty(item, "category")
        if name:
            out["soft_penalty_rules"].append({"kind": "category", "category": name, "penalty": penalty})
    for item in _as_list(model_profile.get("soft_forbidden_regions")):
        name, penalty = _model_named_penalty(item, "region")
        if name:
            out["soft_penalty_rules"].append({"kind": "region", "region": name, "penalty": penalty})

    _merge_min_float(out, "pickup_max_km", model_profile.get("pickup_max_km"))
    _merge_min_float(out, "haul_max_km", model_profile.get("haul_max_km"))
    _merge_min_float(out, "monthly_empty_km_limit", model_profile.get("monthly_empty_km_limit"))
    _merge_max_int(out, "daily_rest_hours", model_profile.get("daily_rest_hours"))
    _merge_max_int(out, "off_days_required", model_profile.get("off_days_required"))
    _merge_min_int(out, "max_daily_orders", model_profile.get("max_daily_orders"))
    _merge_min_int(out, "first_order_deadline_minute", model_profile.get("first_order_deadline_minute"))

    for key, kind in (
        ("soft_pickup_max_km", "pickup_max_km"),
        ("soft_haul_max_km", "haul_max_km"),
        ("soft_monthly_empty_km_limit", "monthly_empty_km_limit"),
    ):
        for item in _as_list(model_profile.get(key)):
            rule = _model_distance_soft_rule(item, kind)
            if rule is not None:
                out["soft_penalty_rules"].append(rule)

    window = _model_window(model_profile.get("scheduled_window") or model_profile.get("daily_sleep_window"))
    if window is not None:
        current_window = out.get("scheduled_window")
        if current_window is None or _window_duration(window) > _window_duration(current_window):
            out["scheduled_window"] = window

    out["fixed_off_days"].update(_model_days(model_profile.get("fixed_off_days")))

    for item in _as_list(model_profile.get("blocked_region_days") or model_profile.get("forbidden_region_days")):
        blocked = _model_blocked_region_days(item)
        if blocked is None:
            continue
        region, days, hard, penalty = blocked
        if hard:
            out["blocked_region_days"].setdefault(region, set()).update(days)
        else:
            out["soft_penalty_rules"].append(
                {"kind": "blocked_region_days", "region": region, "days": sorted(days), "penalty": penalty}
            )

    req_region = _model_required_region(model_profile.get("required_region"))
    if req_region is not None:
        out["required_region"] = _merge_required_region(out.get("required_region"), req_region)

    req_location = _model_required_location(model_profile.get("required_location"))
    if req_location is not None and not isinstance(out.get("required_location"), dict):
        out["required_location"] = req_location

    home_deadline = _model_home_deadline(model_profile.get("home_deadline"))
    if home_deadline is not None and not isinstance(out.get("home_deadline"), dict):
        out["home_deadline"] = home_deadline

    box = _model_box(model_profile.get("allowed_box"))
    if box is not None:
        out["allowed_box"] = _intersect_boxes(out.get("allowed_box"), box)

    for item in _as_list(model_profile.get("forbidden_circles")):
        circle = _model_circle(item)
        if circle is not None:
            out["forbidden_circles"].append(circle)

    stocktake = _model_stocktake_event(model_profile.get("stocktake_event"))
    if stocktake is not None and not isinstance(out.get("stocktake_event"), dict):
        out["stocktake_event"] = stocktake

    banquet = _model_banquet_event(model_profile.get("banquet_event"))
    if banquet is not None and not isinstance(out.get("banquet_event"), dict):
        out["banquet_event"] = banquet

    for event in _model_dated_stop_events(model_profile.get("dated_stop_events")):
        out["dated_stop_events"].append(event)

    for key in ("unknown_hard_rules", "hard_unknown_rules"):
        for item in _as_list(model_profile.get(key)):
            rule = _model_unknown_rule(item, hard=True)
            if rule is not None:
                out["unknown_hard_rules"].append(rule)

    for item in _as_list(model_profile.get("soft_penalty_rules")):
        rule = _model_soft_penalty_rule(item)
        if rule is not None:
            out["soft_penalty_rules"].append(rule)

    out["soft_penalty_rules"] = _dedupe_soft_penalty_rules(out["soft_penalty_rules"])
    out["unknown_hard_rules"] = _dedupe_unknown_rules(out["unknown_hard_rules"])
    out["forbidden_circles"] = _dedupe_dict_list(out["forbidden_circles"])
    out["dated_stop_events"] = _dedupe_dict_list(out["dated_stop_events"])
    out["late_month_work"] = int(out.get("daily_rest_hours", 0) or 0) >= 8 and int(out.get("off_days_required", 0) or 0) >= 3
    return out


def _copy_preference_profile(profile: dict[str, Any]) -> dict[str, Any]:
    out = dict(profile)
    for key in ("forbidden_categories", "preferred_categories", "forbidden_regions", "fixed_off_days"):
        out[key] = set(profile.get(key, set()) or set())
    out["soft_penalty_rules"] = [dict(item) for item in profile.get("soft_penalty_rules", []) if isinstance(item, dict)]
    out["unknown_hard_rules"] = [dict(item) for item in profile.get("unknown_hard_rules", []) if isinstance(item, dict)]
    out["forbidden_circles"] = [dict(item) for item in profile.get("forbidden_circles", []) if isinstance(item, dict)]
    out["event_targets"] = [dict(item) for item in profile.get("event_targets", []) if isinstance(item, dict)]
    out["dated_stop_events"] = [dict(item) for item in profile.get("dated_stop_events", []) if isinstance(item, dict)]
    blocked: dict[str, set[int]] = {}
    for region, days in (profile.get("blocked_region_days") or {}).items():
        blocked[str(region)] = {int(day) for day in days if 0 <= int(day) < 31}
    out["blocked_region_days"] = blocked
    return out


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_text_list(value: Any, max_len: int = 18) -> list[str]:
    out = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("name") or item.get("value") or item.get("category") or item.get("region") or item.get("term")
        text = _model_text(item, max_len=max_len)
        if text:
            out.append(text)
    return out


def _model_text(value: Any, max_len: int = 18) -> str | None:
    text = str(value or "").strip(" ，。；、:：()（）[]{}")
    if not text or text.lower() in {"none", "null", "n/a", "unknown"}:
        return None
    text = re.sub(r"\s+", "", text)
    return text[:max_len] if text else None


def _model_penalty(value: Any, default: float = 500.0) -> float:
    if isinstance(value, dict):
        raw = value.get("penalty", value.get("penalty_amount", default))
    else:
        raw = value
    number = _float_or_none(raw)
    return max(1.0, number if number is not None else default)


def _model_named_penalty(item: Any, name_key: str) -> tuple[str | None, float]:
    if isinstance(item, dict):
        name = _model_text(item.get(name_key) or item.get("name") or item.get("value"))
        return name, _model_penalty(item)
    return _model_text(item), 500.0


def _merge_min_float(out: dict[str, Any], key: str, value: Any) -> None:
    number = _float_or_none(value)
    if number is None or number <= 0:
        return
    current = out.get(key)
    out[key] = number if current is None else min(float(current), number)


def _merge_max_int(out: dict[str, Any], key: str, value: Any) -> None:
    number = _int_or_none(value)
    if number is None or number <= 0:
        return
    current = _int_or_none(out.get(key)) or 0
    out[key] = max(current, number)


def _merge_min_int(out: dict[str, Any], key: str, value: Any) -> None:
    number = _int_or_none(value)
    if number is None or number <= 0:
        return
    current = _int_or_none(out.get(key))
    out[key] = number if current is None else min(current, number)


def _model_distance_soft_rule(item: Any, kind: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    max_km = _float_or_none(item.get("max_km") or item.get("limit_km") or item.get(kind))
    if max_km is None or max_km <= 0:
        return None
    return {"kind": kind, "max_km": max_km, "penalty": _model_penalty(item)}


def _model_window(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        start = _int_or_none(value.get("start_minute", value.get("start")))
        end = _int_or_none(value.get("end_minute", value.get("end")))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        start = _int_or_none(value[0])
        end = _int_or_none(value[1])
    else:
        return None
    if start is None or end is None:
        return None
    start %= DAY_MINUTES
    end %= DAY_MINUTES
    if start == end:
        return None
    return start, end


def _window_duration(window: tuple[int, int] | Any) -> int:
    if not isinstance(window, tuple) or len(window) != 2:
        return 0
    start, end = int(window[0]), int(window[1])
    return end - start if start < end else end + DAY_MINUTES - start


def _model_days(value: Any) -> set[int]:
    raw = []
    for item in _as_list(value):
        number = _int_or_none(item)
        if number is not None:
            raw.append(number)
    if not raw:
        return set()
    if 31 in raw:
        raw = [day - 1 for day in raw if day > 0]
    return {day for day in raw if 0 <= day < 31}


def _model_calendar_days(value: Any) -> set[int]:
    out = set()
    for item in _as_list(value):
        number = _int_or_none(item)
        if number is not None and 1 <= number <= 31:
            out.add(number - 1)
    return out


def _model_day_from_dict(item: dict[str, Any]) -> int | None:
    calendar_raw = item.get("calendar_day")
    if calendar_raw is None:
        calendar_raw = item.get("march_day")
    calendar = _int_or_none(calendar_raw)
    if calendar is not None and 1 <= calendar <= 31:
        return calendar - 1
    day_raw = item.get("day")
    if day_raw is None:
        day_raw = item.get("day_index")
    if day_raw is None:
        day_raw = item.get("day_zero_based")
    day = _int_or_none(day_raw)
    if day is not None:
        if day == 31:
            return 30
        if 0 <= day < 31:
            return day
    return None


def _model_blocked_region_days(item: Any) -> tuple[str, set[int], bool, float] | None:
    if not isinstance(item, dict):
        return None
    region = _model_text(item.get("region") or item.get("name"))
    days = _model_days(item.get("days"))
    if not days:
        days = _model_calendar_days(item.get("calendar_days"))
    if not days and _model_day_from_dict(item) is not None:
        days = {_model_day_from_dict(item) or 0}
    if not region or not days:
        return None
    kind = str(item.get("kind") or item.get("type") or "").lower()
    hard = not (bool(item.get("soft", False)) or kind == "soft" or item.get("hard") is False)
    return region, days, hard, _model_penalty(item)


def _model_required_region(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    region = _model_text(value.get("region") or value.get("name"))
    min_days = _int_or_none(value.get("min_days") or value.get("days_required") or value.get("need_days")) or 0
    lat = _float_or_none(value.get("lat"))
    lng = _float_or_none(value.get("lng"))
    if min_days <= 0 or (not region and (lat is None or lng is None)):
        return None
    out: dict[str, Any] = {"region": region or "required_region", "min_days": min_days}
    if lat is not None and lng is not None:
        out["lat"] = lat
        out["lng"] = lng
        out["radius_km"] = _float_or_none(value.get("radius_km")) or 8.0
    return out


def _merge_required_region(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        return incoming
    out = dict(existing)
    existing_region = str(out.get("region", "") or "")
    incoming_region = str(incoming.get("region", "") or "")
    same_region = not existing_region or not incoming_region or existing_region in incoming_region or incoming_region in existing_region
    if not same_region:
        return out
    out["min_days"] = max(int(out.get("min_days", 0) or 0), int(incoming.get("min_days", 0) or 0))
    for key in ("lat", "lng", "radius_km"):
        if out.get(key) is None and incoming.get(key) is not None:
            out[key] = incoming[key]
    return out


def _model_required_location(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    lat = _float_or_none(value.get("lat"))
    lng = _float_or_none(value.get("lng"))
    min_days = _int_or_none(value.get("min_days") or value.get("days_required") or value.get("need_days")) or 0
    if lat is None or lng is None or min_days <= 0:
        return None
    return {
        "key": str(value.get("key") or f"loc:{lat:.4f},{lng:.4f}"),
        "lat": lat,
        "lng": lng,
        "radius_km": _float_or_none(value.get("radius_km")) or 2.0,
        "min_days": min_days,
    }


def _model_home_deadline(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    target = _model_target(value)
    deadline = _int_or_none(value.get("deadline_minute"))
    if target is None or deadline is None:
        return None
    return {
        "lat": target["lat"],
        "lng": target["lng"],
        "radius_km": _float_or_none(value.get("radius_km")) or 1.0,
        "deadline_minute": max(0, min(DAY_MINUTES - 1, deadline)),
        "release_minute": max(0, min(DAY_MINUTES - 1, _int_or_none(value.get("release_minute")) or 8 * 60)),
    }


def _model_box(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    lat_min = _float_or_none(value.get("lat_min"))
    lat_max = _float_or_none(value.get("lat_max"))
    lng_min = _float_or_none(value.get("lng_min"))
    lng_max = _float_or_none(value.get("lng_max"))
    if None in (lat_min, lat_max, lng_min, lng_max):
        return None
    return {
        "lat_min": min(float(lat_min), float(lat_max)),
        "lat_max": max(float(lat_min), float(lat_max)),
        "lng_min": min(float(lng_min), float(lng_max)),
        "lng_max": max(float(lng_min), float(lng_max)),
    }


def _intersect_boxes(current: Any, incoming: dict[str, float]) -> dict[str, float]:
    if not isinstance(current, dict):
        return incoming
    return {
        "lat_min": max(float(current["lat_min"]), incoming["lat_min"]),
        "lat_max": min(float(current["lat_max"]), incoming["lat_max"]),
        "lng_min": max(float(current["lng_min"]), incoming["lng_min"]),
        "lng_max": min(float(current["lng_max"]), incoming["lng_max"]),
    }


def _model_target(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    lat = _float_or_none(value.get("lat"))
    lng = _float_or_none(value.get("lng"))
    if lat is None or lng is None:
        return None
    return {"lat": lat, "lng": lng}


def _model_circle(value: Any) -> dict[str, float] | None:
    target = _model_target(value)
    if target is None or not isinstance(value, dict):
        return None
    radius = _float_or_none(value.get("radius_km"))
    if radius is None or radius <= 0:
        return None
    return {"lat": target["lat"], "lng": target["lng"], "radius_km": radius}


def _model_stocktake_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    target = _model_target(value.get("target") if isinstance(value.get("target"), dict) else value)
    day = _model_day_from_dict(value)
    if target is None or day is None:
        return None
    return {"day": day, "target": target, "wait_minutes": max(1, _int_or_none(value.get("wait_minutes")) or 120)}


def _model_banquet_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    day = _model_day_from_dict(value)
    gift_target = _model_target(value.get("gift_target"))
    banquet_target = _model_target(value.get("banquet_target") or value.get("target"))
    if day is None or gift_target is None or banquet_target is None:
        return None
    return {
        "day": day,
        "gift_target": gift_target,
        "banquet_target": banquet_target,
        "wait_minutes": max(1, _int_or_none(value.get("wait_minutes")) or 120),
        "wait_until_minute": max(0, min(DAY_MINUTES - 1, _int_or_none(value.get("wait_until_minute")) or 14 * 60)),
    }


def _model_dated_stop_events(value: Any) -> list[dict[str, Any]]:
    events = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        day = _model_day_from_dict(item)
        raw_stops = item.get("stops")
        if day is None or not isinstance(raw_stops, list):
            continue
        stops = []
        for raw_stop in raw_stops:
            if not isinstance(raw_stop, dict):
                continue
            target = _model_target(raw_stop.get("target") if isinstance(raw_stop.get("target"), dict) else raw_stop)
            if target is None:
                continue
            stop: dict[str, Any] = {"target": target}
            wait_minutes = _int_or_none(raw_stop.get("wait_minutes"))
            if wait_minutes is not None and wait_minutes > 0:
                stop["wait_minutes"] = min(12 * 60, wait_minutes)
            wait_until = _int_or_none(raw_stop.get("wait_until_minute"))
            if wait_until is not None:
                stop["wait_until_minute"] = max(0, min(DAY_MINUTES - 1, wait_until))
            stops.append(stop)
        if stops:
            events.append({"day": day, "stops": stops})
    return events


def _model_coords(value: Any) -> list[dict[str, float]]:
    coords = []
    for item in _as_list(value):
        if isinstance(item, dict):
            lat = _float_or_none(item.get("lat"))
            lng = _float_or_none(item.get("lng"))
            radius = _float_or_none(item.get("radius_km")) or 2.0
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            lat = _float_or_none(item[0])
            lng = _float_or_none(item[1])
            radius = _float_or_none(item[2]) if len(item) >= 3 else 2.0
        else:
            continue
        if lat is not None and lng is not None:
            coords.append({"lat": lat, "lng": lng, "radius_km": radius or 2.0})
    return coords[:4]


def _model_unknown_rule(item: Any, hard: bool = False) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    rule: dict[str, Any] = {"kind": "unknown_text", "terms": _as_text_list(item.get("terms"), max_len=12)}
    days = _model_days(item.get("days"))
    if not days:
        days = _model_calendar_days(item.get("calendar_days"))
    rule["days"] = sorted(days)
    coords = _model_coords(item.get("coords") or item.get("coordinates"))
    if coords:
        rule["coords"] = coords
    pickup_max = _float_or_none(item.get("pickup_max_km"))
    if pickup_max is not None and pickup_max > 0:
        rule["pickup_max_km"] = pickup_max
    haul_max = _float_or_none(item.get("haul_max_km"))
    if haul_max is not None and haul_max > 0:
        rule["haul_max_km"] = haul_max
    if not hard:
        rule["penalty"] = _model_penalty(item)
    return rule if _unknown_rule_has_conditions(rule) else None


def _model_soft_penalty_rule(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind", "") or "").strip()
    if kind in {"category", "cargo_category"}:
        category = _model_text(item.get("category") or item.get("name"))
        return {"kind": "category", "category": category, "penalty": _model_penalty(item)} if category else None
    if kind in {"region", "city", "area"}:
        region = _model_text(item.get("region") or item.get("name"))
        return {"kind": "region", "region": region, "penalty": _model_penalty(item)} if region else None
    if kind in {"pickup_max_km", "haul_max_km", "monthly_empty_km_limit"}:
        return _model_distance_soft_rule(item, kind)
    if kind == "blocked_region_days":
        blocked = _model_blocked_region_days({**item, "hard": False})
        if blocked is None:
            return None
        region, days, _hard, penalty = blocked
        return {"kind": "blocked_region_days", "region": region, "days": sorted(days), "penalty": penalty}
    if kind in {"unknown_text", "text", ""}:
        return _model_unknown_rule(item, hard=False)
    return None


def _soft_rule_identity(rule: dict[str, Any]) -> tuple[Any, ...]:
    kind = str(rule.get("kind", ""))
    if kind == "category":
        return kind, str(rule.get("category", ""))
    if kind == "region":
        return kind, str(rule.get("region", ""))
    if kind == "blocked_region_days":
        return kind, str(rule.get("region", "")), tuple(sorted(int(day) for day in rule.get("days", []) or []))
    if kind in {"pickup_max_km", "haul_max_km", "monthly_empty_km_limit"}:
        return kind, round(float(rule.get("max_km", 0.0) or 0.0), 2)
    return (
        kind,
        tuple(sorted(str(term) for term in rule.get("terms", []) or [])),
        tuple(sorted(int(day) for day in rule.get("days", []) or [])),
        _coords_identity(rule.get("coords")),
        round(float(rule.get("pickup_max_km", 0.0) or 0.0), 2),
        round(float(rule.get("haul_max_km", 0.0) or 0.0), 2),
    )


def _dedupe_soft_penalty_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rule in rules:
        if not isinstance(rule, dict) or _soft_rule_penalty(rule) <= 0:
            continue
        key = _soft_rule_identity(rule)
        current = merged.get(key)
        if current is None or _soft_rule_penalty(rule) > _soft_rule_penalty(current):
            merged[key] = dict(rule)
    return list(merged.values())


def _unknown_rule_identity(rule: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(sorted(str(term) for term in rule.get("terms", []) or [])),
        tuple(sorted(int(day) for day in rule.get("days", []) or [])),
        _coords_identity(rule.get("coords")),
        round(float(rule.get("pickup_max_km", 0.0) or 0.0), 2),
        round(float(rule.get("haul_max_km", 0.0) or 0.0), 2),
    )


def _dedupe_unknown_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rule in rules:
        if isinstance(rule, dict) and _unknown_rule_has_conditions(rule):
            out.setdefault(_unknown_rule_identity(rule), dict(rule))
    return list(out.values())


def _coords_identity(value: Any) -> tuple[tuple[float, float, float], ...]:
    out = []
    for coord in _as_list(value):
        if not isinstance(coord, dict):
            continue
        lat = _float_or_none(coord.get("lat"))
        lng = _float_or_none(coord.get("lng"))
        radius = _float_or_none(coord.get("radius_km")) or 2.0
        if lat is not None and lng is not None:
            out.append((round(lat, 4), round(lng, 4), round(radius, 2)))
    return tuple(sorted(out))


def _dedupe_dict_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for item in items:
        try:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except TypeError:
            key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _preference_profile_from_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    categories: set[str] = set()
    preferred_categories: set[str] = set()
    forbidden_regions: set[str] = set()
    soft_penalty_rules: list[dict[str, Any]] = []
    pickup_max: float | None = None
    haul_max: float | None = None
    monthly_empty_km_limit: float | None = None
    daily_rest_hours = 0
    off_days_required = 0
    scheduled_window: tuple[int, int] | None = None
    required_region: dict[str, Any] | None = None
    required_location: dict[str, Any] | None = None
    home_deadline: dict[str, Any] | None = None
    allowed_box: dict[str, float] | None = None
    forbidden_circles: list[dict[str, float]] = []
    max_daily_orders: int | None = None
    first_order_deadline_minute: int | None = None
    blocked_region_days: dict[str, set[int]] = {}
    unknown_hard_rules: list[dict[str, Any]] = []
    fixed_off_days: set[int] = set()
    dated_stop_events: list[dict[str, Any]] = []
    event_targets: list[dict[str, float]] = []
    zengcheng_target: dict[str, float] | None = None
    stocktake_day: int | None = None
    banquet_day: int | None = None
    banquet_target: dict[str, float] | None = None

    for pref in entries:
        text = str(pref.get("content", "")).strip()
        if not text:
            continue
        handled = False
        penalty_amount = _preference_penalty_amount(pref)
        quoted = _quoted_terms(text)
        coords = _coordinates(text)
        days = _preference_days(text, pref)
        hard_negative_order_text = _is_hard_negative_order_text(text)
        soft_negative_order_text = _is_soft_negative_order_text(text)
        hard_block_text = _is_hard_block_text(text)
        negative_order_text = hard_negative_order_text or soft_negative_order_text
        for lat, lng in coords:
            event_targets.append({"lat": lat, "lng": lng})
        if coords and zengcheng_target is None and ("增城" in text or "档口" in text) and "四会" not in text:
            zengcheng_target = {"lat": coords[0][0], "lng": coords[0][1]}
        if coords and ("四会" in text or "赴宴" in text or "做寿" in text):
            banquet_target = {"lat": coords[-1][0], "lng": coords[-1][1]}

        if negative_order_text:
            found_categories = {name for name in KNOWN_CARGO_CATEGORIES if name in text}
            found_categories.update(item for item in quoted if len(item) <= 12)
            found_categories.update(_cargo_terms_from_negative_text(text))
            if hard_negative_order_text:
                categories.update(found_categories)
            else:
                for name in found_categories:
                    soft_penalty_rules.append(
                        {"kind": "category", "category": name, "penalty": penalty_amount, "text": text}
                    )
            handled = handled or bool(found_categories)

        if any(key in text for key in ("优先", "喜欢", "愿意接", "多接", "熟悉", "偏好")) and not any(
            key in text for key in ("不接", "禁接", "推掉", "干不了", "不想接")
        ):
            preferred_categories.update(name for name in KNOWN_CARGO_CATEGORIES if name in text)
            preferred_categories.update(item for item in quoted if len(item) <= 12)
            handled = True

        if negative_order_text or hard_block_text:
            region = _region_from_forbidden_text(text) or _region_from_travel_block_text(text)
            if region:
                if days and hard_block_text and any(key in text for key in ("三月", "3月", "今天", "明天", "后天", "当天")):
                    handled = True
                elif hard_negative_order_text or hard_block_text:
                    forbidden_regions.add(region)
                else:
                    soft_penalty_rules.append(
                        {"kind": "region", "region": region, "penalty": penalty_amount, "text": text}
                    )
                handled = True

        if (
            any(key in text for key in ("空驶", "空车", "空跑", "取货", "提货", "赶去装货", "去装货", "赴装货"))
            and not any(key in text for key in ("总", "累计", "全月", "整月", "自然月", "每月"))
            and "公里" in text
            and ("超过" in text or "不得超过" in text or "不超过" in text)
        ):
            value = _first_number_before_unit(text, "公里")
            if value:
                if _is_hard_limit_text(text):
                    pickup_max = float(value) if pickup_max is None else min(pickup_max, float(value))
                else:
                    soft_penalty_rules.append(
                        {"kind": "pickup_max_km", "max_km": float(value), "penalty": penalty_amount, "text": text}
                    )
                handled = True

        if (
            any(key in text for key in ("距离", "里程", "路程", "车程", "干线", "运输"))
            and "公里" in text
            and not any(key in text for key in ("空驶", "空车", "空跑", "取货", "提货"))
            and ("超过" in text or "不得超过" in text or "不超过" in text)
        ):
            value = _first_number_before_unit(text, "公里")
            if value:
                if _is_hard_limit_text(text):
                    haul_max = float(value) if haul_max is None else min(haul_max, float(value))
                else:
                    soft_penalty_rules.append(
                        {"kind": "haul_max_km", "max_km": float(value), "penalty": penalty_amount, "text": text}
                    )
                handled = True

        if (
            any(key in text for key in ("空驶", "空车", "空跑"))
            and any(key in text for key in ("总", "累计", "全月", "整月", "自然月", "每月"))
            and "公里" in text
            and ("不得超过" in text or "不超过" in text or "不能超过" in text or "最多" in text)
        ):
            value = _first_number_before_unit(text, "公里")
            if value:
                if _is_hard_limit_text(text):
                    monthly_empty_km_limit = (
                        float(value) if monthly_empty_km_limit is None else min(monthly_empty_km_limit, float(value))
                    )
                else:
                    soft_penalty_rules.append(
                        {
                            "kind": "monthly_empty_km_limit",
                            "max_km": float(value),
                            "penalty": penalty_amount,
                            "text": text,
                        }
                    )
                handled = True

        rest_match = re.search(
            r"(?:连续|连着|一段)[^，。；]*?([0-9一二三四五六七八九十两]+)\s*小时",
            text,
        )
        if rest_match is None and ("休息" in text or "睡觉" in text or "睡够" in text):
            rest_match = re.search(
                r"(?:至少|起码|不少于|满|够)\s*([0-9一二三四五六七八九十两]+)\s*小时",
                text,
            )
        if rest_match and ("休息" in text or "停车" in text or "睡觉" in text):
            daily_rest_hours = max(daily_rest_hours, _parse_small_int(rest_match.group(1)) or 0)
            handled = True

        daily_limit = _parse_max_daily_orders(text)
        if daily_limit is not None:
            max_daily_orders = daily_limit if max_daily_orders is None else min(max_daily_orders, daily_limit)
            handled = True

        first_deadline = _parse_first_order_deadline(text)
        if first_deadline is not None:
            first_order_deadline_minute = (
                first_deadline if first_order_deadline_minute is None else min(first_order_deadline_minute, first_deadline)
            )
            handled = True

        parsed_box = _parse_allowed_box(text)
        if parsed_box is not None:
            allowed_box = parsed_box
            handled = True

        forbidden_circle = _parse_forbidden_circle(text)
        if forbidden_circle is not None:
            forbidden_circles.append(forbidden_circle)
            handled = True

        parsed_home = _parse_home_deadline(text)
        if parsed_home is not None:
            home_deadline = parsed_home
            handled = True

        if any(
            key in text
            for key in ("整天", "全天", "完全不出车", "不出车", "停驶", "停运", "不上路", "不跑车", "不排活")
        ) and any(key in text for key in ("每月", "这月", "本月", "月里", "自然月", "三月")):
            value = _number_after_keywords(text, ("至少", "起码", "不少于")) or _number_before_keyword(text, "整天")
            if value is None:
                value = _number_before_keyword(text, "天") or _number_before_keyword(text, "日")
            if value:
                off_days_required = max(off_days_required, value)
                handled = True

        parsed_window = _parse_scheduled_window(text)
        if parsed_window is not None:
            scheduled_window = parsed_window
            handled = True

        if days and any(key in text for key in ("整天", "全天", "完全不出车", "不出车", "停驶", "停运", "检修", "保养", "不排活", "完全歇")):
            fixed_off_days.update(days)
            handled = True

        if ("不同" in text or "自然月" in text) and ("装货" in text or "卸货" in text) and ("至少" in text or "起码" in text):
            need = _number_after_keywords(text, ("至少", "起码", "不少于"))
            region = _region_from_required_text(text)
            if need and region:
                required_region = {"region": region, "min_days": need}
                if coords:
                    lat, lng = coords[0]
                    required_region.update(
                        {
                            "lat": lat,
                            "lng": lng,
                            "radius_km": _radius_km_from_text(text) or 8.0,
                        }
                    )
                handled = True

        if (
            coords
            and ("至少" in text or "起码" in text or "不少于" in text)
            and any(key in text for key in ("天", "日"))
            and any(key in text for key in ("到过", "到达", "抵达", "到目标点", "去到", "停靠", "停到", "经过", "回到"))
        ):
            need = _number_after_keywords(text, ("至少", "起码", "不少于"))
            if need:
                lat, lng = coords[0]
                required_location = {
                    "key": f"loc:{lat:.4f},{lng:.4f}",
                    "lat": lat,
                    "lng": lng,
                    "radius_km": _radius_km_from_text(text) or 1.0,
                    "min_days": need,
                }
                handled = True

        if (
            required_region is None
            and not coords
            and ("至少" in text or "起码" in text or "不少于" in text)
            and any(key in text for key in ("天", "日"))
            and any(key in text for key in ("到过", "到达", "抵达", "去到", "去一趟", "停靠", "经过", "回到"))
        ):
            need = _number_after_keywords(text, ("至少", "起码", "不少于"))
            region = _region_from_required_text(text) or _region_from_required_visit_text(text)
            if need and region:
                required_region = {"region": region, "min_days": need}
                handled = True

        if ("不往" in text or "别给我派进" in text or "不进" in text or "避开" in text or "禁入" in text) and days:
            region = _region_from_block_text(text)
            if region and days:
                if hard_block_text:
                    blocked_region_days.setdefault(region, set()).update(days)
                else:
                    soft_penalty_rules.append(
                        {
                            "kind": "blocked_region_days",
                            "region": region,
                            "days": sorted(days),
                            "penalty": penalty_amount,
                            "text": text,
                        }
                    )
                handled = True

        if days and ("清库存" in text or "盘库" in text or "数目" in text):
            stocktake_day = min(days)
            handled = True
        if days and ("做寿" in text or "寿礼" in text or "赴宴" in text):
            banquet_day = min(days)
            handled = True
        if days and coords and not any(key in text for key in ("清库存", "盘库", "数目", "做寿", "寿礼", "赴宴")):
            dated_stop_events.extend(_generic_dated_stop_events(days, coords, text))
            handled = True

        if not handled:
            hard_rules, soft_rules = _generic_unknown_preference_rules(text, penalty_amount, pref)
            unknown_hard_rules.extend(hard_rules)
            soft_penalty_rules.extend(soft_rules)

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
        "preferred_categories": preferred_categories,
        "forbidden_regions": forbidden_regions,
        "soft_penalty_rules": soft_penalty_rules,
        "pickup_max_km": pickup_max,
        "haul_max_km": haul_max,
        "monthly_empty_km_limit": monthly_empty_km_limit,
        "daily_rest_hours": daily_rest_hours,
        "off_days_required": off_days_required,
        "fixed_off_days": fixed_off_days,
        "scheduled_window": scheduled_window,
        "required_region": required_region,
        "required_location": required_location,
        "home_deadline": home_deadline,
        "allowed_box": allowed_box,
        "forbidden_circles": forbidden_circles,
        "max_daily_orders": max_daily_orders,
        "first_order_deadline_minute": first_order_deadline_minute,
        "blocked_region_days": blocked_region_days,
        "unknown_hard_rules": unknown_hard_rules,
        "event_targets": event_targets,
        "stocktake_event": stocktake_event,
        "banquet_event": banquet_event,
        "dated_stop_events": dated_stop_events,
        "late_month_work": daily_rest_hours >= 8 and off_days_required >= 3,
    }


def _generic_unknown_preference_rules(
    text: str,
    penalty_amount: float,
    entry: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hard = _looks_like_unknown_hard_rule(text)
    soft = not hard and _looks_like_unknown_soft_rule(text)
    if not hard and not soft:
        return [], []

    rule = _unknown_rule_from_text(text, penalty_amount, entry)
    if not _unknown_rule_has_conditions(rule):
        return [], []
    return ([rule], []) if hard else ([], [rule])


def _looks_like_unknown_hard_rule(text: str) -> bool:
    if _is_hard_negative_order_text(text) or _is_hard_block_text(text):
        return True
    return "公里" in text and _is_hard_limit_text(text)


def _looks_like_unknown_soft_rule(text: str) -> bool:
    if _is_soft_negative_order_text(text):
        return True
    if not any(key in text for key in ("扣", "罚", "赔不起", "尽量", "最好别", "少接", "少去")):
        return False
    return any(key in text for key in ("货", "公里", "装货", "卸货", "地区", "市", "区", "县", "镇", "坐标", "去", "往", "进", "那边"))


def _unknown_rule_from_text(
    text: str,
    penalty_amount: float,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "kind": "unknown_text",
        "terms": sorted(_unknown_terms_from_text(text))[:10],
        "days": sorted(_preference_days(text, entry)),
        "penalty": penalty_amount,
        "text": text,
    }
    coords = _coordinates(text)
    if coords:
        radius = _radius_km_from_text(text) or 2.0
        rule["coords"] = [{"lat": lat, "lng": lng, "radius_km": radius} for lat, lng in coords[:3]]
    if "公里" in text:
        value = _first_number_before_unit(text, "公里")
        if value:
            if "空驶" in text or "空车" in text or "空跑" in text:
                rule["pickup_max_km"] = float(value)
            elif any(key in text for key in ("距离", "里程", "路程", "车程")):
                rule["haul_max_km"] = float(value)
    return rule


def _unknown_rule_has_conditions(rule: dict[str, Any]) -> bool:
    return bool(
        rule.get("terms")
        or rule.get("coords")
        or rule.get("pickup_max_km") is not None
        or rule.get("haul_max_km") is not None
    )


def _unknown_terms_from_text(text: str) -> set[str]:
    terms = {name for name in KNOWN_CARGO_CATEGORIES if name in text}
    terms.update(item for item in _quoted_terms(text) if 1 < len(item) <= 12)
    patterns = (
        r"(?:禁止进入|不得进入|不能进入|不准进入|不要进入|禁入|不去|不往|不进|不跑|避开|绕开|别派|别去|别往|少去|不要去|不要进|不要跑|不接|禁接|推掉|不拉|不碰|最好别去|尽量不去|尽量别去)([\u4e00-\u9fa5A-Za-z0-9]{2,12})",
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})(?:货源|货|这类活|这类|类活)",
        r"([\u4e00-\u9fa5]{2,12}(?:省|市|区|县|镇|港|站|园|场))",
    )
    for pattern in patterns:
        for raw in re.findall(pattern, text):
            term = _clean_unknown_term(raw)
            if term:
                terms.add(term)
    return {term for term in terms if _valid_unknown_term(term)}


def _clean_unknown_term(raw: str) -> str:
    term = str(raw).strip(" ，。；、:：()（）")
    for suffix in ("那边", "地区", "区域", "的货源", "货源", "的货", "跑", "活儿", "活", "这类"):
        if term.endswith(suffix):
            term = term[: -len(suffix)]
    return term.strip(" ，。；、")


def _valid_unknown_term(term: str) -> bool:
    if len(term) < 2 or len(term) > 12:
        return False
    stop_terms = {
        "装货地",
        "卸货地",
        "装货",
        "卸货",
        "接单",
        "司机",
        "自然月",
        "三月",
        "公里",
        "地区",
        "货源",
        "这类",
    }
    return term not in stop_terms and not term.isdigit()


def _unknown_rule_matches(
    feature: dict[str, Any],
    status: dict[str, Any],
    rule: dict[str, Any],
    history: list[dict[str, Any]],
) -> bool:
    days = {int(day) for day in rule.get("days", []) or []}
    if days and not _route_overlaps_days(feature, status, days):
        return False

    terms = [str(term) for term in rule.get("terms", []) or [] if str(term).strip()]
    haystacks = (
        str(feature.get("cargo_name", "")),
        str(feature.get("start_city", "")),
        str(feature.get("end_city", "")),
    )
    if terms and any(term in value or value in term for term in terms for value in haystacks if value):
        return True

    pickup_max = rule.get("pickup_max_km")
    if pickup_max is not None and float(feature.get("pickup_km", 0.0) or 0.0) > float(pickup_max):
        return True

    haul_max = rule.get("haul_max_km")
    if haul_max is not None and float(feature.get("haul_km", 0.0) or 0.0) > float(haul_max):
        return True

    for coord in rule.get("coords", []) or []:
        if not isinstance(coord, dict):
            continue
        lat, lng = float(coord.get("lat", 0.0)), float(coord.get("lng", 0.0))
        radius = float(coord.get("radius_km", 2.0) or 2.0)
        if (
            _haversine(float(feature["start_lat"]), float(feature["start_lng"]), lat, lng) <= radius
            or _haversine(float(feature["end_lat"]), float(feature["end_lng"]), lat, lng) <= radius
        ):
            return True
    return False


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
        "price": price,
        "start_lat": start_lat,
        "start_lng": start_lng,
        "end_lat": end_lat,
        "end_lng": end_lng,
        "pickup_km": pickup_km,
        "haul_km": haul_km,
        "ready_min": ready,
        "finish_min": finish,
        "duration_min": total_minutes,
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


def _compact_feature(
    feature: dict[str, Any],
    status: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    region_days: dict[str, dict[str, set[int]]] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out = {
        "cargo_id": feature["cargo_id"],
        "cargo_name": feature["cargo_name"],
        "start_city": feature["start_city"],
        "end_city": feature["end_city"],
        "price": round(float(feature["price"]), 2),
        "pickup_km": round(float(feature["pickup_km"]), 2),
        "haul_km": round(float(feature["haul_km"]), 2),
        "ready_min": int(feature["ready_min"]),
        "finish_min": int(feature["finish_min"]),
        "duration_min": int(feature["duration_min"]),
        "net": round(float(feature["net"]), 2),
        "net_per_hour": round(float(feature["nph"]), 2),
        "estimated_preference_penalty": round(float(feature.get("estimated_penalty", 0.0)), 2),
        "net_after_penalty": round(float(feature.get("net_after_penalty", feature["net"])), 2),
        "risk_adjusted_preference_penalty": round(
            float(feature.get("risk_adjusted_penalty", feature.get("estimated_penalty", 0.0))),
            2,
        ),
        "risk_adjusted_net_after_penalty": round(
            float(feature.get("score_net_after_penalty", feature.get("net_after_penalty", feature["net"]))),
            2,
        ),
        "net_per_hour_after_penalty": round(
            float(feature.get("nph_after_penalty", feature["nph"])),
            2,
        ),
        "soft_penalty_triggers": [
            _compact_soft_penalty_rule(rule)
            for rule in (feature.get("soft_penalty_triggers") or [])[:4]
            if isinstance(rule, dict)
        ],
        "destination_density": int(feature["density"]),
    }
    if status is not None and profile is not None and region_days is not None:
        evidence = _candidate_evidence(feature, status, profile, region_days, history or [])
        if evidence:
            out["selection_evidence"] = evidence
    return out


def _compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "forbidden_categories": sorted(profile["forbidden_categories"]),
        "preferred_categories": sorted(profile.get("preferred_categories", set())),
        "forbidden_regions": sorted(profile["forbidden_regions"]),
        "soft_penalty_rules": [
            _compact_soft_penalty_rule(rule)
            for rule in (profile.get("soft_penalty_rules") or [])[:12]
            if isinstance(rule, dict)
        ],
        "pickup_max_km": profile.get("pickup_max_km"),
        "haul_max_km": profile.get("haul_max_km"),
        "monthly_empty_km_limit": profile.get("monthly_empty_km_limit"),
        "daily_rest_hours": profile.get("daily_rest_hours"),
        "off_days_required": profile.get("off_days_required"),
        "fixed_off_days": sorted(profile.get("fixed_off_days", set())),
        "scheduled_window": profile.get("scheduled_window"),
        "required_region": profile.get("required_region"),
        "required_location": profile.get("required_location"),
        "home_deadline": profile.get("home_deadline"),
        "allowed_box": profile.get("allowed_box"),
        "forbidden_circles": profile.get("forbidden_circles"),
        "max_daily_orders": profile.get("max_daily_orders"),
        "first_order_deadline_minute": profile.get("first_order_deadline_minute"),
        "blocked_region_days": {
            str(region): sorted(int(day) for day in days)
            for region, days in (profile.get("blocked_region_days") or {}).items()
        },
        "unknown_hard_rules": [
            _compact_unknown_rule(rule)
            for rule in (profile.get("unknown_hard_rules") or [])[:8]
            if isinstance(rule, dict)
        ],
        "has_stocktake_event": profile.get("stocktake_event") is not None,
        "has_banquet_event": profile.get("banquet_event") is not None,
        "dated_stop_event_count": len(profile.get("dated_stop_events", []) or []),
    }


def _compact_soft_penalty_rule(rule: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "kind",
        "category",
        "region",
        "terms",
        "max_km",
        "pickup_max_km",
        "haul_max_km",
        "days",
        "penalty",
        "actual_km",
        "excess_km",
    )
    out = {key: rule[key] for key in keep if key in rule}
    coords = rule.get("coords")
    if isinstance(coords, list) and coords:
        out["coord_count"] = len(coords)
    return out


def _compact_unknown_rule(rule: dict[str, Any]) -> dict[str, Any]:
    keep = ("kind", "terms", "days", "pickup_max_km", "haul_max_km", "penalty")
    out = {key: rule[key] for key in keep if key in rule}
    coords = rule.get("coords")
    if isinstance(coords, list) and coords:
        out["coord_count"] = len(coords)
    return out


def _decision_history(api: SimulationApiPort, driver_id: str) -> list[dict[str, Any]]:
    try:
        resp = api.query_decision_history(driver_id, -1)
    except Exception:
        return []
    records = resp.get("records") if isinstance(resp, dict) else None
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def _record_start_end(record: dict[str, Any]) -> tuple[int, int]:
    result = record.get("result")
    end = 0
    if isinstance(result, dict):
        end = int(result.get("simulation_progress_minutes", 0) or 0)
    elapsed = int(record.get("step_elapsed_minutes", 0) or 0)
    return max(0, end - elapsed), max(0, end)


def _accepted_orders_on_day(history: list[dict[str, Any]], day: int) -> int:
    count = 0
    for record in history:
        action = record.get("action")
        result = record.get("result")
        if not isinstance(action, dict) or not isinstance(result, dict):
            continue
        if action.get("action") != "take_order" or not bool(result.get("accepted", False)):
            continue
        start, _ = _record_start_end(record)
        if start // DAY_MINUTES == day:
            count += 1
    return count


def _monthly_empty_km(history: list[dict[str, Any]]) -> float:
    total = 0.0
    for record in history:
        action = record.get("action")
        result = record.get("result")
        if not isinstance(action, dict) or not isinstance(result, dict):
            continue
        if action.get("action") == "reposition":
            total += float(result.get("distance_km", 0.0) or 0.0)
        elif action.get("action") == "take_order" and bool(result.get("accepted", False)):
            total += float(result.get("pickup_deadhead_km", 0.0) or 0.0)
    return total


def _history_progress_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    accepted_count = 0
    daily_orders: dict[int, int] = {}
    accepted_cargo_ids: list[str] = []
    for record in history:
        action = record.get("action")
        result = record.get("result")
        if not isinstance(action, dict) or not isinstance(result, dict):
            continue
        if action.get("action") != "take_order" or not bool(result.get("accepted", False)):
            continue
        accepted_count += 1
        start, _ = _record_start_end(record)
        day = start // DAY_MINUTES
        daily_orders[day] = daily_orders.get(day, 0) + 1
        cargo_id = str(result.get("cargo_id", "") or "").strip()
        if cargo_id:
            accepted_cargo_ids.append(cargo_id)

    last_action: dict[str, Any] = {}
    if history:
        last = history[-1]
        action = last.get("action")
        result = last.get("result")
        if isinstance(action, dict):
            last_action["action"] = action.get("action")
            params = action.get("params")
            if isinstance(params, dict):
                last_action["params"] = params
        if isinstance(result, dict):
            last_action["simulation_progress_minutes"] = result.get("simulation_progress_minutes")
            last_action["accepted"] = result.get("accepted")

    return {
        "total_steps": len(history),
        "accepted_order_count": accepted_count,
        "daily_order_count": {str(day): count for day, count in sorted(daily_orders.items())[-10:]},
        "monthly_empty_km": round(_monthly_empty_km(history), 2),
        "recent_accepted_cargo_ids": accepted_cargo_ids[-12:],
        "last_action": last_action,
    }


def _with_requirement_progress(
    memory_context: dict[str, Any],
    driver_id: str,
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    out = dict(memory_context) if isinstance(memory_context, dict) else {}
    progress_raw = out.get("progress")
    progress = dict(progress_raw) if isinstance(progress_raw, dict) else {}
    requirement_progress = _requirement_progress_summary(driver_id, status, profile, region_days, history)
    if requirement_progress:
        progress["requirements"] = requirement_progress
    out["progress"] = progress
    out.setdefault("preferences", [])
    return out


def _requirement_progress_summary(
    driver_id: str,
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    del history
    day = _time_min(status) // DAY_MINUTES
    state = region_days.get(driver_id, {})
    out: dict[str, Any] = {}

    req = profile.get("required_region")
    if isinstance(req, dict):
        key = _region_requirement_key(req)
        days = sorted(int(item) for item in state.get(key, set()))
        need = int(req.get("min_days", 0) or 0)
        if need > 0:
            item: dict[str, Any] = {
                "key": key,
                "region": req.get("region"),
                "done_days": len(days),
                "need_days": need,
                "remaining_days": max(0, need - len(days)),
                "counted_days_zero_based": days[-10:],
                "current_day_already_counted": day in set(days),
            }
            if req.get("lat") is not None and req.get("lng") is not None:
                item["has_coordinate_radius"] = True
                item["radius_km"] = req.get("radius_km")
            out["required_region"] = item

    loc_req = profile.get("required_location")
    if isinstance(loc_req, dict):
        key = str(loc_req.get("key", "required_location"))
        days = sorted(int(item) for item in state.get(key, set()))
        need = int(loc_req.get("min_days", 0) or 0)
        if need > 0:
            out["required_location"] = {
                "key": key,
                "done_days": len(days),
                "need_days": need,
                "remaining_days": max(0, need - len(days)),
                "counted_days_zero_based": days[-10:],
                "current_day_already_counted": day in set(days),
                "radius_km": loc_req.get("radius_km"),
            }
    return out


def _candidate_evidence(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    driver_id = str(status.get("driver_id", ""))
    day = _time_min(status) // DAY_MINUTES
    state = region_days.get(driver_id, {})
    out: dict[str, Any] = {"route_days_zero_based": _route_days_for_feature(feature, status)}

    req = profile.get("required_region")
    if isinstance(req, dict):
        key = _region_requirement_key(req)
        days = state.get(key, set())
        need = int(req.get("min_days", 0) or 0)
        touches = _feature_touches_region_requirement(feature, req)
        if need > 0:
            out["required_region"] = {
                "touches": touches,
                "adds_new_day": bool(touches and len(days) < need and day not in days),
                "done_days_before_order": len(days),
                "remaining_days_before_order": max(0, need - len(days)),
            }

    loc_req = profile.get("required_location")
    if isinstance(loc_req, dict):
        key = str(loc_req.get("key", "required_location"))
        days = state.get(key, set())
        need = int(loc_req.get("min_days", 0) or 0)
        touches = _feature_touches_location(feature, loc_req)
        if need > 0:
            out["required_location"] = {
                "touches": touches,
                "adds_new_day": bool(touches and len(days) < need and day not in days),
                "done_days_before_order": len(days),
                "remaining_days_before_order": max(0, need - len(days)),
            }

    if str(feature.get("cargo_name", "")) in profile.get("preferred_categories", set()):
        out["preferred_category_match"] = True

    empty_limit = profile.get("monthly_empty_km_limit")
    if empty_limit is not None:
        projected = _monthly_empty_km(history) + float(feature.get("pickup_km", 0.0) or 0.0)
        out["monthly_empty_km_after_order"] = round(projected, 2)

    penalty = float(feature.get("estimated_penalty", 0.0) or 0.0)
    if penalty > 0:
        out["soft_penalty_risk"] = {
            "estimated": round(penalty, 2),
            "trigger_kinds": [
                str(rule.get("kind", "unknown"))
                for rule in (feature.get("soft_penalty_triggers") or [])[:4]
                if isinstance(rule, dict)
            ],
        }
    else:
        out["soft_penalty_risk"] = "none"
    return out


def _route_days_for_feature(feature: dict[str, Any], status: dict[str, Any]) -> list[int]:
    start_day = _time_min(status) // DAY_MINUTES
    finish_day = int(feature.get("finish_min", _time_min(status)) or _time_min(status)) // DAY_MINUTES
    return list(range(start_day, min(finish_day, start_day + 3) + 1))


def _feature_advances_outstanding_requirement(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
) -> bool:
    driver_id = str(status.get("driver_id", ""))
    day = _time_min(status) // DAY_MINUTES
    state = region_days.get(driver_id, {})

    req = profile.get("required_region")
    if isinstance(req, dict):
        days = state.get(_region_requirement_key(req), set())
        need = int(req.get("min_days", 0) or 0)
        if need > 0 and len(days) < need and day not in days and _feature_touches_region_requirement(feature, req):
            return True

    loc_req = profile.get("required_location")
    if isinstance(loc_req, dict):
        key = str(loc_req.get("key", "required_location"))
        days = state.get(key, set())
        need = int(loc_req.get("min_days", 0) or 0)
        if need > 0 and len(days) < need and day not in days and _feature_touches_location(feature, loc_req):
            return True
    return False


def _model_proposal_is_risky(
    selected: dict[str, Any],
    fallback_feature: dict[str, Any],
    candidate_features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> bool:
    if selected.get("cargo_id") == fallback_feature.get("cargo_id"):
        return False

    advances_requirement = _feature_advances_outstanding_requirement(selected, status, profile, region_days)
    selected_penalty = float(selected.get("estimated_penalty", 0.0) or 0.0)
    fallback_penalty = float(fallback_feature.get("estimated_penalty", 0.0) or 0.0)
    if selected_penalty > fallback_penalty and not advances_requirement:
        return True

    if not advances_requirement and not _model_proposal_has_clear_upside(
        selected,
        fallback_feature,
        candidate_features,
        status,
        profile,
        region_days,
        history,
    ):
        return True
    return False


def _model_proposal_has_clear_upside(
    selected: dict[str, Any],
    fallback_feature: dict[str, Any],
    candidate_features: list[dict[str, Any]],
    status: dict[str, Any],
    profile: dict[str, Any],
    region_days: dict[str, dict[str, set[int]]],
    history: list[dict[str, Any]],
) -> bool:
    if not candidate_features:
        return False
    score_ranks = _candidate_ranks(
        candidate_features,
        lambda f: _rule_score(f, status, profile, region_days, history),
    )
    net_ranks = _candidate_ranks(
        candidate_features,
        lambda f: float(f.get("net_after_penalty", f.get("net", 0.0)) or 0.0),
    )
    nph_ranks = _candidate_ranks(
        candidate_features,
        lambda f: float(f.get("nph_after_penalty", f.get("nph", 0.0)) or 0.0),
    )
    selected_id = str(selected.get("cargo_id", "")).strip()
    fallback_id = str(fallback_feature.get("cargo_id", "")).strip()
    missing_rank = len(candidate_features)
    selected_score_rank = score_ranks.get(selected_id, missing_rank)
    selected_net_rank = net_ranks.get(selected_id, missing_rank)
    selected_nph_rank = nph_ranks.get(selected_id, missing_rank)
    fallback_net_rank = net_ranks.get(fallback_id, missing_rank)
    fallback_nph_rank = nph_ranks.get(fallback_id, missing_rank)
    top_score_band = max(1, int(math.sqrt(len(candidate_features))))
    return (
        selected_score_rank < top_score_band
        and selected_net_rank < fallback_net_rank
        and selected_nph_rank < fallback_nph_rank
    )


def _candidate_ranks(
    features: list[dict[str, Any]],
    value_fn: Any,
) -> dict[str, int]:
    ranked = sorted(
        features,
        key=lambda f: (-float(value_fn(f)), str(f.get("cargo_id", ""))),
    )
    ranks: dict[str, int] = {}
    for idx, feature in enumerate(ranked):
        cargo_id = str(feature.get("cargo_id", "")).strip()
        if cargo_id and cargo_id not in ranks:
            ranks[cargo_id] = idx
    return ranks


def _annotate_soft_penalty(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    triggers = _soft_penalty_triggers(feature, status, profile, history)
    penalty = round(sum(_soft_rule_penalty(rule) for rule in triggers), 2)
    net_after = float(feature["net"]) - penalty
    risk_adjusted_penalty = penalty * SOFT_PENALTY_RISK_FACTOR
    score_net_after = float(feature["net"]) - risk_adjusted_penalty
    feature["soft_penalty_triggers"] = triggers
    feature["estimated_penalty"] = penalty
    feature["risk_adjusted_penalty"] = risk_adjusted_penalty
    feature["net_after_penalty"] = net_after
    feature["nph_after_penalty"] = net_after / (max(1, int(feature["duration_min"])) / 60.0)
    feature["score_net_after_penalty"] = score_net_after
    feature["score_nph_after_penalty"] = score_net_after / (max(1, int(feature["duration_min"])) / 60.0)


def _estimated_soft_penalty(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> float:
    return round(sum(_soft_rule_penalty(rule) for rule in _soft_penalty_triggers(feature, status, profile, history)), 2)


def _soft_penalty_triggers(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for rule in profile.get("soft_penalty_rules", []) or []:
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("kind", ""))
        penalty = _soft_rule_penalty(rule)
        if penalty <= 0:
            continue
        triggered = False
        detail: dict[str, Any] = {}
        if kind == "category" and str(feature.get("cargo_name", "")) == str(rule.get("category", "")):
            triggered = True
        elif kind == "region" and _touches_region(feature, str(rule.get("region", ""))):
            triggered = True
        elif kind == "blocked_region_days":
            days = {int(day) for day in rule.get("days", []) or []}
            if _touches_region(feature, str(rule.get("region", ""))) and _route_overlaps_days(feature, status, days):
                triggered = True
        elif kind == "pickup_max_km" and feature["pickup_km"] > float(rule.get("max_km", 0.0) or 0.0):
            max_km = float(rule.get("max_km", 0.0) or 0.0)
            triggered = True
            detail = {"actual_km": float(feature["pickup_km"]), "excess_km": max(0.0, float(feature["pickup_km"]) - max_km)}
        elif kind == "haul_max_km" and feature["haul_km"] > float(rule.get("max_km", 0.0) or 0.0):
            max_km = float(rule.get("max_km", 0.0) or 0.0)
            triggered = True
            detail = {"actual_km": float(feature["haul_km"]), "excess_km": max(0.0, float(feature["haul_km"]) - max_km)}
        elif kind == "monthly_empty_km_limit":
            max_km = float(rule.get("max_km", 0.0) or 0.0)
            projected = _monthly_empty_km(history) + float(feature["pickup_km"])
            if max_km > 0 and projected > max_km + 10.0:
                triggered = True
                detail = {"projected_km": projected, "excess_km": max(0.0, projected - max_km)}
        elif kind == "unknown_text" and _unknown_rule_matches(feature, status, rule, history):
            triggered = True
        if triggered:
            triggers.append({**rule, **detail})
    return triggers


def _soft_rule_penalty(rule: dict[str, Any]) -> float:
    try:
        return max(0.0, float(rule.get("penalty", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _home_deadline_action(status: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
    home = profile.get("home_deadline")
    if not isinstance(home, dict):
        return None
    now = _time_min(status)
    day, tod = divmod(now, DAY_MINUTES)
    lat, lng = float(home["lat"]), float(home["lng"])
    radius = float(home.get("radius_km", 1.0) or 1.0)
    deadline = int(home.get("deadline_minute", 23 * 60) or 23 * 60)
    release = int(home.get("release_minute", 8 * 60) or 8 * 60)
    travel = _distance_minutes(_haversine(_lat(status), _lng(status), lat, lng))
    window = profile.get("scheduled_window")
    in_window = isinstance(window, tuple) and _window_wait_target(day, tod, window) is not None
    should_return = tod >= max(0, deadline - travel - 5)
    if (should_return or in_window) and _haversine(_lat(status), _lng(status), lat, lng) > radius:
        return _reposition(lat, lng)
    if in_window or (tod >= deadline and _haversine(_lat(status), _lng(status), lat, lng) <= radius):
        target = day * DAY_MINUTES + release
        if target <= now:
            target += DAY_MINUTES
        return _wait_until(target, now)
    return None


def _feature_in_allowed_box(feature: dict[str, Any], box: dict[str, float]) -> bool:
    return (
        _point_in_box(float(feature["start_lat"]), float(feature["start_lng"]), box)
        and _point_in_box(float(feature["end_lat"]), float(feature["end_lng"]), box)
    )


def _point_in_box(lat: float, lng: float, box: dict[str, float]) -> bool:
    return (
        float(box["lat_min"]) <= lat <= float(box["lat_max"])
        and float(box["lng_min"]) <= lng <= float(box["lng_max"])
    )


def _feature_touches_circle(feature: dict[str, Any], circle: dict[str, float]) -> bool:
    lat, lng, radius = float(circle["lat"]), float(circle["lng"]), float(circle["radius_km"])
    return (
        _haversine(float(feature["start_lat"]), float(feature["start_lng"]), lat, lng) <= radius
        or _haversine(float(feature["end_lat"]), float(feature["end_lng"]), lat, lng) <= radius
    )


def _feature_touches_location(feature: dict[str, Any], loc: dict[str, Any]) -> bool:
    lat, lng = float(loc["lat"]), float(loc["lng"])
    radius = float(loc.get("radius_km", 2.0) or 2.0)
    return (
        _haversine(float(feature["start_lat"]), float(feature["start_lng"]), lat, lng) <= radius
        or _haversine(float(feature["end_lat"]), float(feature["end_lng"]), lat, lng) <= radius
    )


def _touches_blocked_region_day(feature: dict[str, Any], status: dict[str, Any], profile: dict[str, Any]) -> bool:
    blocked = profile.get("blocked_region_days")
    if not isinstance(blocked, dict) or not blocked:
        return False
    for region, days in blocked.items():
        if not _touches_region(feature, str(region)):
            continue
        if _route_overlaps_days(feature, status, {int(day) for day in days}):
            return True
    return False


def _route_overlaps_days(feature: dict[str, Any], status: dict[str, Any], days: set[int]) -> bool:
    if not days:
        return False
    start_day = _time_min(status) // DAY_MINUTES
    finish_day = int(feature["finish_min"]) // DAY_MINUTES
    return bool(set(range(start_day, finish_day + 1)) & days)


def _can_finish_and_reach_home(feature: dict[str, Any], home: dict[str, Any]) -> bool:
    finish = int(feature["finish_min"])
    day = finish // DAY_MINUTES
    deadline = day * DAY_MINUTES + int(home.get("deadline_minute", 23 * 60) or 23 * 60)
    travel = _distance_minutes(
        _haversine(float(feature["end_lat"]), float(feature["end_lng"]), float(home["lat"]), float(home["lng"]))
    )
    return finish + travel <= deadline


def _feature_conflicts_pending_event(
    feature: dict[str, Any],
    status: dict[str, Any],
    profile: dict[str, Any],
    history: list[dict[str, Any]],
) -> bool:
    now = _time_min(status)
    finish = int(feature["finish_min"])
    for event in _pending_event_specs(profile):
        day = int(event.get("day", -1))
        if day < 0 or now >= (day + 1) * DAY_MINUTES:
            continue
        target = event.get("target")
        if isinstance(target, dict) and _history_satisfies_event_stop(history, event):
            continue
        day_start = day * DAY_MINUTES
        deadline = day_start + int(event.get("arrive_before_minute", DAY_MINUTES) or DAY_MINUTES)
        if now < day_start and finish > day_start:
            return True
        if day_start <= now < deadline and finish > deadline:
            return True
    return False


def _pending_event_specs(profile: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stocktake = profile.get("stocktake_event")
    if isinstance(stocktake, dict) and isinstance(stocktake.get("target"), dict):
        out.append(
            {
                "day": int(stocktake.get("day", -1)),
                "target": stocktake["target"],
                "wait_minutes": int(stocktake.get("wait_minutes", 120) or 120),
            }
        )
    banquet = profile.get("banquet_event")
    if isinstance(banquet, dict) and isinstance(banquet.get("banquet_target"), dict):
        out.append(
            {
                "day": int(banquet.get("day", -1)),
                "target": banquet["banquet_target"],
                "wait_minutes": int(banquet.get("wait_minutes", 120) or 120),
                "arrive_before_minute": 12 * 60,
            }
        )
    for dated in profile.get("dated_stop_events", []) or []:
        if not isinstance(dated, dict):
            continue
        day = int(dated.get("day", -1))
        stops = dated.get("stops")
        if not isinstance(stops, list) or not stops:
            continue
        last_stop = next((stop for stop in reversed(stops) if isinstance(stop, dict)), None)
        if not isinstance(last_stop, dict) or not isinstance(last_stop.get("target"), dict):
            continue
        item = {
            "day": day,
            "target": last_stop["target"],
            "wait_minutes": int(last_stop.get("wait_minutes", 0) or 0),
        }
        if last_stop.get("wait_until_minute") is not None:
            item["arrive_before_minute"] = int(last_stop.get("wait_until_minute") or DAY_MINUTES)
        out.append(item)
    return out


def _history_satisfies_event_stop(history: list[dict[str, Any]], event: dict[str, Any]) -> bool:
    target = event.get("target")
    if not isinstance(target, dict):
        return False
    day = int(event.get("day", -1))
    if day < 0:
        return False
    min_wait = int(event.get("wait_minutes", 0) or 0)
    waited = 0
    arrived = False
    for record in history:
        start, end = _record_start_end(record)
        if end < day * DAY_MINUTES or start >= (day + 1) * DAY_MINUTES:
            continue
        pos = record.get("position_after")
        if not isinstance(pos, dict):
            continue
        try:
            near = _haversine(float(pos["lat"]), float(pos["lng"]), float(target["lat"]), float(target["lng"])) <= 2.0
        except (KeyError, TypeError, ValueError):
            continue
        if not near:
            continue
        arrived = True
        action = record.get("action") if isinstance(record.get("action"), dict) else {}
        if action.get("action") == "wait":
            waited += max(0, min(end, (day + 1) * DAY_MINUTES) - max(start, day * DAY_MINUTES))
    return arrived and waited >= min_wait


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
    return [str(item.get("content", "")) for item in _preference_entries(status)]


def _preference_entries(status: dict[str, Any]) -> list[dict[str, Any]]:
    prefs = status.get("preferences") or []
    out: list[dict[str, Any]] = []
    if isinstance(prefs, list):
        for item in prefs:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str):
                out.append({"content": item})
    return out


def _normalize_preference_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _preference_penalty_amount(entry: dict[str, Any]) -> float:
    try:
        value = float(entry.get("penalty_amount", 0.0) or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else 500.0


def _is_hard_negative_order_text(text: str) -> bool:
    if "不接则" in text or "不接就" in text:
        return False
    return any(
        key in text
        for key in (
            "禁接",
            "一律",
            "推掉",
            "干不了",
            "不接",
            "不拉",
            "不碰",
            "不得接",
            "不能接",
            "禁止接",
            "坚决不接",
            "凡是",
        )
    )


def _is_soft_negative_order_text(text: str) -> bool:
    if _is_hard_negative_order_text(text):
        return False
    return any(
        key in text
        for key in (
            "不想接",
            "不愿接",
            "不太想",
            "尽量不拉",
            "尽量少",
            "少接",
            "少拉",
            "避免",
            "最好别",
            "超一次扣",
            "每次扣",
            "每接一次",
            "扣钱",
            "扣款",
        )
    )


def _is_hard_limit_text(text: str) -> bool:
    return any(key in text for key in ("不得超过", "不超过", "不能超过", "禁止超过", "严禁", "必须"))


def _is_hard_block_text(text: str) -> bool:
    return any(
        key in text
        for key in (
            "别给我派",
            "查车",
            "一律",
            "不得",
            "不能",
            "禁止",
            "不准",
            "不往",
            "不进",
            "不去",
            "不跑",
            "别去",
            "别往",
            "不要去",
            "不要进",
            "禁入",
            "绕开",
        )
    )


def _quoted_terms(text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"[「“\"]([^」”\"]+)[」”\"]", text) if m.strip()]


def _cargo_terms_from_negative_text(text: str) -> set[str]:
    terms = {name for name in KNOWN_CARGO_CATEGORIES if name in text}
    patterns = (
        r"凡是\s*([\u4e00-\u9fa5A-Za-z0-9]{2,12})(?:货源|货物|货|这类活|这类|类活|品类|品种)",
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})(?:货源|货物|货|这类活|这类|类活|品类|品种)(?:我|都|一律|最好|尽量|不)",
        r"(?:不接|禁接|推掉|不拉|不碰|干不了|不想接|不愿接)\s*([\u4e00-\u9fa5A-Za-z0-9]{2,12})",
    )
    for pattern in patterns:
        for raw in re.findall(pattern, text):
            term = _clean_unknown_term(raw)
            if _valid_unknown_term(term):
                terms.add(term)
    return terms


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
            return _clean_region_term(match.group(1))
    return None


def _region_from_travel_block_text(text: str) -> str | None:
    patterns = (
        r"(?:禁止进入|不得进入|不能进入|不准进入|不要进入|禁入|别进|不进|不要进|绕开|避开)\s*([^，。；、]{1,12})",
        r"(?:不去|不往|不跑|别去|别往|不要去|不要往)\s*([^，。；、]{1,12})",
        r"([^，。；、]{2,12})(?:那边|地区|区域|路段|港区|园区|码头|货场)(?:.*?)(?:不去|不往|不进|绕开|避开|禁入)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            term = _clean_region_term(match.group(1))
            if term:
                return term
    return None


def _clean_region_term(raw: str) -> str:
    term = str(raw).strip(" ，。；、:：()（）")
    for suffix in ("那边", "地区", "区域", "路段", "的货", "货源", "跑", "走", "进入", "附近"):
        if term.endswith(suffix):
            term = term[: -len(suffix)]
    return term.strip(" ，。；、")


def _region_from_required_text(text: str) -> str | None:
    match = re.search(r"在([^，。；、（）()]{1,10})的货", text)
    if match:
        return match.group(1)
    match = re.search(r"([\u4e00-\u9fa5]{1,8}(?:区|市|县))", text)
    return match.group(1) if match else None


def _region_from_required_visit_text(text: str) -> str | None:
    patterns = (
        r"(?:到过|到达|抵达|去到|去一趟|停靠|经过|回到)\s*([^，。；、]{1,12})",
        r"([^，。；、]{2,12})(?:至少|起码|不少于)?[0-9一二三四五六七八九十两]+[天日]",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            term = _clean_region_term(match.group(1))
            if term and _valid_unknown_term(term):
                return term
    return None


def _region_from_block_text(text: str) -> str | None:
    match = re.search(r"(?:不往|不进|不去|派进|避开|禁入|绕开)([^，。；、]{1,8})(?:跑|那边|查车|地区|$)", text)
    return _clean_region_term(match.group(1)) if match else None


def _parse_max_daily_orders(text: str) -> int | None:
    if "单" not in text or not any(key in text for key in ("每天", "同一天", "当日", "一天")):
        return None
    patterns = (
        r"(?:不得超过|不超过|最多|至多)\s*([0-9一二三四五六七八九十两]+)\s*单",
        r"([0-9一二三四五六七八九十两]+)\s*单(?:封顶|以内)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _parse_small_int(match.group(1))
    return None


def _parse_first_order_deadline(text: str) -> int | None:
    if "首单" not in text or not any(key in text for key in ("不得晚于", "不晚于", "前")):
        return None
    return _first_clock_minute(text)


def _parse_allowed_box(text: str) -> dict[str, float] | None:
    if not any(key in text for key in ("范围内", "始终在", "不出", "不得出")):
        return None
    match = re.search(
        r"北纬\s*([0-9]+(?:\.[0-9]+)?)\s*(?:至|到|-|~|～)\s*([0-9]+(?:\.[0-9]+)?)[^，。；]*?"
        r"东经\s*([0-9]+(?:\.[0-9]+)?)\s*(?:至|到|-|~|～)\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if not match:
        return None
    lat_a, lat_b, lng_a, lng_b = (float(match.group(i)) for i in range(1, 5))
    return {
        "lat_min": min(lat_a, lat_b),
        "lat_max": max(lat_a, lat_b),
        "lng_min": min(lng_a, lng_b),
        "lng_max": max(lng_a, lng_b),
    }


def _parse_forbidden_circle(text: str) -> dict[str, float] | None:
    if not any(key in text for key in ("不得进入", "禁止进入", "不能进入", "不进")):
        return None
    coords = _coordinates(text)
    radius = _radius_km_from_text(text)
    if not coords or radius is None:
        return None
    lat, lng = coords[0]
    return {"lat": lat, "lng": lng, "radius_km": radius}


def _parse_home_deadline(text: str) -> dict[str, Any] | None:
    if "每天" not in text or not any(key in text for key in ("家", "自家", "老家", "回家", "进家门")):
        return None
    coords = _coordinates(text)
    if not coords:
        return None
    before = re.search(
        r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点\s*前",
        text,
    )
    deadline_minute = None
    before_end = 0
    if before:
        deadline_hour = _parse_clock_hour(before.group(1), before.group(2))
        if deadline_hour is not None:
            deadline_minute = deadline_hour * 60
            before_end = before.end()
    if deadline_minute is None:
        colon_before = re.search(r"([0-2]?\d)(?:[:：]([0-5]\d))?\s*前", text)
        if colon_before:
            deadline_minute = (int(colon_before.group(1)) % 24) * 60 + int(colon_before.group(2) or 0)
            before_end = colon_before.end()
    if deadline_minute is None:
        return None
    release = None
    release_match = re.search(
        r"(?:至|到)\s*(?:次日)?\s*(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点",
        text[before_end:],
    )
    if release_match:
        release_hour = _parse_clock_hour(release_match.group(1), release_match.group(2))
        if release_hour is not None:
            release = release_hour * 60
    if release is None:
        colon_release = re.search(r"(?:至|到)\s*(?:次日)?\s*([0-2]?\d)(?:[:：]([0-5]\d))?", text[before_end:])
        if colon_release:
            release = (int(colon_release.group(1)) % 24) * 60 + int(colon_release.group(2) or 0)
    lat, lng = coords[0]
    return {
        "lat": lat,
        "lng": lng,
        "radius_km": _radius_km_from_text(text) or 1.0,
        "deadline_minute": deadline_minute,
        "release_minute": release or 8 * 60,
    }


def _radius_km_from_text(text: str) -> float | None:
    match = re.search(r"半径\s*([0-9一二三四五六七八九十两百]+)\s*公里", text)
    if match:
        value = _parse_small_int(match.group(1))
        return float(value) if value is not None else None
    match = re.search(r"([0-9一二三四五六七八九十两百]+)\s*公里内", text)
    if match:
        value = _parse_small_int(match.group(1))
        return float(value) if value is not None else None
    return None


def _first_clock_minute(text: str) -> int | None:
    match = re.search(r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点", text)
    if not match:
        return None
    hour = _parse_clock_hour(match.group(1), match.group(2))
    return None if hour is None else hour * 60


def _parse_scheduled_window(text: str) -> tuple[int, int] | None:
    if not any(key in text for key in ("睡觉", "休息", "不接单", "不空车", "不空跑", "熄火", "不跑", "不出车", "停驶", "禁行")):
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
    linked = re.search(
        r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点\s*"
        r"(?:至|到|-|~|～)\s*(?:次日)?\s*"
        r"(凌晨|早上|上午|中午|下午|晚上)?\s*([0-9一二三四五六七八九十两零]+)\s*点",
        text,
    )
    if linked:
        start = _parse_clock_hour(linked.group(1), linked.group(2))
        end = _parse_clock_hour(linked.group(3), linked.group(4))
        if start is not None and end is not None:
            return (start * 60, end * 60)
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


def _preference_days(text: str, entry: dict[str, Any] | None = None) -> set[int]:
    explicit_days = set(_march_days(text))
    days = set(explicit_days)
    ref = _entry_reference_day(entry)
    if ref is not None and not explicit_days:
        if any(key in text for key in ("今天", "今日", "当天", "本日")):
            days.add(ref)
        if "明天" in text:
            days.add(ref + 1)
        if "后天" in text:
            days.add(ref + 2)
        if any(key in text for key in ("月底", "月末", "最后一天")):
            days.add(30)
    return {day for day in days if 0 <= day < 31}


def _entry_reference_day(entry: dict[str, Any] | None) -> int | None:
    if not isinstance(entry, dict):
        return None
    for key in ("first_seen_min", "last_seen_min"):
        if key not in entry:
            continue
        try:
            value = int(entry.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return min(30, max(0, value // DAY_MINUTES))
    return None


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


def _region_requirement_key(req: dict[str, Any]) -> str:
    region = str(req.get("region", "") or "required_region")
    if req.get("lat") is not None and req.get("lng") is not None:
        return f"{region}:{float(req['lat']):.4f},{float(req['lng']):.4f}"
    return region


def _feature_touches_region_requirement(feature: dict[str, Any], req: dict[str, Any]) -> bool:
    region = str(req.get("region", ""))
    if region and _touches_region(feature, region):
        return True
    if req.get("lat") is None or req.get("lng") is None:
        return False
    lat, lng = float(req["lat"]), float(req["lng"])
    radius = float(req.get("radius_km", 8.0) or 8.0)
    return (
        _haversine(float(feature["start_lat"]), float(feature["start_lng"]), lat, lng) <= radius
        or _haversine(float(feature["end_lat"]), float(feature["end_lng"]), lat, lng) <= radius
    )


def _accepted_record_touches_region_requirement(record: dict[str, Any], req: dict[str, Any]) -> bool:
    if req.get("lat") is None or req.get("lng") is None:
        return False
    pos = _accepted_record_position_after(record)
    if pos is None:
        return False
    lat, lng = pos
    return _haversine(lat, lng, float(req["lat"]), float(req["lng"])) <= float(req.get("radius_km", 8.0) or 8.0)


def _accepted_record_touches_location(record: dict[str, Any], loc: dict[str, Any]) -> bool:
    pos = _accepted_record_position_after(record)
    if pos is None:
        return False
    lat, lng = pos
    return _haversine(lat, lng, float(loc["lat"]), float(loc["lng"])) <= float(loc.get("radius_km", 2.0) or 2.0)


def _accepted_record_position_after(record: dict[str, Any]) -> tuple[float, float] | None:
    action = record.get("action")
    result = record.get("result")
    if not isinstance(action, dict) or not isinstance(result, dict):
        return None
    if action.get("action") != "take_order" or not bool(result.get("accepted", False)):
        return None
    pos = record.get("position_after")
    if not isinstance(pos, dict):
        return None
    try:
        return float(pos["lat"]), float(pos["lng"])
    except (KeyError, TypeError, ValueError):
        return None


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
