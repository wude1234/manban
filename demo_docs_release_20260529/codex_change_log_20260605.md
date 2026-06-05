# Codex Change Log 2026-06-05

Target: `demo/agent/model_decision_service.py`

## Completed

- Added `ModelDecisionService._compiled_profile_cache` to cache compiled preference profiles per driver and observed-preference signature.
- Replaced both direct `_preference_profile_from_entries(...)` calls in `decide()` with `self._compile_profile(driver_id, remembered_preferences)`.
- Added `ModelDecisionService._compile_profile(...)` to combine the deterministic local preference parser with a cached model-compiled profile.
- Added `ModelDecisionService._ask_model_for_preference_profile(...)` to ask the official model API for a structured preference profile, with exception fallback to the local parser.
- Added profile merge/sanitization helpers: model output is type-checked, numeric limits are clipped/merged conservatively, soft rules and unknown hard rules are deduplicated, and local parser output remains the baseline.
- Hardened live-model merge after API testing: model `scheduled_window` cannot override a local window and must be at most 12 hours, model-only `home_deadline` is ignored, model-only fixed off days are ignored unless local parsing already found fixed days, and model coordinates/boxes must pass a Guangdong/nearby-region plausibility check.
- Further hardened live-model merge after inspecting raw returns: model blocked-region days no longer expand locally parsed days for the same region, full-month blocked-region outputs are folded into `forbidden_regions`, and redundant/non-actionable `unknown_text` rules for rest, off-days, maintenance, banquets, and already-covered categories/regions are filtered.
- Preserved legally observed preference metadata (`start_time`, `end_time`, `penalty_cap`) in `RuntimePreferenceMemory` for the preference compiler and model context.
- Relaxed `_gate_soft_penalty_candidates(...)`: clean candidates remain preferred, high-upside soft-penalty candidates can pass the existing exception gate, and all-soft candidate pools fall back to the best risk-adjusted options instead of immediate waiting.

## Verification

- `python3 -m py_compile demo/agent/model_decision_service.py` passed.
- `/home/zrr/anaconda3/envs/llava/bin/python -m py_compile demo/agent/model_decision_service.py` passed.
- Function smoke passed for D001/D002 public preference parsing and merge deduplication.
- Compiler cache smoke passed: repeated `_compile_profile(...)` with identical observed preferences called the fake model once and reused the cached model profile.
- Offline fallback simulation smoke passed with a deliberately unavailable model URL:
  `DASHSCOPE_API_KEY=fake /home/zrr/anaconda3/envs/llava/bin/python demo/server/main.py --simulation-days 1 --max-steps 4 --model-api-url http://127.0.0.1:1 --model-timeout 0.2 --results-dir /tmp/demo_docs_profile_smoke`
  Result: 8 completed steps, 0 driver failures.
- Final offline fallback smoke after live-response hardening passed:
  `DASHSCOPE_API_KEY=fake /home/zrr/anaconda3/envs/llava/bin/python demo/server/main.py --simulation-days 1 --max-steps 2 --model-api-url http://127.0.0.1:1 --model-timeout 0.2 --results-dir /tmp/demo_docs_profile_final_smoke`
  Result: 4 completed steps, 0 driver failures.
- Live API probe with the provided key passed for both `qwen-turbo` and `qwen3.5-flash`; both returned valid JSON under `response_format=json_object`. `qwen3.5-flash` had cleaner preference compiler output and lower completion-token use in the D002 compiler probe.
- Live `qwen3.5-flash` simulation smoke passed:
  `DASHSCOPE_API_KEY=... /home/zrr/anaconda3/envs/llava/bin/python demo/server/main.py --simulation-days 1 --max-steps 4 --model-timeout 20 --model-name qwen3.5-flash --results-dir /tmp/demo_docs_profile_api_qwen35`
  Result: 8 completed steps, 0 driver failures, token usage D001=5051 and D002=5654.
- Raw live-model return inspection (`/tmp/demo_docs_profile_api_returns`) showed:
  D001 selected cargo `306563` because it avoided mechanical-equipment/Huizhou constraints and had strong net income; D002 selected cargo `306486` because it advanced the required Zengcheng-region monthly objective while respecting the 55 km soft pickup limit.
- Full 31-day live `qwen3.5-flash` simulation passed:
  `DASHSCOPE_API_KEY=... /home/zrr/anaconda3/envs/llava/bin/python demo/server/main.py --simulation-days 31 --model-timeout 20 --model-name qwen3.5-flash --results-dir /tmp/demo_docs_profile_full_qwen35`
  Result: 237 completed steps, remaining cargo count 0, driver failures 0, end reasons D001=normal and D002=normal, token usage D001=113009 and D002=109665.
- Packaged ZIP:
  `/home/zrr/study/demo_docs_release_20260529/submission_profile_compiler_livechecked_20260605_152621.zip`

## Recovery Notes

- Previous untouched package remains at:
  `/home/zrr/study/demo_docs_release_20260529/submission_hidden_guard_20260605.zip`
- New package source directory:
  `/home/zrr/study/demo_docs_release_20260529/submission_profile_compiler_livechecked_20260605_152621/`
- Intermediate package kept for comparison:
  `/home/zrr/study/demo_docs_release_20260529/submission_profile_compiler_20260605_150710.zip`
