# Evaluation protocol

Status (2026-11-08): **the original protocol was written before any run; seven dated amendments follow it, each written before the runs it governs.** The criteria must not be changed after seeing results (add a dated amendment instead). Where each result comes from: [results/README.md](results/README.md); what is still open: [open-questions.md](open-questions.md). The amendments are at the end of this file, with a list of deviations. Companion to [ROADMAP.md](ROADMAP.md).

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
- Update the README, `docs/results.md` and `docs/ROADMAP.md` with each result.

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

### Amendment 2 (2026-11-08, before any run on seeds 6-10)

Motivation: the confirmatory runs showed the default greedy tree failing H1 on the triage domain. On development seeds 100-119 (20 seeds, never used for a claim) a search over `min_leaf` and the lookahead margin showed lookahead with `min_leaf = 3` (variant C) at or above the default (variant A: greedy, `min_leaf = 2`) in every cell tried, e.g. triage 40 visits 0.80 vs 0.65, 80 visits 0.92 vs 0.79, dashboard unchanged. Constants other than `min_leaf` stay as they are (the margin and penalty grid was flat, 0.86-0.89, so they are not tuned further).

**Test (fresh seeds 6-10; code unchanged since `freeze-1`, apart from the deviations listed above):** held-out agreement of A and C on both domains at 40 and 80 visits and at 60 visits with 10% label noise (6 cells, mean over seeds). **C is adopted as the default only if** its mean is at least A's in every cell and it is better than A by at least 0.05 in the mean over cells; otherwise A stays and the result is reported as a negative one. Ties on the dashboard (1.00 vs 1.00) count as "at least".

### Amendment 3 (2026-11-08, before any run of the service domain on seeds 6-10)

New domain `playbook/service.py` (rule in its docstring, fixed before results): an on-call engineer; the rule turns on a *rate*, errors divided by requests, which the screen shows only as two counts, plus a latency threshold and a version-changed exception. Purpose: a tree that splits on one readout at a time cannot express a quotient, which is how people often reason. Development seeds 100-119 (not used for any claim) were used to set the request volumes (the first version let the raw error count stand in for the rate, which would have hidden the problem) and to build the option under test.

Option R: `decisions.add_ratios` adds one feature `a/b` for every pair of readouts that are always present and positive (penalised like the other derived features in `induce.py`). Everything else is the default tree (variant A of amendment 2).

**Predictions, before running:** A (no ratios) fails H1 on the service domain at 40 and 80 visits. R improves on A but does **not** reach 0.90 mean at 80 visits (development seeds: A 0.59 / 0.66, R 0.85 / 0.88 at 40 / 80 visits).
**Test (seeds 6-10; cells: service at 40 and 80 visits and 60 visits with 10% label noise; dashboard and triage at 40 and 80 visits as a cost check):**
- R is **adopted as an option to switch on** (it is never silently on) if on service it is at least A in every cell with a mean gain of at least 0.10, **and** on dashboard and triage its mean over the four cost cells is no more than 0.03 below A's.
- Otherwise ratios stay out and the result is reported as negative.

### Amendment 4 (2026-11-08, before any run on seeds 6-10 of the guard)

E5 showed that a wrongly tagged answer can lower held-out agreement (triage 0.68 to 0.64 in the worst case). `elicit.vet` is the guard written in response: answers are grouped by the condition they name, and a group is kept only if the refitted rule gets more training decisions right or leaves fewer unexplained under leave-one-out; otherwise the person's words stay on record but the condition does not become a feature. Development seeds 100-114 (80 visits, hidden warmup fact) showed the guard roughly neutral with a perfect expert and slightly helpful with wrong tags; no threshold was tuned.

**Test (seeds 6-10, both domains, 80 visits, hidden warmup, greedy tree; held-out agreement after one elicitation round, with and without the guard):** cells (a) perfect expert, (b) expert right 60% of the time and otherwise tagging the wrong decisions, (c) expert always tagging wrong decisions.
**The guard is adopted into the interview (`pilot elicit`) if** the mean over both domains in (a) is no more than 0.01 below the unguarded value **and** the mean over (b) and (c) is at least 0.01 above it. Otherwise it stays an unused option and the result is reported as negative.

Also in this amendment (code changes from a review of the branch, not experiments): the pilot report fits with the default tree, matching `pilot elicit`; the pilot page ignores modified keys and key repeat; repeated cases keep the item's settings and the batch size cycles instead of growing; judgment lists the readouts behind a ratio rule and the model prompt shows the quotient.

### Amendment 5 (2026-11-08, before the run): H5 on the service domain with ratio features

Question: when the exported rules contain a quotient (`errors/requests`) and the prompt shows the model that quotient, does the judgment section help a small model on a rate rule? Same setup as H5 (Qwen3-VL 4B text only, seeds 1-5, 40 visits, 3 repeats, temperature 0.3, prompt variants A and B as before, arms skill / skill+judgment / skill+judgment strict plus the mechanical rules and the majority baseline), service domain only, ratio features on. Exploratory: no pass/fail bar. The seeds are 1-5 because the domain is new to H5; the H1-H4 runs never touched it.

### Amendment 6 (2026-11-08, before the run): E7, one continuous recording

All capture checks so far record one visit per session, so every decision is the only pause in its recording. Real work is one long recording of many checks, where a person decides faster than the 8-second dwell threshold and moves on with a "Next" click that would be read as an action. E7 (exploratory): one recording of 15 dashboard checks with looks of 2-12 s (uniform), seeds 1-3; for dwell thresholds 8, 5, 3 and 2 s and with "Next run" counted as an action or ignored (`build_decisions(navigation=...)`), report how many decisions are found, for how many visits the readouts were read, and for how many the outcome is right. No bar; prediction: at the default 8 s only the looks of 8 s or more are found (about 40%), the others are missed; without the navigation setting every pause outcome becomes "Next run" and non-actions are lost.

### Amendment 7 (2026-11-08, before any code or run of the LLM-driven interview)

**What is tested.** An interview in which a local model (Qwen3-VL 4B, text only) writes the question about each choice the fitted rule cannot explain, turns the person's free-text answer into a named condition (a feature for the tree), and decides when to stop, adapted from Brennig (2025; targeted queries, captured knowledge incorporated into the event log) and Zuin et al. (2025; iterative questioning with self-critique). Only abstracts of both papers were read, so this is an adaptation, not a replication. Plan: `playbook/interview.py`; question wording lives in `playbook/interview_prompts.py` as named strategies so that it can be changed without touching the plumbing; the v0 strategies are plain placeholders.

**Scenario.** Dashboard and triage domains, 80 visits, the hidden off-screen "warmup" fact (visits with `i % 9` in 3, 4 are made during warmup and the person waits), fitted and questioned on the earliest 70%, tested on the rest, as in H4. Development seeds 100-109 (prompts may be tuned there only); test seeds 6-10, after the code is tagged `freeze-5`.

**Scripted free-text expert** (a different expert from H4's: it answers in words, not with a named fact and tags). For a question about a warmup decision it answers, uniformly at random, one of six clear phrasings: "It was still warming up, so I gave it time." / "I'd just restarted that run, so I didn't want to judge it yet." / "Early days after a restart, I wait a bit." / "The run was only just back up after the restart, so I left it." / "Still in warmup; I don't act then." / "That was right after a restart, too soon to tell."; with probability 0.25 it answers instead one of four vague phrasings ("No idea, it just felt fine." / "Hard to say." / "I don't remember." / "Gut feeling."). For a question about a decision that was *not* made during warmup it answers one of two irrelevant phrasings ("Probably just habit." / "I was busy with something else."). To a follow-up listing other cases by number it answers with the numbers that were truly made during warmup ("Cases 2, 5") or "None of them."; the numbers are read by code, not by the model.

**Definitions.** An extracted condition *matches* the hidden fact if its lower-cased text contains "warm" or "restart". An answer is *clear* if it is one of the six clear phrasings, *vague or irrelevant* otherwise. The *structured-expert gain* is the held-out agreement gain of today's H4 procedure with a perfect expert (`study.elicitation`, accuracy 1.0, guard off) on the same visits. The *interview gain* is the gain after one interview (at most 8 questions, one follow-up each) with this expert.

**Hypotheses (bars fixed now).**
- **H8, extraction:** pooled over all answers, seeds and domains, the extracted condition matches for at least 80% of clear answers, and no condition is extracted for at least 80% of vague and irrelevant answers.
- **H9, end to end:** the interview gain is at least 70% of the structured-expert gain, mean over both domains and seeds 6-10.
- **H10 (exploratory):** the Spearman correlation between the model's 0-1 self-critique rating of an answer and the measured change in the leave-one-out unexplained count after that answer is at least 0.3.
- **Leakage:** none of the questions the model writes contains "warm" or "restart" (the interviewer is never told the hidden fact).
- **Question quality (exploratory, no bar):** with an LLM persona as the expert (the same 4B told the hidden rule and asked to answer briefly and in its own words), the LLM-written question against the fixed template of `elicit.Question.text()`: interview gain and number of questions until the first matching condition.

A result below a bar is reported as negative; prompts are not retuned on seeds 6-10.

**Disclosure and result (added after the run).** Tag `freeze-5`. Development used seeds 100-109 and a separate set of development phrasings (different from the test phrasings above); the interpretation prompt originally contained an example that leaked the hidden fact and was rewritten, its generic categories (a shrug, "I don't know", remarks about the person's own mood, schedule or distractions) overlap in meaning with the test's vague and irrelevant phrasings, and verbatim test strings were removed from it. The stop rule's patience (not fixed in this amendment) was tuned on development seeds from 2 to 4. Result on seeds 6-10: **H8 fails** (clear answers 3 of 6; vague and irrelevant 30 of 30), **H9 fails** (47% of the structured gain), leakage 0, H10 0.79; details in [results.md](results.md#the-llm-driven-interview) and [results/interview.md](results/interview.md).

## Round 2: fixing what failed (amendments 8-11)

Amendments 8-11 were written together on 2026-11-08, before any code of the fixes and before any of their runs. They respond to failures in earlier tests ([results.md](results.md)) and are judged on **fresh test seeds 11-15** (seeds 6-10 were used by amendments 2-4 and 7) and on the **fresh paraphrases** in [`results/interview/paraphrases.json`](results/interview/paraphrases.json), written before the extraction code was touched. Development (where options and prompts may be tuned) uses seeds 100-119 and the `dev` paraphrases. Each amendment states the baseline, run on the same seeds as the fix, and what is reported if a bar is missed. The designs of the fixes were made after seeing the failures, so the bars are blind but the designs are not.

### Amendment 8: the interview (extraction, which misfit to ask, stopping)

**Baseline:** the code at tag `freeze-5` (one-shot extraction, misfits in time order, patience 4), run on the same data as the fix.

**Changes under test.** (a) *Extraction* in three checked steps: a yes/no call "does this answer give a reason?"; if yes, a phrase that must be a near-substring of the answer; the majority of three samples (ties give none); plus a few domain-free examples. (b) *Order* of misfits: `time` (baseline), `surprise` (the purity of the leaf that predicted wrongly, times the number of other misfits with the same signature of what was done against what the rule expected, rare outcomes first), `cluster`. (c) *Group question*: one question about a cluster of similar misfits, all of them tagged unless the person removes some. (d) The stop rule: k non-answers and clusters exhausted or the budget spent.

**Bars (each reported whether met or not).**
- **H11, extraction:** on the 40 fresh test paraphrases (20 clear, 10 vague, 10 irrelevant), a condition is extracted (non-empty, a near-substring of the answer) for at least 16 of 20 clear answers, and none for at least 16 of 20 vague and irrelevant answers. The baseline pipeline is scored on the same 40.
- **H12, order (no model):** on seeds 11-15, both domains, 80 visits, hidden warmup fact, the share of the first four asked misfits that were made during warmup is at least 0.15 higher (absolute) with `surprise` or `cluster` than with `time`.
- **H13, end to end:** with the best ordering and extraction found on development seeds, the interview gain (as amendment 7: one interview on the earliest 70%, held-out agreement before and after) is at least 70% of the structured-expert gain, mean over both domains and seeds 11-15, with a scripted expert that answers in the fresh clear, vague and irrelevant test phrasings at the same rates as amendment 7 (clear for a warmup choice, vague with probability 0.25, irrelevant otherwise).
- If a bar is missed the baseline stays the default and the result is reported as negative.

### Amendment 9: induction (selection, rule list, stable misfits, windows, thin support)

**Baseline:** the default tree at tag `freeze-5` and, where noted, the same tree with `--ratios`, on the same seeds.

**Changes under test.** `induce.fit_auto` picks among plain and ratio features and among the greedy tree, the lookahead tree and a new rule list (sequential covering), keeping the simplest variant whose inner cross-validated accuracy beats the plain default by a margin fixed on development seeds; a misfit is *stable* only if it disagrees in at least 70% of 30 bootstrap fits; a window for drift is chosen by cross-validation on the latest decisions; the report lists thin-support patterns (fewer than 5 cases).

**Bars.**
- **H14, accuracy:** `fit_auto` on triage at 40 visits, seeds 11-15: mean held-out agreement at least 0.90 and worst seed at least 0.75. On the dashboard (40 and 80 visits) and on triage at 80 visits it is not below the baseline by more than 0.01 on average; on the service domain (40 and 80 visits) it is within 0.02 of the baseline with `--ratios`.
- **H15, discoverability (untouched real-ish data):** run once on `docs/results/smoke_test/session/decisions.jsonl` with no flags, the fitted rule uses `train_loss/val_loss`.
- **H16, stable misfits:** at 10% label noise on triage (80 visits, seeds 11-15), the precision of flagged misfits (the share that are the noisy visits) is at least 0.70 (baseline: one-shot leave-one-out; amendment 7's exploratory E2 measured 0.42-0.50).
- **H17, drift:** on the E4b protocol (the rule changes at visit 40 of 80, tested on the last 20), the window chosen by cross-validation reaches at least the better of the two fixed windows minus 0.02, both domains, seeds 11-15.
- **H18, thin support (smoke-test data):** the report's thin-support section lists a pattern involving `gpu_util`.

### Amendment 10: an executable judgment for the agent

**Baseline:** H5's arms (procedure only, with the judgment text, the rules read mechanically) at tag `freeze-5`, re-run on the same seeds.

**Change under test.** `python -m playbook judge` evaluates the exported rules on given readouts and returns the outcome, the rule that fired and an out-of-range or no-rule flag; in the new arm "skill + evaluator" the 4B model reads the screen text into readouts, calls the evaluator, and asks a human when it says to.

**Bar (H19).** On all three domains (dashboard, triage, service with ratio features), seeds 11-15, 40 visits, 3 repeats, temperature 0.3: agreement of the evaluator arm is within 0.05 of the mechanical reader, and at least 0.10 above procedure only. Wrong and missed actions and asks are reported.

### Amendment 11: capture of numbers with separators

**Baseline:** the parsing at tag `freeze-5` on screens drawn with thousands separators.

**Change under test.** The raw token is kept with each readout and separators are repaired per label at pool level; label variants are merged more generally.

**Bar (H20).** On triage screens drawn with the amount as `7,200` style, 40 visits (seed 11), through real OCR, 40 of 40 amounts are read exactly after the fix; the baseline count is reported. If the model cannot meet H8 the fallback (the fixed template and a typed condition) stays the default and the finding is the finding. Out of scope for the bars, and left open for the team member who is thinking through what to ask and how to judge answers: the final question wording, a rubric for answer quality, and what counts as success with a real expert.
