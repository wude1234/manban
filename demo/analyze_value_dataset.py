"""Analyze value/regret labels and current action traces.

This script is intentionally small and deterministic: it does not call any
model.  It converts the local exploration history into concrete search
recommendations, so the next probe round targets route-level regret instead of
randomly tweaking thresholds.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_VALUE_DATASET = DEMO_ROOT / "results" / "value_dataset" / "value_dataset.jsonl"
DEFAULT_OUT_DIR = DEMO_ROOT / "results" / "value_dataset"


CURRENT_V94_DRIVER_NET = {
    "D001": 18586.68,
    "D002": 34189.64,
    "D003": 35363.97,
    "D004": 39516.78,
    "D005": 28505.81,
    "D006": 37010.05,
    "D007": 32527.88,
    "D008": 36051.86,
    "D009": 19851.46,
    "D010": 33563.57,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze value dataset and current traces.")
    parser.add_argument("--dataset", default=str(DEFAULT_VALUE_DATASET))
    parser.add_argument(
        "--results-dir",
        default="",
        help="Optional current full-run result dir containing actions_202603_D*.jsonl.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    rows = _load_jsonl(Path(args.dataset))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = _build_report(rows, top_n=max(1, int(args.top_n)))
    trace_report: dict[str, Any] = {}
    if args.results_dir:
        trace_report = _analyze_traces(Path(args.results_dir), top_n=max(1, int(args.top_n)))
        report["current_trace_analysis"] = trace_report

    (out_dir / "value_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(out_dir / "value_analysis.md", report)
    print(f"written: {out_dir / 'value_analysis.md'}")
    print(json.dumps(_console_summary(report), ensure_ascii=False, indent=2))
    return 0


def _build_report(rows: list[dict[str, Any]], *, top_n: int) -> dict[str, Any]:
    labeled = [row for row in rows if row.get("source_type") != "beam" and row.get("delta_vs_baseline") is not None]
    beam = [row for row in rows if row.get("source_type") == "beam"]
    positives = [row for row in labeled if _float(row.get("delta_vs_baseline")) > 0.01]
    above_current = []
    for row in labeled:
        driver_id = str(row.get("driver_id") or "")
        score = row.get("score")
        if driver_id in CURRENT_V94_DRIVER_NET and score is not None:
            gap = round(_float(score) - CURRENT_V94_DRIVER_NET[driver_id], 2)
            if gap > 0.01:
                above_current.append({**row, "gap_vs_current_driver": gap})

    by_driver: dict[str, dict[str, Any]] = {}
    for driver_id in sorted({str(row.get("driver_id") or "") for row in labeled}):
        group = [row for row in labeled if row.get("driver_id") == driver_id]
        deltas = [_float(row.get("delta_vs_baseline")) for row in group]
        pos = [row for row in group if _float(row.get("delta_vs_baseline")) > 0.01]
        by_driver[driver_id] = {
            "rows": len(group),
            "positive": len(pos),
            "neutral": sum(1 for value in deltas if abs(value) <= 0.01),
            "negative": sum(1 for value in deltas if value < -0.01),
            "positive_rate": round(len(pos) / max(1, len(group)), 5),
            "best_delta": round(max(deltas), 2) if deltas else 0.0,
            "median_delta": round(median(deltas), 2) if deltas else 0.0,
            "current_driver_net": CURRENT_V94_DRIVER_NET.get(driver_id),
            "top_positive": [_compact_row(row) for row in sorted(pos, key=lambda r: _float(r.get("delta_vs_baseline")), reverse=True)[:top_n]],
        }

    family_signal = []
    for family, group in _groups(labeled, "candidate_family").items():
        deltas = [_float(row.get("delta_vs_baseline")) for row in group]
        family_signal.append(
            {
                "family": family or "sequence_pair",
                "rows": len(group),
                "positive_rate": round(sum(1 for value in deltas if value > 0.01) / max(1, len(group)), 5),
                "mean_delta": round(mean(deltas), 2) if deltas else 0.0,
                "best_delta": round(max(deltas), 2) if deltas else 0.0,
            }
        )
    family_signal.sort(key=lambda item: (item["positive_rate"], item["best_delta"]), reverse=True)

    beam_signal = []
    for driver_id, group in _groups(beam, "driver_id").items():
        errors = [_float(row.get("proxy_error")) for row in group if row.get("proxy_error") is not None]
        if not errors:
            continue
        beam_signal.append(
            {
                "driver_id": driver_id,
                "rows": len(group),
                "mean_error": round(mean(errors), 2),
                "median_error": round(median(errors), 2),
                "worst_error": round(min(errors), 2),
                "best_error": round(max(errors), 2),
            }
        )
    beam_signal.sort(key=lambda item: item["mean_error"])

    return {
        "dataset_rows": len(rows),
        "labeled_rows": len(labeled),
        "positive_rows": len(positives),
        "above_current_driver_rows": len(above_current),
        "above_current_driver_top": [_compact_row(row) for row in sorted(above_current, key=lambda r: r["gap_vs_current_driver"], reverse=True)[:top_n]],
        "by_driver": by_driver,
        "family_signal": family_signal,
        "beam_proxy_signal": beam_signal,
        "search_implications": _search_implications(by_driver, family_signal, beam_signal, above_current),
    }


def _analyze_traces(results_dir: Path, *, top_n: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted(results_dir.glob("actions_202603_D*.jsonl")):
        driver_id = _driver_id_from_action_path(path)
        records = _load_jsonl(path)
        rows = [_trace_row(record) for record in records]
        waits = [row for row in rows if row["action"] == "wait"]
        orders = [row for row in rows if row["action"] == "take_order"]
        repos = [row for row in rows if row["action"] == "reposition"]
        long_waits = sorted(waits, key=lambda row: (row["exec_minutes"], row["step"]), reverse=True)[:top_n]
        low_eff_orders = sorted(
            [row for row in orders if row["elapsed_minutes"] >= 180],
            key=lambda row: (row["pickup_haul_ratio"], row["elapsed_minutes"]),
            reverse=True,
        )[:top_n]
        day_idle = _day_idle_summary(rows)
        out[driver_id] = {
            "steps": len(rows),
            "wait_steps": len(waits),
            "order_steps": len(orders),
            "reposition_steps": len(repos),
            "wait_hours": round(sum(row["exec_minutes"] for row in waits) / 60.0, 2),
            "active_hours": round(sum(row["exec_minutes"] for row in orders + repos) / 60.0, 2),
            "pickup_km": round(sum(row["pickup_km"] for row in orders), 2),
            "haul_km": round(sum(row["haul_km"] for row in orders), 2),
            "pickup_haul_ratio": round(
                sum(row["pickup_km"] for row in orders) / max(1.0, sum(row["haul_km"] for row in orders)),
                3,
            ),
            "long_waits": long_waits,
            "low_efficiency_orders": low_eff_orders,
            "idle_days": day_idle[:top_n],
            "recommended_probe_steps": _recommend_steps(rows, top_n=top_n),
            "recommended_sequence_pairs": _recommend_pairs(rows, top_n=top_n),
        }
    return out


def _trace_row(record: dict[str, Any]) -> dict[str, Any]:
    action = record.get("action") if isinstance(record.get("action"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    step = _int(record.get("step"))
    start_progress = _progress_before(record)
    end_progress = _int(result.get("simulation_progress_minutes"))
    elapsed = _float(record.get("step_elapsed_minutes"))
    exec_minutes = _float(record.get("action_exec_cost_minutes"))
    query = _float(record.get("query_scan_cost_minutes"))
    pickup = _float(result.get("pickup_deadhead_km"))
    haul = _float(result.get("haul_distance_km"))
    return {
        "step": step,
        "day": int(start_progress // 1440 + 1) if start_progress is not None else None,
        "minute": int(start_progress % 1440) if start_progress is not None else None,
        "end_day": int(end_progress // 1440 + 1) if end_progress is not None else None,
        "action": str(action.get("action") or ""),
        "cargo_id": str(params.get("cargo_id") or ""),
        "wait_minutes": _int(params.get("duration_minutes")) if action.get("action") == "wait" else 0,
        "elapsed_minutes": round(elapsed, 2),
        "exec_minutes": round(exec_minutes, 2),
        "query_minutes": round(query, 2),
        "pickup_km": round(pickup, 2),
        "haul_km": round(haul, 2),
        "pickup_haul_ratio": round(pickup / max(1.0, haul), 3),
        "start_time": _format_day_minute(start_progress),
        "end_time": record.get("simulation_end_time"),
    }


def _progress_before(record: dict[str, Any]) -> int | None:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    end_progress = result.get("simulation_progress_minutes")
    try:
        return int(end_progress) - int(float(record.get("step_elapsed_minutes", 0) or 0))
    except (TypeError, ValueError):
        return None


def _day_idle_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[int, dict[str, Any]] = defaultdict(lambda: {"wait": 0.0, "active": 0.0, "orders": 0, "steps": []})
    for row in rows:
        day = row.get("day")
        if day is None:
            continue
        bucket = by_day[int(day)]
        bucket["steps"].append(row["step"])
        if row["action"] == "wait":
            bucket["wait"] += row["exec_minutes"]
        elif row["action"] in {"take_order", "reposition"}:
            bucket["active"] += row["exec_minutes"]
        if row["action"] == "take_order":
            bucket["orders"] += 1
    out = []
    for day, bucket in by_day.items():
        out.append(
            {
                "day": day,
                "wait_hours": round(bucket["wait"] / 60.0, 2),
                "active_hours": round(bucket["active"] / 60.0, 2),
                "orders": bucket["orders"],
                "step_span": f"{min(bucket['steps'])}-{max(bucket['steps'])}" if bucket["steps"] else "",
            }
        )
    out.sort(key=lambda row: (row["wait_hours"], -row["orders"]), reverse=True)
    return out


def _recommend_steps(rows: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        score = 0.0
        if row["action"] == "wait":
            score += row["exec_minutes"] * 0.55
            if row["exec_minutes"] >= 240:
                score += 80.0
        if row["action"] == "take_order":
            score += row["pickup_km"] * 2.0 + row["elapsed_minutes"] * 0.12
            score += max(0.0, row["pickup_haul_ratio"] - 0.5) * 120.0
        if row["action"] == "reposition":
            score += row["exec_minutes"] * 0.8 + 100.0
        if row.get("day") and row["day"] >= 24:
            score *= 1.2
        if row.get("day") and row["day"] >= 28:
            score *= 1.25
        candidates.append({**row, "probe_priority": round(score, 2)})
    candidates.sort(key=lambda row: row["probe_priority"], reverse=True)
    return candidates[:top_n]


def _recommend_pairs(rows: list[dict[str, Any]], *, top_n: int) -> list[str]:
    probe_steps = [row["step"] for row in _recommend_steps(rows, top_n=max(top_n * 2, 8))]
    pairs: list[str] = []
    for idx, left in enumerate(probe_steps):
        for right in probe_steps[idx + 1 :]:
            if 1 <= right - left <= 28:
                pair = f"{left}:{right}"
                if pair not in pairs:
                    pairs.append(pair)
            if len(pairs) >= top_n:
                return pairs
    return pairs


def _search_implications(
    by_driver: dict[str, dict[str, Any]],
    family_signal: list[dict[str, Any]],
    beam_signal: list[dict[str, Any]],
    above_current: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    if not above_current:
        notes.append("No historical branch beats the current v94 driver score; old positives are already absorbed, so new gains require different state/action search.")
    sparse = [driver for driver, item in by_driver.items() if item["positive_rate"] < 0.005 and item["rows"] >= 500]
    if sparse:
        notes.append(f"Positive labels are sparse for {','.join(sparse)}; broad top-k rerank is expected to destroy score unless gated by route value.")
    if family_signal:
        best_family = family_signal[0]
        notes.append(
            f"Best family by positive rate is {best_family['family']} ({best_family['positive_rate']}); active reposition/sequence repair should be explored as candidate generation, not blind policy."
        )
    bad_beam = [item["driver_id"] for item in beam_signal if item["mean_error"] < -1000]
    if bad_beam:
        notes.append(f"Beam proxy overestimates tail value for {','.join(bad_beam)}; widen beam only after adding preference/rest/fragmentation penalties.")
    notes.append("Next high-yield probes should target long idle plateaus and low-efficiency order clusters on low-net drivers D001/D005/D009, plus tail route repair on D007/D010.")
    return notes


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "driver_id": row.get("driver_id"),
        "source_type": row.get("source_type"),
        "step_key": row.get("step_key"),
        "action_signature": row.get("action_signature"),
        "score": row.get("score"),
        "delta_vs_baseline": row.get("delta_vs_baseline"),
        "gross_delta": row.get("gross_delta"),
        "distance_delta": row.get("distance_delta"),
        "penalty_delta": row.get("penalty_delta"),
        "source_path": row.get("source_path"),
    }
    if "gap_vs_current_driver" in row:
        out["gap_vs_current_driver"] = row["gap_vs_current_driver"]
    return out


def _console_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_rows": report.get("dataset_rows"),
        "positive_rows": report.get("positive_rows"),
        "above_current_driver_rows": report.get("above_current_driver_rows"),
        "search_implications": report.get("search_implications", []),
    }


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Value Analysis",
        "",
        "## Key Findings",
        "",
    ]
    for note in report.get("search_implications", []):
        lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "## Driver Label Saturation",
            "",
            "| driver | rows | positives | positive_rate | best_delta | current_net |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for driver_id, item in sorted((report.get("by_driver") or {}).items()):
        lines.append(
            f"| {driver_id} | {item['rows']} | {item['positive']} | {item['positive_rate']:.5f} | "
            f"{item['best_delta']:.2f} | {item.get('current_driver_net') or 0:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Family Signal",
            "",
            "| family | rows | positive_rate | mean_delta | best_delta |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in (report.get("family_signal") or [])[:12]:
        lines.append(
            f"| {item['family']} | {item['rows']} | {item['positive_rate']:.5f} | "
            f"{item['mean_delta']:.2f} | {item['best_delta']:.2f} |"
        )

    trace = report.get("current_trace_analysis") or {}
    if trace:
        lines.extend(
            [
                "",
                "## Current Trace Hotspots",
                "",
                "| driver | wait_h | active_h | pickup/haul | recommended_steps | sequence_pairs |",
                "| --- | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for driver_id, item in sorted(trace.items()):
            steps = ",".join(str(row["step"]) for row in item.get("recommended_probe_steps", [])[:8])
            pairs = ",".join(item.get("recommended_sequence_pairs", [])[:8])
            lines.append(
                f"| {driver_id} | {item['wait_hours']:.2f} | {item['active_hours']:.2f} | "
                f"{item['pickup_haul_ratio']:.3f} | `{steps}` | `{pairs}` |"
            )

        lines.extend(["", "## Low-Net Driver Detail", ""])
        for driver_id in ("D001", "D005", "D009"):
            item = trace.get(driver_id)
            if not item:
                continue
            lines.append(f"### {driver_id}")
            lines.append("")
            lines.append("| kind | step | day | action | cargo | exec | pickup | haul | start |")
            lines.append("| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |")
            for row in item.get("recommended_probe_steps", [])[:10]:
                lines.append(
                    f"| probe | {row['step']} | {row.get('day') or ''} | {row['action']} | {row.get('cargo_id','')} | "
                    f"{row['exec_minutes']:.1f} | {row['pickup_km']:.1f} | {row['haul_km']:.1f} | {row.get('start_time','')} |"
                )
            lines.append("")

    lines.extend(
        [
            "## Next Probe Recipe",
            "",
            "- Use dynamic candidate generation on the recommended single steps to test active reposition/wait alternatives.",
            "- Use two-step sequence probes on recommended pairs to test route repair, because most positive labels are sequence-level.",
            "- Treat any positive as a teacher label first; only submit after distilling it into a guarded state rule.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _groups(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row.get(key) or "")].append(row)
    return out


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _driver_id_from_action_path(path: Path) -> str:
    parts = path.stem.split("_")
    for part in parts:
        if part.startswith("D") and len(part) == 4:
            return part
    return path.stem


def _format_day_minute(progress: int | None) -> str:
    if progress is None:
        return ""
    day = progress // 1440 + 1
    minute = progress % 1440
    return f"D{day:02d} {minute // 60:02d}:{minute % 60:02d}"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
