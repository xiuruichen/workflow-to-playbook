# Design notes

Why the system is built the way it is, what the first tests taught, and what was considered and left out. Results are in [results.md](results.md); the plan is in [ROADMAP.md](ROADMAP.md).

## Why this exists

Much expertise is **tacit**: people know how to do something on a computer, and when to do it or leave it alone, but rarely write it down; when they do, they skip the "obvious" details. Watching the work is the most faithful record. The project turns that observation into explicit, reviewable, reusable knowledge, as a building block for digital twins of knowledge work:

1. **Capture** behaviour passively (what Screenpipe does, but focused on one task).
2. **Interpret** it: into steps (what GodHands does for SOPs) and into the decisions between them, including doing nothing.
3. **Keep a human in the loop** wherever the machine is unsure or cannot explain a choice, so the result becomes trustworthy ground truth.

The uncertainty is the research hook. A low-confidence step marks where an observer cannot recover intent from pixels; a choice the fitted rule cannot explain marks where the person knew something the screen did not show. Both point at the tacit part.

## Architecture

```
recorder.py ──► <local app data>/sessions/<id>/{recording.mp4, events.jsonl, keyframes/, manifest.json}
     │            (events carry app + window title and, via uia.py, the UI element clicked or typed into)
keyframes.py (two-scale change detection, video import, click annotation, crops)
     │
     ├── Playbooks (what)
     │   backend.py + hardware.py + security.py: which model (local by default, sized to RAM/VRAM), egress guard
     │   analyzer.py   pass 1: windows of keyframes + events + OCR text + click crops ──► vision model ──► StepCandidates
     │                 pass 2: all candidates + first/last frame ──► vision model ──► Playbook (merged steps)
     │   consistency.py: typed values (keyboard log) vs values seen on screen ──► review notes
     │   token_certainty.py: token probabilities ──► per-step hesitation score ──► low-confidence flag
     │   generator.py ──► playbook.md / .html / .json        skill.py ──► skill/SKILL.md + skill.json
     │
     └── Decisions (when and why)
         frames.py ──► decisions.py (pauses + OCR readouts + words + next action; pooled across sessions)
              ──► induce.py (readable tree) ──► elicit.py (questions on the misfits) ──► skill.py judgment ──► replay.py (deciders)
         knowledge.py: observability class and tacit score
         pilot.py: offline case page, report and interview for a real person

archive.py + tilecodec.py: idle session folder ◄──► encrypted <id>.pbx
app.py (Streamlit) and playbook/__main__.py (CLI) orchestrate the above; local_setup.py installs the model.
Evaluation: scenarios.py + evaluate.py (playbooks); dashboard.py, triage.py, service.py + study.py (decisions);
            scripts/ (live tests, experiment runners); docs/results/ (outputs); labels.py (reviewer labels for calibration)
```

`models.py` holds the pydantic contracts between stages. Every stage reads and writes files, so any stage can be re-run alone (`analyze`, `render`).

## Design decisions: playbooks

- **Event-anchored keyframes beat fixed-interval sampling.** A timer either misses fast actions or wastes calls on idle screens. Before/after pairs around real input events give the model the frames that explain each action, and the click location (a numbered ring) removes most ambiguity about *what* was clicked.
- **Two passes.** Windows of 3–8 keyframes keep per-frame detail high; the consolidation pass sees the whole workflow, so it can name the goal and merge micro-actions. Windows share a boundary keyframe, so every transition is analysed once.
- **Calibrated confidence, not raw model confidence.** Self-reported confidence is poorly calibrated: the local 2B model wrote 0.9 for every step in the evaluation scenarios. Rules based on facts the model cannot see (no input event, repaired JSON, long gaps) make the flag more meaningful, and the model must give *evidence* and an *uncertainty reason*, which turns a flag into a concrete question for the reviewer.
- **Two kinds of review flag.** Low confidence (⚠️) means the system does not know what happened. A review note (🔎) means it knows what happened but something looks wrong: a typed value that differs from its source, a likely typo, an undone action. The second kind came out of the first real test and is arguably the more valuable: it surfaces the human's mistakes and unexplained decisions, which is where tacit knowledge, or its absence, shows.
- **Never silently lose information.** A segment that fails to analyse becomes a confidence-0 step. Candidates that pass 2 forgets are kept as raw steps. Dropped candidates are logged in `analysis.json`.
- **Small models need facts, not pixels.** The recorder takes the clicked element's name from the accessibility API (requested at press time, so it sees the UI before the click changes it); local OCR adds exact text near each click and in changed regions; a full-resolution crop accompanies each click; the JSON schema is enforced as a grammar. The consistency check takes OCR text too, so catching a mistyped value no longer depends on the model reading it.
- **OCR only where it matters.** Full-frame OCR cost ~4.5 s per frame on the development laptop; turning off upscaling and the rotation classifier gave ~1.8 s, and reading only crops around clicks and changes (cached) cuts it further.
- **Deterministic checks where possible.** The keyboard log is ground truth for what was typed, so comparing it with values seen on screen is string matching with no model. Only a value recorded *before* the typing proves a correct copy, and the user's own earlier input (a mistyped command still visible in the terminal) is never treated as a source. Error messages in every kind of app quote the input they refuse, so new on-screen error text that cites something just typed flags that entry with no knowledge of the app.
- **Read how the model chose, not what it says about itself.** Token probabilities are a by-product of generating the reply (asking for them cost about 0.2% per token). Raw they are ~130 KB per reply, so only each step's weakest token is cached. The score is the smallest gap between a chosen token and its best meaningful rival, in `target` and `value` only (in descriptions, hesitation is nearly all wording). The flag is applied after pass 2, so changing the cutoff changes no prompt.
- **An agent export that carries the uncertainty with it.** The point of a digital twin is that someone else can do the task. Inputs become placeholders; a value typed after being read becomes a reference to that earlier step (a recorded typo must not be replayed); every flagged, unconfirmed step becomes an "ask a human first" gate. The flags that mark where tacit knowledge hides become the places where an agent must defer to the expert.
- **Domain-neutral by construction.** Nothing in capture or analysis assumes an app. Context comes from the OS, and the prompts list what makes a step repeatable in each kind of work (paths and commands for coding, recipients and field values for email, before/after values for settings). Checked with scripted scenarios, not assumed.
- **Video time = wall time.** The recorder duplicates frames when capture lags, so `#t=<event time>` always lands on the right moment.

## Design decisions: decisions and rules

- **Dwell is the trace of a non-action.** Leaving a run alone leaves no click; the pause before the next action is all there is. This is also the weakest link: a pause is a rough proxy for attention, and fast decisions fall below the 8 s default (hence `--dwell`, and `--navigation` for controls that only move on).
- **A depth-3 tree, not a learned model.** The person has to be able to read, dispute and correct the rule, and a few dozen decisions cannot support more. It is a simple stand-in for inverse reinforcement learning (Ng and Russell, 2000). The cost is known: one condition per regime, rare factors missed.
- **Cross-session context is derived, not shown.** `changed_x` and `delta_x` come from neighbouring decisions because "this value changed since last time" is on no single screen. A split on such a derived feature must beat a plain on-screen number by a margin, since there are many of them and they can fit noise. Splits must also improve *training accuracy*: a readout that drifts with time (loss) once made every held-out decision ask a human.
- **Opt-in, never silent.** Ratio features, lookahead and the interview guard are options, because each was tested against a criterion fixed beforehand and either was adopted only as an option or was not adopted ([results.md](results.md)).
- **Ask about the misfits, not everything.** `elicit` questions the choices the rule gets wrong under leave-one-out, shown beside the most similar choices where the person did what the rule expected. A named condition becomes a feature; the words are kept verbatim.
- **Pre-registration.** The protocol was written before any run, with predictions recorded (including ones that turned out wrong), seeds 0 and 100–119 reserved for development, and every later change either an amendment written before its run or a listed deviation. Negative results are kept at the same prominence as positive ones.
- **Test the fast harness against the real one.** `study.py` builds decisions directly from visit sequences; a test compares it with what real OCR reads from rendered screens. That test found two capture bugs (a label spelt two ways, and a thousands separator read as a decimal point).

## Design decisions: infrastructure

- **On-prem by default; the cloud is an explicit opt-in.** One OpenAI-compatible client talks to a local server on `127.0.0.1`. An egress guard refuses any endpoint that is not loopback or private-network unless `ALLOW_CLOUD=true`, and `PROVIDER=gemini` needs that flag too, so a stray setting cannot upload screenshots.
- **Hardware-aware.** The model tier, screenshots per request, image size and context window are chosen from RAM/VRAM (unified memory on Apple silicon). "Suitable for most systems" means the smallest machines must work. Pacing and quota logic are skipped for local models; timeouts are long because CPU inference takes minutes.
- **Free-tier friendly cloud mode.** Throttling, retries that respect the suggested wait, response caching (re-runs and resumes are free), downscaled JPEGs, an ordered fallback chain of models, and remembering exhausted models until their quota resets.
- **Compression that knows what a screen recording is.** Keyframes are analysis inputs, so they restore bit-exact: a 16×16 tile-delta codec aligned with JPEG's blocks stores only new tiles, with references for tiles seen before, never a frame larger than its JPEG, and a SHA-256 check on restore. The video is only for people, so it gets AV1 with every frame kept: frame dropping was tried and shifted what appeared at a given timestamp, which would break `#t=` links.
- **Encryption that fails loudly.** AES-256-GCM per 4 MB chunk, with associated data binding each chunk to the file's salt, its record and its position. The key lives in the OS keyring, not next to the data.
- **Archive when idle, not right after analysis.** Packing straight after `run` would encrypt the playbook the user is about to open. Sessions archive after 2 untouched days and restore transparently.

## What the first tests taught

**First real test** (Gemini, a 3-minute live recording of looking up five cities' populations into Excel). The playbook reconstructed the workflow correctly and the consolidation pass noticed two genuine data-entry discrepancies, but reported them only as open questions while the steps scored 0.95. That gap motivated the review-note flag. One discrepancy was missed because the typed value and the search result fell in different segments and only the consolidation pass could connect them, and that pass ran on a weaker model after quota ran out: the consolidation pass needs the strongest model available, and cross-segment consistency is a job for a deterministic check, which was then built.

**Generality review.** The prompts were biased toward research and spreadsheets; there was no app or window context; repeated keys flooded the event log; and a real bug: duplicate detection compared 160 px thumbnails, so small meaningful changes (a new line of terminal output, a typed value) were treated as "the same screen" and merged. The coding scenario had 11 events but only 6 keyframes, against 13 after the fix. All fixed; the scenario results are the evidence.

**The decision layer** was first checked on drawn frames, then in a real window ([results.md](results.md)). Live runs found problems drawn frames could not: an unnamed control labelled "Button", click coordinates in screen pixels against smaller keyframes, a drifting readout that fooled the tree, and a test script that froze its own window.

## Tuning knobs

`WINDOW_SIZE` (4 is more careful, 8–10 fewer calls); `CHANGE_THRESHOLD` (lower for subtle UIs such as spreadsheets); `settle_s` in `config.py` (raise for slow web apps); calibration constants at the top of `analyzer.py` (`PENALTY_*`, `MERGE_LEEWAY`). See [configuration.md](configuration.md).

## AI/ML: what is in, what is next

**In use.** Vision-language models for the core understanding (local Qwen3-VL by default, Gemini on opt-in); local OCR (RapidOCR on ONNX Runtime) for exact on-screen text; and cheap, non-learned components that make the model's job easier and catch its blind spots: OS window metadata and UI Automation names, two-scale change detection, rule-based confidence calibration, the deterministic consistency check, and a readable decision tree.

**Collecting now, learn later: confidence calibration.** The rule-based penalties are guesses. Reviewers mark steps Correct or Wrong and `python -m playbook labels` exports them with the features the rules use. With roughly 100–200 labelled steps, a logistic or isotonic regression to P(correct) can replace the hand-set penalties. Fitting it now, with no data, would be false rigour.

**Considered and deferred.**
- *Self-consistency* (analyse each segment twice and compare): a good uncertainty signal, but it doubles analysis time, the binding constraint on a laptop CPU.
- *Fine-tuning a vision model*: no labelled data, and general models already handle arbitrary apps.
- *Embeddings to compare recordings*: useful for clustering many recordings of one task (expert against novice, essential against habitual steps); needs many recordings first.
- *Think-aloud audio* for the reasons that are off-screen: the highest-value addition for the decision layer, but it needs a speech-to-text dependency and microphone capture ([open-questions.md](open-questions.md)).
- *Cross-session memory and task models* from the literature: not built; pooling already supplies the cross-session context the experiments needed.

## Known limitations

**Playbooks.** CPU inference takes minutes per request. UI Automation and window metadata are Windows-only; OCR, archives and local analysis work on all three OSes. Single monitor. A change smaller than ~150 px at 640 px wide (a single digit in a cell) does not get its own keyframe, though the event log still records what was typed. The consistency check is conservative (5+ digit numbers or 5+ character strings; at most 2 changed digits against any value seen, up to half against a number read since the previous typed entry). Keyboard-only actions with no visible effect (Ctrl+C) are inferred from the event log and usually flagged. Typed text is recorded verbatim unless `MASK_TYPED_TEXT=true`. Fast typing in imported videos can produce many intermediate keyframes. Confidence is still a heuristic. pynput on Wayland and macOS needs extra permissions; development and testing were on Windows 11.

**Decisions.** See the limits in [tacit-knowledge.md](tacit-knowledge.md#limits) and the open problems in [open-questions.md](open-questions.md).
