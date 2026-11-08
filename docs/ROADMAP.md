# Roadmap: implementing ideas from the literature

Status: **Phase A is partly built** (marked ✅ below); everything else is planned. Citation keys refer to [`references.bib`](references.bib). Notes on each paper are from abstracts; read the full text before relying on a detail (marked **check**).

## Goal

Move from "one recording → one playbook" to capturing **tacit knowledge**: decisions an expert makes but has never stated. The hard cases are (1) rules visible only across many sessions, (2) decisions that are *non-actions* (looked, did nothing), and (3) reasons that depend on context from days earlier. Target use case: an ML engineer deciding over two weeks which training runs to kill, restart or leave alone.

Constraint: everything must run on a light-load laptop, so deterministic code comes first and the small local model is used only where nothing else works.

## What we take from each paper

| # | Source | Idea we implement | New / changed code | Phase |
|---|---|---|---|---|
| 1 ✅ | Iyamu 2026 `iyamu2026activityframes` | Model-free compilation of raw capture into typed episodes with pointers back to the evidence | `playbook/frames.py`: frames `{app, window, t0, t1, input volume, dwell, on-screen values, evidence ids}` from `events.jsonl`, keyframes and OCR | A |
| 2 | Wornow 2024 `wornow2024wonderbread` | Evaluate documentation (step recall) separately from judgment (is this step or run correct?) | `evaluate.py`: add step recall and correct/incorrect F1 per scenario | A |
| 3 | Brennig 2025 `brennig2025revealing`, Zuin 2025 `zuin2025tacit` | Ask targeted questions to draw out tacit knowledge; write answers back into the event record | `playbook/elicit.py`: questions generated from the cases where a fitted rule and the expert disagree; answers stored with provenance | B |
| 4 ✅ | Ng and Russell 2000 `ng2000irl` | Recover the rule behind observed behaviour (inverse-RL framing), here as an interpretable classifier over screen state, including the "no action" outcome | `playbook/induce.py`: shallow decision tree / rule list over frame features | B |
| 5 ✅ | Polanyi 1966, Nonaka and Takeuchi 1995 | Tacit vs explicit framing; externalization step | `playbook/knowledge.py`: observability classes O1–O6 and a 0–2 tacit rubric (below); elicited answers marked as externalized | A, B |
| 6 | Wang 2025 `wang2025awm` | Keep induced workflows in a persistent store and retrieve the relevant ones later | `playbook/memory.py`: cross-session store keyed by task; context facts (e.g. "batch size raised Tuesday") attach to later decisions | C |
| 7 | Jiang 2026 `jiang2026taskmodels` | Separate interleaved tasks; model a goal hierarchy plus control flow, not a flat list | `playbook/taskmodel.py` plus `Task`/`Branch` in `models.py`; rendered by `generator.py`. Symbolic first. **check** how much of the paper's method needs an LLM | C |
| 8 | Huang 2026 `huang2026work2skill` | Skills carry workflow rules, step dependencies and completion checks | `skill.py`: add `dependencies` and `completion_checks` to `SKILL.md` / `skill.json` | C |
| 9 | Hayati 2026 `hayati2026kolab`, Meng 2026 `meng2026clawmark` | Long-horizon, multi-day evaluation design; possible external data | evaluation protocol only. **check** licences and access first | C |

Cited as related work only (they train models or run agents, out of scope): VideoAgentTrek, Watch and Learn, VPT, ShowUI-Aloha. cotomi Act and Tacit Fragments are unread; read them before assigning any idea to them.

## Built so far

- `playbook/frames.py`: active and dwell frames from a session, with evidence pointers. Dwell frames are the trace of non-actions.
- `playbook/decisions.py`: the decision log (`decisions.jsonl`): labelled numbers read by local OCR at each pause, the outcome that followed (or `none`), and cross-session context (`changed_<name>`, `delta_<name>`).
- `playbook/induce.py`: a depth-limited decision tree over those features, leave-one-out disagreements, chronological held-out accuracy.
- `playbook/knowledge.py`: O1–O6 classes and a 0–4 tacit score for steps and decisions (rule-based heuristics). Steps are classified on measured evidence only: `O6` needs confidence below the review threshold or a recorded "model hesitated" note, because small local models write an `uncertainty_reason` on every step, so its presence says nothing (found in a local run where nearly every step came out `O6`). `annotate_playbook` writes `observability` and `tacit_score` onto each step; the Markdown report (class table, per-step line), the HTML viewer and the exported skill show them. Checked by unit tests only; the classes themselves are still heuristics, not validated against what a person would call tacit.
- `playbook/elicit.py` and `python -m playbook elicit`: one question per decision the rule can't explain, comparing it with the most similar decisions; the answer (verbatim, with an optional named fact and the other decisions it held for) is stored, the fact becomes a 0/1 feature and the rule is refitted. Check so far, on 60 synthetic decisions with a hidden "warmup" fact: 7 unexplained decisions, all of them warmup cases; one tagged answer raised the rule from 88% to 100% and cleared all 7. This used a simulated expert who tags perfectly, so it shows the mechanism, not how real people answer.
- Skill export with judgment (`python -m playbook export --judgment [sessions]`): `SKILL.md` and `skill.json` gain a "Judgment calls" section with the fitted rules (support per rule, thin ones marked), the person's own reasons, the value ranges seen, the unexplained cases, and an "ask a human first" boundary. Conditions the person named that aren't on screen are marked "ask whether it applies". Checked by unit tests on synthetic decisions; no agent has run such a skill yet.
- `playbook/replay.py` and `python -m playbook replay [sessions] [--model]`: fit the judgment on the earliest 70% of decisions and replay the rest through deciders: the majority outcome, a mechanical reader of the exported rules, and (with `--model`) a language model given the skill with and without the judgment section. Reports agreement with what the person did, how often it asked a human, and wrong vs missed actions. On the 40-visit dashboard benchmark (12 held-out visits): majority 58%, rules 100%. First real-model run (local Qwen3-VL 2B, text only, 57 s for the 12 held-out visits, one run, no repeats): the skill with the procedure only agreed on 5/12 (7 missed actions, because it nearly always answered "none"); the skill with the judgment section agreed on 1/12 and asked a human on 6, missing 5 actions. So **with this model, adding the judgment section did not help**; it made it more hesitant and still unable to apply the thresholds. A first attempt failed for a fixable reason, which this run already includes the fix for: the rules used `changed_batch_size` but neither the prompt nor the skill said what it meant or supplied it, so the skill now defines `changed_x` and the replay supplies it. The rules arm (100%) only shows the export is complete enough to act on. Not yet tried: a larger model, repeats, other prompt wording. Fact values for held-out decisions are supplied as if a human had been asked.
- **Live test** (`scripts/live_dashboard_test.py [visits] [seed]`): a real full-screen window, recorded by the real recorder (screen capture, OS input hooks, UI Automation), driven with real mouse clicks; 24 recordings, ~10 minutes, seed 0, one run. The scripted "person" follows the planted rule, so this tests capture and the pipeline on real screens, not a human's behaviour. Results: 24/24 readouts and 24/24 outcomes read correctly, one decision per recording. It found four things the drawn-frame benchmark could not: (1) the outcome label said "Button" (the unnamed control) rather than "Stop run", and once fixed the click position still had to be scaled from screen pixels to the smaller keyframes; (2) a tree split on `loss` that did not improve training accuracy (loss drifts with time) made the exported rules ask a human on every held-out decision, so splits must now improve training accuracy; (3) 24 visits are too few: the training half held one "spiking right after a batch change" case, so the exception was not learned (replay: rules 7/8, majority 4/8, one wrong action on the exception); (4) my first run stalled because the test script froze its own window while stopping the recorder (a harness issue, not a recorder bug). **40-visit live run** (same seed and visits as the synthetic benchmark, after those fixes, one run, ~17 minutes): 40/40 readouts and 40/40 outcomes correct; the rule fitted on the earliest 28 was the planted rule exactly (`spikes <= 1.5` leave alone; `spikes > 1.5` and batch size not changed: Stop run, 16/16; `spikes > 1.5` and batch size changed: leave alone, 3/3); on the 12 later visits the rules agreed on 12/12 and the most-common-outcome baseline on 7/12. This matches the synthetic benchmark, so with enough examples the real-capture path loses nothing. Caveats: the fixes were made after the 24-visit run, same seed, so this is a re-run rather than an independent test; the "person" is a script; the benchmark was designed so the exception appears often enough. Not done: a real human; the model arms live.
- `playbook/dashboard.py`: the planted-rule benchmark (`python -m playbook.dashboard`) and `tests/test_decisions.py`.
- CLI: `python -m playbook decisions [session]` and `python -m playbook induce [sessions...]`.

First result (synthetic, 40 simulated visits, seed 0, real recorder and local OCR, one run): the capture matched the planted rule on 40/40 visits, and the tree fitted on the earliest 28 recovered the planted rule exactly and scored 12/12 on the rest. Without the cross-session `changed_` feature it scored 11/12; the majority-outcome baseline scored 7/12. This shows the pipeline works on clean, text-labelled screens. It is not evidence about real experts, and the 12-visit test set is too small for the ablation gap to mean much. The benchmark was tuned (change rate, spike weights) until the context-dependent cases appeared in training, so report it as a pipeline check, not a result.

Known limits: readouts must be on-screen text (no chart reading); dwell is a proxy for attention; the outcome label comes from the UI element or text near the click; the knowledge classes are heuristics.

## Taxonomy used by `knowledge.py` (our proposal, to be checked against the advisor's version)

Observability class, assigned per extracted item:
- **O1** single-step observable (click Save)
- **O2** multi-step observable (copy, switch window, paste)
- **O3** decision visible, rule hidden (kill / restart / leave a run)
- **O4** non-action decision (only dwell time)
- **O5** cross-session context (the reason is in an earlier session)
- **O6** unobservable (off-screen; needs narration or an interview)

Tacit rubric, 0–2 each: articulability, observability class, context dependence, horizon (step / session / multi-session), verifiability against held-out decisions. The class picks the method: record (O1–O2), pool and induce (O3–O5), ask (O6 and every disagreement).

## Phases

**Phase A: foundations (weeks 1–3)**
1. `frames.py`, dwell events and a per-session `decisions.jsonl` (`{t, screen values, action or "none"}`).
2. `dashboard` scenario in `scenarios.py` with a planted rule (two grad-norm spikes within N steps means kill, unless batch size just changed), plus a second domain so the result isn't one trick.
3. `docs/evaluation-protocol.md`, written *before* running: hypotheses, metrics, baselines, ablations, seeds, success criteria.
4. WONDERBREAD-style metrics in `evaluate.py`.
5. `knowledge.py` classifier (rules first), shown in the playbook and in the skill export as "ask the expert" gates.

**Phase B: the core research contribution (weeks 4–8)**
6. `induce.py`: fit a rule on pooled decisions; report accuracy on held-out decisions, with and without "no action" labels and cross-session context.
7. `elicit.py`: surface rule-vs-behaviour disagreements with the two screens side by side; store the expert's answer as a stated rule with provenance; refit.
8. Optional think-aloud audio, transcribed locally and aligned to decisions (the cheapest way into O6).

**Phase C: scale and reuse (months 2–4)**
9. `memory.py` cross-session store with context facts.
10. `taskmodel.py` goal hierarchy and branches.
11. Skill completion checks and dependencies; replay an exported skill with a computer-use agent and compare end state.
12. Real expert sessions (consent and ethics handled with the research partner; not decided here) and long-horizon evaluation.

## Evaluation, summarised

- **Metrics:** step recall; correct/incorrect judgment F1; flag precision and recall; rule-recovery accuracy on held-out decisions; fraction of disagreements the expert confirms as a real missing rule.
- **Baselines:** the current flat-playbook pipeline; single-session (no pooling).
- **Ablations:** no dwell events; no cross-session context; no elicitation round.
- **Success statement:** the expert recognizes the induced rule as partly right and corrects it, and the corrected rule predicts held-out decisions better than the first fit.

## Risks

- Synthetic scenarios show the plumbing works, not real-world accuracy. Real data comes before any strong claim.
- Dwell time is a noisy proxy for attention (the person may have stepped away).
- A cross-session decision log is more sensitive than one recording; keep the egress guard and archive encryption, and add redaction.
- Small local models judge poorly; keep rule fitting symbolic.

## Open items for the research partner

- Confirm or correct the O1–O6 classes and the rubric.
- Name the second domain for the synthetic benchmark.
- Decide the consent / ethics route for recording real experts.
- Decide whether the first paper centers on the benchmark, the elicitation loop, or both.
