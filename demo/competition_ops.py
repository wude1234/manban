"""Competition operations toolkit.

This is the local "tool layer" for the truck-agent competition.  It keeps the
online decision strategy small and deterministic, while giving offline agents a
stable interface for experiment comparison, memory updates, and driver skills.

Commands:
  list-runs      List current/history runs and scores.
  compare        Compare two run directories at driver level.
  update-memory  Persist best-run memory and generate driver skill notes.
  next           Print the next high-value experiment suggestions.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = DEMO_ROOT / "results"
DEFAULT_HISTORY_DIR = DEFAULT_RESULTS_DIR / "history"
DEFAULT_MEMORY_FILE = DEMO_ROOT / "agent_memory.json"
DEFAULT_SKILLS_DIR = DEMO_ROOT / "skills" / "driver_profiles"
BASELINE_SCORE = 282658.53


DRIVER_NOTES: dict[str, str] = {
    "D001": "Shenzhen-only short-chain driver. Rest penalties are capped and often cheaper than losing good orders.",
    "D002": "Stable high earner. Preserve 4 no-order days and daily 4h rest; current marginal-value behavior is strong.",
    "D003": "Deadhead penalty reaches cap quickly. After cap, chase high net while preserving forbidden-zone and 02:00-05:00 guards.",
    "D004": "Daily quota driver. Treat first order and 3-order limit as a scheduling problem, not pure greedy ranking.",
    "D005": "Hard-filter driver. Keep 100km haul, 90km pickup, and 23:00-06:00 night rules strict.",
    "D006": "High-gross driver. Hard 5h daily rest was negative in experiments; use shadow price rather than hard rest.",
    "D007": "Clean-constraint driver. Night window, machinery ban, 180km haul cap, and one free day already work.",
    "D008": "Expansion-value driver. Keep weekday rest and pickup cap; food orders are soft penalties only.",
    "D009": "Home and known-cargo driver. Do not use all-step LLM or strict home margin; repair only the exact bad day.",
    "D010": "Family-event driver. Family and target visits are hard; daily 3h rest should be opportunity-cost priced.",
}


NEXT_EXPERIMENTS = [
    {
        "name": "Agentic algorithm grid: visible chain value + shadow rest",
        "why": "Date-specific rest patches found a signal, but the submit strategy must generalize. Test whether endpoint chain value and rest shadow pricing recover that signal online.",
        "env": {
            "AGENT_STRATEGY": "new_release_agentic_planner_agent",
            "AGENT_AP_ENABLE_D004_LUNCH_FIRST_TRADEOFF": "1",
            "AGENT_AP_D004_LUNCH_FIRST_MIN_NET": "680",
            "AGENT_AP_D004_LUNCH_FIRST_MIN_NPH": "50",
            "AGENT_AP_ENABLE_VISIBLE_CHAIN_VALUE": "1",
            "AGENT_AP_ENABLE_SHADOW_REST": "1",
            "AGENT_AP_SHADOW_REST_DRIVERS": "D001,D010",
        },
    },
    {
        "name": "D001 chain-value calibration",
        "why": "The largest positive result came from D001 changing the downstream route chain, not from one isolated rest day. Tune D001 chain value before touching more hard rules.",
        "env": {
            "AGENT_STRATEGY": "new_release_agentic_planner_agent",
            "AGENT_AP_ENABLE_D004_LUNCH_FIRST_TRADEOFF": "1",
            "AGENT_AP_D004_LUNCH_FIRST_MIN_NET": "680",
            "AGENT_AP_D004_LUNCH_FIRST_MIN_NPH": "50",
            "AGENT_AP_ENABLE_VISIBLE_CHAIN_VALUE": "1",
            "AGENT_AP_D001_CHAIN_WEIGHT": "0.70",
        },
    },
    {
        "name": "Gated LLM rerank after algorithm baseline",
        "why": "Use Qwen only after the deterministic algorithm is strong, and only for near-tie/high-constraint choices. LLM should break ties, not replace the optimizer.",
        "env": {
            "AGENT_STRATEGY": "llm_rerank_agent",
            "AGENT_LLM_RERANK_BASE_STRATEGY": "new_release_agentic_planner_agent",
            "AGENT_AP_ENABLE_VISIBLE_CHAIN_VALUE": "1",
            "AGENT_AP_ENABLE_SHADOW_REST": "1",
            "AGENT_AP_SHADOW_REST_DRIVERS": "D001,D010",
            "AGENT_LLM_RERANK_DRIVERS": "D004,D009,D010",
            "AGENT_LLM_RERANK_TOP_K": "8",
            "AGENT_LLM_ENABLE_THINKING": "0",
        },
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline competition tool layer.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-runs", help="List current and historical runs.")
    p_list.add_argument("--root", default=str(DEMO_ROOT), help="Demo root directory.")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--sort", choices=["score", "time"], default="score")

    p_cmp = sub.add_parser("compare", help="Compare two run directories.")
    p_cmp.add_argument("--base-dir", default="", help="Base run dir. Defaults to best known historical run.")
    p_cmp.add_argument("--exp-dir", default=str(DEFAULT_RESULTS_DIR), help="Experiment run dir.")

    p_mem = sub.add_parser("update-memory", help="Write agent_memory.json and driver skill notes.")
    p_mem.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    p_mem.add_argument("--label", default="")
    p_mem.add_argument("--memory-file", default=str(DEFAULT_MEMORY_FILE))
    p_mem.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR))

    p_next = sub.add_parser("next", help="Print next high-value experiment suggestions.")
    p_next.add_argument("--memory-file", default=str(DEFAULT_MEMORY_FILE))

    args = parser.parse_args()
    if args.cmd == "list-runs":
        print_json(list_runs(Path(args.root), limit=args.limit, sort_key=args.sort))
    elif args.cmd == "compare":
        base = Path(args.base_dir) if args.base_dir else _best_run_dir(DEMO_ROOT)
        print_json(compare_runs(base, Path(args.exp_dir)))
    elif args.cmd == "update-memory":
        print_json(update_memory(Path(args.results_dir), args.label, Path(args.memory_file), Path(args.skills_dir)))
    elif args.cmd == "next":
        print_json(next_experiments(Path(args.memory_file)))
    return 0


def list_runs(root: Path, *, limit: int, sort_key: str) -> list[dict[str, Any]]:
    demo_root = root.resolve()
    candidates: list[Path] = [demo_root / "results"]
    candidates.extend(sorted((demo_root / "results" / "history").glob("*")))
    rows = [_run_row(path, current=(path == demo_root / "results")) for path in candidates]
    rows = [row for row in rows if row is not None]
    if sort_key == "score":
        rows.sort(key=lambda row: float(row["score"]), reverse=True)
    else:
        rows.sort(key=lambda row: str(row["mtime"]), reverse=True)
    return rows[:limit]


def compare_runs(base_dir: Path, exp_dir: Path) -> dict[str, Any]:
    base = _load_run(base_dir)
    exp = _load_run(exp_dir)
    base_drivers = _driver_map(base["income"])
    exp_drivers = _driver_map(exp["income"])
    driver_rows: list[dict[str, Any]] = []
    for driver_id in sorted(set(base_drivers) | set(exp_drivers)):
        b = base_drivers.get(driver_id, {})
        e = exp_drivers.get(driver_id, {})
        b_inc = b.get("income", {})
        e_inc = e.get("income", {})
        row = {
            "driver_id": driver_id,
            "delta_net": _round2(float(e_inc.get("net_income", 0.0)) - float(b_inc.get("net_income", 0.0))),
            "base_net": b_inc.get("net_income", 0.0),
            "exp_net": e_inc.get("net_income", 0.0),
            "delta_penalty": _round2(float(e_inc.get("preference_penalty", 0.0)) - float(b_inc.get("preference_penalty", 0.0))),
            "base_penalty": b_inc.get("preference_penalty", 0.0),
            "exp_penalty": e_inc.get("preference_penalty", 0.0),
            "delta_gross": _round2(float(e_inc.get("gross_income", 0.0)) - float(b_inc.get("gross_income", 0.0))),
            "delta_distance": _round2(float(e_inc.get("distance_km", 0.0)) - float(b_inc.get("distance_km", 0.0))),
        }
        if any(abs(float(row[key])) > 1e-6 for key in ("delta_net", "delta_penalty", "delta_gross", "delta_distance")):
            driver_rows.append(row)
    driver_rows.sort(key=lambda row: abs(float(row["delta_net"])), reverse=True)
    base_score = _score(base["income"])
    exp_score = _score(exp["income"])
    return {
        "base": {"path": str(base["path"]), "score": base_score, "penalty": _penalty(base["income"])},
        "experiment": {"path": str(exp["path"]), "score": exp_score, "penalty": _penalty(exp["income"])},
        "delta": {
            "score": _round2(exp_score - base_score),
            "vs_baseline_282658_53": _round2(exp_score - BASELINE_SCORE),
            "penalty": _round2(_penalty(exp["income"]) - _penalty(base["income"])),
        },
        "drivers": driver_rows,
        "verdict": _verdict(exp_score, base_score),
    }


def update_memory(results_dir: Path, label: str, memory_file: Path, skills_dir: Path) -> dict[str, Any]:
    run = _load_run(results_dir)
    income = run["income"]
    label = label.strip() or _default_label(results_dir)
    score = _score(income)
    memory = _read_json(memory_file, default={"runs": [], "driver_profiles": {}})
    memory["updated_at"] = datetime.now().isoformat(timespec="seconds")
    memory.setdefault("runs", [])
    memory.setdefault("driver_profiles", {})

    run_item = {
        "label": label,
        "path": str(results_dir.resolve()),
        "score": score,
        "delta_vs_baseline": _round2(score - BASELINE_SCORE),
        "penalty": _penalty(income),
        "tokens": _tokens(income),
    }
    memory["runs"] = [item for item in memory["runs"] if item.get("path") != run_item["path"]]
    memory["runs"].append(run_item)
    memory["runs"].sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    memory["best_run"] = memory["runs"][0] if memory["runs"] else run_item

    created_skills: list[str] = []
    skills_dir.mkdir(parents=True, exist_ok=True)
    for driver in income.get("drivers", []) or []:
        driver_id = str(driver.get("driver_id", ""))
        profile = _driver_profile(driver)
        memory["driver_profiles"][driver_id] = profile
        path = skills_dir / f"{driver_id}.md"
        path.write_text(_render_driver_skill(driver_id, profile), encoding="utf-8")
        created_skills.append(str(path))

    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "memory_file": str(memory_file),
        "skills_dir": str(skills_dir),
        "created_skills": created_skills,
        "recorded_run": run_item,
        "best_run": memory.get("best_run"),
    }


def next_experiments(memory_file: Path) -> dict[str, Any]:
    memory = _read_json(memory_file, default={})
    return {
        "best_run": memory.get("best_run"),
        "next_experiments": NEXT_EXPERIMENTS,
        "baseline_score": BASELINE_SCORE,
    }


def _run_row(path: Path, *, current: bool) -> dict[str, Any] | None:
    monthly = path / "monthly_income_202603.json"
    if not monthly.is_file():
        return None
    data = json.loads(monthly.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    return {
        "label": "current" if current else path.name,
        "path": str(path),
        "score": _score(data),
        "delta_vs_baseline": _round2(_score(data) - BASELINE_SCORE),
        "penalty": summary.get("total_preference_penalty", 0.0),
        "tokens": (summary.get("total_token_usage") or {}).get("total_tokens", 0),
        "failed_driver_count": summary.get("failed_driver_count", 0),
        "mtime": datetime.fromtimestamp(monthly.stat().st_mtime).isoformat(timespec="seconds"),
    }


def _load_run(run_dir: Path) -> dict[str, Any]:
    path = run_dir.resolve()
    monthly = path / "monthly_income_202603.json"
    if not monthly.is_file():
        raise FileNotFoundError(monthly)
    return {"path": path, "income": json.loads(monthly.read_text(encoding="utf-8"))}


def _best_run_dir(root: Path) -> Path:
    rows = list_runs(root, limit=1, sort_key="score")
    if not rows:
        raise FileNotFoundError("No monthly_income_202603.json found under demo/results")
    return Path(rows[0]["path"])


def _driver_map(income: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("driver_id", "")): item for item in income.get("drivers", []) or []}


def _score(income: dict[str, Any]) -> float:
    summary = income.get("summary", {})
    return float(summary.get("total_net_income_all_drivers", summary.get("total_net_income", 0.0)) or 0.0)


def _penalty(income: dict[str, Any]) -> float:
    return float((income.get("summary") or {}).get("total_preference_penalty", 0.0) or 0.0)


def _tokens(income: dict[str, Any]) -> int:
    return int(((income.get("summary") or {}).get("total_token_usage") or {}).get("total_tokens", 0) or 0)


def _driver_profile(driver: dict[str, Any]) -> dict[str, Any]:
    driver_id = str(driver.get("driver_id", ""))
    inc = driver.get("income") or {}
    rules = []
    for rule in (driver.get("preference_check") or {}).get("rules", []) or []:
        if not isinstance(rule, dict):
            continue
        detail = {k: v for k, v in rule.items() if k not in {"preference_text"}}
        rules.append(detail)
    positive_penalties = [rule for rule in rules if float(rule.get("penalty", 0.0) or 0.0) > 0.0]
    return {
        "driver_id": driver_id,
        "net_income": inc.get("net_income"),
        "gross_income": inc.get("gross_income"),
        "distance_km": inc.get("distance_km"),
        "preference_penalty": inc.get("preference_penalty"),
        "active_penalties": positive_penalties,
        "policy_note": DRIVER_NOTES.get(driver_id, "No driver-specific note yet."),
    }


def _render_driver_skill(driver_id: str, profile: dict[str, Any]) -> str:
    penalties = profile.get("active_penalties") or []
    lines = [
        f"# {driver_id} Driver Skill",
        "",
        "## Current Profile",
        "",
        f"- Net income: {profile.get('net_income')}",
        f"- Gross income: {profile.get('gross_income')}",
        f"- Distance km: {profile.get('distance_km')}",
        f"- Preference penalty: {profile.get('preference_penalty')}",
        "",
        "## Policy Note",
        "",
        profile.get("policy_note", ""),
        "",
        "## Active Penalties",
        "",
    ]
    if penalties:
        for item in penalties:
            lines.append(f"- {item}")
    else:
        lines.append("- No active penalty in the recorded run.")
    lines.extend(
        [
            "",
            "## Usage",
            "",
            "Use this as offline procedural memory when proposing strategy changes. Do not read this file from the online competition strategy.",
            "",
        ]
    )
    return "\n".join(lines)


def _default_label(results_dir: Path) -> str:
    if results_dir.name == "results":
        return "current"
    return results_dir.name


def _verdict(exp_score: float, base_score: float) -> str:
    if exp_score > base_score + 1e-6:
        return "improved_vs_base"
    if exp_score < base_score - 1e-6:
        return "regressed_vs_base"
    return "same_as_base"


def _read_json(path: Path, *, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _round2(value: float) -> float:
    return round(float(value), 2)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
