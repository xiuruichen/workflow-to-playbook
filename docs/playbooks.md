# Playbooks: recovering *what* was done

The first layer of the project turns one screen recording into a reviewable step-by-step procedure. It matters for the tacit-knowledge goal because of where it is unsure: the steps whose intent cannot be read from pixels are exactly where unstated knowledge hides, and the playbook flags them.

**Output of one analysis**
- every step linked to a **timestamp**; in `playbook.html`, clicking a step plays the video from there;
- before/after **screenshots** per step;
- a **confidence score (0–1)**; steps are **flagged for review** when confidence is below 0.70, *or* when the action is clear but something looks off (a typed value that differs from its source, an input the software rejected), always with the reason and the evidence;
- the **inputs** that would change next time, and **open questions** the system could not answer;
- optionally an **agent skill** (`SKILL.md` + `skill.json`), below.

An example generated on a laptop CPU by the local model is in [`examples/city-population-lookup/`](../examples/city-population-lookup/playbook.md): a scripted 23-second recording where the person types 186,412 where the source says 168,412, and the consistency check flags that step.

## The pipeline

```
 screen + mouse/keyboard + UI element names ──► keyframes (before/after each action) ──► local OCR (exact on-screen text)
                                                                                           │
                                         local vision model, pass 1: actions per segment ◄─┘
                                                                                           │
  playbook.md / .html ◄── generator ◄── calibrated confidence + consistency check ◄── pass 2: merge into a playbook
```

1. **Capture** (`recorder.py`). `mss` grabs the screen at 5 fps into an H.264 video; `pynput` logs input. Keystrokes are grouped into typed bursts, repeated keys collapse, clicks become single, double, right-click or drag, scrolls merge. On Windows every event records the **app and window title** it happened in, and switching windows is its own event. The recorder saves a keyframe **just before** each event and another **~0.8 s after**, plus keyframes when the screen changes on its own and has settled, plus a slow heartbeat. Video time equals wall-clock time, so event timestamps double as seek positions.
2. **Keyframes** (`keyframes.py`). Change detection at two scales: a 160 px thumbnail catches big changes, a 640 px image catches small meaningful ones (a typed value, a new terminal line) while ignoring blinking cursors and spinners.
3. **Analysis** (`analyzer.py`, prompts in `prompts.py`). An `openai` client pointed at the local server's endpoint on `127.0.0.1` (or Gemini, on explicit opt-in). Small local models read small text poorly, so more of the facts come from deterministic sources and the model mostly writes them up:
   - **UI Automation** (Windows, `uia.py`): the accessibility API says what is under the pointer at each click and which field was typed into, with its final value. Password-like fields are never recorded.
   - **Local OCR** (`ocr.py`, RapidOCR on ONNX Runtime): text near each click and text that newly appeared goes into the prompt and into the consistency check.
   - **Zoomed crops**: a full-resolution 448 px crop around each click accompanies the downscaled screenshot.
   - **Structured output**: the JSON schema is passed as a grammar constraint, so small models cannot return malformed JSON.
   - **Pass 1** sends windows of 3–8 keyframes (10 for Gemini) with numbered red rings drawn where each click happened, plus the event log, and asks for step candidates with `confidence`, `evidence` and `uncertainty_reason`. **Pass 2** consolidates: merges micro-actions, drops noise, works out the goal, prerequisites, inputs and open questions, and adds a `review_note` to any step that looks wrong though its action is clear.
4. **Confidence calibration.** The model's own score is adjusted by facts it cannot see:

   | Rule | Adjustment |
   |---|---|
   | No mouse/keyboard event backs up the step (or the video was imported) | −0.15 |
   | Model output needed a JSON repair retry | −0.10 |
   | Step inferred across a >20 s gap between screenshots | −0.10 |
   | Step merged from several candidates | ≤ weakest candidate + 0.10 |

   A step **needs review** when its calibrated confidence is below `CONFIDENCE_THRESHOLD` (0.70), meaning the system is unsure what happened (⚠️); or when it has a review note, meaning the system understood the action but something looks off (🔎).
5. **Generation** (`generator.py`): Markdown and a self-contained HTML viewer with a review summary, prerequisites, inputs, steps with timestamps and screenshots, and open questions. The report also carries a table of how much of the procedure the recording could and could not explain, by observability class ([tacit-knowledge.md](tacit-knowledge.md#observability-classes)).

## The deterministic consistency check

`consistency.py` makes no model call. It compares what was typed (from the keyboard log, which is exact) with values seen on screen anywhere in the recording, and flags near misses: swapped or changed digits (`315,613` vs `315,663`), almost-identical emails, names, paths and commands (`jon.doe@` vs `john.doe@`). It catches copy mistakes that the model misses when the source and the typed copy are far apart. A number typed right after reading a similar one is held to a looser standard (up to half its digits changed), since that is a misread rather than a different value. Only local OCR text or a step where the model read a value counts as proof of a correct copy.

It also flags **input the software rejected**: new on-screen text that reads like an error and quotes something just typed (`The term 'pyhton' is not recognized`, `gti: command not found`, `'jon.doe@' is not a valid email`) puts a review note on that entry, in any app. The pattern also matches when OCR drops the spaces.

## Hesitation as a signal

On local models a step is also flagged when the model **hesitated** (`token_certainty.py`). A small model reports about 0.9 for nearly everything, but while writing it weighs each token against the alternatives. If a token in a step's target or value was nearly tied with a rival that means something different, the step is flagged and the reason names both (`"line" over "code"`). It adds no model calls and only a score per step to the cache. It shows hesitation, not truth: a confident misread or a person's own typo will not show up, which is what the consistency check is for.

## Export for AI agents

`python -m playbook export` (or **Download agent skill** in the Review tab) turns a playbook into a skill an agent can follow: `SKILL.md` in the [Agent Skills](https://agentskills.io) format, plus a tool-neutral `skill.json`. No model call.

- **Inputs become placeholders** (`{{city_name}}`). When the model listed none, what the user typed is used.
- **Data flows between steps.** A value typed after being read on screen is exported as "the value read in step 3", not as a constant, because next time the page will show something else. This also stops a recorded typo from being replayed.
- **Dependencies and completion checks.** Each step lists the step it depends on (`depends_on`); `skill.json` carries `completion_checks` (a value typed from an earlier read equals what is read *this* time; an end-state check from the last step's expected result, else the goal), listed under "Done when". Nothing is invented. No replay scores an agent against them yet.
- **Uncertainty becomes a gate.** Every flagged, unconfirmed step says **Ask a human first**, with the viewer's reasons. Steps a reviewer marked wrong are left out.
- **With `--judgment`**, the skill also says *when* to act: the fitted decision rules, the person's own reasons, the value ranges seen, and an "ask a human first" boundary ([tacit-knowledge.md](tacit-knowledge.md)).
- **Privacy.** No screenshots, video or event log are included. With `--judgment` the skill carries summaries of the person's decisions (numbers that were on screen, session ids, fitted rules, their words if they answered questions). Read it before sharing.

Review the playbook first: the skill is only as good as its steps.

## Evaluating playbooks

`python -m playbook.evaluate` builds four scripted recordings with fictional data (`scenarios.py`) that run through the real recorder logic, so they have genuine input events, window titles and keyframes, and scores each against known answers:

| Scenario | What happens | Planted mistake |
|---|---|---|
| `coding` | run a script in VS Code's terminal, read a NameError, fix the variable, save, re-run | the first command is typed `pyhton app.py` |
| `email` | read a request in Outlook, compose a reply with an attachment, send | recipient typed `jon.doe@…` but the sender is `john.doe@…` |
| `files` | create a folder, rename a file (F2), drag it into the folder, turn on a setting | none (measures false alarms) |
| `research` | search the web, open a result, Alt+Tab to Excel, enter the number | `186,412` typed, but the page says `168,412` |

It prints, per scenario, the step recall, whether the mistake was flagged, the flag precision/recall/F1 and the false alarms. Results are in [results.md](results.md#playbooks-on-four-scripted-scenarios). Responses are cached, so re-runs are free; `--no-api` only builds the recordings.

## Limits

CPU inference is slow (minutes per request). UI Automation and window metadata are Windows-only. One monitor. Tiny changes (a single digit in a cell) may not get a keyframe of their own; the event log still records exactly what was typed. The consistency check is conservative (5+ digit numbers or 5+ character strings; at most 2 changed digits against any value seen). Keyboard-only actions with no visible effect (Ctrl+C) are inferred from the event log and usually get flagged, by design. Typed text is recorded verbatim unless `MASK_TYPED_TEXT=true`. The four scenarios are synthetic: they test generality, not real-world accuracy. More in [design-notes.md](design-notes.md).
