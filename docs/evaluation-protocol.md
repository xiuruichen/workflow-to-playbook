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

(none yet)
