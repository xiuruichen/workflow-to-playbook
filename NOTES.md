# Project notes

## Why this exists

Much expertise is **tacit**: people know *how* to do something on a computer but rarely write it down, and when they do, they skip the "obvious" details (which filter, which column they checked, which source they trusted). Watching the work is the most faithful record. This prototype converts that observation into an explicit, reviewable procedure, and is meant as a first building block for **digital twins** of knowledge work:

1. **Capture** behaviour passively (what Screenpipe does, but focused on one task).
2. **Interpret** it into intent-level steps (what GodHands does for SOPs).
3. **Keep a human in the loop** wherever the machine is unsure, so the playbook becomes trustworthy ground truth.

The confidence flags are the key research hook. They mark where an observer can't recover intent from pixels alone. In other words, they point to where the tacit part of the knowledge is.

## Architecture

```
recorder.py ──► sessions/<id>/{recording.mp4, events.jsonl, keyframes/, manifest.json}
     │                                  ▲
keyframes.py (change detection, video import, click annotation)
     │
analyzer.py  pass 1: windows of keyframes + events ──► Gemini ──► StepCandidates (calibrated)
             pass 2: all candidates + first/last frame ──► Gemini ──► Playbook (merged steps)
     │
generator.py ──► playbook.md / playbook.html / playbook.json
app.py (Streamlit) and playbook/__main__.py (CLI) orchestrate the above.
```

`models.py` holds the pydantic contracts between stages. Every stage reads and writes files, so any stage can be re-run on its own (`analyze`, `render`).

## Design decisions

- **Event-anchored keyframes beat fixed-interval sampling.** A timer either misses fast actions or wastes API calls on idle screens. Before/after pairs around real input events give the model exactly the frames that explain each action, and the click location (drawn as a numbered ring) removes most of the ambiguity about *what* was clicked.
- **Two passes.** Windows of ~10 keyframes keep per-frame detail high. The consolidation pass sees the whole workflow, so it can name the goal and merge micro-actions into meaningful steps. Windows share a boundary keyframe, so every transition is analyzed exactly once.
- **Calibrated confidence, not raw model confidence.** LLM self-reported confidence is poorly calibrated. Simple rules based on facts the model can't see (no input event, repaired JSON, long gaps) make the flag more meaningful. The model also has to give *evidence* and an *uncertainty reason*, which turns a flag into a concrete question for the reviewer.
- **Two kinds of review flag.** Low confidence (⚠️) means *the system doesn't know what happened*. A review note (🔎) means *it knows what happened, but something looks wrong*: a typed value that differs from its source, a likely typo, an undone action. The second kind came out of the first real test (see below) and is arguably the more valuable one: it surfaces the human's mistakes and unexplained decisions, which is exactly where tacit knowledge (or its absence) shows.
- **Never silently lose information.** A segment that fails to analyze becomes a confidence-0 step ("review the recording manually"). Candidates that pass 2 forgets are kept as raw steps. Dropped candidates are logged in `analysis.json`.
- **Free-tier friendly.** Throttling, retries that respect Google's suggested wait, response caching (re-runs and resumes cost nothing), downscaled JPEGs, an ordered fallback chain of models (each has its own daily quota), and remembering exhausted models until their quota resets.
- **OpenAI-compatible client.** Switching to another vision provider (OpenRouter, a local vLLM/Ollama server, OpenAI) only needs `GEMINI_BASE_URL`, `GEMINI_MODEL` and the key.
- **Video time = wall time.** The recorder duplicates frames when capture lags, so `#t=<event time>` always lands on the right moment.

## Findings so far

**First real test** (3-minute live recording: looking up the populations of five cities in Edge/Chrome and entering them into Excel; 70 keyframes, 71 input events):

- The playbook correctly reconstructed the workflow: 11 steps alternating "search for X's population" / "record it in Excel", with the right values and timestamps, and inferred inputs (`city_name`, `population_value`).
- The consolidation pass noticed **two genuine data-entry discrepancies** (315,613 entered vs 315,663 shown; 3,163,843 entered vs 3,863,148 searched) and a stray click on an empty cell. But it reported them only as open questions while the steps scored 0.95 and were not flagged. That gap motivated the review-note flag.
- Re-running with review notes flagged the Los Angeles mismatch (quoting both values) and a stray keystroke before "Boston". It missed the Cincinnati one: the typed value and the search result fell in different segments, so only the consolidation pass could connect them, and that pass ran on a Flash-Lite model after the stronger models ran out of quota. The Lite consolidation also merged poorly (32 steps vs 11). **Lesson:** the consolidation pass needs the strongest model available; cross-segment consistency checks are a good candidate for a deterministic check later (compare values typed against values read in earlier steps).
- No steps fell below 0.70. Either the recording was clean, or the model is overconfident. This is the main open question for evaluation (below).
- **Free-tier reality:** Gemini 2.5 Flash is no longer offered to new keys, some listed models have a free quota of 0, and the daily quota per model can run out after roughly 10–20 requests. The fallback chain plus larger windows (~9 requests for a 3-minute task) make the free tier workable.

**Synthetic example** (`examples/city-population-lookup/`): a fictional search → spreadsheet workflow with a deliberate digit swap (168,412 → 186,412). It is imported as video, so there are no input events. All 4 steps were reconstructed, and the typo was flagged with both values quoted.

## Known limitations

- **Single monitor** (choose with `MONITOR`). Multi-monitor workflows lose actions on other screens.
- **No audio / narration.** The *why* behind decisions is only inferred. Think-aloud narration would be the highest-value addition for capturing tacit knowledge.
- **Keyboard-only actions with no visible effect** (e.g. Ctrl+C) are inferred from the event log only. They usually get flagged, which is intended.
- **Typed text is recorded verbatim** unless `MASK_TYPED_TEXT=true`. Passwords typed during a recording end up in `events.jsonl` and prompts. Pause first.
- **Fast typing in imported videos** can produce many intermediate keyframes. Keyframes have a minimum gap of 1 s, but long recordings still mean more API calls.
- **pynput on Wayland/macOS** needs extra permissions. It was developed and tested on Windows 11.
- Model confidence is still a heuristic. Treat 0.70 as a starting point and tune it against human review results (see evaluation ideas below).

## Tuning knobs

- `WINDOW_SIZE`: 4 gives more careful per-step analysis; 8–10 means fewer API calls.
- `CHANGE_THRESHOLD`: lower it for subtle UIs (spreadsheets), raise it if video or animations create noise.
- `settle_s` (config.py): increase for slow web apps so the "after" frame shows the loaded result.
- Calibration constants are at the top of `analyzer.py` (`PENALTY_*`, `MERGE_LEEWAY`).

## Evaluation ideas

1. Record 3–5 workflows of each type (web research, spreadsheet editing, file/settings management).
2. Have a person write the "true" step list for each.
3. Measure step recall/precision, timestamp accuracy, and, most importantly, **flag quality**: are flagged steps actually the wrong or ambiguous ones? A good system has high precision on unflagged steps.
4. Fit the calibration penalties and the threshold to those results.

## Roadmap

- [ ] Optional think-aloud audio track, transcribed and aligned to steps (captures the *why*).
- [ ] Accessibility-tree / UI Automation capture (exact element names, no OCR guessing).
- [ ] Multi-monitor and active-window metadata (app name, window title, URL) per event.
- [ ] Automatic redaction of sensitive regions before upload.
- [ ] Export to agent-executable formats (e.g. browser-automation scripts or tool-call plans), so a playbook can be replayed by an AI agent: the "digital twin" step.
- [ ] Compare multiple recordings of the same task to separate the essential steps from personal habits, and to surface expert-vs-novice differences.
- [ ] Optional local OCR (Tesseract) as a cross-check for low-confidence steps.
