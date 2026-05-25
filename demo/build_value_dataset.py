"""Build a regret/value dataset from local counterfactual exploration outputs.

The competition agent is an online planner, so it cannot know future cargoes at
submission time.  The local harnesses, however, already give us supervised
labels: for a state/action branch, complete the month with the base policy and
score the exact tail.  This script consolidates those labels into a lightweight
regret table that can be used to design a better value proxy.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent
RESULTS_ROOT = DEMO_ROOT / "results"
DEFAULT_OUT_DIR = RESULTS_ROOT / "value_dataset"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a value/regret dataset from probe summaries.")
    parser.add_argument("--results-root", default=str(RESULTS_ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-abs-delta", type=float, default=0.01)
    args = parser.parse_args()

    results_root = Path(args.results_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    rows.extend(_load_dynamic_rows(results_root, min_abs_delta=float(args.min_abs_delta)))
    rows.extend(_load_sequence_rows(results_root, min_abs_delta=float(args.min_abs_delta)))
    rows.extend(_load_beam_rows(results_root))

    rows.sort(key=lambda row: (str(row.get("driver_id", "")), str(row.get("source_type", "")), -_float(row.get("delta_vs_baseline"))))
    _write_jsonl(out_dir / "value_dataset.jsonl", rows)
    _write_csv(out_dir / "value_dataset.csv", rows)
    _write_markdown(out_dir / "value_dataset_summary.md", rows)

    print(f"rows={len(rows)}")
    print(f"written: {out_dir / 'value_dataset_summary.md'}")
    positives = [row for row in rows if _float(row.get("delta_vs_baseline")) > float(args.min_abs_delta)]
    for row in sorted(positives, key=lambda r: _float(r.get("delta_vs_baseline")), reverse=True)[:12]:
        print(
            json.dumps(
                {
                    "driver": row.get("driver_id"),
                    "source": row.get("source_type"),
                    "step_key": row.get("step_key"),
                    "action": row.get("action_signature"),
                    "delta": row.get("delta_vs_baseline"),
                    "score": row.get("score"),
                    "label": row.get("candidate_label"),
                    "source_path": row.get("source_path"),
                },
                ensure_ascii=False,
            )
        )
    return 0


def _load_dynamic_rows(results_root: Path, *, min_abs_delta: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results_root.rglob("dynamic_summary.json")):
        payload = _read_json(path)
        if not isinstance(payload, list):
            continue
        driver_id = _infer_driver_id(path, payload)
        group_baselines = _dynamic_baselines(payload)
        for item in payload:
            if not isinstance(item, dict) or item.get("status") not in (None, "ok"):
                continue
            action = item.get("candidate_action") if isinstance(item.get("candidate_action"), dict) else {}
            target_step = _int(item.get("target_step"))
            baseline = group_baselines.get(target_step, {})
            score = _float_or_none(item.get("score"))
            delta = _float_or_none(item.get("delta_vs_baseline"))
            row = {
                "source_type": "dynamic",
                "source_path": _rel(path),
                "run_dir": item.get("run_dir"),
                "driver_id": driver_id,
                "step_key": f"{target_step}",
                "target_step": target_step,
                "candidate_rank": _int(item.get("candidate_rank")),
                "candidate_label": item.get("candidate_label"),
                "is_rule_action": bool(item.get("is_rule_action")),
                "action_kind": _action_kind(action),
                "action_signature": _action_signature(action),
                "cargo_id": _cargo_id(action),
                "wait_minutes": _wait_minutes(action),
                "score": score,
                "delta_vs_baseline": delta,
                "label_class": _label_class(delta, min_abs_delta),
                "gross": _float_or_none(item.get("gross")),
                "distance": _float_or_none(item.get("distance")),
                "penalty": _float_or_none(item.get("penalty")),
                "steps": _int(item.get("steps")),
                "progress_minutes": _int(item.get("progress_minutes")),
                "baseline_score": _float_or_none(baseline.get("score")),
                "gross_delta": _delta(item.get("gross"), baseline.get("gross")),
                "distance_delta": _delta(item.get("distance"), baseline.get("distance")),
                "penalty_delta": _delta(item.get("penalty"), baseline.get("penalty")),
                "steps_delta": _delta(item.get("steps"), baseline.get("steps")),
                "progress_delta": _delta(item.get("progress_minutes"), baseline.get("progress_minutes")),
            }
            row.update(_label_features(str(row.get("candidate_label") or "")))
            rows.append(row)
    return rows


def _load_sequence_rows(results_root: Path, *, min_abs_delta: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results_root.rglob("sequence_summary.json")):
        payload = _read_json(path)
        if not isinstance(payload, list):
            continue
        driver_id = _infer_driver_id(path, payload)
        group_baselines = _sequence_baselines(payload)
        for item in payload:
            if not isinstance(item, dict) or item.get("status") not in (None, "ok"):
                continue
            first = item.get("first_action") if isinstance(item.get("first_action"), dict) else {}
            second = item.get("second_action") if isinstance(item.get("second_action"), dict) else {}
            first_step = _int(item.get("first_step"))
            second_step = _int(item.get("second_step"))
            step_key = f"{first_step}:{second_step}"
            baseline = group_baselines.get((first_step, second_step), {})
            score = _float_or_none(item.get("score"))
            delta = _float_or_none(item.get("delta_vs_baseline"))
            row = {
                "source_type": "sequence",
                "source_path": _rel(path),
                "run_dir": item.get("run_dir"),
                "driver_id": driver_id,
                "step_key": step_key,
                "first_step": first_step,
                "second_step": second_step,
                "first_rank": _int(item.get("first_rank")),
                "second_rank": _int(item.get("second_rank")),
                "candidate_label": f"f{_action_signature(first)}__s{_action_signature(second)}",
                "is_rule_action": bool(item.get("is_rule_first")) and bool(item.get("is_rule_second")),
                "is_rule_first": bool(item.get("is_rule_first")),
                "is_rule_second": bool(item.get("is_rule_second")),
                "action_kind": f"{_action_kind(first)}+{_action_kind(second)}",
                "action_signature": f"{_action_signature(first)} -> {_action_signature(second)}",
                "first_action_signature": _action_signature(first),
                "second_action_signature": _action_signature(second),
                "cargo_id": ",".join(part for part in (_cargo_id(first), _cargo_id(second)) if part),
                "wait_minutes": (_wait_minutes(first) or 0) + (_wait_minutes(second) or 0),
                "score": score,
                "delta_vs_baseline": delta,
                "label_class": _label_class(delta, min_abs_delta),
                "gross": _float_or_none(item.get("gross")),
                "distance": _float_or_none(item.get("distance")),
                "penalty": _float_or_none(item.get("penalty")),
                "steps": _int(item.get("steps")),
                "progress_minutes": _int(item.get("progress_minutes")),
                "baseline_score": _float_or_none(baseline.get("score")),
                "gross_delta": _delta(item.get("gross"), baseline.get("gross")),
                "distance_delta": _delta(item.get("distance"), baseline.get("distance")),
                "penalty_delta": _delta(item.get("penalty"), baseline.get("penalty")),
                "steps_delta": _delta(item.get("steps"), baseline.get("steps")),
                "progress_delta": _delta(item.get("progress_minutes"), baseline.get("progress_minutes")),
            }
            rows.append(row)
    return rows


def _load_beam_rows(results_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results_root.rglob("beam_summary.json")):
        payload = _read_json(path)
        if not isinstance(payload, list):
            continue
        driver_id = _infer_driver_id(path, payload)
        for item in payload:
            if not isinstance(item, dict):
                continue
            exact = _float_or_none(item.get("exact_net_income"))
            label = str(item.get("label") or "")
            rows.append(
                {
                    "source_type": "beam",
                    "source_path": _rel(path),
                    "run_dir": item.get("run_dir"),
                    "driver_id": driver_id,
                    "step_key": "",
                    "candidate_rank": _int(item.get("candidate")),
                    "candidate_label": _shorten(label, 220),
                    "is_rule_action": False,
                    "action_kind": "trajectory",
                    "action_signature": _trajectory_signature(label),
                    "score": exact,
                    "delta_vs_baseline": None,
                    "label_class": "unlabeled",
                    "gross": _float_or_none(item.get("exact_gross")),
                    "distance": _float_or_none(item.get("exact_distance")),
                    "penalty": _float_or_none(item.get("exact_penalty")),
                    "steps": _int(item.get("steps")),
                    "progress_minutes": _int(item.get("progress_minutes")),
                    "proxy_score": _float_or_none(item.get("proxy_score")),
                    "proxy_error": None if exact is None else round(exact - _float(item.get("proxy_score")), 2),
                    "beam_steps": _int(item.get("beam_steps")),
                    "beam_progress_minutes": _int(item.get("beam_progress_minutes")),
                }
            )
    return rows


def _dynamic_baselines(payload: list[Any]) -> dict[int | None, dict[str, Any]]:
    baselines: dict[int | None, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        step = _int(item.get("target_step"))
        if item.get("is_rule_action") or _float(item.get("delta_vs_baseline")) == 0.0:
            current = baselines.get(step)
            if current is None or bool(item.get("is_rule_action")):
                baselines[step] = item
    return baselines


def _sequence_baselines(payload: list[Any]) -> dict[tuple[int | None, int | None], dict[str, Any]]:
    baselines: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        key = (_int(item.get("first_step")), _int(item.get("second_step")))
        if (item.get("is_rule_first") and item.get("is_rule_second")) or _float(item.get("delta_vs_baseline")) == 0.0:
            current = baselines.get(key)
            if current is None or (item.get("is_rule_first") and item.get("is_rule_second")):
                baselines[key] = item
    return baselines


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    labeled = [row for row in rows if row.get("source_type") != "beam"]
    positives = [row for row in labeled if _float(row.get("delta_vs_baseline")) > 0.01]
    negatives = [row for row in labeled if _float(row.get("delta_vs_baseline")) < -0.01]
    neutrals = [row for row in labeled if abs(_float(row.get("delta_vs_baseline"))) <= 0.01]
    beam = [row for row in rows if row.get("source_type") == "beam"]

    lines = [
        "# Value Dataset Summary",
        "",
        "This report consolidates local full-tail counterfactual labels into a regret table.",
        "",
        "## Coverage",
        "",
        f"- total rows: {len(rows)}",
        f"- labeled dynamic/sequence rows: {len(labeled)}",
        f"- positives: {len(positives)}",
        f"- neutral/no-op: {len(neutrals)}",
        f"- negatives: {len(negatives)}",
        f"- beam candidates without baseline delta: {len(beam)}",
        "",
        "## Labeled Rows By Driver",
        "",
        "| driver | rows | positive | neutral | negative | best_delta | median_delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for driver_id in sorted({str(row.get("driver_id")) for row in labeled}):
        group = [row for row in labeled if row.get("driver_id") == driver_id]
        deltas = [_float(row.get("delta_vs_baseline")) for row in group]
        lines.append(
            "| {driver} | {rows} | {pos} | {neu} | {neg} | {best:.2f} | {med:.2f} |".format(
                driver=driver_id,
                rows=len(group),
                pos=sum(1 for row in group if _float(row.get("delta_vs_baseline")) > 0.01),
                neu=sum(1 for row in group if abs(_float(row.get("delta_vs_baseline"))) <= 0.01),
                neg=sum(1 for row in group if _float(row.get("delta_vs_baseline")) < -0.01),
                best=max(deltas) if deltas else 0.0,
                med=median(deltas) if deltas else 0.0,
            )
        )

    lines.extend(
        [
            "",
            "## Top Positive Regret Labels",
            "",
            "| driver | source | step | action | delta | gross_delta | distance_delta | penalty_delta | path |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in sorted(positives, key=lambda r: _float(r.get("delta_vs_baseline")), reverse=True)[:30]:
        lines.append(
            "| {driver} | {source} | {step} | `{action}` | {delta:.2f} | {gross:.2f} | {dist:.2f} | {pen:.2f} | {path} |".format(
                driver=row.get("driver_id"),
                source=row.get("source_type"),
                step=row.get("step_key"),
                action=_shorten(str(row.get("action_signature") or ""), 55),
                delta=_float(row.get("delta_vs_baseline")),
                gross=_float(row.get("gross_delta")),
                dist=_float(row.get("distance_delta")),
                pen=_float(row.get("penalty_delta")),
                path=row.get("source_path"),
            )
        )

    lines.extend(
        [
            "",
            "## Candidate Family Signal",
            "",
            "| family | rows | positive_rate | mean_delta | best_delta |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for family, group in _groups(labeled, "candidate_family").items():
        deltas = [_float(row.get("delta_vs_baseline")) for row in group]
        lines.append(
            f"| {family} | {len(group)} | {sum(1 for d in deltas if d > 0.01) / max(1, len(group)):.3f} | "
            f"{mean(deltas):.2f} | {max(deltas):.2f} |"
        )

    lines.extend(
        [
            "",
            "## Action-Type Signal",
            "",
            "| action_kind | rows | positive_rate | mean_delta | best_delta |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for action_kind, group in _groups(labeled, "action_kind").items():
        deltas = [_float(row.get("delta_vs_baseline")) for row in group]
        lines.append(
            f"| `{action_kind}` | {len(group)} | {sum(1 for d in deltas if d > 0.01) / max(1, len(group)):.3f} | "
            f"{mean(deltas):.2f} | {max(deltas):.2f} |"
        )

    if beam:
        lines.extend(
            [
                "",
                "## Beam Proxy Error",
                "",
                "| driver | candidates | mean_exact | mean_proxy | mean_exact_minus_proxy | worst_error |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for driver_id, group in _groups(beam, "driver_id").items():
            exacts = [_float(row.get("score")) for row in group if row.get("score") is not None]
            proxies = [_float(row.get("proxy_score")) for row in group if row.get("proxy_score") is not None]
            errors = [_float(row.get("proxy_error")) for row in group if row.get("proxy_error") is not None]
            lines.append(
                f"| {driver_id} | {len(group)} | {_safe_mean(exacts):.2f} | {_safe_mean(proxies):.2f} | "
                f"{_safe_mean(errors):.2f} | {(min(errors) if errors else 0.0):.2f} |"
            )

    lines.extend(
        [
            "",
            "## Immediate Algorithm Notes",
            "",
            "- Positive labels are sparse; broad reranking/search is mostly destructive unless the value proxy is much sharper.",
            "- Several positive branches accept higher preference penalty when the after-state unlocks a stronger tail chain, so penalty must be marginal rather than a hard constraint.",
            "- Beam proxy error is large on recent smoke runs, confirming that wider beam without a preference/state-value correction is not a high-yield direction.",
            "- Next scorer should rank by expected tail value, not just current net/NPH; this dataset is the teacher table for that scorer.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _groups(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row.get(key) or "")].append(row)
    return dict(sorted(out.items(), key=lambda item: (-len(item[1]), item[0])))


def _label_features(label: str) -> dict[str, Any]:
    lower = label.lower()
    if label == "rule":
        family = "rule"
    elif lower.startswith("top_"):
        family = "top_cargo"
    elif lower.startswith("deep_"):
        family = "deep_cargo"
    elif lower.startswith("dynrepos"):
        family = "dynamic_reposition"
    elif lower.startswith("wait"):
        family = "wait"
    elif lower.startswith("load"):
        family = "event_wait"
    else:
        family = lower.split("_", 1)[0] if lower else "unknown"
    return {"candidate_family": family}


def _infer_driver_id(path: Path, payload: list[Any]) -> str:
    for item in payload:
        if isinstance(item, dict):
            run_dir = item.get("run_dir")
            if isinstance(run_dir, str):
                match = re.search(r"actions_202603_(D\d{3})", run_dir)
                if match:
                    return match.group(1)
    text = str(path)
    matches = re.findall(r"D\d{3}", text, flags=re.IGNORECASE)
    if matches:
        return matches[-1].upper()
    return "UNKNOWN"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _action_kind(action: dict[str, Any]) -> str:
    return str(action.get("action") or "unknown")


def _action_signature(action: dict[str, Any]) -> str:
    kind = _action_kind(action)
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if kind == "take_order":
        return f"take:{params.get('cargo_id')}"
    if kind == "wait":
        return f"wait:{params.get('duration_minutes')}"
    if kind == "reposition":
        lat = _float_or_none(params.get("latitude"))
        lng = _float_or_none(params.get("longitude"))
        if lat is None or lng is None:
            return "reposition:unknown"
        return f"reposition:{lat:.4f},{lng:.4f}"
    return kind


def _trajectory_signature(label: str) -> str:
    if not label:
        return "trajectory"
    parts = [part for part in label.split(">") if part and part != "root"]
    if len(parts) <= 8:
        return " > ".join(parts)
    return " > ".join(parts[:4] + ["..."] + parts[-3:])


def _cargo_id(action: dict[str, Any]) -> str:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    cargo_id = params.get("cargo_id")
    return "" if cargo_id is None else str(cargo_id)


def _wait_minutes(action: dict[str, Any]) -> int | None:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    if _action_kind(action) != "wait":
        return None
    return _int(params.get("duration_minutes"))


def _label_class(delta: float | None, threshold: float) -> str:
    if delta is None:
        return "unlabeled"
    if delta > threshold:
        return "positive"
    if delta < -threshold:
        return "negative"
    return "neutral"


def _delta(value: Any, baseline: Any) -> float | None:
    if value is None or baseline is None:
        return None
    return round(_float(value) - _float(baseline), 2)


def _float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(out):
        return 0.0
    return out


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _shorten(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(DEMO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
