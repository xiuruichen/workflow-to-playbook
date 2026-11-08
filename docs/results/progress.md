# Progress log (autonomous-work branch)

Times are local. Plan: `docs/evaluation-protocol.md` + the 8-hour plan agreed 2026-11-07.

- 23:05 Started. Branch `autonomous-work` from `main` (77b9992). RAM 7.6 GB free of 15.2 GB. Word has an open document, left alone.
- 23:10 Added `qwen3-vl-4b` to `playbook/llama_runtime.py` (publisher checksums); downloading llama-server + the 4B in the background via `docs/results/fetch_model.py` (does not touch `local_model.json`; Ollama's 2B stays the configured model).
- Step 1 done: `playbook/study.py` fast harness (+ fidelity test against the real capture path, which found OCR spelling "Batch size" as "Batchsize"), `induce --without`, flag precision/recall/F1.
- Step 2 done: categorical on-screen words as features; `playbook/triage.py` (second domain), `scripts/live_triage_test.py`, `dashboard --domain`. The fidelity test also found OCR reading "9,871" as "9.871" (not fixed; triage screen shows amounts without separators). Triage real-capture check on development seed 100: 40/40 outcomes match the planted rule; the fitted rule equals the fast harness's.
- Dev finding: greedy depth-3 tree gets 0.64 held-out on triage at 40 visits (1.0 on dashboard); depth 4/5 no help; opt-in lookahead 0.83. Recorded in protocol amendment 1 with a prediction that H1 fails on triage.
- Step 3: amendment 1 written, code frozen as tag `freeze-1`.
- Step 4 (confirmatory H1-H4) done on the fast harness: H1 holds on dashboard, FAILS on triage (as predicted); H4 narrow. See `docs/results/confirmatory.md`.
- H6 live runs: first attempt aborted at once (our window was not in the foreground; the click guard stopped it, nothing was clicked elsewhere); fixed with an Alt-key + SetForegroundWindow workaround in `scripts/live_dashboard_test.py` (a deviation in test scripts only), restarted 23:24. Windows log: `docs/results/h6/windows.log`.
- H6 done (23:24-23:48; mouse taken over in two windows, see `docs/results/h6/windows.log`): triage and dashboard seed 1, 40/40 readouts and outcomes each.
- Exploratory E1-E6 done (`docs/results/exploratory.md`). E6 led to a documented deviation (`induce.path_features`).
- Pilot kit, skill dependencies/completion checks, open-questions written. Next: H5 with the 4B model.
