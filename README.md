# Workflow → Playbook (prototype)

Record someone doing a task on their computer, then automatically turn the recording into a **step-by-step Markdown playbook**:

- every step links back to a **timestamp in the recording**,
- before/after **screenshots** for each step,
- a **confidence score (0–1)** per step, and anything below **0.70 is flagged for human review** with the reason and the evidence the model used,
- the **inputs** that would change next time (search terms, file names, values), and **open questions** the system couldn't answer.

Inspired by [Screenpipe](https://screenpipe.com/) (continuous screen capture) and [GodHands](https://godhands.ai/) (recording → SOPs). The goal is to make **tacit knowledge** (how an expert actually does something) explicit, reviewable, and reusable, as a building block for digital twins of work.

```
 screen + mouse/keyboard ──► keyframes (before/after each action) ──► Gemini vision (pass 1: actions per segment)
                                                                       │
              playbook.md ◄── generator ◄── calibrated confidence ◄── Gemini (pass 2: merge into a coherent playbook)
```

---

## 1. Setup (Windows, macOS or Linux; Python 3.10+)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env      # macOS/Linux: cp .env.example .env
```

Get a **free Gemini API key** at <https://aistudio.google.com/apikey> and paste it into `.env`:

```
GEMINI_API_KEY=your-key-here
```

No ffmpeg, Tesseract, or GPU install is needed (`imageio-ffmpeg` bundles an encoder; Gemini reads on-screen text itself).

> **macOS:** grant your terminal *Screen Recording* and *Accessibility* permissions (System Settings → Privacy & Security), otherwise capture is black and input events are missing.

## 2. Use it

### Option A: the UI (recommended)

```bash
streamlit run app.py
```

1. **Capture**: click *Start recording*, switch to your task, and press **Ctrl+Shift+Q** when done (**Ctrl+Shift+P** pauses). Or upload an existing screen recording.
2. **Analyze**: one click. A progress bar shows each segment going to Gemini.
3. **Review**: watch the video next to the steps, jump to any step's timestamp, read why steps were flagged, edit titles and instructions, tick *Verified*, then save or download `playbook.md`.

### Option B: the command line

```bash
python -m playbook run                      # record → analyze → playbook (Ctrl+Shift+Q to stop)
python -m playbook record                   # just record
python -m playbook import my_recording.mp4  # use an existing video (mp4/mov/mkv/webm)
python -m playbook analyze [session|latest] # (re)run the vision analysis
python -m playbook render  [session|latest] # rebuild playbook.md from playbook.json (no API calls)
python -m playbook list
python -m playbook check                    # test your key: which models work right now?
```

Each session lives in `sessions/<timestamp>/`:

| File | What it is |
|---|---|
| `recording.mp4` | the screen video (H.264, plays in any browser) |
| `events.jsonl` | mouse clicks, drags, scrolls, typed text and shortcuts, with timestamps |
| `keyframes/` | screenshots taken right before / after each action and on visual changes |
| `manifest.json` | the keyframe ↔ timestamp ↔ event mapping |
| `analysis.json` | raw step candidates from the model, per-segment context, dropped steps |
| `playbook.json` / `playbook.md` | the final playbook (JSON for tools, Markdown for people) |

Open `playbook.md` in VS Code (Ctrl+Shift+V) or any Markdown viewer. Timestamp links like `[00:02:13](recording.mp4#t=133)` open the video at that moment in a browser.

### Try it without recording

```bash
python tests/make_sample_video.py sample_workflow.mp4   # synthetic search → copy-into-spreadsheet workflow
python -m playbook import sample_workflow.mp4
```

## 3. How it works

1. **Capture** (`playbook/recorder.py`): `mss` grabs the screen at 5 fps into an H.264 video. `pynput` logs input. Raw keystrokes are grouped into *typed bursts* ("typed 'quarterly revenue'"), clicks into single, double, right-click or drag, and scrolls into one event. For each event the recorder saves a keyframe **just before** it and another **~0.8 s after** (once the UI has reacted). It also saves keyframes when the screen changes significantly without input (page loads) and a slow heartbeat. Video time = wall-clock time, so event timestamps double as seek positions.
2. **Keyframes** (`playbook/keyframes.py`): cheap pixel-diff change detection on 160-px thumbnails. For imported videos it saves before/after frames around each scene change.
3. **Analysis** (`playbook/analyzer.py`, prompts in `playbook/prompts.py`): uses the `openai` client pointed at Gemini's OpenAI-compatible endpoint.
   - **Pass 1:** sends windows of ~6 keyframes with **numbered red rings drawn where each click happened** plus the event log, and asks for JSON step candidates with `confidence`, `evidence` and `uncertainty_reason`.
   - **Pass 2:** consolidates all candidates into a playbook: it merges micro-actions, drops noise, and works out the goal, prerequisites, inputs and open questions.
4. **Confidence calibration**: the model's self-reported score is adjusted by facts the model can't see:

   | Rule | Adjustment |
   |---|---|
   | No mouse/keyboard event backs up the step (or the video was imported) | −0.15 |
   | Model output needed a JSON repair retry | −0.10 |
   | Step was inferred across a >20 s gap between screenshots | −0.10 |
   | Step merged from several candidates | ≤ weakest candidate + 0.10 (a single-candidate step can never be raised) |

   Steps below `CONFIDENCE_THRESHOLD` (0.70) get a **⚠️ NEEDS REVIEW** block with the reason, evidence, adjustments, and a checkbox.
5. **Generation** (`playbook/generator.py`): Markdown with a review summary, prerequisites, inputs table, steps with timestamps and screenshots, and open questions.

## 4. Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | | required for analysis |
| `GEMINI_MODEL` | `gemini-3.5-flash` | any vision model your key can use. Run `python -m playbook check` to see which models have free quota for your key right now. |
| `GEMINI_FALLBACK_MODELS` | 3.5-flash, 3.6-flash, 3-flash-preview, then Flash-Lite models | tried in order when the model is unavailable or its free quota is used up; the switch is shown live and noted in the playbook |
| `RPM_LIMIT` | `5` | free-tier limits differ by project (check AI Studio). Calls are throttled to this. |
| `CONFIDENCE_THRESHOLD` | `0.70` | review flag cutoff |
| `WINDOW_SIZE` | `10` | keyframes per vision call (higher = fewer calls against the small free daily quota; lower = more careful per-frame analysis) |
| `CAPTURE_FPS` | `5` | recording frame rate |
| `HEARTBEAT_S` | `10` | idle keyframe interval |
| `CHANGE_THRESHOLD` | `0.02` | fraction of changed pixels that counts as a visual change |
| `MASK_TYPED_TEXT` | `false` | replace typed text with • (privacy) |
| `MONITOR` | `1` | which monitor to record (1 = primary) |
| `SESSIONS_DIR` | `./sessions` | move this outside OneDrive/Dropbox if large videos syncing is a problem |

**Rate limits:** if Google says the quota for a model is used up (or is 0 on the free tier), the analyzer immediately switches to the next fallback model instead of retrying. Per-minute limits are retried after the wait Google suggests, with a live countdown in the progress bar.

**API usage:** about `keyframes / 9 + 1` requests per recording; a 3-minute task with ~70 keyframes is about 9 requests. Free-tier daily quotas are per model and can be as small as ~20 requests/day, which is why the fallback chain exists. Every response is cached in `.cache/`, so re-running `analyze` after a failure or quota stop resumes for free.

## 5. Privacy

Screenshots of your screen are **sent to Google** for analysis. On the free tier, Google may use submitted data to improve its products. Don't record passwords, personal data, or confidential documents. Use **Ctrl+Shift+P** to pause (paused time is blanked in the video and no keyframes or events are captured), and `MASK_TYPED_TEXT=true` to keep typed text out of the logs and prompts.

## 6. Tips for good playbooks

- Work at a normal, deliberate pace. Pause a beat after important actions so the "after" frame shows the result.
- Keep the relevant window maximized; tiny text is the #1 cause of low confidence.
- Imported videos work, but live capture is noticeably better because clicks and typed text are known exactly.
- One task per recording; 1–10 minutes is the sweet spot.

## 7. Development

```bash
pytest            # no API key needed: the vision client is mocked
```

See [NOTES.md](NOTES.md) for design rationale, limitations and the roadmap.
