"""Build a hybrid result directory from existing per-driver action files.

This utility is for local score/submission artifact assembly.  It does not run
an agent; it copies selected action JSONL files, writes a consistent
``run_summary_202603.json``, then invokes ``calc_monthly_income.py``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a hybrid score result directory.")
    parser.add_argument("--base-dir", required=True, help="Directory containing baseline actions_202603_D*.jsonl files.")
    parser.add_argument("--out-dir", required=True, help="Directory to write the hybrid result.")
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        help="Replacement mapping DRIVER=path/to/actions.jsonl. Can be repeated.",
    )
    parser.add_argument("--simulate-time-seconds", type=float, default=0.0)
    args = parser.parse_args()

    started = time.perf_counter()
    base_dir = Path(args.base_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    replacements = _parse_replacements(args.replace)
    copied: dict[str, Path] = {}

    for driver_idx in range(1, 11):
        driver_id = f"D{driver_idx:03d}"
        source = replacements.get(driver_id)
        if source is None:
            matches = sorted(base_dir.glob(f"actions_202603_{driver_id}_*.jsonl"))
            if not matches:
                raise FileNotFoundError(f"missing base action file for {driver_id} in {base_dir}")
            source = matches[0]
        if not source.is_file():
            raise FileNotFoundError(f"missing replacement action file for {driver_id}: {source}")
        target = out_dir / source.name
        if target.exists():
            target.unlink()
        shutil.copy2(source, target)
        copied[driver_id] = target

    step_counts = {driver_id: _count_lines(path) for driver_id, path in copied.items()}
    summary = {
        "month": "2026-03",
        "simulate_time_seconds": round(float(args.simulate_time_seconds) or (time.perf_counter() - started), 2),
        "simulation_duration_days": 30,
        "completed_steps": sum(step_counts.values()),
        "remaining_cargo_count": 0,
        "driver_completed_steps": step_counts,
        "driver_result_files": {driver_id: str(path) for driver_id, path in copied.items()},
    }
    (out_dir / "run_summary_202603.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(DEMO_ROOT / "calc_monthly_income.py"),
            "--project-root",
            str(DEMO_ROOT),
            "--results-dir",
            str(out_dir),
        ],
        cwd=str(DEMO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (out_dir / "calc.log").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout, end="")
        return proc.returncode
    monthly = json.loads((out_dir / "monthly_income_202603.json").read_text(encoding="utf-8"))
    print(json.dumps(monthly.get("summary", {}), ensure_ascii=False, indent=2))
    return 0


def _parse_replacements(items: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--replace must be DRIVER=path, got: {item}")
        driver_id, raw_path = item.split("=", 1)
        driver_id = driver_id.strip().upper()
        if not driver_id:
            raise ValueError(f"empty driver id in replacement: {item}")
        out[driver_id] = Path(raw_path).resolve()
    return out


def _count_lines(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


if __name__ == "__main__":
    raise SystemExit(main())
