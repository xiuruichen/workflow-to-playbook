# Smoke test: a hidden rule, a real window, one long recording

**Date:** 2026-11-08 · **Run:** `docs/results/smoke_test/` · **Status:** one run, not pre-registered, not independent (the author of the rule was also the judge).

## What it tests

Every earlier check of the decision pipeline used either a scripted "person" or decisions generated directly from a formula. This test removes both. A real full-screen window shows a case; the real recorder captures the screen and the mouse; a person (here an AI) reads the case and decides by a rule the pipeline knows nothing about; the decision is carried out as a **real mouse click**. Afterwards the whole pipeline runs on the single recording and tries to recover the rule.

It is meant as an end-to-end smoke and stress test: does the capture survive a long, continuous, unscripted session with decoys on screen, and does the rule fit find what the person actually did?

## Setup

**The hidden rule** was written to a file before any case was seen (`docs/results/smoke_test/sealed_rule.txt`). The person watches experiment runs and decides *Kill* or *Keep*:

1. Overfitting: kill if the epoch is at least 5 and validation loss is about 25% or more above training loss (a **ratio**, never shown on screen).
2. Wasted GPU: kill if GPU utilisation is under about 30, **except runs owned by Carol** (a categorical exception).
3. If the run is the same as at the previous check, keep it (a **cross-session** exception).
4. Everything else: keep. The grad norm and the clock on screen are noise.

**The harness** (`scripts/live_hidden_rule_test.py`) shows one case per screen, with eight labelled lines (run ID, epoch, train loss, val loss, GPU util, grad norm, owner, clock) and two buttons. The person writes `A` or `L` into a file; the harness moves the real mouse and clicks Kill or Keep. 50 cases, one recording, one continuous session.

**The judging** was done by reading each case on screen and applying the rule by feel, with no formula run. In a three-case trial of the harness beforehand, a screenshot of the live window was viewed to confirm that the screen shows what the harness reports.

## What happened

| Stage | Result |
|---|---|
| Recording | 408 s, 50 clicks, 3 MB video |
| Reading it (OCR, decision log) | 29 s |
| Decisions found | **50 of 50** choices (with `--dwell 3 --navigation "Keep run"`) |
| Readouts read exactly | 50/50 (numbers, including the decoys) |
| Owner word read | 50/50 |
| Outcome (kill vs keep) | 50/50 |

The person killed 14 of the 50 runs.

| Rule fit | Fit on all 50 | Predicts the last 15 (fitted on the first 35) | What it found |
|---|---|---|---|
| Default tree | 92% | 80% | a mixture of `val_loss`, `delta_val_loss`, `gpu_util`; not the ratio |
| With `--ratios` | **96%** | **80%** | `train_loss/val_loss <= 0.80` and `changed_run_id` |
| Always "keep" (baseline) | 72% | 67% | nothing |

With ratios on, the fitted rule was:

```
train_loss/val_loss <= 0.80 and changed_run_id <= 0.5 -> keep   (3/3)
train_loss/val_loss <= 0.80 and changed_run_id >  0.5 -> kill   (12/12)
train_loss/val_loss >  0.80                           -> keep   (33/35)
```

## Analysis

**What worked.**
- **Capture is solid.** A continuous 7-minute session with real clicks and decoy numbers produced one decision per choice, with every number, the owner word and the outcome read correctly. Both the dwell setting and the navigation setting (which the earlier continuous-recording experiment showed to be necessary) did their job.
- **The ratio rule was recovered, and its threshold matched.** `train_loss/val_loss <= 0.80` is the same as validation loss at least 25% above training loss. Nothing on screen shows a ratio; the tool found it by trying quotients of the readouts.
- **The cross-session exception was recovered.** `changed_run_id` is the "same run as last time" rule. The fit also read it correctly in the other direction (3 of 3 repeats kept).
- **The decoys were ignored.** The grad norm and the clock appear in no rule.
- **The report pointed at the right gaps.** Against the person's own statement it listed `epoch` and `gpu_util` as "mentioned, but the fit does not use it", which is where the fit fell short.

**What did not work.**
- **The GPU rule and the Carol exception were missed.** Only 2 of the 14 kills came from the GPU rule: most low-GPU cases were Carol's, a repeat of a run already judged, or just above the line (29 to 31). Two examples cannot support a rule with an exception; this is a sample-size limit, not a bug.
- **The ratio only appeared with `--ratios`.** The default tree split on raw `val_loss` and its change, which is a poor stand-in. A real user would not know to switch ratios on.
- **The held-out score is soft.** 80% on 15 cases against 67% for the baseline is one more correct case per eight.

**What it says about the project.**
1. The full path (real recording, OCR, decision log, rule fit, report) works end to end on an unscripted session. That was the main thing to establish before involving a person.
2. The tool recovers the *dominant* factors of a person's rule and loses the *rare* ones. This matches the earlier benchmarks (a compound rule needs about 100 observations) and now holds with an interactive judge.
3. Which features the tool is allowed to try matters as much as how it fits them. The one factor that needed a quotient was invisible until quotients were offered.

**Limits of the test.** The person who wrote the rule also applied it, so the choices are cleaner and more consistent than a real person's would be (no drift, no forgotten criteria; the judge was not tired or distracted). One run, 50 cases, a held-out set of 15. The cases were drawn by a script from a fixed seed, so repeated runs would vary mainly in how often the rare factors occur.

## Follow-ups

- Switch ratios on by default for the report, or show the ratio fit next to the default when the person's own words mention a quotient ("share", "rate", "percent").
- Make the harness draw more cases that exercise rare factors (it is a stress test, so it can oversample them) and re-run.
- Run the same protocol with a human as the person: [pilot-guide.md](pilot-guide.md).

## Reproduce

```bash
python scripts/live_hidden_rule_test.py OUT_DIR 50 5     # opens a window; write A or L into OUT_DIR/decision.txt for each case in OUT_DIR/current.json
python scripts/analyze_hidden_rule_test.py OUT_DIR       # capture check, rule fits, report
```

The harness takes over the mouse for the length of the session. Press Esc in its window to abort.
