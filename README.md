# Workflow → Playbook (prototype)

[![tests](https://github.com/xiuruichen/workflow-to-playbook/actions/workflows/tests.yml/badge.svg)](https://github.com/xiuruichen/workflow-to-playbook/actions/workflows/tests.yml)

Record someone doing a task on their computer, then automatically turn the recording into a **step-by-step playbook** (Markdown, plus an interactive HTML viewer):

- every step links back to a **timestamp in the recording**; in `playbook.html` clicking a step plays the video from that moment,
- before/after **screenshots** for each step,
- a **confidence score (0–1)** per step. Steps are **flagged for human review** when confidence is below **0.70** *or* when the action is clear but something looks off (e.g. a value typed that differs from its source, caught by the model or by a deterministic consistency check), always with the reason and the evidence,
- the **inputs** that would change next time (search terms, file names, values), and **open questions** the system couldn't answer.
- an optional **agent-ready skill** (`SKILL.md` + `skill.json`): the same procedure for an AI agent, with inputs as placeholders and every unconfirmed step marked *ask a human first* (see [Export for AI agents](#export-for-ai-agents)).

**Fully on-prem by default.** Analysis runs on a local vision model ([Qwen3-VL](https://ollama.com/library/qwen3-vl) through [Ollama](https://ollama.com)), sized automatically to the computer, so recordings never leave the machine. Sessions you aren't using are kept as **compressed, encrypted archives** (`.pbx`, about 4× smaller) and are decrypted only when you open, re-analyze or extract a playbook from them. A cloud model (Gemini) is still available as an explicit opt-in.

**See an example:** [`examples/city-population-lookup/`](examples/city-population-lookup/playbook.md). It was generated on a laptop CPU by the local model (Qwen3-VL 2B, low-power mode) from a scripted 23-second recording (fictional data) of looking up a city's population and entering it into a spreadsheet. The person types 186,412 where the source says 168,412, and the deterministic consistency check flags that step for review. Download the folder and open `playbook.html` to try the viewer.

**Works for any kind of computer work**, not just one app: documents and spreadsheets, coding and terminals, email and forms, file management and settings, web research. The recorder logs which app and window each action happened in, and an evaluation harness checks this on four scripted scenarios with known answers (see [Evaluation](#evaluation)).

Inspired by [Screenpipe](https://screenpipe.com/) (continuous screen capture) and [GodHands](https://godhands.ai/) (recording → SOPs). The goal is to make **tacit knowledge** (how an expert actually does something) explicit, reviewable, and reusable, as a building block for digital twins of work.

```
 screen + mouse/keyboard + UI element names ──► keyframes (before/after each action) ──► local OCR (exact on-screen text)
                                                                                           │
                                         local vision model, pass 1: actions per segment ◄─┘
                                                                                           │
  playbook.md / .html ◄── generator ◄── calibrated confidence + consistency check ◄── pass 2: merge into a playbook
                                                                                           │
                                     idle sessions ──► encrypted .pbx archive (lossless keyframes, AV1 video)
```

---

## 1. Setup (Windows, macOS or Linux; Python 3.10+)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env      # macOS/Linux: cp .env.example .env   (optional: every setting has a default)
```

**Slow laptop on Windows?** Put `LOW_POWER=true` in `.env`, skip Ollama and just run `python -m playbook setup-local`: it downloads everything it needs (see [below](#low-power-mode)).

Otherwise install **[Ollama](https://ollama.com/download)** (Windows: `winget install Ollama.Ollama`; macOS: the app or `brew install ollama`; Linux: the script on that page), start it, and run:

```bash
python -m playbook setup-local
```

This checks your RAM and GPU, picks the largest model that runs comfortably, checks there is enough disk space, asks before downloading it, and times a test request:

| Your computer | Model | Download | Screenshots per request |
|---|---|---|---|
| < 3.5 GB RAM free | `qwen3-vl:2b-instruct` | ~1.9 GB | 3, at 896 px |
| 8–15 GB RAM, no big GPU (most laptops) | `qwen3-vl:4b-instruct` | ~3.3 GB | 4, at 1024 px |
| ≥ 16 GB RAM, or a GPU with ≥ 8 GB | `qwen3-vl:8b-instruct` | ~6.1 GB | 6, at 1280 px |
| GPU with ≥ 24 GB, or Apple silicon with ≥ 36 GB | `qwen3-vl:32b-instruct` | ~21 GB | 8, at 1280 px |

<a id="low-power-mode"></a>**Slow or easily overloaded computer?** Put `LOW_POWER=true` in `.env` before running `setup-local`. It uses the smallest model, limits it, OCR and video encoding to half the CPU threads, at most 6 (`MAX_THREADS` changes that), runs at below-normal priority so the desktop stays responsive, skips the zoomed click crops (the local OCR still reads the text near each click), and archives video only with a hardware encoder (otherwise it keeps the original rather than running a CPU-heavy encode).

On Windows, low-power mode also uses llama.cpp's `llama-server` instead of Ollama (`LOCAL_RUNTIME=llama`): `setup-local` downloads a pinned build and Qwen3-VL 2B Instruct (~1.5 GB, SHA-256 checked), and the server starts only for the length of an analysis, so it holds no memory in between. It is about twice as fast as Ollama on a CPU, because screenshots stay at their native size (~450 tokens instead of ~1,040) and the system prompt is reused between requests, and it consolidates without merging steps (small models merge badly). On an 8 GB laptop with 4 threads, a 30-second recording took about 14 minutes and at most ~2 GB of RAM; low-power mode now uses 6 threads there, which encodes each screenshot ~40% faster. While it runs, the server only accepts requests carrying a per-install key, so web pages open in your browser can't use it. Elsewhere, set `LLAMA_SERVER` to your own llama-server build, or keep Ollama.

On a laptop CPU, expect minutes per request rather than seconds. Responses are cached, so you only pay that once per recording. No GPU, Tesseract or separate ffmpeg install is needed: OCR runs on ONNX Runtime and `imageio-ffmpeg` bundles the video encoders.

**Air-gapped machines:** the only network access is the one-time model download. For the llama runtime, copy the `llama` folder from `%LOCALAPPDATA%\WorkflowPlaybook\` on a connected machine to the same place, then run `python -m playbook setup-local --yes`: files that are already present and pass their SHA-256 check aren't downloaded again. For Ollama, copy its models folder (`~/.ollama/models`, or `OLLAMA_MODELS`) and keep Ollama bound to `127.0.0.1` (its default; don't set `OLLAMA_HOST=0.0.0.0`).

> **macOS:** grant your terminal *Screen Recording* and *Accessibility* permissions (System Settings → Privacy & Security), otherwise capture is black and input events are missing.

## 2. Use it

### Option A: the UI (recommended)

```bash
streamlit run app.py
```

1. **Capture**: click *Start recording*, switch to your task, and press **Ctrl+Shift+Q** when done (**Ctrl+Shift+P** pauses). Or upload an existing screen recording.
2. **Analyze**: one click. A progress bar shows each segment going to the local model.
3. **Review**: watch the video next to the steps, jump to any step's timestamp, read why steps were flagged, edit titles and instructions, mark each step **Correct** or **Wrong**, then save (rewrites `playbook.md` and `playbook.html`) or download the Markdown. Your Correct/Wrong labels are kept: they are the data for improving confidence scores later (`python -m playbook labels`).

Archived sessions show a 🔒 in the session list; **Restore session** decrypts one, **Archive session** packs one away now.

### Option B: the command line

```bash
python -m playbook setup-local              # one-time: choose + download a local model
python -m playbook run                      # record → analyze → playbook (Ctrl+Shift+Q to stop)
python -m playbook record                   # just record
python -m playbook import my_recording.mp4  # use an existing video (mp4/mov/mkv/webm)
python -m playbook analyze [session|latest] # (re)run the vision analysis
python -m playbook render  [session|latest] # rebuild playbook.md/.html from playbook.json (no API calls)
python -m playbook export  [session|latest] # agent-ready skill: SKILL.md + skill.json (see below)
python -m playbook list                     # 🔒 = archived
python -m playbook compact [session|--all|--idle-days N]  # compress + encrypt into .pbx archives
python -m playbook compact --bench latest   # measure compression on a copy (the session is untouched)
python -m playbook restore <session>        # decrypt + restore (analyze/render do this automatically)
python -m playbook migrate                  # move sessions from the old ./sessions folder (e.g. in OneDrive)
python -m playbook key --export             # back up the archive encryption key
python -m playbook check                    # is the model installed and reachable?
python -m playbook labels                   # export your Correct/Wrong reviews to labels.csv
python -m playbook decisions [session]      # log what was on screen at each pause and what you did next
python -m playbook induce [sessions...]     # fit a readable rule to pooled decisions; list what it can't explain
python -m playbook elicit [sessions...]     # answer questions about those; named facts become features, rule is refitted
python -m playbook replay [sessions...]     # fit on the earliest 70% of decisions, replay the rest (--model adds a local model)
python -m playbook export --judgment [...]  # agent skill that also says when to act
python -m playbook.evaluate                 # score the pipeline on 4 scripted scenarios (see Evaluation)
```

Sessions live in a per-user local folder, **not** the project folder (which may be inside OneDrive): `%LOCALAPPDATA%\WorkflowPlaybook\sessions\` on Windows, `~/Library/Application Support/WorkflowPlaybook/sessions/` on macOS, `~/.local/share/WorkflowPlaybook/sessions/` on Linux. Each session is a folder `<timestamp>/` while in use, or a single `<timestamp>.pbx` archive when not:

| File | What it is |
|---|---|
| `recording.mp4` | the screen video (H.264, plays in any browser) |
| `events.jsonl` | mouse clicks, drags, scrolls, typed text, shortcuts and window switches, with timestamps, the app/window they happened in, and (Windows) the UI element, e.g. `Button "New Email"` |
| `keyframes/` | screenshots taken right before / after each action and on visual changes |
| `ocr.json` | cached local OCR of the keyframe regions that matter |
| `manifest.json` | the keyframe ↔ timestamp ↔ event mapping |
| `analysis.json` | raw step candidates from the model, per-segment context, dropped steps |
| `playbook.json` / `playbook.md` | the final playbook (JSON for tools, Markdown for people) |
| `playbook.html` | self-contained viewer: the recording beside the steps; click any step to play from there |
| `skill/` | `SKILL.md` + `skill.json` for AI agents, written by `export` |

Open `playbook.html` in a browser for the best experience, or `playbook.md` in VS Code (Ctrl+Shift+V) or any Markdown viewer. Markdown timestamp links like `[00:02:13](recording.mp4#t=133)` seek only when the video is opened in a browser.

### Export for AI agents

A playbook is written for people. `python -m playbook export` (or **⬇ Download agent skill** in the Review tab) turns it into a skill an AI agent can follow: `SKILL.md` in the [Agent Skills](https://agentskills.io) format that Claude and other agent tools load directly, plus a tool-neutral `skill.json` for automation frameworks. It is written to `<session>/skill/`, and needs no model call.

- **Inputs become placeholders.** The values that change between runs (search terms, recipients, file names) appear as `{{city_name}}` in every step. When the model listed no inputs (common with small local models), what the user typed is used instead.
- **Data flows between steps.** A value typed after being read on screen (copied from a web page into a sheet, say) is exported as "the value read in step 3", not as a constant, because next time the page will show something else. This also stops a recorded typo being replayed. Small models don't always write a step for reading the value: in the [example](examples/city-population-lookup/skill/SKILL.md) it becomes an input instead, and the flagged step still says *Ask a human first*.
- **Uncertainty becomes a gate.** Every step that was flagged and not confirmed in review says **Ask a human first**, with the same reasons the viewer shows. Steps a reviewer marked wrong are left out.
- **Nothing private beyond the playbook text.** No screenshots, video or event log are included. With `--judgment` (see [below](#when-to-act-decisions-rules-and-the-expert-loop)) the skill also carries summaries of your decisions: the numbers that were on screen, session ids, the rules fitted to them, and your own words if you answered questions. Read it before sharing.

Review the playbook first: the skill can only be as good as the steps it is built from.

### Try it without recording

```bash
python -m playbook.evaluate research                    # scripted search → spreadsheet workflow (with a deliberate typo), analyzed locally

# Or import a video, which has no input events to work from:
python tests/make_sample_video.py sample_workflow.mp4
python -m playbook import sample_workflow.mp4
```

The first command reproduces the [example](examples/city-population-lookup/playbook.md) in `<sessions>/_eval/research/` after `setup-local` (model output varies a little between runs; expect several minutes or more on a laptop CPU).

<a id="when-to-act-decisions-rules-and-the-expert-loop"></a>

### When to act: decisions, rules and the expert loop

A playbook says *what* to do. Much expertise is *when*: looking at a chart for twenty seconds and leaving a run alone leaves no click. For that, the tool can also log **decision points**: every pause of 8 seconds or more (`playbook/frames.py`) together with the labelled numbers on screen at that moment (local OCR) and the action that followed, or `none` (`playbook/decisions.py`). Decisions from many sessions are pooled, with cross-session context such as "this value changed since the last check". `induce` fits a short, readable decision tree (`playbook/induce.py`) and lists the decisions it can't explain; `elicit` asks you about each of those, compared with the most similar decisions, and turns a condition you name into a feature (`playbook/elicit.py`); `replay` tests whether the rules reproduce your later decisions; `export --judgment` writes the rules, your reasons and an "ask a human first" boundary into the agent skill. Each decision, and each step of a playbook, is also classified by how observable it is (`playbook/knowledge.py`): the Markdown report gets a "What the recording could and could not explain" table, every step shows its class (`O1`–`O6`) and tacit score, the HTML viewer shows the counts, and the exported skill carries each step's class. A step counts as unobservable (`O6`) only on measured evidence (low calibrated confidence, or the model hesitating between targets), never because the model wrote a remark.

This is a research direction and is checked only on a synthetic benchmark (`python -m playbook.dashboard`), where the planted rule was recovered exactly; a first run of a small local model with the resulting skill did **not** follow it. Readouts must be text on screen (charts are not read), and a pause is only a rough proxy for attention. See [docs/ROADMAP.md](docs/ROADMAP.md) for results and limits, and [docs/evaluation-protocol.md](docs/evaluation-protocol.md) for the hypotheses, metrics and seeds fixed before the next round of runs.

## 3. How it works

1. **Capture** (`playbook/recorder.py`): `mss` grabs the screen at 5 fps into an H.264 video. `pynput` logs input. Raw keystrokes are grouped into *typed bursts* ("typed 'quarterly revenue'"), repeated keys collapse ("pressed down ×6"), clicks become single, double, right-click or drag, and scrolls merge into one event. On Windows every event also records the **app and window title** it happened in (e.g. `"Budget.xlsx - Excel" (EXCEL.EXE)`), and switching windows (Alt+Tab, taskbar, dialogs) becomes its own event. For each event the recorder saves a keyframe **just before** it and another **~0.8 s after** (once the UI has reacted). It also saves keyframes when the screen changes without input and has settled (page loads, command output), plus a slow heartbeat. Video time = wall-clock time, so event timestamps double as seek positions.
2. **Keyframes** (`playbook/keyframes.py`): change detection at two scales. A 160-px thumbnail catches big changes (page loads, app switches); a 640-px image catches small but meaningful ones (a typed value, a new line of terminal output) while ignoring blinking cursors and spinners. For imported videos it saves before/after frames around each scene change.
3. **Analysis** (`playbook/analyzer.py`, prompts in `playbook/prompts.py`): uses the `openai` client pointed at the local server's OpenAI-compatible endpoint on `127.0.0.1` (llama-server or Ollama) (or, if you opt in, Gemini's). Small local models read small text poorly, so more of the facts come from deterministic sources and the model mostly writes them up:
   - **UI Automation** (Windows, `playbook/uia.py`): the recorder asks the accessibility API what is under the pointer at the moment of each click, and which field was typed into and its final value (`typed "jon.doe@…" into Edit "To"`). Values of password-like fields are never recorded.
   - **Local OCR** (`playbook/ocr.py`, RapidOCR on ONNX Runtime): text near each click and text that newly appeared is added to the prompt, and fed to the consistency check.
   - **Zoomed crops**: a full-resolution 448 px crop around each click goes along with the downscaled screenshot.
   - **Structured output**: the JSON schema is passed as a grammar constraint, so small models can't return malformed JSON.
   - **Pass 1:** sends windows of 3–8 keyframes (10 for Gemini) with **numbered red rings drawn where each click happened** plus the event log (with app and window titles), and asks for JSON step candidates with `confidence`, `evidence` and `uncertainty_reason`, plus the key values visible on screen (emails, numbers, names, paths). The prompts list what makes a step repeatable in each kind of work: file paths and commands for coding, recipients and field values for email and forms, and so on.
   - **Pass 2:** consolidates all candidates into a playbook: it merges micro-actions, drops noise, works out the goal, prerequisites, inputs and open questions, and adds a `review_note` to any step that looks wrong even though the action is clear.
4. **Confidence calibration**: the model's self-reported score is adjusted by facts the model can't see:

   | Rule | Adjustment |
   |---|---|
   | No mouse/keyboard event backs up the step (or the video was imported) | −0.15 |
   | Model output needed a JSON repair retry | −0.10 |
   | Step was inferred across a >20 s gap between screenshots | −0.10 |
   | Step merged from several candidates | ≤ weakest candidate + 0.10 (a single-candidate step can never be raised) |

   A step **needs review** when either:
   - ⚠️ its calibrated confidence is below `CONFIDENCE_THRESHOLD` (0.70): *the system isn't sure what happened*; or
   - 🔎 it has a review note: *the system understood the action, but something looks off* (a typed value that differs from its source, a likely typo, an action that was undone, an unexplained choice).

   Review notes come from the model and from a **deterministic consistency check** (`playbook/consistency.py`, no API call). The check compares what was typed (from the keyboard log, which is exact) with values seen on screen anywhere in the recording, and flags near misses: swapped or changed digits (`315,613` vs `315,663`), or almost-identical emails, names, paths and commands (`jon.doe@` vs `john.doe@`). It catches copy mistakes that the model misses when the source and the typed copy are far apart in the recording. A number typed right after reading a similar one is held to a looser standard (up to half its digits changed, e.g. `3,163,843` for `3,863,148`), since that's a misread rather than a different value. Only local OCR text or a step where the model read a value counts as proof that a value was copied correctly. It also flags input the software rejected: when new on-screen text reads like an error and quotes or names something just typed (`The term 'pyhton' is not recognized`, `gti: command not found`, `'jon.doe@' is not a valid email`), that entry gets a review note, in any app.

   On local models, a step's confidence also drops below the threshold when the model **hesitated** (`playbook/token_certainty.py`). A small model reports about 0.9 for nearly everything, but while writing it weighs each token against the alternatives. If a token in the step's target or value was nearly tied with a rival that means something different (filler words, punctuation and capitalization don't count), the step is flagged and the reason names both, e.g. `"line" over "code"`. This adds no model calls and only a score per step to the cache. It shows hesitation, not truth: a confident misread or a person's typo won't show up, which is what the consistency check is for.

   Flagged steps get a **NEEDS REVIEW** block with the reasons, the evidence (with timestamps), the confidence adjustments, and a "Verified by a human" checkbox.
5. **Generation** (`playbook/generator.py`): Markdown and a self-contained HTML viewer, with a review summary, prerequisites, inputs, steps with timestamps and screenshots, and open questions.
6. **Archiving** (`playbook/archive.py`, `playbook/tilecodec.py`): see [Archives](#archives).

## Archives

Screen recordings are mostly static: the same window chrome, a small region that changes. The `.pbx` format uses that:

| Part | How it's stored | Exact? |
|---|---|---|
| keyframes (the analysis input) | **tile-delta codec**: 16×16 tiles aligned with JPEG blocks; unchanged tiles cost nothing, tiles seen before (switching back to a window) are references, new tiles go into a lossless WebP canvas. A frame is never stored larger than its original JPEG. | **bit-exact pixels**, SHA-256 checked on restore, so re-analysis gives identical requests (cache hits) |
| video (for people watching) | re-encoded to AV1: Intel/NVIDIA/AMD hardware encoder if present, else software AV1, else HEVC. Every frame is kept, so `#t=` links still land right; the duration is checked. `ARCHIVE_VIDEO=original` keeps it as is, `drop` leaves it out. | lossy but text stays sharp (42–47 dB PSNR in testing) |
| JSON / Markdown / HTML | zstd level 19 | exact |

Everything is encrypted with **AES-256-GCM** in 4 MB authenticated chunks bound to their position, so a wrong key, a flipped bit, reordering or truncation all fail loudly. The key is a random 256-bit key in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service), with a per-file key derived from each archive's salt. Without a keyring, set `ARCHIVE_PASSPHRASE` (stretched with scrypt). **If you lose the key, the archives can't be opened**: run `python -m playbook key --export` and keep the backup somewhere safe (`key --import` restores it on another machine).

By default a session is archived automatically once it hasn't been touched for 2 days (`AUTO_COMPACT=idle:2`, checked when the CLI or app starts). `analyze`, `render` and the UI restore archived sessions on demand. Packing a restored session away again only rewrites what changed: the video and keyframes are copied from the old archive.

Measured on a real 3-minute session (70 keyframes):

| | Before | After |
|---|---|---|
| keyframes | 8.47 MB | 2.27 MB (lossless) |
| video | 9.20 MB | 2.18 MB (AV1, Intel Quick Sync) |
| metadata | 0.14 MB | 0.02 MB |
| **total** | **17.8 MB** | **4.5 MB (4.0× smaller)**, 26 s to pack, 4.7 s to restore |

## 4. Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `PROVIDER` | `local` | `local` (a model on this machine) or `gemini` |
| `ALLOW_CLOUD` | `false` | must be `true` for `PROVIDER=gemini`; without it, requests to anything but this machine or the private network are refused |
| `LOCAL_MODEL` | `auto` | `auto` uses what `setup-local` configured (or picks by RAM/VRAM), or set an Ollama tag such as `qwen3-vl:2b-instruct` |
| `LOCAL_MAX_TOKENS` | `3000` | cap on each local reply, so a rambling model can't hold a request for many minutes |
| `LOCAL_TIMEOUT_S` | `1800` | seconds to wait for one local request (CPU inference can take several minutes) |
| `LOCAL_RUNTIME` | `auto` | local server `setup-local` installs: `llama` (llama-server, faster on a CPU, started only while analyzing), `ollama`, or `auto` (llama in low-power mode on Windows) |
| `LLAMA_SERVER` | | path to your own `llama-server` binary (default: the build `setup-local` downloads) |
| `LLAMA_PORT` | `18080` | port llama-server listens on (always 127.0.0.1); change it if another program uses it |
| `IMAGE_MAX_TOKENS` | `448` | llama runtime: tokens per screenshot; 448 is the native size of an 896 px image |
| `LOCAL_BASE_URL` | `http://127.0.0.1:11434/v1` | must be on this machine or the private network |
| `LOW_POWER` | `false` | lighter load for slow machines: smallest model, capped threads, low priority, no zoom crops, hardware-only video encoding |
| `MAX_THREADS` | `0` | CPU threads for the model, OCR and encoders (0 = all; half, at most 6, in low-power mode) |
| `USE_OCR` / `SEND_CROPS` | `true` | local OCR and zoomed click crops (accuracy aids for small models) |
| `CAPTURE_UI_ELEMENTS` | `true` | record the clicked / typed-into UI element (Windows UI Automation) |
| `AUTO_COMPACT` | `idle:2` | `idle:<days>`, `after_analysis`, or `off` |
| `ARCHIVE_VIDEO` | `compress` | `compress`, `original`, or `drop` |
| `ARCHIVE_PASSPHRASE` | | only if there is no OS keyring |
| `SESSIONS_DIR` / `CACHE_DIR` | per-user local app-data folder | refused inside OneDrive/Dropbox/iCloud/Google Drive unless `ALLOW_SYNCED_DIR=true` |
| `GEMINI_API_KEY` | | only for `PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.5-flash` | any vision model your key can use. Run `python -m playbook check` to see which models have free quota for your key right now. |
| `GEMINI_FALLBACK_MODELS` | 3.5-flash, 3.6-flash, 3-flash-preview, then Flash-Lite models | tried in order when the model is unavailable or its free quota is used up; the switch is shown live and noted in the playbook |
| `RPM_LIMIT` | `5` | free-tier limits differ by project (check AI Studio). Calls are throttled to this. |
| `CONFIDENCE_THRESHOLD` | `0.70` | review flag cutoff |
| `TOKEN_CERTAINTY_MIN` | `0.30` | local models: flag a step when a token in its target or value is this close to a rival (0 = off). Changing it needs no model call |
| `WINDOW_SIZE` | `0` (auto) | keyframes per vision call; auto = 3–8 by local model size, 10 for Gemini |
| `CAPTURE_FPS` | `5` | recording frame rate |
| `HEARTBEAT_S` | `10` | idle keyframe interval |
| `CHANGE_THRESHOLD` | `0.02` | fraction of changed pixels that counts as a visual change |
| `MASK_TYPED_TEXT` | `false` | replace typed text with • (privacy) |
| `CAPTURE_WINDOW_TITLES` | `true` | record the focused app and window title with each event (Windows) |
| `MONITOR` | `1` | which monitor to record (1 = primary) |

**Gemini only — rate limits:** if Google says the quota for a model is used up (or is 0 on the free tier), the analyzer immediately switches to the next fallback model instead of retrying, and remembers that until the quota resets (`model_status.json` in the cache folder) so later runs don't waste time on it. Per-minute limits are retried after the wait Google suggests, with a live countdown in the progress bar. `python -m playbook check` re-tests every model and clears remembered blocks for models that work again.

**Gemini only — API usage:** about `keyframes / 9 + 1` requests per recording; a 3-minute task with ~70 keyframes is about 9 requests. Free-tier daily quotas are per model and can be as small as ~20 requests/day, which is why the fallback chain exists. Every response (local or cloud) is cached, so re-running `analyze` after a failure or quota stop resumes for free.

## 5. Privacy and security

**What the software guarantees:**
- **Nothing leaves the machine.** Analysis, OCR and UI Automation run locally. Before any request, the endpoint is checked: anything that isn't loopback or a private-network address is refused unless you set `ALLOW_CLOUD=true`.
- **No cloud-synced storage.** Sessions and the response cache live in a local app-data folder, and recording into a OneDrive, Dropbox, iCloud or Google Drive folder is refused (`ALLOW_SYNCED_DIR=true` overrides). `python -m playbook migrate` moves sessions out of the old `./sessions` folder.
- **Encrypted at rest when idle.** See [Archives](#archives).
- **The UI is local-only.** `.streamlit/config.toml` binds Streamlit to `127.0.0.1` and turns off its usage statistics (on by default in Streamlit).

**What's still up to you:**
- Turn on full-disk encryption (BitLocker / FileVault / LUKS): sessions that are in use are ordinary files.
- If you used the project folder in OneDrive before, OneDrive keeps deleted files in its recycle bin and version history; empty those after `migrate`.
- Back up the archive key (`python -m playbook key --export`).

**If you opt in to Gemini** (`PROVIDER=gemini`, `ALLOW_CLOUD=true`), screenshots are **sent to Google**. On the free tier, Google may use submitted data to improve its products.

In every mode, don't record passwords, personal data or confidential documents you don't need to. Use **Ctrl+Shift+P** to pause (paused time is blanked in the video and no keyframes or events are captured), and `MASK_TYPED_TEXT=true` to keep typed text and field values out of the logs and prompts. Window titles and UI element names (which can contain document names or email subjects) are recorded too; set `CAPTURE_WINDOW_TITLES=false` / `CAPTURE_UI_ELEMENTS=false` to turn that off.

## 6. Tips for good playbooks

- Work at a normal, deliberate pace. Pause a beat after important actions so the "after" frame shows the result.
- Keep the relevant window maximized; tiny text is the #1 cause of low confidence.
- Imported videos work, but live capture is noticeably better because clicks and typed text are known exactly.
- One task per recording; 1–10 minutes is the sweet spot.

## 7. Evaluation

`python -m playbook.evaluate` builds four scripted recordings of different kinds of work with fictional data (`playbook/scenarios.py`). They run through the real recorder logic, so they have genuine input events, window titles and keyframes. Each is then analyzed and scored against known answers:

| Scenario | What happens | Planted mistake |
|---|---|---|
| `coding` | run a script in VS Code's terminal, read a NameError, fix the variable, save, re-run | the first command is typed `pyhton app.py` |
| `email` | read a request in Outlook, compose a reply with an attachment, send | recipient typed `jon.doe@…`, but the sender is `john.doe@…` |
| `files` | create a folder, rename a file (F2), drag it into the folder, turn on a setting | none (measures false alarms) |
| `research` | search the web, open a result, Alt+Tab to Excel, enter the number | `186,412` typed, but the page says `168,412` |

It prints, per scenario, how many expected steps were found, whether the mistake was flagged, and how many correct steps were flagged anyway (false alarms). Results so far are in [NOTES.md](NOTES.md#evaluation-results). Responses are cached, so re-runs are free; `--no-api` only builds the recordings.

## 8. Development

```bash
pytest            # no model or API key needed: the vision client is mocked; archives use throwaway keys
```

The same tests run on GitHub Actions (Ubuntu and Windows) for every push and pull request.

See [NOTES.md](NOTES.md) for design rationale, limitations and the roadmap.

## 9. Related work and references

This project is an academic effort on capturing **tacit knowledge** from observed computer work. The full BibTeX is in [`docs/references.bib`](docs/references.bib); each entry records how far it has been checked. So far the arXiv abstract pages were read, **not** the full texts, so the notes below say only what the abstracts support. Entries marked *TODO verify* still need their author lists, venues or page numbers checked against the publisher.

**Recordings to written procedures.** Wornow et al. (2024) introduce WONDERBREAD, a benchmark of business-process documentation, knowledge-transfer and improvement tasks. They report that models document workflows with good step recall but do poorly at judging whether a workflow was completed correctly. Our evaluation (Section 7) borrows that split between listing steps and judging them. Xu et al. (2024) apply in-context ensembling of pseudo labels to low-level workflow understanding in video-language models.

**Recordings to reusable agent skills.** Huang et al. (2026, Work2Skill) induce skills from synchronized screen, input and accessibility-tree demonstrations, capturing workflow rules, step dependencies and completion checks. Our recorder collects the same three signals and our skill export (Section 2) carries placeholders and human gates. Jiang et al. (2026) induce task models, a hierarchical objective model plus a procedure model, from computer-use traces, separating interleaved tasks. Zhang et al. (2026, ShowUI-Aloha) and Oyamada et al. (2026, cotomi Act) also learn from human recordings; the latter has not been read yet.

**Agent memory.** Wang et al. (2025, Agent Workflow Memory) induce reusable workflows from experience and supply them to later tasks. Iyamu (2026, Activity Frames) compiles captured screen activity into typed, evidence-linked episodes without a model; like that work, our consistency check (Section 3) is deterministic.

**Web-scale video and long-horizon data.** Lu et al. (2025, VideoAgentTrek), Song et al. (2025, Watch and Learn) and Baker et al. (2022, VPT) learn to act from unlabeled video. Hayati et al. (2026, Kolab) and Meng et al. (2026, ClawMark) provide long-horizon, naturalistic benchmarks. These train models and are outside this project's scope; they inform the evaluation design.

**Tacit knowledge.** Polanyi (1966) and Nonaka and Takeuchi (1995) give the framing: expertise that people cannot fully state, and its conversion into explicit knowledge. Zuin et al. (2025) and Brennig (2025) use LLM-driven interviews to draw out tacit knowledge and add it to organizational records. Ng and Russell (2000) frame recovering the rule behind observed behaviour as inverse reinforcement learning.

**What this repository adds, and what it does not yet do.** The current code covers single-session recording, flagged steps and agent-ready export. The research direction (see [NOTES.md](NOTES.md) and the plan): classifying what kind of knowledge each item is (observable single-step, multi-step, hidden decision, non-action, cross-session, unobservable), logging decision points including non-actions, pooling them across sessions, fitting an interpretable rule, and asking the expert about the cases where rule and behaviour disagree. Frames, the decision log, rule fitting and the classes are implemented and checked on a synthetic benchmark (`python -m playbook decisions`, `python -m playbook induce`, `python -m playbook.dashboard`; see [docs/ROADMAP.md](docs/ROADMAP.md)). The ask-the-expert loop and the replay test exist but have only been tried with simulated experts and a 2B model. Persistent cross-session memory, task models and any test on real experts are not done. The techniques above are starting points, adapted rather than replicated.

## License

[MIT](LICENSE)
