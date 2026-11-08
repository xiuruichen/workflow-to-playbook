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
token_certainty.py: token probabilities from pass 1 ──► per-step score ──► low-confidence flag after pass 2
     │
generator.py ──► playbook.md / playbook.html / playbook.json
skill.py ──► skill/SKILL.md + skill.json (agent-ready: placeholders, step-to-step data, human gates)
archive.py + tilecodec.py: idle session folder ◄──► encrypted <id>.pbx (lossless keyframes, AV1 video, zstd JSON)
app.py (Streamlit) and playbook/__main__.py (CLI) orchestrate the above; local_setup.py installs the model.
scenarios.py + evaluate.py: scripted multi-domain recordings with ground truth ──► scorecard
labels.py: reviewer Correct/Wrong labels ──► labels.csv (future calibration data)
```

`models.py` holds the pydantic contracts between stages. Every stage reads and writes files, so any stage can be re-run on its own (`analyze`, `render`).

## Design decisions

- **Event-anchored keyframes beat fixed-interval sampling.** A timer either misses fast actions or wastes API calls on idle screens. Before/after pairs around real input events give the model exactly the frames that explain each action, and the click location (drawn as a numbered ring) removes most of the ambiguity about *what* was clicked.
- **Two passes.** Windows of 3–8 keyframes (10 on Gemini) keep per-frame detail high. The consolidation pass sees the whole workflow, so it can name the goal and merge micro-actions into meaningful steps. Windows share a boundary keyframe, so every transition is analyzed exactly once.
- **Calibrated confidence, not raw model confidence.** LLM self-reported confidence is poorly calibrated. Simple rules based on facts the model can't see (no input event, repaired JSON, long gaps) make the flag more meaningful. The model also has to give *evidence* and an *uncertainty reason*, which turns a flag into a concrete question for the reviewer.
- **Two kinds of review flag.** Low confidence (⚠️) means *the system doesn't know what happened*. A review note (🔎) means *it knows what happened, but something looks wrong*: a typed value that differs from its source, a likely typo, an undone action. The second kind came out of the first real test (see below) and is arguably the more valuable one: it surfaces the human's mistakes and unexplained decisions, which is exactly where tacit knowledge (or its absence) shows.
- **Never silently lose information.** A segment that fails to analyze becomes a confidence-0 step ("review the recording manually"). Candidates that pass 2 forgets are kept as raw steps. Dropped candidates are logged in `analysis.json`.
- **On-prem by default; the cloud is an explicit opt-in.** The same OpenAI-compatible client talks to Ollama on `127.0.0.1`. An egress guard refuses any endpoint that isn't loopback or private-network unless `ALLOW_CLOUD=true`, and `PROVIDER=gemini` needs that flag as well, so a stray setting can't upload screenshots.
- **Free-tier friendly in the optional cloud mode.** Throttling, retries that respect Google's suggested wait, response caching (re-runs and resumes cost nothing), downscaled JPEGs, an ordered fallback chain of models (each has its own daily quota), and remembering exhausted models until their quota resets.
- **Hardware-aware, not one-size-fits-all.** "Suitable for most systems" means the smallest machines must work, so the model tier (Qwen3-VL 2B/4B/8B/32B), screenshots per request, image size and context window are chosen from RAM/VRAM (unified memory on Apple silicon). Pacing and quota logic is skipped for local models; timeouts are long because CPU inference takes minutes.
- **Small models need facts, not pixels.** Rather than hoping a 4B model reads 9-pt text, the recorder takes the clicked element's name from the accessibility API (UI Automation, requested at press time so it sees the UI *before* the click changes it), local OCR adds exact text near each click and in changed regions, a full-resolution crop accompanies each click, and the JSON schema is enforced as a grammar. The consistency check also takes OCR text, so catching a mistyped value no longer depends on the model reading it.
- **OCR only where it matters.** Full-frame OCR cost ~4.5 s per frame on this laptop. Turning off RapidOCR's upscaling to 736 px and its rotation classifier brought it to ~1.8 s; reading only crops around clicks and changed regions (cached in `ocr.json`) cuts it further.
- **Compression that knows what a screen recording is.** Keyframes are analysis inputs, so they must restore bit-exact: a 16×16 tile-delta codec (aligned with JPEG's MCUs, so unchanged regions decode identically) stores only new tiles, as lossless WebP, with references for tiles seen before. It never stores a frame larger than its JPEG and verifies a SHA-256 of the pixels on restore. The video is only for people, so it gets AV1 with every frame kept: frame dropping (`mpdecimate`) was tried and shifted what appeared at a given timestamp, which would break `#t=` links.
- **Encryption that fails loudly.** AES-256-GCM per 4 MB chunk, with associated data binding each chunk to the file's salt, its record and its position, so tampering, reordering and truncation are all detected. The key lives in the OS keyring, not next to the data.
- **Archive when idle, not right after analysis.** Packing immediately after `run` would encrypt the playbook the user is about to open. Sessions are archived after 2 untouched days instead (`AUTO_COMPACT`), and restored transparently by `analyze`/`render`/the UI. Re-packing copies the unchanged video and keyframe records from the old archive.
- **Video time = wall time.** The recorder duplicates frames when capture lags, so `#t=<event time>` always lands on the right moment.
- **Domain-neutral by construction.** Nothing in capture or analysis assumes an app. Context comes from the OS (app and window title per event, window-switch events), and the prompts list what makes a step repeatable in each kind of work (paths and commands for coding, recipients and field values for email/forms, before/after values for settings). This is verified with scripted scenarios rather than assumed.
- **An agent-ready export that carries the uncertainty with it.** The point of a digital twin is that someone (or something) else can do the task. `skill.py` turns a playbook into a skill an agent can follow: input examples become placeholders, a value typed after being read on screen becomes a reference to that earlier step (the next run will read a different value, and a recorded typo must not be replayed), and every step that was flagged and not confirmed by a reviewer becomes an explicit "ask a human first" gate. The flags that mark where tacit knowledge hides in the playbook become the places where an agent has to defer to the expert.
- **Read how the model chose, not what it says about itself.** The local 2B model wrote confidence 0.9 for every step in the evaluation scenarios, so the number carried no signal. Token probabilities are a byproduct of generating the reply: asking for them cost about 0.2% per token (87.5 vs 87.4 ms). Raw they are ~130 KB per reply, so only each step's weakest token is cached (~160 bytes per reply). The score is the smallest gap between a chosen token and its best meaningful rival, in `target` and `value` only: in descriptions and evidence, hesitation is nearly all wording. The flag is applied after pass 2, so changing the cutoff changes no prompt and re-analyzing stays free. Replies cached before this have no scores, and the playbook says so rather than treating them as certain.
- **Deterministic checks where possible.** The keyboard log is ground truth for what was typed, so comparing it against values seen on screen is pure string matching with no model needed. Only a value recorded *before* the typing proves a correct copy, and the user's own earlier input (e.g. a mistyped command still visible in the terminal) is never treated as a source. The same log shows when software rejected an input: error messages in every kind of app quote the input they refuse (`'pyhton' is not recognized`, `gti: command not found`, `'jon.doe@' is not a valid email`, `No results for "springfeild"`), so new on-screen error text that cites something just typed flags that entry. It needs no knowledge of the app.

## Findings so far

**First real test** (run on Gemini, before local mode existed; 3-minute live recording: looking up the populations of five cities in Edge/Chrome and entering them into Excel; 70 keyframes, 71 input events):

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

**Synthetic example** (`examples/city-population-lookup/`): the `research` evaluation scenario, analyzed by the local 2B model on a laptop CPU. A fictional search → spreadsheet workflow with a deliberate digit swap (168,412 → 186,412). It has 8 steps, and the consistency check flagged the typo with both values quoted. An earlier version generated by Gemini from an imported video is in git history.

## Known limitations

- **CPU inference is slow.** Qwen3-VL 4B on a laptop CPU takes minutes per request, so a 3-minute recording can take tens of minutes to analyze the first time (cached afterwards). A GPU or Apple silicon is much faster.
- **UI Automation is Windows-only**; OCR, the archive and local analysis work on all three OSes.
- **Restored keyframes are PNG** (exact pixels, but larger than the original JPEGs) while a session is in use.
- **Losing the archive key loses the archives.** Back it up with `key --export`.
- **AV1 playback:** archived videos are AV1, which current browsers play; a few older players don't. `ARCHIVE_VIDEO=original` avoids re-encoding.

- **Single monitor** (choose with `MONITOR`). Multi-monitor workflows lose actions on other screens.
- **App/window metadata is Windows-only** for now (Win32 calls via ctypes). On macOS/Linux events have no window context; the model falls back to reading the screen.
- **Tiny changes can merge.** A change smaller than ~150 pixels at 640 px wide (e.g. a single digit in a cell) doesn't get its own keyframe, so that blinking cursors and spinners don't create keyframes. The event log still records exactly what was typed.
- **The consistency check is conservative.** It needs 5+ digit numbers or 5+ character strings. Against any value seen in the recording it allows at most 2 changed digits; against a number read since the previous typed entry it allows up to half the digits (same magnitude and leading digit), which catches Los Angeles (3,163,843 vs 3,863,148). Bigger rewrites of text, and numbers copied from further back, still rely on the model.
- **No audio / narration.** The *why* behind decisions is only inferred. Think-aloud narration would be the highest-value addition for capturing tacit knowledge.
- **Keyboard-only actions with no visible effect** (e.g. Ctrl+C) are inferred from the event log only. They usually get flagged, which is intended.
- **Typed text is recorded verbatim** unless `MASK_TYPED_TEXT=true`. Passwords typed during a recording end up in `events.jsonl` and prompts. Pause first.
- **Fast typing in imported videos** can produce many intermediate keyframes. Keyframes have a minimum gap of 1 s, but long recordings still mean more model calls.
- **pynput on Wayland/macOS** needs extra permissions. It was developed and tested on Windows 11.
- Model confidence is still a heuristic. Treat 0.70 as a starting point and tune it against human review results (see evaluation ideas below).

## Tuning knobs

- `WINDOW_SIZE`: 4 gives more careful per-step analysis; 8–10 means fewer model calls.
- `CHANGE_THRESHOLD`: lower it for subtle UIs (spreadsheets), raise it if video or animations create noise.
- `settle_s` (config.py): increase for slow web apps so the "after" frame shows the loaded result.
- Calibration constants are at the top of `analyzer.py` (`PENALTY_*`, `MERGE_LEEWAY`).

## Evaluation results

**Local model on an 8 GB laptop.** Development laptop: 7.6 GB RAM, Intel Core Ultra 5 135U, no GPU, `LOW_POWER=true` (4 threads, below-normal priority), with a browser open. Current setup: Qwen3-VL 2B Instruct (Q4_K_M) on llama.cpp's `llama-server`, started only for the analysis.

| scenario | steps | expected found | mistake | false flags | time | peak RAM |
|---|---|---|---|---|---|---|
| email (28 s recording) | 10 | 5/5 | caught | 0 | 14 min | 2.0 GB |
| files (6 segments) | 12 | 4/4 | n/a | 0 | 29 min | 2.0 GB |
| research | 8 | 3/4 | caught | 0 | 8 min | 3.1 GB |
| coding | 12 | 4/5 | caught | 0 | 21 min | 3.1 GB |

Email and files ran at 4 threads; research and coding at 6, with Edge and Teams closed. Peak RAM for research and coding is llama-server's working set sampled every 15 s (it reserved up to 4.5 GB); the earlier 2.0 GB figures were measured differently and are probably low, so plan on ~3 GB. Free memory fell to ~330 MB during the research run. All three planted mistakes are caught by the deterministic checks, not the model, and the "mistake" and "false flags" columns are from replaying every scenario against the cached answers after the last change to the checks. Missed steps: "read 168,412" (research, also missed by Gemini Flash-Lite) and the Ctrl+S save (coding).

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
- **Threads.** Encoding a screenshot with the vision projector is the slowest part of a request (prompt text is read at ~45-70 tokens/s and reused across segments). Per screenshot: 40-46 s at 4 threads, 24-26 s at 6, 20-26 s at 8 on this 14-thread CPU, so low-power mode now uses half the CPU threads, at most 6 (still below-normal priority). A full uncached re-run at 6 threads is still to be measured.
- **Bonsai 2.** The 2B used half the RAM but lost a step and couldn't produce a valid consolidation; the 4B read prompts at ~5.6 tokens/s against ~23 for Qwen3-VL 2B on this CPU (the ternary kernels don't offset twice the parameters here). Neither is offered.

Earlier fixes on the Ollama path:
- The plain `qwen3-vl:2b` tag is the *thinking* variant: it wrote ~2,000 hidden reasoning tokens for a two-line answer (and ~3,500 with thinking "disabled"), so real requests timed out or came back empty. All tiers now use the `-instruct` tags, replies are capped (`LOCAL_MAX_TOKENS`, 3000), and two empty replies in a row stop with a clear message instead of ~25 minutes of retries.
- Ollama spends ~1,040 tokens on every image regardless of its size, and this CPU reads ~15 prompt tokens/s at 4 threads — about 70 s per image. Low-power mode therefore skips the zoomed click crops (the local OCR still reports the text near each click), which brought a segment from ~6,800 prompt tokens / 9.5 min to ~4,800 / 5.5 min. The local timeout is 30 min, since a timeout restarts a request from zero.
- The context window for the smallest tier is 8192 tokens (one segment's prompt is larger than the 4096 default).

The 2B model is good at listing steps but weak at judging them: it never wrote a review note for the planted email typo, so on small machines the deterministic consistency check does that job. At first it looked like the check missed it too. It had flagged the typo, but on the wrong step: the 2B model times steps a keyframe late, so its "click the To field" step contained the typing time, and the scorer rightly counted a note there as a false flag. Notes now go on the step that says it entered the value, and only OCR text or read/select steps count as proof of a correct copy (small models also write the typed address as the value of the click into the field, which used to explain the typo away). Replayed from the cached answers, the email scenario now shows the mistake caught with no false flags. In coding the model wrote "Type 'pyhton app.py'" as an ordinary step; there is no correct value on screen to compare it with, only the terminal's error, which the rejected-input check now reads. A network watcher logging every connection by Python and Ollama during a local run recorded none leaving the machine. The larger tiers on a bigger machine are still to be measured.

**Optional cloud run, for comparison.** `python -m playbook.evaluate`, run 2026-10-24 on `gemini-3.5-flash-lite` (the stronger free models were out of daily quota):

| Scenario | Expected steps found | Planted mistake | False alarms | API calls |
|---|---|---|---|---|
| coding (VS Code + terminal) | 5/5 | ✅ caught by the model (`pyhton`) | 0 | 2 |
| email (Outlook + attachment) | 5/5 | ✅ caught by the consistency check (`jon.doe@` vs `john.doe@`) | 0 | 2 |
| files + settings | 4/4 | n/a (none planted) | 0 | 3 |
| research + spreadsheet | 3/4 | ✅ caught by the model (`186,412` vs `168,412`) | 0 | 2 |

The one missed expected step ("read the population 168,412") is Lite-model variation: the value still appears in the mismatch flag. On the first run, before the visible-values change, the email typo was missed: the model never wrote a "read John's email" step, so nothing recorded the correct address. Then the check over-flagged the corrected `python app.py` against the earlier typo still visible in the terminal. Both were fixed and are covered by tests.

**Token certainty (2026-11-03), a partial run.** Fresh local run of coding and email; the run was stopped for low memory partway through `files`, before `research`, so those two are unmeasured. Scores below are re-computed offline from the saved token probabilities with the final filter.

| flagged by hesitation at cutoff | 0.20 | 0.25–0.35 | 0.40–0.50 |
|---|---|---|---|
| coding (10 steps) | 0 | 2 | 3 |
| email (10 steps) | 0 | 0 | 0 |

At 0.30 the two flags in coding are `line` over `code`, on a step that said `pyhton` was typed into "the line of code" when it went to the terminal (a real catch, though the rejected-input check had already flagged that step), and `terminal` over `command` on a Press Enter step (wording, so a false alarm). Email's specific targets (`To`, `Send`) scored 0.84–1.0. That is one good flag and one false alarm from 20 synthetic steps: enough to set a starting cutoff, not to say how well it predicts wrong steps. Reviewer labels now include `token_certainty`, so real recordings can answer that. Both planted mistakes were still caught by the deterministic checks; hesitation doesn't and shouldn't catch them, because the model firmly reports what the person typed.

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

**Fixes from the live runs (2026-11).** Four changes came from running the local 2B model on real recordings, each with a test: (1) on the 8192-token window the consolidation prompt (steps plus two screenshots) overflowed by 58 tokens, so it now retries once text-only and compact; (2) OCR dropped spaces ("isnotrecognized"), hiding the terminal's rejection of a typo, so the rejected-input check also tries the text with spaces removed; (3) the model's free-text review remarks appeared on nearly every step, so on local models a remark becomes a flag only if it quotes two near-miss values that code can check, and is otherwise kept as a plain note; (4) for the same reason a step is `O6` only on low confidence or a hesitation note. Not re-measured on the full four-scenario table above.

**Confirmatory runs H1–H4 (2026-11-07, seeds 1–5, code at tag `freeze-1`; full tables in `docs/results/confirmatory.md`).** Scripted "person", drawn-frame-equivalent decision logs from the fast harness (checked against the real capture path by a test). Held-out sets are small (12 decisions at 40 visits, 24 at 80), so one miss moves a seed by 8 or 4 points.
- **H1 (held-out agreement >= 0.90 mean, >= 0.80 on every seed): holds on the dashboard** (1.00 on all five seeds at 40 and at 80 visits, majority baseline 0.40–0.56) and **fails on the invoice-triage domain**: greedy induction 0.87 mean (worst seed 0.67) at 40 visits and 0.89 (0.75) at 80; with lookahead 0.87 (0.67) and 0.93 (0.79). The prediction recorded in amendment 1, that triage would fail, was right, although the development seeds had been more pessimistic (0.64) than the confirmatory ones. So the method recovers a single-regime rule from 40 visits but only part of a rule with two regimes, three outcomes and a word on screen.
- **H2 (cross-session context helps): holds on the dashboard** (1.00 vs 0.78 at 40, 0.80 at 80) and on triage except greedy at 40 visits (0.87 vs 0.87); with 80 visits 0.89 vs 0.80 (lookahead 0.93 vs 0.86).
- **H3 (descriptive only):** without the non-action decisions the rule can only say "act" and agreement falls to 0.23–0.48. This shows that non-actions have to be logged; it does not show they carry hidden information.
- **H4 (one elicitation round with a simulated expert who always names the hidden fact): holds only narrowly.** Mean held-out agreement rose from 0.81 to 0.85 (dashboard) and 0.68 to 0.71 (triage), but in 6 of 10 runs nothing changed (in two the rule's disagreements happened not to include a warmup decision, so the expert had nothing to answer), and on triage the number of unexplained decisions did not shrink (19.6 before and after). A perfect, scripted expert is the best case.
- The lookahead tree adds on triage and costs on noisy labels (see ROADMAP); the exploratory studies E1–E6 follow in `docs/results/exploratory.md`.

**H5, does the judgment help an agent (2026-11-07/08, local Qwen3-VL 4B Q4_K_M, text only, seeds 1–5, 40 visits, 12 held-out each, 3 repeats at temperature 0.3; `docs/results/h5/h5.md`).** Agreement with the person's later decisions:

| | procedure only | + judgment (A) | + judgment, strict (B) | rules read mechanically | most common outcome |
|---|---|---|---|---|---|
| dashboard | 0.77 | 0.77 | 0.80 | 1.00 | 0.40 |
| triage | 0.44 | 0.56 | 0.55 | 0.82 | 0.40 |

- On the dashboard the judgment section does not clearly help (tie for A, +0.03 for B, inside the seed spread of 0.58–1.00). Procedure-only already scores 0.77 because it answers "do nothing" and the person mostly did; it missed 42 actions. B acted far more (32 wrong actions against 9 for A) for a small agreement gain.
- On triage it helps by 0.11–0.12, mostly because the model *asks a human* (45 asks in 180 answers) and acts wrongly less often (22–24 wrong actions against 100). It does not apply the thresholds: mechanically following the same rules gets 0.82.
- So with a 4B model, after fixing the earlier setup problems, the judgment section is **a safer boundary rather than better decisions**. Compared with the 2B result in ROADMAP (judgment 1/12 vs 5/12), the direction changed on triage and not on the dashboard; both are small models, single runs per seed, and the scripted person follows a clean rule.

**Amendment 2 test (fresh seeds 6–10, `docs/results/confirmatory2.md`): lookahead with `min_leaf` 3 (C) against the default (A).** C was at least as good as A in all six cells (for example triage at 80 visits 0.97 vs 0.88, dashboard at 40 visits 0.95 vs 0.88) but the mean gain was +0.030, below the +0.05 bar fixed in advance, so **C is not adopted as the default**; it stays available (`induce.fit(..., lookahead=True, min_leaf=3)`). At 40 visits triage is still 0.75 for both. The bar was set before the run; I am not moving it.

**Amendment 3 test (third domain, `service.py`: a rule on errors divided by requests; seeds 6–10; `docs/results/confirmatory3.md`).** One-readout-at-a-time trees cannot express a quotient: held-out agreement 0.57 / 0.72 / 0.59 at 40 / 80 visits / 60 visits with 10% label noise. With ratio features (`--ratios`) 0.78 / 0.93 / 0.81 (+0.21 on average, bar +0.10), and no change on the dashboard or triage domains (cost check 0.00, bar −0.03), so **ratio features are adopted as a switch-on option** (never silently on). One prediction written beforehand was wrong: I predicted ratios would *not* reach 0.90 at 80 visits and they reached 0.93 (5 seeds, 24 held-out visits, range 0.83–1.00). A declared limit: the ratio is only tried between readouts that are always present and positive, and the direction is by alphabet.

**Amendment 4 test (elicitation guard `elicit.vet`, seeds 6–10, 80 visits with a hidden warmup fact; `docs/results/confirmatory4.md`).** The guard changed nothing in any cell, so by the bar set beforehand (not below −0.01 with a perfect expert, at least +0.01 with wrong tags) it is **not adopted**; it stays an unused option. On these seeds the loop with a perfect scripted expert gave +0.12 on the dashboard (0.85 → 0.97) and +0.03 on triage (0.72 → 0.74), and wrong tags cost nothing here (they cost 0.04 in one E5 cell on other seeds), so the guard has nothing to fix yet. Open: whether a real person's wrong answers look like the scripted ones.

**H6, real capture (2026-11-07, seed 1, 40 visits each, real recorder and real mouse, scripted person; `docs/results/h6/`).** Triage: 40/40 readouts (numbers and the vendor word) and 40/40 outcomes read correctly, one decision per recording; the rule fitted on the earliest 28 scored 0.67 on the last 12 (same as the fast harness would predict for a compound rule), majority baseline 0.08. Dashboard: 40/40 and 40/40; rules 12/12 on the last 12, majority 0.67. H6 (>= 0.95 correct) holds for both. Not a test of a human.

**Exploratory studies E1–E6 (`docs/results/exploratory.md`, seeds 1–5, nothing pre-set to pass).**
- **E1 learning curve.** Dashboard: 1.00 from 40 visits, 0.77–0.93 at 20, below that unreliable. Triage: 0.50–0.63 at 20, 0.87 at 40, 0.86–0.93 at 80, 0.86 (greedy) / 0.97 (lookahead) at 120. A rule with several regimes needs on the order of 100 observations, more than a person will usually give in a session.
- **E2 label noise** (the person sometimes acts against their own rule). Dashboard: 0.97 / 0.93 / 0.77 at 5 / 10 / 20% noise; the disagreements point at the noisy visits (precision 0.93 / 0.84 / 0.71, recall 1.00 / 1.00 / 0.91). Triage degrades much faster (0.72 at 5%, 0.58 at 20%) and the disagreements are mostly *not* the noisy visits (precision 0.42–0.50), so a rule-vs-behaviour disagreement is weak evidence of a hidden reason when the rule is itself poorly learned. Lookahead is no better under noise.
- **E3 OCR misreads.** No effect up to 5% of readouts misread on the dashboard; a drop to 0.81 at 10%. Triage 0.86 → 0.81–0.87.
- **E4 distractors / drift.** Irrelevant readouts (up to 8) do not hurt the dashboard and cost triage about 4 points. After a rule change, fitting on all earlier visits (0.89 / 0.86) beats fitting only on the visits after the change for triage (0.67), because 20 visits are too few; on the dashboard the after-change-only fit is the same (greedy 0.87) or better (lookahead 0.96). No recency fix was built.
- **E5 imperfect expert.** Gains come only from right facts: an expert who names the right fact 100%, 80% or 60% of the time gives the same result (the questions about warmup decisions are few, so they are mostly answered), and one who is never right gives none; wrongly tagged decisions can cost (triage 0.68 → 0.64 at worst case). No guard was added.
- **E6 classifier.** The frozen `classify_decision` got 60% of dashboard decisions right (119 of 200) and 40% of triage decisions (79 of 200): it marks every decision O5 once the rule uses any cross-session feature. Using the decision's own path through the rule (deviation, `induce.path_features`) gets 200/200 on the dashboard and 163/200 (82%) on triage.

**Considered and deferred:**
- **Self-consistency (analyze each segment twice and compare).** A good uncertainty signal, but it doubles analysis time, and that's the binding constraint on a laptop CPU.
- **Fine-tuning or training a vision model.** No labelled data, and general models already handle arbitrary apps. Not worth it at prototype stage.
- **Embeddings to compare recordings.** Useful later for clustering many recordings of the same task (expert vs novice, essential vs habitual steps). That's the digital-twin direction, and it needs many recordings first.

## Roadmap

Research direction (tacit-knowledge capture, built on ideas from the literature): see [docs/ROADMAP.md](docs/ROADMAP.md). The list below is the engineering roadmap.

- [x] Frames, decision log (including non-actions), rule fitting and knowledge classes: `frames.py`, `decisions.py`, `induce.py`, `knowledge.py`; planted-rule benchmark in `dashboard.py`.
- [x] Ask-the-expert loop on the decisions a fitted rule can't explain (`elicit.py`, `python -m playbook elicit`): checked with a simulated expert only, not yet with a real one.
- [x] Judgment calls in the agent skill export (`export --judgment`).
- [x] Skill dependencies and completion checks (`depends_on`, `completion_checks`); [ ] replay a skill with a computer-use agent and score it against them.
- [x] Pilot kit for one real person (`pilot.py`, `docs/pilot-guide.md`): not yet run with a human.
- [x] Protocol amendment 1 and code freeze `freeze-1` (2026-11-07), before the confirmatory runs; it records a prediction that H1 fails on triage at 40 visits.
- [x] Second domain (`triage.py`: invoice triage, three outcomes, a categorical cue, a different cross-session exception) and categorical on-screen words as features. Live script: `scripts/live_triage_test.py`. Found two capture problems by comparing the fast harness with real OCR: "Batch size" read as "Batchsize" (fixed, `unify_names`) and "9,871" read as "9.871" (**not fixed**: the triage screen shows amounts without separators; a real screen with thousands separators would be misread).
- [x] Fast experiment harness (`study.py`), ablation switches (`induce --without`), flag precision/recall/F1 in `evaluate.py`, and a fix for OCR spelling a label two ways (`unify_names`).
- [x] Evaluation protocol written before the next runs (`docs/evaluation-protocol.md`). [ ] Run it: fresh seeds, a second domain, a larger model with repeats.
- [x] Observability class (`O1`–`O6`) and tacit score on every playbook step, shown in the report, viewer and skill export; `O6` only on measured evidence. [ ] Check the classes against what real experts call tacit.
- [x] Replay harness (`replay`). First run with the local 2B model: the judgment section did not help it (1/12 vs 5/12 without; it mostly asked a human). [ ] Try a larger model and repeats; [ ] run on real recordings.
- [x] Live test with a real window and real input (`scripts/live_dashboard_test.py`): capture exact on 24/24 and 40/40; the exception rule was not learned from 24 visits but was, exactly, from 40.
- [ ] Optional think-aloud audio track, transcribed and aligned to steps (captures the *why*).
- [x] Accessibility-tree / UI Automation capture of clicked and typed-into elements (Windows).
- [ ] The same via AX (macOS) / AT-SPI (Linux).
- [x] Fully local analysis (Ollama + Qwen3-VL), hardware-aware model choice, egress guard.
- [x] Encrypted, compacted archives of idle sessions.
- [ ] Measure the local model on real recordings and on the larger tiers. All four evaluation scenarios are measured on the 2B tier.
- [x] Active-window metadata (app, window title) per event, and window-switch events (Windows).
- [ ] The same on macOS/Linux; browser URL capture; multi-monitor.
- [x] Token-probability flag for steps the local model hesitated on.
- [ ] Measure it on `files`, `research` and real recordings: do low scores predict wrong steps?
- [ ] Learned confidence calibration from reviewer labels (`labels.csv`) once ~100–200 steps are labelled.
- [ ] Real-world evaluation set: several real recordings per activity type, scored with reviewer labels.
- [ ] Automatic redaction of sensitive regions.
- [x] Export to an agent-ready skill (`SKILL.md` + `skill.json`): placeholders for inputs, data flow between steps, human gates for unconfirmed steps.
- [ ] Replay a skill with a computer-use agent and score it against the recording (does it reach the same end state?).
- [ ] Compare multiple recordings of the same task to separate the essential steps from personal habits, and to surface expert-vs-novice differences.
- [x] Local OCR of the regions around clicks and changes.
