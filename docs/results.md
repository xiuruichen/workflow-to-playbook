# Results

Everything below was produced with a scripted person, an AI acting as the person, or synthetic recordings. **No real expert has been tested.** Hypotheses H1–H7, criteria and seeds were written before the runs ([evaluation-protocol.md](evaluation-protocol.md), with six dated amendments); every number links to a file in [`results/`](results/README.md), which also gives the command that reproduces it. Predictions that turned out wrong are said so.

## The decision work at a glance

| Question | Result |
|---|---|
| Is a planted rule recovered from 40 visits? (H1: held-out agreement ≥ 0.90) | Dashboard: yes, 1.00 on every seed. **Triage: no**, 0.87 mean (worst seed 0.67); 0.89–0.93 at 80 visits. A rule with several regimes needs about 100 visits |
| Does cross-session context help? (H2) | Yes, except one tie on triage at 40 visits |
| Do non-actions have to be logged? (H3) | Yes: without them the rule can only say "act". Descriptive only |
| Does one round of questions to the expert help? (H4) | Narrowly: +0.04 and +0.03 with a perfect scripted expert; 6 of 10 runs unchanged |
| Does the exported judgment help a small model act? (H5, Qwen3-VL 4B, text only) | Not on the dashboard (0.77 → 0.77; 0.80 with the strict prompt). Triage 0.44 → 0.56, mostly because the model asks a human more often. Rate-rule domain 0.55 → 0.68 (0.75 strict). Reading the same rules mechanically scores 1.00 / 0.82 / 0.65 |
| Does real capture read the screens correctly? (H6) | Yes: 40/40 readouts and outcomes on two domains, and 50/50 in the [smoke test](smoke-test.md) with an interactive judge |
| Does a rule about a rate need extra features? | Yes: one-readout trees 0.57–0.72; with `--ratios` 0.78–0.93 (adopted as an option) |
| What did **not** help | Lookahead tree as the default (+0.03, bar +0.05); a guard against wrong interview answers (no effect) |
| Where does it break? | Label noise hurts compound rules far more than simple ones; a recording of many fast checks finds 38% of decisions with the default 8 s dwell; rare factors (2 examples in 50) are missed |

### Hidden-rule smoke test (real window, real clicks, an AI as the person)

Full write-up: [smoke-test.md](smoke-test.md). 50 decisions from 50 clicks, every readout, word and outcome read correctly. With ratio features the fit found the planted loss-ratio threshold and the same-run exception (96% fit, 80% on the last 15 against 67% for the baseline) and missed a rare GPU rule and its exception.

### H1–H4: confirmatory runs (seeds 1–5, code at tag `freeze-1`; [`results/confirmatory.md`](results/confirmatory.md))

Held-out sets are small (12 decisions at 40 visits, 24 at 80), so one miss moves a seed by 8 or 4 points.

- **H1 holds on the dashboard and fails on triage.** Greedy induction: triage 0.87 mean (worst 0.67) at 40 visits and 0.89 (0.75) at 80; with lookahead 0.87 (0.67) and 0.93 (0.79). The prediction written beforehand, that triage would fail, was right, though the development seeds had been more pessimistic (0.64).
- **H2:** the dashboard 1.00 with context against 0.78 (40 visits) and 0.80 (80) without; triage 0.89 against 0.80 at 80 visits (lookahead 0.93 against 0.86); a tie for greedy triage at 40 visits.
- **H3 (descriptive):** without the non-action decisions agreement falls to 0.23–0.48.
- **H4:** mean held-out agreement rose from 0.81 to 0.85 (dashboard) and 0.68 to 0.71 (triage), but in 6 of 10 runs nothing changed, and on triage the unexplained count did not shrink. A perfect scripted expert is the best case.

### H5: does the judgment help an agent? (Qwen3-VL 4B Q4_K_M, text only, seeds 1–5, 40 visits, 12 held-out each, 3 repeats at temperature 0.3; [`results/h5/h5.md`](results/h5/h5.md))

Agreement with the person's later decisions:

| | procedure only | + judgment (A) | + judgment, strict (B) | rules read mechanically | most common outcome |
|---|---|---|---|---|---|
| dashboard | 0.77 | 0.77 | 0.80 | 1.00 | 0.40 |
| triage | 0.44 | 0.56 | 0.55 | 0.82 | 0.40 |
| service (rate rule, ratio features; [`h5_service.md`](results/h5/h5_service.md)) | 0.55 | 0.68 | 0.75 | 0.65 | — |

- On the dashboard the judgment section does not clearly help (inside the seed spread of 0.58–1.00). Procedure-only already scores 0.77 because it answers "do nothing" and the person mostly did. The strict prompt acted far more (32 wrong actions against 9) for a small gain.
- On triage it helps mostly because the model **asks a human** (45 asks in 180 answers) and acts wrongly less often (22–24 wrong actions against 100). It does not apply the thresholds: following the same rules mechanically gets 0.82.
- On the rate-rule domain it helps (+0.13, +0.20), and the model beat the mechanical reader because the reader declines out-of-range values.
- So with a 4B model the judgment section is **a safer boundary more than better decisions**. One model, one run per seed, a scripted person. The strict prompt variant had a bug in its first run (the sentence was never added), found because its numbers matched variant A exactly in all 30 runs; it was fixed and re-run ([protocol deviations](evaluation-protocol.md)).

### H6: real capture (seed 1, 40 visits each, real recorder and mouse, scripted person; [`results/h6/`](results/h6/))

Triage: 40/40 readouts (numbers and the vendor word) and 40/40 outcomes; the rule fitted on 28 scored 0.67 on the last 12, baseline 0.08. Dashboard: 40/40 and 40/40; rules 12/12, baseline 0.67. H6 (≥ 0.95 correct) holds for both.

### Later amendments (seeds 6–10, criteria fixed before each run)

- **Lookahead with `min_leaf` 3 as the default** ([`confirmatory2.md`](results/confirmatory2.md)): at least as good in all six cells (triage at 80 visits 0.97 against 0.88) but +0.03 on average against a +0.05 bar, so **not adopted**; still available.
- **A rate rule and ratio features** ([`confirmatory3.md`](results/confirmatory3.md)): 0.57 / 0.72 / 0.59 without, 0.78 / 0.93 / 0.81 with (+0.21, bar +0.10), no cost on the other domains, **adopted as a switch-on option**. A written prediction was wrong: ratios were predicted to stay under 0.90 at 80 visits and reached 0.93.
- **A guard against wrong interview answers** ([`confirmatory4.md`](results/confirmatory4.md)): no effect in any cell, **not adopted**. With a perfect scripted expert one round gave +0.12 on the dashboard and +0.03 on triage.

### Exploratory studies E1–E7 (nothing pre-set to pass; [`exploratory.md`](results/exploratory.md), [`e7_continuous.md`](results/e7_continuous.md))

- **E1 learning curve.** Dashboard 1.00 from 40 visits (0.77–0.93 at 20). Triage 0.50–0.63 at 20, 0.87 at 40, 0.86–0.93 at 80, 0.86 greedy / 0.97 lookahead at 120.
- **E2 label noise** (the person sometimes acts against their rule). Dashboard 0.97 / 0.93 / 0.77 at 5 / 10 / 20%, with the disagreements pointing at the noisy visits (precision 0.93 / 0.84 / 0.71). Triage degrades much faster (0.72 at 5%, 0.58 at 20%) and its disagreements are mostly *not* the noisy visits (precision 0.42–0.50): a disagreement is weak evidence of a hidden reason when the rule is itself poorly learned.
- **E3 OCR misreads.** No effect up to 5% of readouts on the dashboard; 0.81 at 10%.
- **E4 distractors and drift.** Up to 8 irrelevant readouts cost triage about 4 points and the dashboard nothing. After a rule change, fitting on all earlier visits beats fitting only on the visits after the change for triage (0.86 against 0.67; 20 visits are too few).
- **E5 imperfect expert.** Gains come only from right facts; a wrongly tagged answer can cost (triage 0.68 → 0.64 at worst).
- **E6 classifier check.** The original `classify_decision` marked every decision O5 once the rule used any cross-session feature (60% right on the dashboard, 40% on triage). Using the decision's own path through the rule gets 200/200 and 163/200.
- **E7 one continuous recording of 15 checks** (looks of 2–12 s). The 8 s default finds 7.0 of 15 decisions (readouts right for 5.7); 3 s finds 14.0 (12.0 right); with a "Next run" click counted as an action the outcome is right for only 2–6 visits, against all those found when it is declared a navigation control.

### Pilot dry run with an AI as the person ([`results/pilot_dry_run/`](results/pilot_dry_run/))

A three-part hidden rule written first; 60 cases judged by reading them. The default tree fit 92% and predicted 83% of the last 18 (baseline 78%): it recovered the batch-change exception, a long-gap rule the person never mentioned (reported as "you did not mention it"), and a spike threshold of 3 instead of 2; it missed the new-dataset patience, which only the lookahead tree found (and that variant lost the batch-change exception). A depth-4 tree fit all 60 and predicted no better.

### Early results, before the protocol (dashboard, seed 0, development)

Capture on drawn frames 40/40, with the fitted rule exact and 12/12 on the rest. A first live run (24 visits) found four problems that drawn frames could not: the outcome label was "Button" instead of "Stop run" and click positions needed scaling from screen pixels; a split on a drifting readout (`loss`) made every held-out decision ask a human, so splits must now improve training accuracy; 24 visits were too few to learn the exception; and the test script froze its own window. A second live run (40 visits, after the fixes) recovered the rule exactly. The first replay with the 2B model found the judgment section hurt (1/12 against 5/12): the rules used `changed_batch_size` but nothing said what it meant, which the skill now defines. A simulated expert with one tagged answer cleared all 7 unexplained decisions (88% → 100%).

## Playbooks on four scripted scenarios

Scenarios (`playbook.evaluate`, [playbooks.md](playbooks.md#evaluating-playbooks)) have one planted mistake each. The mistakes are caught by the deterministic checks, not the model.

**Local model on an 8 GB laptop** (7.6 GB RAM, Intel Core Ultra 5 135U, no GPU, `LOW_POWER=true`; Qwen3-VL 2B Instruct Q4_K_M on llama-server):

| scenario | steps | expected found | mistake | false flags | time | peak RAM |
|---|---|---|---|---|---|---|
| email (28 s recording) | 10 | 5/5 | caught | 0 | 14 min | 2.0 GB |
| files (6 segments) | 12 | 4/4 | n/a | 0 | 29 min | 2.0 GB |
| research | 8 | 3/4 | caught | 0 | 8 min | 3.1 GB |
| coding | 12 | 4/5 | caught | 0 | 21 min | 3.1 GB |

Email and files ran at 4 threads, research and coding at 6 with other apps closed. Peak RAM for the last two is the server's working set sampled every 15 s; the 2.0 GB figures were measured differently and are probably low, so plan on about 3 GB. Missed steps: "read 168,412" (research, also missed by a Gemini Flash-Lite run) and the Ctrl+S save (coding). The new step-recall and flag-F1 metrics have **not** been re-run on these scenarios.

**How the email scenario went from 38 to 14 minutes** (one run each):

| setup | expected found | false flags | time | peak RAM |
|---|---|---|---|---|
| Ollama, `qwen3-vl:2b-instruct` | 5/5 | 1 | 38 min | ~2.6 GB |
| llama-server, Bonsai 2 2B (ternary) | 4/5 | 12 (consolidation failed twice) | 24 min | 1.0 GB |
| llama-server, Bonsai 2 4B | stopped | — | ~10 min per segment | — |
| llama-server, Qwen3-VL 2B, full consolidation | 5/5 | 1 | 33 min | 1.9 GB |
| llama-server, Qwen3-VL 2B, lean consolidation (current) | 5/5 | 1 | 14 min | 2.0 GB |

- **Runtime.** Ollama scales every screenshot to ~1,040 tokens; llama-server's `--image-max-tokens 448` keeps an 896 px screenshot at native size and reuses the cached system prompt, so a segment went from ~4,800 to ~1,750 new prompt tokens.
- **Consolidation** was the other half of the wait: rewriting every step took the 2B model ~3,000 tokens (8 min). In low-power mode it now returns only an id, a title and keep/drop per step, without merging (allowed to merge, it collapsed 9 actions into 2) and without review notes (it wrote one for every step); the deterministic check still flags typed-versus-on-screen mismatches. About 1.5 min now.
- **Threads.** Encoding a screenshot is the slowest part of a request: 40–46 s at 4 threads, 24–26 s at 6, 20–26 s at 8 on a 14-thread CPU, so low-power mode uses half the threads, at most 6.
- **Bonsai 2** used half the RAM but lost a step and could not produce a valid consolidation; its 4B read prompts at ~5.6 tokens/s against ~23 for Qwen3-VL 2B. Neither is offered.
- **Earlier fixes on the Ollama path.** The plain `qwen3-vl:2b` tag is the *thinking* variant (~2,000 hidden tokens for a two-line answer), so all tiers use the `-instruct` tags and replies are capped. Ollama spends ~1,040 tokens on every image whatever its size, so low-power mode skips zoomed crops. The smallest tier's context is 8,192 tokens.
- **The 2B model lists steps well and judges them poorly:** it never wrote a review note for the planted email typo, so the deterministic check does that job. It had flagged the typo on the wrong step at first (the model times steps a keyframe late); notes now go on the step that says it entered the value.
- **Fixes from live runs (2026-11).** A consolidation prompt overflowed the 8,192-token window by 58 tokens (now retried text-only); OCR dropped spaces ("isnotrecognized"), hiding a terminal's rejection (the check now also tries text without spaces); a small model's free-text remarks appeared on nearly every step (on local models a remark becomes a flag only if it quotes two near-miss values code can check).

**Optional cloud run** (2026-10-24, `gemini-3.5-flash-lite`, stronger models out of quota): coding 5/5 with the mistake caught by the model; email 5/5, caught by the consistency check; files 4/4, none planted; research 3/4, caught by the model; no false alarms; 2–3 API calls each. The first run missed the email typo (the model never wrote a "read John's email" step) and over-flagged the corrected `python app.py`; both are fixed and tested.

**Token certainty** (2026-11-03, a partial run: coding and email; stopped for low memory before `research`): at a 0.30 cutoff two coding steps flag. One is a real catch (`line` over `code` on a step that said `pyhton` was typed into "the line of code" when it went to the terminal, though the rejected-input check had already flagged it); one is a false alarm (`terminal` over `command`, wording). Email's specific targets scored 0.84–1.0. One good flag and one false alarm from 20 synthetic steps: enough to set a starting cutoff, not to say how well hesitation predicts wrong steps. Reviewer labels now include `token_certainty` so real recordings can answer that.

**First real test** (Gemini, 3-minute live recording of looking up five cities' populations into Excel; 70 keyframes): the playbook reconstructed the workflow (11 steps, right values and timestamps) and noticed two genuine data-entry discrepancies but reported them only as open questions while the steps scored 0.95, which motivated the review-note flag. The consolidation pass needs the strongest model available; the lite model that ran after quota ran out merged poorly (32 steps against 11).

## Caveats

- The scenarios and benchmarks are synthetic: clean screens, readable fonts, clean rules.
- The people in the decision experiments are scripted or an AI who wrote the rule they apply.
- Held-out sets are small; the smoke test's was 15 cases.
- The pre-registration fixes seeds and criteria, but some choices (the domains' base rates, which options to test) were made by the people who read the results; the protocol's amendments list them.
