#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/zrr/anaconda3/envs/llava/bin/python}"
JOBS="${JOBS:-3}"
TAG_PREFIX="${TAG_PREFIX:-legal_value_batch}"
LOG_ROOT="$ROOT/results/batch_logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="$LOG_ROOT/${STAMP}_${TAG_PREFIX}"

mkdir -p "$RUN_ROOT"

run_grid() {
  local name="$1"
  local grid="$2"
  local trace="${3:-0}"
  local log="$RUN_ROOT/${name}.log"
  echo "[batch] start $name grid=$grid trace=$trace log=$log"
  if [[ "$trace" == "1" ]]; then
    (cd "$ROOT" && "$PYTHON_BIN" run_agentic_algo_grid.py --python "$PYTHON_BIN" --tag "${TAG_PREFIX}_${name}" --trace --grid "$grid") >"$log" 2>&1
  else
    (cd "$ROOT" && "$PYTHON_BIN" run_agentic_algo_grid.py --python "$PYTHON_BIN" --tag "${TAG_PREFIX}_${name}" --grid "$grid") >"$log" 2>&1
  fi
  echo "[batch] done  $name"
}

wait_for_slot() {
  while (( $(jobs -rp | wc -l) >= JOBS )); do
    sleep 5
  done
}

run_grid "baseline" "submission_official_clean,submission_official_distilled_value" 1 &
wait_for_slot

run_grid "single_tight" "legal_value_d003_tight,legal_value_d008_tight,legal_value_d010_tight" 1 &
wait_for_slot

run_grid "pair_tight" "legal_value_d003d008_tight,legal_value_d003d010_tight,legal_value_d008d010_tight,legal_value_core_tight" 0 &
wait_for_slot

run_grid "single_ultratight" "legal_value_d003_ultratight,legal_value_d008_ultratight,legal_value_d010_ultratight,legal_value_core_ultratight" 0 &
wait_for_slot

run_grid "single_light" "legal_value_d003_light,legal_value_d008_light,legal_value_d010_light,legal_value_core_light,legal_value_d003d008_light" 0 &
wait

echo
echo "[batch] all done: $RUN_ROOT"
echo "[batch] grid summaries:"
find "$ROOT/results/grid_agentic_algo" -maxdepth 1 -type d -name "*${TAG_PREFIX}_*" -printf '%f\n' | sort | tail -20
