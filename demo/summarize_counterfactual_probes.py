"""Summarize one or more counterfactual rollout probe directories.

The probe output is intentionally verbose because every candidate writes a
complete replay.  This helper turns those rows into the only table we need for
agent distillation: rule action, best action, score delta, and penalty delta.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize counterfactual probe results.")
    parser.add_argument("paths", nargs="+", help="Probe directories or counterfactual_summary.json files.")
    parser.add_argument("--out", default="", help="Optional markdown output path.")
    parser.add_argument("--min-delta", type=float, default=0.01)
    args = parser.parse_args()

    summaries: list[dict[str, Any]] = []
    for raw in args.paths:
        path = Path(raw)
        summary_path = path if path.name == "counterfactual_summary.json" else path / "counterfactual_summary.json"
        if not summary_path.is_file():
            summaries.append({"probe": str(path), "status": "missing"})
            continue
        summaries.extend(_summarize_file(summary_path, min_delta=args.min_delta))

    text = _render_markdown(summaries)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        json_path = out_path.with_suffix(".json")
        json_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {out_path}")
        print(f"written: {json_path}")
    print(text)
    return 0


def _summarize_file(path: Path, *, min_delta: float) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return [{"probe": str(path.parent), "status": "invalid"}]
    out: list[dict[str, Any]] = []
    for step in sorted({int(row.get("target_step", 0) or 0) for row in rows}):
        step_rows = [row for row in rows if int(row.get("target_step", 0) or 0) == step]
        scored = [row for row in step_rows if row.get("score") is not None]
        if not scored:
            out.append({"probe": str(path.parent), "target_step": step, "status": "unscored"})
            continue
        rule = next((row for row in scored if row.get("is_rule_action")), None)
        best = max(scored, key=lambda row: float(row.get("score") or -1e18))
        if rule is None:
            out.append(
                {
                    "probe": str(path.parent),
                    "target_step": step,
                    "status": "no_rule",
                    "best_score": _num(best.get("score")),
                    "best_action": best.get("candidate_action"),
                    "best_penalty": _num(best.get("penalty")),
                }
            )
            continue
        delta = float(best.get("score") or 0.0) - float(rule.get("score") or 0.0)
        penalty_delta = float(best.get("penalty") or 0.0) - float(rule.get("penalty") or 0.0)
        status = "positive" if delta >= min_delta else "flat_or_negative"
        out.append(
            {
                "probe": str(path.parent),
                "target_step": step,
                "status": status,
                "delta": round(delta, 2),
                "penalty_delta": round(penalty_delta, 2),
                "rule_score": _num(rule.get("score")),
                "best_score": _num(best.get("score")),
                "rule_penalty": _num(rule.get("penalty")),
                "best_penalty": _num(best.get("penalty")),
                "rule_action": rule.get("candidate_action"),
                "best_action": best.get("candidate_action"),
                "best_run_dir": best.get("run_dir"),
            }
        )
    return out


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    positives = [row for row in rows if row.get("status") == "positive"]
    positives.sort(key=lambda row: float(row.get("delta") or 0.0), reverse=True)
    lines = ["# Counterfactual Probe Summary", ""]
    lines.append("## Positive Candidates")
    lines.append("")
    lines.append("| probe | step | delta | penalty_delta | rule | best |")
    lines.append("| --- | ---: | ---: | ---: | --- | --- |")
    for row in positives:
        lines.append(
            f"| `{Path(str(row.get('probe'))).name}` | {row.get('target_step')} | "
            f"{_fmt(row.get('delta'))} | {_fmt(row.get('penalty_delta'))} | "
            f"`{_compact_action(row.get('rule_action'))}` | `{_compact_action(row.get('best_action'))}` |"
        )
    if not positives:
        lines.append("| none |  |  |  |  |  |")
    lines.append("")
    lines.append("## All Steps")
    lines.append("")
    lines.append("| probe | step | status | delta | penalty_delta | best |")
    lines.append("| --- | ---: | --- | ---: | ---: | --- |")
    for row in rows:
        lines.append(
            f"| `{Path(str(row.get('probe'))).name}` | {row.get('target_step', '')} | {row.get('status')} | "
            f"{_fmt(row.get('delta'))} | {_fmt(row.get('penalty_delta'))} | "
            f"`{_compact_action(row.get('best_action'))}` |"
        )
    return "\n".join(lines) + "\n"


def _compact_action(action: Any) -> str:
    if not isinstance(action, dict):
        return ""
    name = str(action.get("action", ""))
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if name == "take_order":
        return f"take:{params.get('cargo_id', '')}"
    if name == "wait":
        return f"wait:{params.get('duration_minutes', '')}"
    if name == "reposition":
        return f"repos:{float(params.get('latitude', 0.0) or 0.0):.2f},{float(params.get('longitude', 0.0) or 0.0):.2f}"
    return name


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
