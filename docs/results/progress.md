# Progress log (autonomous-work branch)

Times are local. Plan: `docs/evaluation-protocol.md` + the 8-hour plan agreed 2026-11-07.

- 23:05 Started. Branch `autonomous-work` from `main` (77b9992). RAM 7.6 GB free of 15.2 GB. Word has an open document, left alone.
- 23:10 Added `qwen3-vl-4b` to `playbook/llama_runtime.py` (publisher checksums); downloading llama-server + the 4B in the background via `docs/results/fetch_model.py` (does not touch `local_model.json`; Ollama's 2B stays the configured model).
