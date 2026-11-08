# Tacit knowledge: recovering *when* and *why*

A playbook says what to do. Much expertise is *when*: looking at a chart for twenty seconds and leaving a run alone leaves no click, so no step. This layer captures those decisions, including the decision to do nothing, fits a readable rule to them, and asks the person about the cases the rule cannot explain.

| Question | Tool | Output |
|---|---|---|
| What did they look at, and what did they do next (or not)? | `decisions` | a decision log per session |
| What rule fits their choices? | `induce` | a short decision tree, readable as sentences |
| What does the rule not explain? | `induce`, `elicit` | the choices it gets wrong, with questions |
| Why? | `elicit`, `pilot elicit` | the person's words and named conditions, which become features |
| Does the rule predict later choices? | `replay` | agreement on the held-out choices |
| Can an agent use it? | `export --judgment` | rules, reasons and an "ask a human first" boundary in the skill |

```
 frames ──► decisions ──► induce ──► elicit ──► export --judgment ──► replay
 (pauses)   (screen at each pause     (readable   (questions on        (rules + reasons   (do later choices
             + what happened next)     tree)       the misfits)        in the agent skill) follow the rules?)
```

**Status.** Checked on synthetic benchmarks with a scripted person, on an AI acting as the person (a [smoke test](smoke-test.md) with a real window and real clicks), and never with a human. Results: [results.md](results.md). Hypotheses, criteria and amendments: [evaluation-protocol.md](evaluation-protocol.md).

## The decision log

`python -m playbook decisions [session]` writes `decisions.jsonl` next to the session.

- A **decision point** is a *dwell*: a pause of at least 8 seconds between input events (`frames.py`). The screen at the end of the pause is the evidence.
- The **outcome** is the action that followed the pause, or `none` if the person did nothing (`decisions.py`). Non-actions are the trace of tacit judgment.
- What was on screen is read by local OCR as **labelled numbers** (`Spikes: 2`, `Amount: 5200`) and **labelled words** (`Vendor: Known`). A word becomes a 0/1 feature only if its label takes at least two words, each seen at least twice.
- **Cross-session context** is added when decisions from several sessions are pooled: for each readout, `changed_x` (it differs from the previous decision's value) and `delta_x`. A "this value changed since last time" fact shows on no single screen.
- **Ratios** of readouts (`errors/requests`) are added only with `--ratios`, never silently. They matter because people reason in rates, while screens show counts.

**One long recording of many checks.** The defaults suit one check per recording. For continuous work, name the controls that only move to the next item and shorten the dwell:

```bash
python -m playbook decisions [session] --dwell 3 --navigation "Next,Next run"
```

Without these, the 8-second default finds about 38% of fast decisions and a "Next" click is read as the person acting (experiment E7 in [results.md](results.md)). Nothing infers which controls only navigate.

## Fitting a rule

```bash
python -m playbook induce [sessions...] [--ratios] [--without context|none]
```

`induce.py` fits a depth-3 decision tree over the features, prints it as sentences, reports how many choices it fits and how well it predicts the later ones (fit on the earliest 70%), and lists the choices it cannot explain (leave-one-out). A tree is used because the person has to be able to read, dispute and correct it. `--without` drops the cross-session features or the non-actions, for ablations. `lookahead=True` (a Python option, not on the command line) chooses each split by how well its children fit after one more split; it recovers more of a compound rule from few observations and fits noise more, so it is opt-in.

```
spikes <= 1.5 -> keep                                         (13/13)
spikes >  1.5 and changed_batch_size <= 0.5 -> stop           (13/13)
spikes >  1.5 and changed_batch_size >  0.5 -> keep           (2/2)
```

## Asking about what the rule cannot explain

```bash
python -m playbook elicit [sessions...]
```

For each choice the rule gets wrong, `elicit.py` shows the person what the rule expected, what they did, what was on screen, and how it differs from the most similar choices where they did what the rule expected. They answer in their own words and may name a condition ("warming up") and tag which other choices it held for. A named condition becomes a 0/1 feature and the rule is refitted. Answers are stored verbatim with a timestamp.

## Observability classes

`knowledge.py` sorts every playbook step and decision by what a recording can show:

| Class | Meaning | Method |
|---|---|---|
| O1 | single-step: one action whose reason is visible | record |
| O2 | multi-step: meaning only across steps (read, switch window, paste) | record |
| O3 | hidden rule: a visible choice among alternatives, rule not stated | fit a rule |
| O4 | non-action: the choice was to do nothing | fit a rule |
| O5 | cross-session: the reason lies in an earlier session | fit a rule |
| O6 | unobservable: the reason is off-screen | ask the person |

Each also gets a 0–4 tacit score. A playbook step is `O6` only on measured evidence (calibrated confidence below the review threshold, or the model hesitating between targets), never because the model wrote a remark. A decision is `O5` only if its own path through the fitted rule uses a cross-session feature. These are heuristics, built on the framing of Polanyi and of Nonaka and Takeuchi ([related-work.md](related-work.md)); they have not been checked against human labels.

## Replay: do later choices follow the rules?

`python -m playbook replay [sessions...] [--model]` fits on the earliest 70% of decisions and replays the rest through deciders: the most common outcome, a mechanical reader of the exported rules, and (with `--model`) a language model given the skill with and without the judgment section. It reports agreement, how often the decider asked a human, and wrong versus missed actions.

## A pilot with a real person

`python -m playbook pilot make|report|elicit` ([pilot-guide.md](pilot-guide.md)):

- `make` writes an offline page where the person judges 60 cases of a theme they pick (a training run, an invoice, a support ticket) by their own rule, with an optional reason per case, and then states the rule in words;
- `report` gives the fitted rule, held-out accuracy, the choices it cannot explain, and the person's own statement set against the rule (which fitted features they did and did not mention, and which they mentioned that the fit ignored);
- `elicit` interviews them about the misfits and refits.

Tested with scripted and AI persons and under node; **not yet run with a human**. The success statement of the project: the person recognises the fitted rule as partly right and corrects it, and the corrected rule predicts later choices better than the first fit.

## Benchmarks and test harnesses

| Domain (`playbook/`) | Hidden rule the "person" follows | What it tests |
|---|---|---|
| Training dashboard (`dashboard.py`) | stop the run at 2+ gradient spikes, unless the batch size just changed | cross-session context; non-actions |
| Invoice triage (`triage.py`) | amount ≥ 5,000: escalate if 30+ days overdue and it is a new invoice; below: approve if the vendor is Known | three outcomes, a word on screen, a different cross-session exception |
| Service health (`service.py`) | page on-call if errors/requests ≥ 5%; roll back if ≥ 1% and latency ≥ 400 ms unless the version just changed | a rule about a rate the screen never shows |

- `python -m playbook.dashboard --domain dashboard|triage --visits 40 --seed N` runs one through the real recorder, OCR and fitting.
- `scripts/live_dashboard_test.py` and `scripts/live_triage_test.py` do it in a real window with real mouse input and a scripted person.
- `scripts/live_hidden_rule_test.py` is the interactive version: a person (or an AI) reads each case and answers by writing `A` or `L` into a file, and the harness performs the click. `scripts/analyze_hidden_rule_test.py` checks capture and fits the rule. See the [smoke test](smoke-test.md).
- `playbook/study.py` builds decision logs directly from visit sequences, in milliseconds, with knobs for label noise, OCR misreads, distractor readouts, rule drift and an off-screen fact. A test compares it with what real OCR reads from rendered screens.
- `scripts/run_*.py` are the experiment runners; [results/README.md](results/README.md) maps each result to its command.

## Limits

- Readouts must be text on screen (`Label: value`); charts and unlabelled numbers are not read.
- Local OCR can read `9,871` as `9.871` (not handled) and drop the space in a label (`Batchsize`; merged only when names differ by underscores).
- A pause is a rough proxy for attention.
- Rules are depth-3 trees: one condition per regime, and about 100 observations for a rule with several. Rare factors (two examples in fifty) are missed.
- Label noise hurts compound rules quickly, and a disagreement with the rule is weak evidence of a hidden reason when the rule is itself poorly learned.
- Every check so far used a scripted or AI person who follows a clean rule. No human has been tested.
