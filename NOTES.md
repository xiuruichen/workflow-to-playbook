# Project notes

## Why this exists

Much expertise is **tacit**: people know *how* to do something on a computer but rarely write it down, and when they do, they skip the "obvious" details (which filter, which column they checked, which source they trusted). Watching the work is the most faithful record. This prototype converts that observation into an explicit, reviewable procedure, and is meant as a first building block for **digital twins** of knowledge work:

1. **Capture** behaviour passively (what Screenpipe does, but focused on one task).
2. **Interpret** it into intent-level steps (what GodHands does for SOPs).
3. **Keep a human in the loop** wherever the machine is unsure, so the playbook becomes trustworthy ground truth.

The confidence flags are the key research hook. They mark where an observer can't recover intent from pixels alone. In other words, they point to where the tacit part of the knowledge is.

## Architecture

```
recorder.py ──► <local app data>/sessions/<id>/{recording.mp4, events.jsonl, keyframes/, manifest.json}
     │            (events carry app + window title and, via uia.py, the UI element clicked / typed into)
keyframes.py (two-scale change detection, video import, click annotation, crops)
     │
backend.py + hardware.py + security.py: which model (local Ollama by default, sized to RAM/VRAM), egress guard
analyzer.py  pass 1: windows of keyframes + events + OCR text (ocr.py) + click crops ──► vision model ──► StepCandidates
             pass 2: all candidates + first/last frame ──► vision model ──► Playbook (merged steps)
consistency.py: typed values (keyboard log) vs values seen on screen (model + OCR) ──► review notes
     │
generator.py ──► playbook.md / playbook.html / playbook.json
archive.py + tilecodec.py: idle session folder ◄──► encrypted <id>.pbx (lossless keyframes, AV1 video, zstd JSON)
app.py (Streamlit) and playbook/__main__.py (CLI) orchestrate the above; local_setup.py installs the model.
scenarios.py + evaluate.py: scripted multi-domain recordings with ground truth ──► scorecard
labels.py: reviewer Correct/Wrong labels ──► labels.csv (future calibration data)
```

`models.py` holds the pydantic contracts between stages. Every stage reads and writes files, so any stage can be re-run on its own (`analyze`, `render`).

## Design decisions

- **Event-anchored keyframes beat fixed-interval sampling.** A timer either misses fast actions or wastes API calls on idle screens. Before/after pairs around real input events give the model exactly the frames that explain each action, and the click location (drawn as a numbered ring) removes most of the ambiguity about *what* was clicked.
- **Two passes.** Windows of ~10 keyframes keep per-frame detail high. The consolidation pass sees the whole workflow, so it can name the goal and merge micro-actions into meaningful steps. Windows share a boundary keyframe, so every transition is analyzed exactly once.
- **Calibrated confidence, not raw model confidence.** LLM self-reported confidence is poorly calibrated. Simple rules based on facts the model can't see (no input event, repaired JSON, long gaps) make the flag more meaningful. The model also has to give *evidence* and an *uncertainty reason*, which turns a flag into a concrete question for the reviewer.
- **Two kinds of review flag.** Low confidence (⚠️) means *the system doesn't know what happened*. A review note (🔎) means *it knows what happened, but something looks wrong*: a typed value that differs from its source, a likely typo, an undone action. The second kind came out of the first real test (see below) and is arguably the more valuable one: it surfaces the human's mistakes and unexplained decisions, which is exactly where tacit knowledge (or its absence) shows.
- **Never silently lose information.** A segment that fails to analyze becomes a confidence-0 step ("review the recording manually"). Candidates that pass 2 forgets are kept as raw steps. Dropped candidates are logged in `analysis.json`.
- **Free-tier friendly.** Throttling, retries that respect Google's suggested wait, response caching (re-runs and resumes cost nothing), downscaled JPEGs, an ordered fallback chain of models (each has its own daily quota), and remembering exhausted models until their quota resets.
- **On-prem by default; the cloud is an explicit opt-in.** The same OpenAI-compatible client talks to Ollama on `127.0.0.1`. An egress guard refuses any endpoint that isn't loopback or private-network unless `ALLOW_CLOUD=true`, and `PROVIDER=gemini` needs that flag as well, so a stray setting can't upload screenshots.
- **Hardware-aware, not one-size-fits-all.** "Suitable for most systems" means the smallest machines must work, so the model tier (Qwen3-VL 2B/4B/8B/32B), screenshots per request, image size and context window are chosen from RAM/VRAM (unified memory on Apple silicon). Pacing and quota logic is skipped for local models; timeouts are long because CPU inference takes minutes.
- **Small models need facts, not pixels.** Rather than hoping a 4B model reads 9-pt text, the recorder takes the clicked element's name from the accessibility API (UI Automation, requested at press time so it sees the UI *before* the click changes it), local OCR adds exact text near each click and in changed regions, a full-resolution crop accompanies each click, and the JSON schema is enforced as a grammar. The consistency check also takes OCR text, so catching a mistyped value no longer depends on the model reading it.
- **OCR only where it matters.** Full-frame OCR cost ~4.5 s per frame on this laptop. Turning off RapidOCR's upscaling to 736 px and its rotation classifier brought it to ~1.8 s; reading only crops around clicks and changed regions (cached in `ocr.json`) cuts it further.
- **Compression that knows what a screen recording is.** Keyframes are analysis inputs, so they must restore bit-exact: a 16×16 tile-delta codec (aligned with JPEG's MCUs, so unchanged regions decode identically) stores only new tiles, as lossless WebP, with references for tiles seen before. It never stores a frame larger than its JPEG and verifies a SHA-256 of the pixels on restore. The video is only for people, so it gets AV1 with every frame kept: frame dropping (`mpdecimate`) was tried and shifted what appeared at a given timestamp, which would break `#t=` links.
- **Encryption that fails loudly.** AES-256-GCM per 4 MB chunk, with associated data binding each chunk to the file's salt, its record and its position, so tampering, reordering and truncation are all detected. The key lives in the OS keyring, not next to the data.
- **Archive when idle, not right after analysis.** Packing immediately after `run` would encrypt the playbook the user is about to open. Sessions are archived after 2 untouched days instead (`AUTO_COMPACT`), and restored transparently by `analyze`/`render`/the UI. Re-packing copies the unchanged video and keyframe records from the old archive.
- **Video time = wall time.** The recorder duplicates frames when capture lags, so `#t=<event time>` always lands on the right moment.
- **Domain-neutral by construction.** Nothing in capture or analysis assumes an app. Context comes from the OS (app and window title per event, window-switch events), and the prompts list what makes a step repeatable in each kind of work (paths and commands for coding, recipients and field values for email/forms, before/after values for settings). This is verified with scripted scenarios rather than assumed.
- **Deterministic checks where possible.** The keyboard log is ground truth for what was typed, so comparing it against values seen on screen is pure string matching with no model needed. Only a value recorded *before* the typing proves a correct copy, and the user's own earlier input (e.g. a mistyped command still visible in the terminal) is never treated as a source.

## Findings so far

**First real test** (3-minute live recording: looking up the populations of five cities in Edge/Chrome and entering them into Excel; 70 keyframes, 71 input events):

- The playbook correctly reconstructed the workflow: 11 steps alternating "search for X's population" / "record it in Excel", with the right values and timestamps, and inferred inputs (`city_name`, `population_value`).
- The consolidation pass noticed **two genuine data-entry discrepancies** (315,613 entered vs 315,663 shown; 3,163,843 entered vs 3,863,148 searched) and a stray click on an empty cell. But it reported them only as open questions while the steps scored 0.95 and were not flagged. That gap motivated the review-note flag.
- Re-running with review notes flagged the Los Angeles mismatch (quoting both values) and a stray keystroke before "Boston". It missed the Cincinnati one: the typed value and the search result fell in different segments, so only the consolidation pass could connect them, and that pass ran on a Flash-Lite model after the stronger models ran out of quota. The Lite consolidation also merged poorly (32 steps vs 11). **Lesson:** the consolidation pass needs the strongest model available; cross-segment consistency checks are a good candidate for a deterministic check later (compare values typed against values read in earlier steps).
- No steps fell below 0.70. Either the recording was clean, or the model is overconfident. This is the main open question for evaluation (below).
- **Free-tier reality:** Gemini 2.5 Flash is no longer offered to new keys, some listed models have a free quota of 0, and the daily quota per model can run out after roughly 10–20 requests. The fallback chain plus larger windows (~9 requests for a 3-minute task) make the free tier workable.

**Generality review.** A review of the pipeline for other kinds of work found:
- The prompts were biased toward research and spreadsheets.
- There was no app or window context.
- Repeated keys flooded the event log.
- **A real bug:** duplicate detection compared 160-px thumbnails, so small but meaningful changes (a new line of terminal output, a typed value) were treated as "the same screen" and merged. That hit coding, forms and spreadsheets on high-resolution screens hardest: the coding scenario had 11 events but only 6 keyframes, versus 13 after the fix.

All of these are fixed. The evaluation results below are the evidence.

**Synthetic example** (`examples/city-population-lookup/`): a fictional search → spreadsheet workflow with a deliberate digit swap (168,412 → 186,412). It is imported as video, so there are no input events. All 4 steps were reconstructed, and the typo was flagged with both values quoted.

## Known limitations

- **CPU inference is slow.** Qwen3-VL 4B on a laptop CPU takes minutes per request, so a 3-minute recording can take tens of minutes to analyze the first time (cached afterwards). A GPU or Apple silicon is much faster.
- **UI Automation is Windows-only**; OCR, the archive and local analysis work on all three OSes.
- **Restored keyframes are PNG** (exact pixels, but larger than the original JPEGs) while a session is in use.
- **Losing the archive key loses the archives.** Back it up with `key --export`.
- **AV1 playback:** archived videos are AV1, which current browsers play; a few older players don't. `ARCHIVE_VIDEO=original` avoids re-encoding.

- **Single monitor** (choose with `MONITOR`). Multi-monitor workflows lose actions on other screens.
- **App/window metadata is Windows-only** for now (Win32 calls via ctypes). On macOS/Linux events have no window context; the model falls back to reading the screen.
- **Tiny changes can merge.** A change smaller than ~150 pixels at 640 px wide (e.g. a single digit in a cell) doesn't get its own keyframe, so that blinking cursors and spinners don't create keyframes. The event log still records exactly what was typed.
- **The consistency check is conservative.** It needs 5+ digit numbers or 5+ character strings, and at most 2 changed digits. It misses bigger transcription errors (Los Angeles: 3,163,843 vs 3,863,148); the model has to catch those.
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

## Evaluation results

`python -m playbook.evaluate`, run 2026-10-24 on `gemini-3.5-flash-lite` (the stronger free models were out of daily quota):

| Scenario | Expected steps found | Planted mistake | False alarms | API calls |
|---|---|---|---|---|
| coding (VS Code + terminal) | 5/5 | ✅ caught by the model (`pyhton`) | 0 | 2 |
| email (Outlook + attachment) | 5/5 | ✅ caught by the consistency check (`jon.doe@` vs `john.doe@`) | 0 | 2 |
| files + settings | 4/4 | n/a (none planted) | 0 | 3 |
| research + spreadsheet | 3/4 | ✅ caught by the model (`186,412` vs `168,412`) | 0 | 2 |

The one missed expected step ("read the population 168,412") is Lite-model variation: the value still appears in the mismatch flag. On the first run, before the visible-values change, the email typo was missed: the model never wrote a "read John's email" step, so nothing recorded the correct address. Then the check over-flagged the corrected `python app.py` against the earlier typo still visible in the terminal. Both were fixed and are covered by tests.

**Local model on an 8 GB laptop.** Development laptop: 7.6 GB RAM, Intel Core Ultra 5 135U, no GPU, `LOW_POWER=true` (4 threads, below-normal priority), with a browser open. Current setup: Qwen3-VL 2B Instruct (Q4_K_M) on llama.cpp's `llama-server`, started only for the analysis.

| scenario | steps | expected found | mistake | false flags | time | peak RAM |
|---|---|---|---|---|---|---|
| email (28 s recording) | 10 | 5/5 | missed | 1 | 14 min | 2.0 GB |
| files (6 segments) | 12 | 4/4 | n/a | 0 | 29 min | 2.0 GB |

How the same email scenario got from 38 to 14 minutes (one run each):

| setup | expected found | false flags | time | peak RAM |
|---|---|---|---|---|
| Ollama, `qwen3-vl:2b-instruct` | 5/5 | 1 | 38 min | ~2.6 GB |
| llama-server, Bonsai 2 2B (PrismML, ternary) | 4/5 | 12 (consolidation failed twice) | 24 min | 1.0 GB |
| llama-server, Bonsai 2 4B | — (stopped) | — | ~10 min per segment | — |
| llama-server, Qwen3-VL 2B, full consolidation | 5/5 | 1 | 33 min | 1.9 GB |
| llama-server, Qwen3-VL 2B, lean consolidation (current) | 5/5 | 1 | 14 min | 2.0 GB |

- **Runtime.** Ollama scales every screenshot to ~1,040 tokens; llama-server's `--image-max-tokens 448` keeps an 896 px screenshot at its native size and reuses the cached system prompt, so a segment went from ~4,800 to ~1,750 new prompt tokens (~3 min instead of ~5.5 at 4 threads).
- **Consolidation was the other half of the wait.** Rewriting every step's fields took the 2B model ~3,000 tokens (8 min at ~6 tokens/s), often cut off and repaired. In low-power mode the model now returns only an id, a title and keep/drop per step, without merging (when allowed to merge from that little context it collapsed 9 actions into 2 steps) and without review notes (it wrote one for every step); descriptions, targets and values come from the per-segment results, and the deterministic consistency check still flags typed-vs-on-screen mismatches. Consolidation now takes ~1.5 min.
- **Bounded output.** Lists and strings in the local JSON schema have maximum sizes, so a model stuck repeating itself stops inside the grammar (one runaway reply took 10 min before that).
- **Bonsai 2.** The 2B used half the RAM but lost a step and couldn't produce a valid consolidation; the 4B read prompts at ~5.6 tokens/s against ~23 for Qwen3-VL 2B on this CPU (the ternary kernels don't offset twice the parameters here). Neither is offered.

Earlier fixes on the Ollama path:
- The plain `qwen3-vl:2b` tag is the *thinking* variant: it wrote ~2,000 hidden reasoning tokens for a two-line answer (and ~3,500 with thinking "disabled"), so real requests timed out or came back empty. All tiers now use the `-instruct` tags, replies are capped (`LOCAL_MAX_TOKENS`, 3000), and two empty replies in a row stop with a clear message instead of ~25 minutes of retries.
- Ollama spends ~1,040 tokens on every image regardless of its size, and this CPU reads ~15 prompt tokens/s at 4 threads — about 70 s per image. Low-power mode therefore skips the zoomed click crops (the local OCR still reports the text near each click), which brought a segment from ~6,800 prompt tokens / 9.5 min to ~4,800 / 5.5 min. The local timeout is 30 min, since a timeout restarts a request from zero.
- The context window for the smallest tier is 8192 tokens (one segment's prompt is larger than the 4096 default).

The planted mistake in the email scenario was not caught by any 2B configuration — the model is good at listing steps but weak at judging them. A network watcher logging every connection by Python and Ollama during a local run recorded none leaving the machine. The other two scenarios, and the larger tiers on a bigger machine, are still to be measured.

**Caveats:**
- The scenarios are synthetic: clean screens, readable fonts, one mistake each.
- They test generality of the pipeline, not real-world accuracy.

**Next steps:**
1. Record 3–5 *real* workflows of each type.
2. Have a person mark each step Correct/Wrong in the UI.
3. Measure flag precision and recall from `labels.csv`.

## AI/ML: what's in, what's next, and why

**In use:**
- **Vision-language models** for the core understanding, which is the right tool for reading arbitrary UIs. Local Qwen3-VL by default; Gemini on opt-in.
- **Local OCR** (RapidOCR / ONNX Runtime, small CPU models) for exact on-screen text.
- **Cheap, non-learned components** that make the model's job easier and catch its blind spots:
  - OS window metadata and UI Automation element names
  - two-scale change detection
  - rule-based confidence calibration
  - the deterministic consistency check

**Collecting now, learn later: confidence calibration.** The rule-based penalties are guesses. Reviewers now mark steps Correct/Wrong, and `python -m playbook labels` exports them with the features the rules use (model confidence, event support, gaps, merges, action type). With roughly 100–200 labelled steps, a logistic or isotonic regression from those features to P(correct) can replace the hand-set penalties. That's a few lines of scikit-learn, and it's the most valuable ML addition. Fitting it now, with no data, would be fake rigour.

**Considered and deferred:**
- **Self-consistency (analyze each segment twice and compare).** A good uncertainty signal, but it doubles API use, and that's the binding constraint on the free tier.
- **Fine-tuning or training a vision model.** No labelled data, and general models already handle arbitrary apps. Not worth it at prototype stage.
- **Embeddings to compare recordings.** Useful later for clustering many recordings of the same task (expert vs novice, essential vs habitual steps). That's the digital-twin direction, and it needs many recordings first.

## Roadmap

- [ ] Optional think-aloud audio track, transcribed and aligned to steps (captures the *why*).
- [x] Accessibility-tree / UI Automation capture of clicked and typed-into elements (Windows).
- [ ] The same via AX (macOS) / AT-SPI (Linux).
- [x] Fully local analysis (Ollama + Qwen3-VL), hardware-aware model choice, egress guard.
- [x] Encrypted, compacted archives of idle sessions.
- [ ] Measure the local model on the evaluation scenarios and real recordings (blocked on disk space on the dev laptop).
- [x] Active-window metadata (app, window title) per event, and window-switch events (Windows).
- [ ] The same on macOS/Linux; browser URL capture; multi-monitor.
- [ ] Learned confidence calibration from reviewer labels (`labels.csv`) once ~100–200 steps are labelled.
- [ ] Real-world evaluation set: several real recordings per activity type, scored with reviewer labels.
- [ ] Automatic redaction of sensitive regions before upload.
- [ ] Export to agent-executable formats (e.g. browser-automation scripts or tool-call plans), so a playbook can be replayed by an AI agent: the "digital twin" step.
- [ ] Compare multiple recordings of the same task to separate the essential steps from personal habits, and to surface expert-vs-novice differences.
- [x] Local OCR of the regions around clicks and changes.
