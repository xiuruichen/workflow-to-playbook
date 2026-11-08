# Where each result comes from

All commands run from the project root with the project's `.venv`. Seeds and commits are recorded in each output file.

| Result | File(s) | Command | Seeds | Code |
|---|---|---|---|---|
| H1-H4 confirmatory | `confirmatory.md/.json` | `python scripts/run_confirmatory.py` | 1-5 | tag `freeze-1` |
| H6 real capture | `h6/*` | `bash docs/results/h6/run_live.sh` (takes over the mouse, ~25 min) | 1 | tag `freeze-1` + foreground fix |
| Exploratory E1-E6 | `exploratory.md/.json` | `python scripts/run_exploratory.py` | 1-5 | `freeze-1` + `induce.path_features` |
| H5 agent benefit | `h5/h5.md`, `h5/results.jsonl` | `python scripts/run_h5.py` then `python scripts/summarize_h5.py` (needs the Qwen3-VL 4B files: `python docs/results/fetch_model.py`) | 1-5, 3 repeats | `freeze-1` + strict-prompt fix |
| Amendment 2 (lookahead, min_leaf 3) | `confirmatory2.md/.json` | `python scripts/run_confirmatory2.py` | 6-10 | tag `freeze-2` |
| Amendment 3 (ratio features, service domain) | `confirmatory3.md/.json` | `python scripts/run_confirmatory3.py` | 6-10 | tag `freeze-3` |
| Amendment 4 (elicitation guard) | `confirmatory4.md/.json` | `python scripts/run_confirmatory4.py` | 6-10 | tag `freeze-4` |
| H5 on the service domain (amendment 5) | `h5/h5_service.md`, `h5/results_service.jsonl` | `python scripts/run_h5.py --domains service --ratios --results results_service.jsonl` | 1-5, 3 repeats | tag `freeze-4` + `scripts/run_h5.py` options |
| E7 continuous recording | `e7_continuous.md/.json` | `python scripts/run_continuous.py` | 1-3 | tag `freeze-4` + navigation/dwell options |
| Pilot dry run with an AI as the person | `pilot_dry_run/` | `python -m playbook pilot make --theme run --cases 60 --seed 11`, then `pilot report pilot_dry_run/pilot_log.json` | 11 | current `main` |
| Hidden-rule smoke test, real window, AI as the person | `smoke_test/` | `python scripts/live_hidden_rule_test.py OUT 50 5`, answer each case, then `python scripts/analyze_hidden_rule_test.py OUT` | 5 | current `main` |
| LLM-driven interview (amendment 7) | `interview.md`, `interview/` | `python scripts/run_interview.py`, then `--summarize`; `--expert llm --strategy template,v0_open,...` for question quality | 6-10 (dev: 100-109) | tag `freeze-5` |
| Round 2: extraction on fresh paraphrases (amendment 8, H11) | `fix_extraction_dev.md`, `fix_extraction_test.md`, `interview/extraction_*.json`, `interview/paraphrases.json` | `python scripts/run_fix_extraction.py --set dev` / `--set test` | fresh paraphrases | tag `freeze-6b` |
| Round 2: ordering (H12) and end-to-end interview (H13) | `fix_order.md`, `fix_interview_test.md`, `interview/fix_interview_*.jsonl` | `python scripts/run_fix_interview.py --order-test`; `--test --arms v0/time/single,gated/time/single`; then `--summarize --test --chosen gated/time/single` | 11-15 (dev 100-104) | tag `freeze-6b` |
| Round 2: induction (H14-H18) | `fix_induction.md` | `python scripts/run_fix_induction.py` | 11-15 and the smoke-test recording | tag `freeze-6a` |
| Round 2: executable judgment for the agent (H19) | `fix_agent.md`, `fix_agent/results.jsonl` | `python scripts/run_fix_agent.py`, then `--summarize` | 11-15 | tag `freeze-6b` |
| Round 2: thousands separators (H20) | `fix_capture.md`, `fix_capture_seed100.md` | `python scripts/run_fix_capture.py [seed count]` | 11 (post hoc: 100) | tag `freeze-6a` |
| Triage capture on a development seed | `dev/triage_capture_seed100.json` | `python -m playbook.dashboard --domain triage --visits 40 --seed 100` | 100 | development only |

Development seeds (0 and 100-119) were used to build and tune; no claim rests on them. `docs/evaluation-protocol.md` holds the hypotheses, criteria, amendments and the list of deviations.
