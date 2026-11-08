# Evaluation protocol

Status: **written before the next round of runs**; the criteria below must not be changed after seeing results (add a dated amendment instead). Companion to [ROADMAP.md](ROADMAP.md).

## What has already been seen (so it cannot count as confirmation)

- Synthetic dashboard benchmark, **seed 0**, 40 visits: tuned (change rate, spike weights) until the context-dependent cases appeared in training; live re-run used the same seed after fixes made from the 24-visit run.
- Replay with the local Qwen3-VL 2B on seed 0 (12 held-out visits), one run.

Confirmatory runs therefore use **fresh seeds 1–5** and any second domain, never seed 0.

## Questions and hypotheses

| # | Question | Hypothesis | Falsified if |
|---|---|---|---|
| H1 | Does `induce` recover a planted rule from pooled decisions? | Held-out agreement of the fitted rules ≥ 0.90 on each of seeds 1–5 (40 visits, chronological 70/30 split) | any seed < 0.80, or mean < 0.90 |
| H2 | Does cross-session context matter? | Rules with `changed_*` features beat the same fit without them on held-out agreement | no mean improvement over seeds 1–5 |
| H3 | Do non-actions matter? | Fitting with `none` outcomes beats fitting on acted-on visits only | no mean improvement |
| H4 | Does one elicitation round help? | After answering the unexplained decisions, held-out agreement rises and the unexplained set shrinks | no rise on a hidden-fact scenario |
| H5 | Does the exported judgment help an agent? | An LLM given the skill **with** the judgment section agrees with the person more than one given the procedure only | agreement is not higher over ≥ 3 repeats per seed |
| H6 | Does the capture path lose anything vs. drawn frames? | Live readouts and outcomes ≥ 0.95 correct | below 0.95 |
| H7 | Does the step classifier (O1–O6) match human judgment of what is tacit? | `O6` steps are the ones a reviewer calls "reason not visible", precision and recall ≥ 0.7 | below 0.7 on a labelled set |

H5 is expected to be the weak one (the first 2B run failed); report it either way.

## Metrics

- **Held-out agreement**: fraction of later decisions where the decider's outcome equals the person's. Also report *wrong action* (acted when the person did not, or a different action) and *missed action* separately, and the *asked-a-human* rate.
- **Rule recovery**: match of the fitted rule to the planted rule on all visits (`dashboard.rule_recovery`).
- **Documentation recall** (WONDERBREAD-style): expected steps found / expected steps.
- **Judgment F1**: for steps/runs a reviewer marks correct vs incorrect, F1 of the system's flag.
- **Flag precision and recall**: planted mistakes caught; correct steps flagged anyway.
- **Confirmed disagreements**: fraction of rule-vs-behaviour disagreements the person confirms as a real missing rule (real-person pilot only).
- Report mean, min and max over seeds; never a single run alone.

## Baselines

1. Most-common outcome of the training decisions.
2. The flat playbook without a judgment section (current pipeline).
3. Single-session fit (no pooling).

## Ablations

No dwell frames; no cross-session context; no elicitation round; skill without the judgment section.

## Setup

- Split: earliest 70% of decisions train, the rest test, chronological (no shuffling).
- Seeds: 1–5 for confirmatory synthetic runs; seed 0 stays a development seed.
- Models for H5: the local 2B already tried, plus at least one larger model; ≥ 3 repeats per seed with temperature as configured, config recorded.
- Second domain: a different UI and rule shape, built before looking at results on it; planted rule written down in the scenario's docstring.
- Fixed in advance: tree depth limit and minimum support are the current defaults in `induce.py`; changing them after seeing results counts as an amendment.

## Real-person pilot (separate from the above)

- One person, about 40 real decisions, recorded with the real recorder; their consent is obtained first and the data stays local.
- Procedure: `decisions` → `induce` → `elicit` → `replay`; the person then says in their own words when they act, and we compare it with the fitted rule.
- Reported as a case study (n = 1). It supports no claim about experts in general.
- Success statement from the roadmap: the person recognizes the induced rule as partly right, corrects it, and the corrected rule predicts held-out decisions better than the first fit.

## Reporting rules

- Report negative results (as with the first replay).
- State what was tuned and on which seed.
- Simulated experts and scripted "people" are labelled as such everywhere.
- Update README, NOTES.md and ROADMAP.md with each result.

## Amendments

### Amendment 1 (2026-11-07, before any confirmatory run)

**Code frozen as tag `freeze-1`.** Everything below was developed and tuned on seeds 0 and 100-109 only; seeds 1-5 have not been used for anything. Code changes after the tag are listed under "Deviations" at the end of this section.

What changed since the protocol was first written, and why:
- **Second domain exists** (`playbook/triage.py`, rule fixed in its docstring before results). Its base rates were adjusted on seeds 100-102 so every branch of the rule is learnable from 40 visits (the first version, with 4 escalations in 40 visits, was not). On-screen *words* are now features (`decisions.py`), and OCR spelling variants of a label are merged (`unify_names`).
- **Two induction arms.** `induce.fit` is greedy by default; `lookahead=True` picks a split by how well its children fit after one more split and is used only if it adds at least 5% training accuracy. Both are reported for H1, H2 and H3. Reason: on development seeds the greedy tree reached 0.64 held-out agreement on triage at 40 visits (lookahead 0.83) and 1.0 on the dashboard (lookahead also 1.0); with 10% label noise the dashboard fell from 0.82 to 0.76 under lookahead.
- **Prediction recorded before running:** H1 (>= 0.90 on every seed, 40 visits) will hold for the dashboard and **fail for triage** under greedy induction, and may fail under lookahead. We therefore also run **80 visits** for H1 on both domains. A failure on triage is a result, not a reason to retune.
- **Baseline 3 (single-session fit) is not computable**: each session holds one decision, so there is nothing to fit; reported as n/a. The without-context ablation stands in for "no pooling of state across sessions".
- **H3 is descriptive.** Without the non-action decisions the training set has a single outcome and the fitted rule can only ever say "act", so held-out agreement is poor by construction. We report it, but it does not test whether non-actions carry information beyond their obvious presence.
- **H5 prompts**: variant A is `replay.model_decider` as it stands; variant B (`strict=True`) adds one sentence telling the model to apply the exported rules literally, to reason no further, and to ask a human when none applies. No other prompt variants.

Exploratory studies (labelled exploratory in every report; run after the confirmatory runs; 5 seeds, both domains; held-out agreement unless stated, greedy and lookahead):
- **E1 learning curve**: n in {10, 20, 30, 40, 60, 80, 120}.
- **E2 label noise**: the person acts against their rule with p in {0, 0.05, 0.1, 0.2}, n = 60; also the share of `disagreements` that are the noisy visits.
- **E3 OCR misreads**: a digit of a readout is wrong with p in {0, 0.02, 0.05, 0.1}, n = 60.
- **E4a distractors**: k in {0, 2, 4, 8} irrelevant readouts, n = 60. **E4b drift**: the rule changes at visit 40 of 80; compare a rule fitted on all visits with one fitted on the visits after the change, on the last 20 visits.
- **E5 imperfect expert**: n = 80 with the hidden warmup fact; the expert names the right fact with probability {1, 0.8, 0.6, 0}, and (separately) tags the wrong decisions with a wrong fact.
- **E6 classifier check** (`knowledge.classify_decision`): ground truth per decision is O5 if the planted outcome depends on an earlier visit (`Domain.depends_on_history`), else O4 if the planted outcome is "none", else O3. Report the confusion matrix, n = 40, seeds 1-5. The current classifier calls every decision O5 once the fitted rule uses any cross-session feature, so low O5 precision is expected.

H6 (real capture): triage seed 1 and dashboard seed 1, 40 visits each, on the real recorder with real mouse input. Scripted people.

Hardware/time limits: all runs are on one Windows laptop (15 GB RAM); H5 uses a 4B Qwen3-VL (Q4_K_M, publisher checksums in `llama_runtime.py`) in place of the 2B used before, text only.

#### Deviations (code or scripts changed after tag `freeze-1`)
- `scripts/live_dashboard_test.py`, `scripts/live_triage_test.py`: added a foreground workaround (synthetic Alt key + SetForegroundWindow) and UTF-8 output. The first H6 attempt aborted immediately because our window was behind the terminal; the click guard stopped it, nothing was clicked elsewhere. Capture and analysis code unchanged.
- `induce.path_features` and the use of it in `python -m playbook induce` and in the pilot report, so a decision is called cross-session (O5) only if its own path through the rule uses a cross-session feature. Made after E6 showed the frozen classifier calls almost everything O5. E6 reports both versions; H1-H4 and E1-E5 are unaffected (no change to fitting).
- New scripts only: `run_confirmatory.py`, `run_exploratory.py`, `run_h5.py`, `summarize_h5.py`.
- **Bug in H5 prompt variant B, found from the results.** The "strict" sentence was never added to the prompt (my edit of `replay.model_decider` silently did not apply), so the first 30 strict runs equalled variant A exactly. Noticed because the two arms had identical numbers in all 30 runs. Fixed, covered by `test_strict_prompt_variant_changes_the_system_message`, and the strict arm re-run in full; the invalid rows are kept in `docs/results/h5/results_strict_noop.jsonl`. Variant A and the other arms were not re-run. The summary script's verdict rule was also changed from "any difference" to "more than two points" after it called a 0.772 vs 0.767 tie a win.
