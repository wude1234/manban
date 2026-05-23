"""Post-run harness report for agent strategy exploration.

This tool does not run the simulator.  It reads one completed run directory and
turns the action logs plus monthly scoring file into concrete next experiments.
Use it after every promising run to avoid blind parameter sweeps.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent
HOME_D009 = (23.12, 113.28)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a harness report from one simulator run.")
    parser.add_argument(
        "--run-dir",
        default="",
        help="Run directory containing monthly_income_202603.json and actions_202603_*.jsonl.",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Output directory. Defaults to <run-dir>/harness.",
    )
    parser.add_argument("--top-actions", type=int, default=12)
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "harness"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = build_report(run_dir, top_actions=args.top_actions)
    (out_dir / "harness_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "harness_report.md").write_text(render_markdown(report), encoding="utf-8")

    print(f"run_dir: {run_dir}")
    print(f"written: {out_dir / 'harness_report.md'}")
    print(f"written: {out_dir / 'harness_report.json'}")
    print()
    print(_brief(report))
    return 0


def build_report(run_dir: Path, *, top_actions: int) -> dict[str, Any]:
    income = _load_json(run_dir / "monthly_income_202603.json")
    actions = {driver: rows for driver, rows in _load_actions(run_dir).items()}
    driver_income = _driver_income_rows(income)
    hotspots = _preference_hotspots(income)
    action_stats = {driver: _action_stats(rows) for driver, rows in actions.items()}
    rest_gaps = {
        "D001": _rest_gap_report(actions.get("D001", []), required_minutes=8 * 60),
        "D006": _rest_gap_report(actions.get("D006", []), required_minutes=5 * 60),
        "D010": _rest_gap_report(actions.get("D010", []), required_minutes=3 * 60),
    }
    driver_events = {
        "D003": _d003_deadhead_report(actions.get("D003", []), top_n=top_actions),
        "D004": _d004_day_report(actions.get("D004", [])),
        "D009": _d009_home_report(actions.get("D009", [])),
        "D010": _d010_family_report(income),
    }
    experiments = _recommended_experiments()
    return {
        "run_dir": str(run_dir),
        "summary": income.get("summary", {}),
        "driver_income": driver_income,
        "preference_hotspots": hotspots,
        "action_stats": action_stats,
        "rest_gaps": rest_gaps,
        "driver_events": driver_events,
        "recommended_experiments": experiments,
        "interpretation": _interpretation(hotspots, rest_gaps, driver_events),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report.get("summary", {})
    lines.append("# Agent Harness Report")
    lines.append("")
    lines.append(f"- run_dir: `{report.get('run_dir')}`")
    lines.append(f"- score: `{_fmt(summary.get('total_net_income_all_drivers'))}`")
    lines.append(f"- preference_penalty: `{_fmt(summary.get('total_preference_penalty'))}`")
    lines.append(f"- failed_driver_count: `{summary.get('failed_driver_count')}`")
    lines.append("")

    lines.append("## Preference Hotspots")
    lines.append("")
    lines.append("| rank | driver | penalty | rule | detail |")
    lines.append("| --- | --- | ---: | --- | --- |")
    for idx, row in enumerate(report.get("preference_hotspots", [])[:12], 1):
        lines.append(
            f"| {idx} | {row.get('driver_id')} | {_fmt(row.get('penalty'))} | "
            f"{_escape(row.get('rule'))} | `{_compact(row.get('detail'))}` |"
        )
    lines.append("")

    lines.append("## Driver Income")
    lines.append("")
    lines.append("| driver | net | gross | distance | penalty |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for row in report.get("driver_income", []):
        lines.append(
            f"| {row.get('driver_id')} | {_fmt(row.get('net_income'))} | {_fmt(row.get('gross_income'))} | "
            f"{_fmt(row.get('distance_km'))} | {_fmt(row.get('preference_penalty'))} |"
        )
    lines.append("")

    lines.append("## Harness Findings")
    lines.append("")
    for item in report.get("interpretation", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Rest Gap Details")
    lines.append("")
    for driver, data in report.get("rest_gaps", {}).items():
        if not data:
            continue
        bad_days = data.get("bad_days", [])
        preview = ", ".join(f"D{d['day']:02d}:{d['longest_wait_min']}m" for d in bad_days[:16])
        lines.append(
            f"- {driver}: required={data.get('required_minutes')}m, bad_days={len(bad_days)}, "
            f"preview={preview or 'none'}"
        )
    lines.append("")

    lines.append("## Event Diagnostics")
    lines.append("")
    d003 = report.get("driver_events", {}).get("D003", {})
    lines.append(
        f"- D003 deadhead: pickup_deadhead={_fmt(d003.get('pickup_deadhead_km'))}km, "
        f"reposition={_fmt(d003.get('reposition_km'))}km, top_orders={_compact(d003.get('top_pickup_deadheads'))}"
    )
    d004 = report.get("driver_events", {}).get("D004", {})
    lines.append(
        f"- D004 day issues: late_first_days={_compact(d004.get('late_first_days'))}, "
        f"over_quota_days={_compact(d004.get('over_quota_days'))}, lunch_overlap_steps={_compact(d004.get('lunch_overlap_steps'))}"
    )
    d009 = report.get("driver_events", {}).get("D009", {})
    lines.append(f"- D009 23:00 boundary records: `{_compact(d009.get('records_crossing_23'))}`")
    d010 = report.get("driver_events", {}).get("D010", {})
    lines.append(f"- D010 family: `{_compact(d010)}`")
    lines.append("")

    lines.append("## Recommended Experiments")
    lines.append("")
    for group in report.get("recommended_experiments", []):
        lines.append(f"### {group['name']}")
        lines.append("")
        lines.append(group["purpose"])
        lines.append("")
        lines.append("```bash")
        lines.append(group["command"])
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def _brief(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    hotspots = report.get("preference_hotspots", [])[:5]
    lines = [
        f"score={_fmt(summary.get('total_net_income_all_drivers'))} penalty={_fmt(summary.get('total_preference_penalty'))}",
        "top_hotspots="
        + ", ".join(f"{h.get('driver_id')}:{_fmt(h.get('penalty'))}" for h in hotspots),
        "next="
        + ", ".join(group["name"] for group in report.get("recommended_experiments", [])[:4]),
    ]
    return "\n".join(lines)


def _driver_income_rows(income: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in income.get("drivers", []) or []:
        if not isinstance(item, dict):
            continue
        inc = item.get("income") or {}
        rows.append(
            {
                "driver_id": item.get("driver_id"),
                "net_income": inc.get("net_income"),
                "gross_income": inc.get("gross_income"),
                "distance_km": inc.get("distance_km"),
                "cost": inc.get("cost"),
                "preference_penalty": inc.get("preference_penalty"),
            }
        )
    return sorted(rows, key=lambda r: str(r.get("driver_id", "")))


def _preference_hotspots(income: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in income.get("drivers", []) or []:
        if not isinstance(item, dict):
            continue
        driver_id = str(item.get("driver_id", "")).strip()
        pref = item.get("preference_check") or {}
        for rule in pref.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            penalty = _float(rule.get("penalty"))
            if penalty <= 0:
                continue
            rows.append(
                {
                    "driver_id": driver_id,
                    "penalty": round(penalty, 2),
                    "rule": rule.get("rule"),
                    "detail": {k: v for k, v in rule.items() if k not in {"rule", "preference_text"}},
                }
            )
    rows.sort(key=lambda row: float(row.get("penalty") or 0.0), reverse=True)
    return rows


def _load_actions(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    summary_path = run_dir / "run_summary_202603.json"
    if summary_path.is_file():
        summary = _load_json(summary_path)
        for driver_id, path in (summary.get("driver_result_files") or {}).items():
            action_path = Path(path)
            if action_path.is_file():
                out[str(driver_id).upper()] = list(_iter_jsonl(action_path))
    for path in sorted(run_dir.glob("actions_202603_D*.jsonl")):
        driver_id = _driver_from_action_path(path)
        out.setdefault(driver_id, list(_iter_jsonl(path)))
    return out


def _action_stats(actions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    accepted = 0
    query_scan = 0
    elapsed = 0
    exec_minutes: defaultdict[str, int] = defaultdict(int)
    for rec in actions:
        kind = _action_name(rec)
        counts[kind] += 1
        query_scan += _int(rec.get("query_scan_cost_minutes"))
        elapsed += _int(rec.get("step_elapsed_minutes"))
        exec_minutes[kind] += _int(rec.get("action_exec_cost_minutes"))
        if kind == "take_order" and bool((rec.get("result") or {}).get("accepted")):
            accepted += 1
    return {
        "steps": len(actions),
        "actions": dict(counts),
        "accepted_orders": accepted,
        "query_scan_minutes": query_scan,
        "elapsed_minutes": elapsed,
        "exec_hours_by_action": {k: round(v / 60.0, 2) for k, v in sorted(exec_minutes.items())},
    }


def _rest_gap_report(actions: list[dict[str, Any]], *, required_minutes: int) -> dict[str, Any]:
    if not actions:
        return {}
    horizon_days = max(30, math.ceil(max(_record_end(rec) for rec in actions) / 1440))
    by_day: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for rec in actions:
        if _action_name(rec) != "wait":
            continue
        start = _record_action_start(rec)
        end = _record_end(rec)
        for day in range(start // 1440, end // 1440 + 1):
            a = max(start, day * 1440)
            b = min(end, (day + 1) * 1440)
            if b > a:
                by_day[day + 1].append((a - day * 1440, b - day * 1440))
    bad_days: list[dict[str, Any]] = []
    for day in range(1, horizon_days + 1):
        longest = _longest_merged(by_day.get(day, []))
        if longest < required_minutes:
            bad_days.append({"day": day, "longest_wait_min": longest, "gap_min": required_minutes - longest})
    return {"required_minutes": required_minutes, "bad_days": bad_days}


def _d003_deadhead_report(actions: list[dict[str, Any]], *, top_n: int) -> dict[str, Any]:
    pickup_total = 0.0
    reposition_total = 0.0
    pickups: list[dict[str, Any]] = []
    repositions: list[dict[str, Any]] = []
    for rec in actions:
        result = rec.get("result") or {}
        kind = _action_name(rec)
        if kind == "take_order" and bool(result.get("accepted")):
            km = _float(result.get("pickup_deadhead_km"))
            pickup_total += km
            pickups.append(
                {
                    "step": rec.get("step"),
                    "day": _record_action_start(rec) // 1440 + 1,
                    "cargo_id": ((rec.get("action") or {}).get("params") or {}).get("cargo_id"),
                    "pickup_deadhead_km": round(km, 2),
                    "haul_km": round(_float(result.get("haul_distance_km")), 2),
                    "end_time": rec.get("simulation_end_time"),
                }
            )
        elif kind == "reposition":
            km = _float(result.get("distance_km"))
            reposition_total += km
            repositions.append(
                {
                    "step": rec.get("step"),
                    "day": _record_action_start(rec) // 1440 + 1,
                    "distance_km": round(km, 2),
                    "end_time": rec.get("simulation_end_time"),
                }
            )
    pickups.sort(key=lambda row: float(row["pickup_deadhead_km"]), reverse=True)
    repositions.sort(key=lambda row: float(row["distance_km"]), reverse=True)
    return {
        "pickup_deadhead_km": round(pickup_total, 2),
        "reposition_km": round(reposition_total, 2),
        "top_pickup_deadheads": pickups[:top_n],
        "top_repositions": repositions[:top_n],
    }


def _d004_day_report(actions: list[dict[str, Any]]) -> dict[str, Any]:
    accepted_by_day: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    lunch_overlap: list[dict[str, Any]] = []
    for rec in actions:
        kind = _action_name(rec)
        start = _record_action_start(rec)
        end = _record_end(rec)
        if kind == "take_order" and bool((rec.get("result") or {}).get("accepted")):
            accepted_by_day[start // 1440 + 1].append(rec)
        if kind in {"take_order", "reposition"} and _overlaps_day_window(start, end, 12 * 60, 13 * 60):
            lunch_overlap.append(
                {
                    "step": rec.get("step"),
                    "day": start // 1440 + 1,
                    "action": kind,
                    "start_minute": start % 1440,
                    "end_minute": end % 1440,
                    "end_time": rec.get("simulation_end_time"),
                }
            )
    late_first: list[dict[str, Any]] = []
    over_quota: list[dict[str, Any]] = []
    for day, rows in sorted(accepted_by_day.items()):
        rows.sort(key=_record_action_start)
        first = _record_action_start(rows[0]) % 1440
        if first > 12 * 60:
            late_first.append({"day": day, "first_start_min": first, "first_step": rows[0].get("step")})
        if len(rows) > 3:
            over_quota.append({"day": day, "orders": len(rows), "extra": len(rows) - 3})
    return {
        "late_first_days": late_first,
        "over_quota_days": over_quota,
        "lunch_overlap_steps": lunch_overlap,
        "orders_by_day": {day: len(rows) for day, rows in sorted(accepted_by_day.items())},
    }


def _d009_home_report(actions: list[dict[str, Any]]) -> dict[str, Any]:
    crossing: list[dict[str, Any]] = []
    night_active: list[dict[str, Any]] = []
    for rec in actions:
        start = _record_action_start(rec)
        end = _record_end(rec)
        kind = _action_name(rec)
        if _crosses_daily_minute(start, end, 23 * 60):
            after = rec.get("position_after") or {}
            crossing.append(
                {
                    "step": rec.get("step"),
                    "day": start // 1440 + 1,
                    "action": kind,
                    "start_minute": start % 1440,
                    "end_minute": end % 1440,
                    "end_time": rec.get("simulation_end_time"),
                    "distance_to_home_after_km": round(
                        haversine_km(_float(after.get("lat")), _float(after.get("lng")), HOME_D009[0], HOME_D009[1]), 2
                    ),
                }
            )
        if kind in {"take_order", "reposition"} and _overlaps_night_23_8(start, end):
            night_active.append(
                {
                    "step": rec.get("step"),
                    "day": start // 1440 + 1,
                    "action": kind,
                    "start_minute": start % 1440,
                    "end_minute": end % 1440,
                    "end_time": rec.get("simulation_end_time"),
                }
            )
    return {"records_crossing_23": crossing, "night_active_records": night_active}


def _d010_family_report(income: dict[str, Any]) -> dict[str, Any]:
    for item in income.get("drivers", []) or []:
        if str(item.get("driver_id", "")).upper() != "D010":
            continue
        for rule in ((item.get("preference_check") or {}).get("rules") or []):
            if isinstance(rule, dict) and "家事" in str(rule.get("rule", "")):
                return {k: v for k, v in rule.items() if k not in {"preference_text"}}
    return {}


def _recommended_experiments() -> list[dict[str, str]]:
    py = "/home/zrr/anaconda3/envs/llava/bin/python"
    base = f"cd {DEMO_ROOT} && {py} run_agentic_algo_grid.py --python {py}"
    return [
        {
            "name": "v29_d006_rest_cost_curve",
            "purpose": "Measure whether D006 can buy down the 5600 rest penalty without losing more cargo net.",
            "command": base
            + ' --tag v29_d006_rest_cost_curve --grid "hot_v29_d006_forced_nph60,hot_v29_d006_forced_nph80,hot_v29_d006_forced_morning,hot_v29_d006_forced_after1,hot_v29_d006_shadow_nph60,hot_v29_d006_shadow_nph80,hot_v29_d006_shadow_morning"',
        },
        {
            "name": "v29_d004_day_scheduler",
            "purpose": "Probe D004 first-order, lunch, and max-three-order tradeoffs around the remaining 1800 penalty.",
            "command": base
            + ' --tag v29_d004_day_scheduler --grid "hot_v29_d004_lunch640_50,hot_v29_d004_lunch660_50,hot_v29_d004_lunch680_48,hot_v29_d004_lunch700_50,hot_v29_d004_strict_quota,hot_v29_d004_strict_quota_loose"',
        },
        {
            "name": "v29_d009_home_boundary",
            "purpose": "Find whether the single 900 D009 home violation is cheaper to avoid than to accept.",
            "command": base
            + ' --tag v29_d009_home_boundary --grid "hot_v29_d009_home_slack025,hot_v29_d009_home_slack040,hot_v29_d009_evening_stay45,hot_v29_d009_evening_stay60,hot_v29_d009_limit200,hot_v29_d009_limit240"',
        },
        {
            "name": "v29_d010_rest_after_family",
            "purpose": "After v28 fixed the family event, test whether D010 3h daily rests can stack without harming net.",
            "command": base
            + ' --tag v29_d010_rest_after_family --grid "hot_v29_d010_opp_rest35,hot_v29_d010_opp_rest45,hot_v29_d010_opp_rest60"',
        },
        {
            "name": "v29_flash_guarded_agent",
            "purpose": "Use Qwen3.5-Flash as guarded skill critic after v28; checks agentic value without free-form action risk.",
            "command": "cd "
            + str(DEMO_ROOT)
            + f' && DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY" {py} run_agentic_algo_grid.py --python {py} --tag v29_flash_guarded_agent --grid "hot_v29_flash_confirm,hot_v29_flash_d010_top3_gap12,hot_v29_flash_core_top2"',
        },
    ]


def _interpretation(
    hotspots: list[dict[str, Any]],
    rest_gaps: dict[str, Any],
    events: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    if hotspots:
        top = hotspots[0]
        out.append(
            f"Top remaining penalty is {top.get('driver_id')} {top.get('rule')} = {_fmt(top.get('penalty'))}; prioritize this only if the opportunity cost is below the penalty saved."
        )
    d006_bad = len((rest_gaps.get("D006") or {}).get("bad_days", []))
    if d006_bad:
        out.append(
            f"D006 misses 5h rest on {d006_bad} days. Previous broad forced-rest probes were negative, so next tests should target low-opportunity windows, not blanket daily rest."
        )
    d004 = events.get("D004") or {}
    if d004.get("late_first_days") or d004.get("lunch_overlap_steps"):
        out.append(
            "D004 still has day-scheduler errors. This is a finite-state scheduling problem: first accepted action before noon, no active action at 12-13, and cap marginal 4th+ orders."
        )
    d009 = events.get("D009") or {}
    if d009.get("records_crossing_23") or d009.get("night_active_records"):
        out.append(
            "D009 has a concrete 23:00 boundary issue. Inspect the crossing record before adding stronger home rules, because avoiding it may lose a profitable late order."
        )
    d010_family = (events.get("D010") or {}).get("penalty_absence_minutes")
    if d010_family:
        out.append(
            f"D010 family penalty is now only {_fmt(d010_family)} from unavoidable pickup-home transit minutes; further D010 gain should target daily 3h rest or order chain value."
        )
    d003 = events.get("D003") or {}
    if _float(d003.get("pickup_deadhead_km")) > 1000:
        out.append(
            "D003 deadhead cap is massively exceeded and likely already penalty-capped. Reducing it is only useful if it also improves net fuel cost or avoids long pickup waste."
        )
    return out


def _latest_run_dir() -> Path:
    root = DEMO_ROOT / "results" / "grid_agentic_algo"
    matches = sorted(root.glob("20*/0*_*"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if not matches:
        raise FileNotFoundError(f"no run directories under {root}")
    return matches[-1]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _driver_from_action_path(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return parts[2].upper()
    return path.stem.upper()


def _action_name(record: dict[str, Any]) -> str:
    return str((record.get("action") or {}).get("action", "")).strip().lower()


def _record_step_start(record: dict[str, Any]) -> int:
    return max(0, _record_end(record) - _int(record.get("step_elapsed_minutes")))


def _record_action_start(record: dict[str, Any]) -> int:
    return _record_step_start(record) + _int(record.get("query_scan_cost_minutes"))


def _record_end(record: dict[str, Any]) -> int:
    return _int((record.get("result") or {}).get("simulation_progress_minutes"))


def _longest_merged(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    intervals = sorted(intervals)
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return max(end - start for start, end in merged)


def _overlaps_day_window(start: int, end: int, window_start: int, window_end: int) -> bool:
    for day in range(start // 1440, end // 1440 + 1):
        a = day * 1440 + window_start
        b = day * 1440 + window_end
        if max(start, a) < min(end, b):
            return True
    return False


def _crosses_daily_minute(start: int, end: int, minute: int) -> bool:
    for day in range(start // 1440, end // 1440 + 1):
        point = day * 1440 + minute
        if start <= point <= end:
            return True
    return False


def _overlaps_night_23_8(start: int, end: int) -> bool:
    for day in range(start // 1440 - 1, end // 1440 + 1):
        if max(start, day * 1440 + 23 * 60) < min(end, (day + 1) * 1440 + 8 * 60):
            return True
    return False


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _compact(value: Any, *, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
