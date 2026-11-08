# Roadmap: implementing ideas from the literature

Status (2026-11-08): **Phases A and B are built and checked on synthetic benchmarks; Phase C is partly built; nothing has been tested with a real expert yet.** The table below is the state of every roadmap item; the sections after it hold the detail. Citation keys refer to [`references.bib`](references.bib). Notes on each paper are from abstracts; read the full text before relying on a detail (marked **check**).

## Goal

Move from "one recording → one playbook" to capturing **tacit knowledge**: decisions an expert makes but has never stated. The hard cases are (1) rules visible only across many sessions, (2) decisions that are *non-actions* (looked, did nothing), and (3) reasons that depend on context from days earlier. Target use case: an ML engineer deciding over two weeks which training runs to kill, restart or leave alone.

Constraint: everything must run on a light-load laptop, so deterministic code comes first and the small local model is used only where nothing else works.

## Status at a glance (2026-11-08)

| Item | State | Evidence / where |
|---|---|---|
| 1 Frames and dwell (`frames.py`) | built | used by every decision experiment |
| 2 Documentation vs judgment metrics (`evaluate.py`) | built, **not re-scored** | step recall, flag precision/recall/F1 implemented and unit-tested; the four scripted scenarios were not re-run (needs a model; no cloud calls were allowed) |
| 3 Elicitation (`elicit.py`) | built, simulated expert only | H4 narrow gain; interview also in `pilot elicit`; **no real person yet** |
| 4 Rule induction (`induce.py`) | built | H1 holds on the dashboard, fails on triage; options `lookahead`, `--ratios`, `--without` |
| 5 Observability classes (`knowledge.py`) | built, heuristics | cross-session class by the decision's own path; proxy check E6; **H7 (human labels) not run** |
| 6 Cross-session memory (`memory.py`) | **not built, on purpose** | pooling already supplies the cross-session context the experiments needed |
| 7 Task models (`taskmodel.py`) | not built | no evidence yet that it is the bottleneck |
| 8 Skill dependencies and completion checks (`skill.py`) | built | `depends_on`, `completion_checks`; no agent replay scores against them yet |
| 9 Long-horizon evaluation | not started | needs real multi-day data |
| Second and third domains | built | `triage.py`, `service.py` |
| Think-aloud audio (B8) | not built | needs a speech-to-text dependency; typed reasons in the pilot cover it at small scale |
| Real expert sessions (C12) | **pilot kit ready, not run** | `playbook/pilot.py`, [pilot-guide.md](pilot-guide.md) |

**What to do next, in order:** (1) run the pilot with one real person (about 45 minutes) and score it as the guide says; (2) if it works, a second stage with a real recorded task (needs `--dwell` and `--navigation`, see E7); (3) label a set of steps for H7; (4) re-score the scripted scenarios with the new metrics; (5) only then Phase C items 6, 7 and 9. Open decisions are in [open-questions.md](open-questions.md).

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
| 8 ✅ | Huang 2026 `huang2026work2skill` | Skills carry workflow rules, step dependencies and completion checks | `skill.py`: add `dependencies` and `completion_checks` to `SKILL.md` / `skill.json` | C |
| 9 | Hayati 2026 `hayati2026kolab`, Meng 2026 `meng2026clawmark` | Long-horizon, multi-day evaluation design; possible external data | evaluation protocol only. **check** licences and access first | C |

Cited as related work only (they train models or run agents, out of scope): VideoAgentTrek, Watch and Learn, VPT, ShowUI-Aloha. cotomi Act and Tacit Fragments are unread; read them before assigning any idea to them.

## Built so far

| Module | What it does |
|---|---|
| `frames.py` | Active and dwell frames from a session, with pointers to the evidence. Dwell frames are the trace of non-actions. |
| `decisions.py` | The decision log (`decisions.jsonl`): labelled numbers and words read by local OCR at each pause, the outcome that followed (or `none`), and cross-session context (`changed_x`, `delta_x`). `--dwell` and `--navigation` adapt it to one long recording of many checks. `add_ratios` adds quotients of readouts. |
| `induce.py` | A depth-3 decision tree over those features; leave-one-out disagreements; chronological held-out accuracy; ablations (`--without context\|none`); opt-in lookahead. |
| `elicit.py` | One question per decision the rule cannot explain, set against the most similar decisions; a named condition becomes a 0/1 feature and the rule is refitted. `vet` (a guard against wrong answers) exists but is not used. |
| `skill.py` | Agent skill export with a "Judgment calls" section (rules, the person's reasons, value ranges, an "ask a human first" boundary), `depends_on` and `completion_checks`. |
| `replay.py` | Fits the judgment on the earliest 70% of decisions and replays the rest through deciders: majority outcome, a mechanical reader of the rules, and a language model with and without the judgment section. |
| `knowledge.py` | O1-O6 class and a 0-4 tacit score for steps and decisions (heuristics). A step is `O6` only on measured evidence; a decision is `O5` only if its own path through the rule uses a cross-session feature. |
| `dashboard.py`, `triage.py`, `service.py` | The three planted-rule benchmarks (training run; invoice triage; service health with a rate rule), each with a screen renderer for the real recorder. |
| `study.py` | A fast, model-free harness for the protocol's experiments (noise, misreads, distractors, drift, an off-screen fact). A test compares it with real OCR on rendered screens. |
| `pilot.py` | Offline case page for a real person, a report on their log, and an interview. |
| `scripts/` | `live_dashboard_test.py`, `live_triage_test.py` (scripted person, real window and mouse); `live_hidden_rule_test.py` + `analyze_hidden_rule_test.py` (an interactive person judges cases on a real window; one long recording); `run_*.py` experiment runners. |

## Results

Summaries with caveats are in [NOTES.md](../NOTES.md#evaluation-results) and the README; every number links to a file in [`results/`](results/README.md). In brief (scripted person, synthetic domains):

- A single-regime rule is recovered from 40 visits; a rule with several regimes needs about 100.
- Cross-session context and logging non-actions are necessary; label noise hurts compound rules quickly.
- One round of questions to a perfect scripted expert helps a little; wrong answers cost little on these seeds.
- A 4B model given the exported rules follows them worse than a mechanical reader; it helps mainly by asking a human, and clearly helps only on the rate-rule domain.
- Real capture reads the benchmark screens correctly (40/40 on two domains); long recordings need `--dwell` and `--navigation`.
- Not helpful: lookahead as the default (+0.03, bar +0.05) and the interview guard (no effect).

Known limits: readouts must be on-screen text (no chart reading); dwell is a proxy for attention; the outcome label comes from the UI element or the text near the click; the knowledge classes are heuristics.

## Taxonomy used by `knowledge.py` (a proposal, not yet checked against human labels)

Observability class, assigned per extracted item:
- **O1** single-step observable (click Save)
- **O2** multi-step observable (copy, switch window, paste)
- **O3** decision visible, rule hidden (kill / restart / leave a run)
- **O4** non-action decision (only dwell time)
- **O5** cross-session context (the reason is in an earlier session)
- **O6** unobservable (off-screen; needs narration or an interview)

Implemented as a 0-4 score (a count of reasons, see `knowledge.py`), not as the five 0-2 axes below, which remain the proposal. Since 2026-11-08 a decision is O5 only if its own path through the fitted rule uses a cross-session feature. Tacit rubric, 0–2 each: articulability, observability class, context dependence, horizon (step / session / multi-session), verifiability against held-out decisions. The class picks the method: record (O1–O2), pool and induce (O3–O5), ask (O6 and every disagreement).

## Phases

**Phase A: foundations (weeks 1–3)**
1. ✅ `frames.py`, dwell events and a per-session `decisions.jsonl` (`{t, screen values, action or "none"}`).
2. ✅ `dashboard.py` with a planted rule (two grad-norm spikes means kill, unless batch size just changed), plus second and third domains (`triage.py`, `service.py`) so the result isn't one trick.
3. ✅ [`evaluation-protocol.md`](evaluation-protocol.md), written *before* running: hypotheses H1–H7, metrics, baselines, ablations, seeds (1–5 for confirmatory runs; seeds 0 and 100–109 are development seeds), success criteria. Amendment 1 (2026-11-07) freezes the code as tag `freeze-1`, adds the exploratory studies E1–E6 and records a prediction that H1 fails on the triage domain at 40 visits. Confirmatory runs are next.
4. ✅ (implemented, not re-scored) WONDERBREAD-style metrics in `evaluate.py`.
5. ✅ `knowledge.py` classifier (rules first), shown in the playbook and in the skill export as "ask the expert" gates.

**Phase B: the core research contribution (weeks 4–8)**
6. ✅ `induce.py`: fit a rule on pooled decisions; report accuracy on held-out decisions, with and without "no action" labels and cross-session context.
7. ✅ (simulated expert) `elicit.py`: surface rule-vs-behaviour disagreements with the two screens side by side; store the expert's answer as a stated rule with provenance; refit.
8. Optional think-aloud audio, transcribed locally and aligned to decisions (the cheapest way into O6).

**Phase C: scale and reuse (months 2–4)**
9. `memory.py` cross-session store with context facts.
10. `taskmodel.py` goal hierarchy and branches.
11. ✅ (checks and dependencies) / open (replay with an agent): skill completion checks and dependencies; replay an exported skill with a computer-use agent and compare end state.
12. Real expert sessions and long-horizon evaluation. The pilot kit is ready; it has not been run. The consent and ethics route for anyone other than the researcher is undecided.

## Evaluation, summarised

- **Metrics:** step recall; correct/incorrect judgment F1; flag precision and recall; rule-recovery accuracy on held-out decisions; fraction of disagreements the expert confirms as a real missing rule.
- **Baselines:** the current flat-playbook pipeline; the most common outcome. A single-session fit is not computable with one decision per session (protocol amendment 1).
- **Ablations:** no dwell events; no cross-session context; no elicitation round.
- **Success statement:** the expert recognizes the induced rule as partly right and corrects it, and the corrected rule predicts held-out decisions better than the first fit.

## Risks

- Synthetic scenarios show the plumbing works, not real-world accuracy. Real data comes before any strong claim.
- Dwell time is a noisy proxy for attention (the person may have stepped away).
- A cross-session decision log is more sensitive than one recording; keep the egress guard and archive encryption, and add redaction.
- Small local models judge poorly; keep rule fitting symbolic. (H5 with a 4B model: the exported rules are followed worse than a mechanical reader follows them.)
- The scripted "person" follows a clean rule; real people are inconsistent and drift. The noise studies (E2, E4) show compound rules degrade quickly.
- Capture assumes `Label: value` text, one check per recording by default, and a few OCR formats (E7, thousands separators, split labels); real recordings need `--dwell` and `--navigation`.
- Seeds and criteria were fixed in advance, but some choices (base rates of the domains, which options to test) were made by the people who read the results; protocol amendments 1-6 list them.

## Open questions

- Are the O1-O6 classes and the rubric right? (No human-labelled check exists; see H7 in the protocol.)
- Which domain or task for the real-person pilot?
- What is the consent and ethics route for recording anyone other than the researcher?
- Should the first paper centre on the benchmark, the elicitation loop, or both? The results lean towards a paper with negative and mixed findings unless the pilot works.

The full list, with defaults and known problems, is in [open-questions.md](open-questions.md).
