# Roadmap

## Goal

Recover **tacit knowledge** from observed computer work: not only what an expert did, but *when* they act, *when they deliberately don't*, and *why*, in a form they can read, dispute and correct, and that an agent can use. The hard cases are rules visible only across many sessions, decisions that are non-actions, and reasons that depend on context from days earlier. Target use case: an ML engineer deciding over two weeks which training runs to kill, restart or leave alone.

**Success statement:** the expert recognises the fitted rule as partly right and corrects it, and the corrected rule predicts their later decisions better than the first fit.

**Constraint:** everything runs on a light-load laptop, so deterministic code comes first and the small local model is used only where nothing else works.

## Where we are (2026-11-08)

| Workstream | State | Evidence |
|---|---|---|
| Capture and playbooks (what) | built | four scripted scenarios, local model ([results.md](results.md#playbooks-on-four-scripted-scenarios)) |
| Decision log, including non-actions | built | real-capture check 40/40 on two domains; 50/50 in the [smoke test](smoke-test.md) |
| Rule induction (when) | built; chooses automatically between plain, ratio and rule-list fits | a single-regime rule from 40 visits; rate rules found with no flag; compound rules still need about 100 visits (invoice domain 0.72 at 40) |
| Elicitation (why) | built, scripted experts only | one round helps a little (+0.03 to +0.12) with a perfect expert; the 4B-driven interview now reads 17 of 20 clear answers and recovers the full (small) gain on fresh seeds; which misfit to ask first is unsolved |
| Agent export with judgment | built; rules callable as a tool (`judge`) | the 4B model with the tool scores what a mechanical reader of the rules scores; the rules fitted from 28 visits are the ceiling |
| Observability classes | built, heuristic | checked only against planted ground truth |
| Real-person pilot | **kit ready, not run** | [pilot-guide.md](pilot-guide.md) |
| Evaluation | pre-registered, synthetic only | [evaluation-protocol.md](evaluation-protocol.md) with seven amendments |

Nothing has been tested with a real expert. Everything so far used a scripted person, or an AI that wrote the rule it applied.

## Next steps, in order

1. **Run the pilot with one real person** (about 45 minutes; [pilot-guide.md](pilot-guide.md)). Done when the four scoring questions in the guide are answered, including a no. This is the only step that can show the goal is met, and it decides what is worth building next.
2. **A second stage with a real recorded task** (`record`, then `decisions --dwell 3 --navigation <words>`, `induce`, `elicit`, `replay`). Needs readouts that are text on screen.
3. **A human-labelled set for H7**: which steps a reviewer calls "reason not visible", to check the observability classes against people rather than planted truth.
4. **Design the interview questions and the scoring of answers with the team member working on them** ([interview-guide.md](interview-guide.md)), now that extraction works (17 of 20 clear answers); the open problem is *which* misfit to ask about, where nothing tried beat time order.
5. **Triage-type rules at 40 visits** (0.72 held-out, with or without automatic selection): the remaining failure of the induction fixes. Untried: structure from the person's own stated rule, and asking about thresholds.
6. **Re-score the four scripted scenarios** with the step-recall and flag-F1 metrics (needs a model run).
7. **A hint about rare factors** that is not dominated by chance ratio conditions (the H18 failure).
8. Only then: think-aloud audio for the reasons that are off-screen; cross-session memory and task models.

## Not built, on purpose

- **Cross-session memory** (Wang 2025): pooling decisions already supplies the cross-session context the experiments needed.
- **Task models** (Jiang 2026): no evidence yet that interleaved tasks are the bottleneck.
- **Think-aloud audio:** the highest-value addition for the off-screen "why", but it needs a speech-to-text dependency and microphone capture; the pilot's typed reasons cover it at small scale.
- **Training or fine-tuning a vision model:** no labelled data; general models already read arbitrary UIs.
- **Chart reading:** readouts must be text on screen.

## What each paper contributes to the code

| Source | Idea | Where | State |
|---|---|---|---|
| Iyamu 2026 (`iyamu2026activityframes`) | Model-free compilation of raw capture into evidence-linked episodes | `frames.py` | built |
| Wornow 2024 (`wornow2024wonderbread`) | Evaluate documentation (step recall) separately from judgment | `evaluate.py` | built; not re-scored |
| Brennig 2025, Zuin 2025 | Ask targeted questions to draw out tacit knowledge; iterate with self-critique | `elicit.py`; `interview.py` (`--llm`) | built; scripted experts; pre-registered bars on extraction and end-to-end gain not met with a 4B model |
| Ng and Russell 2000 (`ng2000irl`) | Recover the rule behind behaviour, here as a readable classifier including the "no action" outcome | `induce.py` | built |
| Polanyi 1966, Nonaka and Takeuchi 1995 | Tacit versus explicit framing | `knowledge.py` | built; heuristic |
| Huang 2026 (`huang2026work2skill`) | Skills carry rules, dependencies and completion checks | `skill.py` | built; no agent replay yet |
| Wang 2025 (`wang2025awm`) | Persistent store of induced workflows | `memory.py` | not built |
| Jiang 2026 (`jiang2026taskmodels`) | Goal hierarchy and control flow | `taskmodel.py` | not built |
| Hayati 2026, Meng 2026 | Long-horizon, multi-day evaluation design | evaluation protocol | not started; needs real data |

VideoAgentTrek, Watch and Learn, VPT and ShowUI-Aloha are related work only (they train models or run agents). cotomi Act and Tacit Fragments could not be fetched and are not relied on. Details: [related-work.md](related-work.md).

## The observability rubric (a proposal)

The classes O1–O6 ([tacit-knowledge.md](tacit-knowledge.md#observability-classes)) are implemented as a 0–4 tacit score (a count of reasons, see `knowledge.py`). The proposal behind them scores five axes 0–2 each: articulability, observability class, context dependence, horizon (step, session, multi-session) and verifiability against held-out decisions. The class picks the method: record (O1–O2), pool and fit (O3–O5), ask (O6 and every disagreement). Neither the classes nor the rubric has been checked against human labels (H7).

## Risks

- Synthetic benchmarks show the plumbing works, not real-world accuracy.
- Real people are inconsistent and drift; the noise studies show compound rules degrade quickly, and a disagreement with a poorly learned rule is weak evidence of a hidden reason.
- A pause is a noisy proxy for attention.
- Capture assumes `Label: value` text and needs `--dwell` and `--navigation` for long recordings.
- A cross-session decision log is more sensitive than one recording; keep the egress guard and archive encryption, and add redaction.
- Small local models follow exported rules worse than a mechanical reader does.
- Seeds and criteria were fixed in advance, but some choices (the domains' base rates, which options to test) were made by the people who read the results; the protocol's amendments list them.

## Open questions

See [open-questions.md](open-questions.md): the consent and ethics route for anyone other than the researcher, the scope of a first paper, the human-labelled set for H7, and the theme and participant for the pilot.
