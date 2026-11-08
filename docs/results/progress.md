# Progress log (autonomous-work branch)

Times are local. Plan: `docs/evaluation-protocol.md` + the 8-hour plan agreed 2026-11-07.

- 23:05 Started. Branch `autonomous-work` from `main` (77b9992). RAM 7.6 GB free of 15.2 GB. Word has an open document, left alone.
- 23:10 Added `qwen3-vl-4b` to `playbook/llama_runtime.py` (publisher checksums); downloading llama-server + the 4B in the background via `docs/results/fetch_model.py` (does not touch `local_model.json`; Ollama's 2B stays the configured model).
- Step 1 done: `playbook/study.py` fast harness (+ fidelity test against the real capture path, which found OCR spelling "Batch size" as "Batchsize"), `induce --without`, flag precision/recall/F1.
- Step 2 done: categorical on-screen words as features; `playbook/triage.py` (second domain), `scripts/live_triage_test.py`, `dashboard --domain`. The fidelity test also found OCR reading "9,871" as "9.871" (not fixed; triage screen shows amounts without separators). Triage real-capture check on development seed 100: 40/40 outcomes match the planted rule; the fitted rule equals the fast harness's.
- Dev finding: greedy depth-3 tree gets 0.64 held-out on triage at 40 visits (1.0 on dashboard); depth 4/5 no help; opt-in lookahead 0.83. Recorded in protocol amendment 1 with a prediction that H1 fails on triage.
- Step 3: amendment 1 written, code frozen as tag `freeze-1`.
