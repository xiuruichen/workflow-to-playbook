# Tacit knowledge from screen recordings

[![tests](https://github.com/xiuruichen/workflow-to-playbook/actions/workflows/tests.yml/badge.svg)](https://github.com/xiuruichen/workflow-to-playbook/actions/workflows/tests.yml)

**Record an expert at work and recover not only *what* they did, but *when* they act, when they deliberately don't, and *why*:** step-by-step playbooks, readable decision rules, and an interview about what the rules cannot explain. Runs on your own machine; nothing is uploaded.

> **Status: a research prototype.** Every result so far comes from scripted people, synthetic recordings, and an AI acting as the person (including one end-to-end test on a real window with real clicks). It has **not yet been tried with a human expert**; that pilot is built and ready ([docs/pilot-guide.md](docs/pilot-guide.md)). Repository `workflow-to-playbook`, Python package `playbook`: the playbook generator was the first layer, and the project has grown beyond it.

## The problem

Much expertise is tacit. People know how to do a task on a computer, and when to act or leave things alone, but rarely write it down, and when they do they skip the "obvious" parts. Watching the work is the most faithful record, but a recording shows only what was done. The interesting knowledge is often in what was *not* done: looking at a chart for twenty seconds and leaving a run alone leaves no click.

## Three layers

| Question | What the project produces | Where |
|---|---|---|
| **What** did they do? | a reviewable step-by-step playbook, flagged where intent can't be read from pixels, and an agent skill | [docs/playbooks.md](docs/playbooks.md) |
| **When** do they act, and when not? | a log of decisions (what was on screen at each pause, and what happened next, including nothing) and a short readable rule fitted to them | [docs/tacit-knowledge.md](docs/tacit-knowledge.md) |
| **Why**, where the rule fails? | an interview about the choices the rule can't explain; the person's words become features and the rule is refitted | [docs/tacit-knowledge.md](docs/tacit-knowledge.md) |

The uncertainty is the point. A low-confidence step marks where an observer can't recover intent; a choice the fitted rule can't explain marks where the person knew something the screen did not show. Both point at the tacit part, and the exported agent skill turns them into explicit "ask a human first" gates.

## An example

An AI played an experiment-tracking engineer with a hidden rule (written to a file before any case was shown): *kill a run when validation loss is 25% above training loss, or the GPU is idle, except Carol's runs; leave it if it is the same run as the last check.* A real window showed 50 cases, the real recorder captured the screen and the mouse, and the cases were judged by reading them and clicking Kill or Keep. From the one recording the tool read every screen correctly, and fitted:

```
train_loss/val_loss <= 0.80 and changed_run_id <= 0.5 -> keep   (3/3)
train_loss/val_loss <= 0.80 and changed_run_id >  0.5 -> kill   (12/12)
train_loss/val_loss >  0.80                           -> keep   (33/35)
```

That is the planted 25% rule, found from a quotient that appears nowhere on screen, plus the same-run exception. It missed the rarely-triggered GPU rule (two examples in fifty). Full write-up with analysis: [docs/smoke-test.md](docs/smoke-test.md).

## How it works

```
 screen + mouse/keyboard + UI element names ──► keyframes (before/after each action) ──► local OCR
                                                        │                                    │
                 ┌──────────────────────────────────────┴──────────┐                         │
                 ▼                                                   ▼                         ▼
   local vision model ──► playbook (what)               pauses + what was on screen ──► decision log
   + consistency checks   + agent skill                          (when, including "did nothing")
                                                                       │
                                                  readable rule ──► interview on the misfits ──► refit
                                                        (when)                (why)
```

Capture is the screen, input events, app and window titles, and (on Windows) the names of the UI elements touched. A local vision model (Qwen3-VL, sized to your machine) writes up the steps; deterministic checks (typed-versus-seen values, rejected input) do the parts a small model gets wrong. A short decision tree over the numbers and words read from screen at each pause is fitted to the person's choices.

## What we found

| Question | Result (scripted or AI person) |
|---|---|
| Is a rule recovered from 40 visits? | A single-condition rule, exactly. A rule with several regimes needs about 100 visits (0.87 held-out agreement at 40) |
| Is the real capture path reliable? | Yes: every readout, word and outcome correct on 40/40 (two domains) and 50/50 (smoke test) |
| Do rules about rates need help? | Yes: one-readout trees score 0.57–0.72, with ratio features 0.78–0.93; the default now tries ratios, a lookahead tree and a rule list by cross-validation and found the planted ratio on the smoke-test recording without any flag |
| Does one round of questions help? | A little (+0.03 to +0.12 with a perfect expert). A local 4B model can run the interview: with a gated extraction it read 17 of 20 clear answers and recovered the full (small) structured gain on fresh seeds |
| Does handing an agent the rules help? | As text, a 4B model mostly asks a human more often and helps clearly on one of three domains. As an executable tool (`python -m playbook judge`) it scores exactly what a mechanical reader of the rules scores, so the limit is now the rules fitted from 28 visits |
| Where does it break? | Compound rules at 40 visits (0.72 on the invoice domain, with or without the automatic choice), label noise, rare factors, a rule that drifts, fast continuous decisions (needs `--dwell` and `--navigation`) |

Hypotheses and criteria were fixed before the runs, and results that were negative or contradicted a written prediction are reported as such: [docs/results.md](docs/results.md), [docs/evaluation-protocol.md](docs/evaluation-protocol.md).

## Quick start

Python 3.10+; Windows, macOS or Linux. Details: [docs/getting-started.md](docs/getting-started.md).

```bash
python -m venv .venv && .venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playbook setup-local                         # picks and downloads a local vision model (playbooks only)
```

```bash
# playbook: record a task, analyse it, open the result
python -m playbook run                                 # Ctrl+Shift+Q stops; or: streamlit run app.py

# decisions: log the pauses, fit a rule, ask about the misfits
python -m playbook decisions [--dwell 3 --navigation "Next"]
python -m playbook induce [--ratios]
python -m playbook elicit

# a pilot with a real person (offline page, report, interview)
python -m playbook pilot make --theme run --cases 60
```

No GPU is needed; on a laptop CPU a playbook takes minutes per request, once (responses are cached). The decision tools need only the recording and the local OCR.

## Documentation

| Read this | For |
|---|---|
| [docs/tacit-knowledge.md](docs/tacit-knowledge.md) | the decision log, rule fitting, the interview, observability classes, the pilot, the benchmarks |
| [docs/smoke-test.md](docs/smoke-test.md) | the end-to-end hidden-rule test: setup, results, analysis |
| [docs/results.md](docs/results.md) | all results, with caveats |
| [docs/playbooks.md](docs/playbooks.md) | how a recording becomes a playbook; confidence, checks, the agent skill |
| [docs/getting-started.md](docs/getting-started.md) | install, local models, low-power mode, the UI and CLI |
| [docs/configuration.md](docs/configuration.md), [docs/privacy-and-archives.md](docs/privacy-and-archives.md) | settings; privacy, encryption, archives |
| [docs/pilot-guide.md](docs/pilot-guide.md), [docs/interview-guide.md](docs/interview-guide.md) | running the pilot with one real person; designing the interview questions and scoring answers |
| [docs/ROADMAP.md](docs/ROADMAP.md), [docs/open-questions.md](docs/open-questions.md) | what is done, what is next, what needs a decision |
| [docs/evaluation-protocol.md](docs/evaluation-protocol.md), [docs/results/](docs/results/README.md) | hypotheses, criteria, amendments; the data and the command for every number |
| [docs/design-notes.md](docs/design-notes.md), [docs/related-work.md](docs/related-work.md) | why it is built this way; literature and references |

## Repository layout

```
playbook/    the package: recorder, analyzer, decisions, induce, elicit, knowledge, pilot, benchmarks, archives
app.py       the Streamlit UI
scripts/     live tests (real window, real mouse), experiment runners
tests/       about 230 tests; no model or key needed (a few need the local OCR; one needs node)
docs/        the documentation above; docs/results/ holds every result file
examples/    a generated playbook to open in a browser
```

```bash
pytest       # the vision client is mocked; archives use throwaway keys
```

The tests also run on GitHub Actions (Ubuntu and Windows) for every push and pull request. Git tags `freeze-1` to `freeze-4` mark the code at each pre-registered point.

## Limits to know about

Readouts must be text on screen (`Label: value`); charts are not read. A pause is a rough proxy for attention. Rules are depth-3 trees: they find the dominant conditions and miss rare ones. Window metadata and UI element names are Windows-only. Everything in the decision layer has been checked with scripted or AI people who follow clean rules; real people are inconsistent. The list with fixes in progress is in [docs/open-questions.md](docs/open-questions.md).

## Related work

Wornow et al. (WONDERBREAD) for scoring documentation separately from judgment; Huang et al. (Work2Skill) for skills that carry dependencies and completion checks; Iyamu (Activity Frames) for model-free, evidence-linked episodes; Polanyi and Nonaka and Takeuchi for the tacit-knowledge framing; Zuin et al. and Brennig for interviews that draw tacit knowledge out; Ng and Russell for recovering the rule behind behaviour. Full list, with how far each source was checked: [docs/related-work.md](docs/related-work.md) and [docs/references.bib](docs/references.bib). Inspired by [Screenpipe](https://screenpipe.com/) and [GodHands](https://godhands.ai/).

## License

[MIT](LICENSE)
