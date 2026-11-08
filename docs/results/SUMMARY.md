# Summary of the autonomous block (branch `autonomous-work`, 2026-11-07/08)

Everything here is a scripted "person" on synthetic domains, except where stated. Nothing yet involves a real expert.

## Built
- Fast model-free harness (`study.py`), checked against the real capture path; ablations; flag precision/recall/F1.
- Second domain (invoice triage) with a word on screen and a different cross-session exception; categorical readouts as features; opt-in lookahead tree.
- Skill export with `depends_on` and `completion_checks`; observability class for cross-session decisions from the decision's own path.
- Pilot kit for one real person (`python -m playbook pilot make|report|elicit`, `docs/pilot-guide.md`).
- Qwen3-VL 4B added to the local runtime table (publisher checksums).

## Results (protocol: `docs/evaluation-protocol.md`, amendment 1, tag `freeze-1`)
| | result |
|---|---|
| H1 rule recovery >= 0.90 | holds on the dashboard (1.00); **fails on triage** (0.87 at 40 visits, 0.89-0.93 at 80), as predicted |
| H2 cross-session context helps | holds, except greedy triage at 40 visits (tie) |
| H3 non-actions | descriptive only: without them the rule can only say "act" |
| H4 one elicitation round | holds narrowly (+0.04, +0.03); 6 of 10 runs unchanged |
| H5 judgment helps an agent (4B) | not on the dashboard (0.77 -> 0.77/0.80); on triage 0.44 -> 0.56, mostly by asking a human; rules read mechanically 1.00 / 0.82 |
| H6 real capture | holds on both domains (40/40 readouts and outcomes) |
| H7 classifier vs human labels | not run (needs a human labelled set); E6 proxy: path-based O5 is 100% / 82% right vs 60% / 40% before |

Exploratory: a compound rule needs about 100+ visits; label noise hurts triage far more than the dashboard and its disagreements are weak evidence of hidden reasons there; OCR misreads up to 5% are harmless on the dashboard.

## Bugs found by the work itself
Fast-harness fidelity test: OCR spells "Batch size" as "Batchsize" (fixed) and reads "9,871" as "9.871" (not fixed). First H6 attempt: window not in the foreground (guard worked, fixed). H5 variant B: the strict sentence was never applied (found because results were identical; fixed and re-run).

## Not done / for you
See `docs/open-questions.md`. The one experiment that can show the goal is met, the real-person pilot, is ready and needs you (about 45 minutes).
