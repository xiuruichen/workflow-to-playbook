# Getting started

Python 3.10+ on Windows, macOS or Linux. Everything runs on your machine; nothing is uploaded unless you opt in to a cloud model ([privacy-and-archives.md](privacy-and-archives.md)).

## Install

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env      # macOS/Linux: cp .env.example .env   (optional: every setting has a default)
```

> **macOS:** grant your terminal *Screen Recording* and *Accessibility* permissions (System Settings → Privacy & Security), otherwise capture is black and input events are missing.

The decision tools (`decisions`, `induce`, `elicit`, `replay`, `pilot`) need only the recording and the local OCR, which `pip install` brings. **The playbook tools also need a local vision model**, below.

## Choose a local vision model

Install **[Ollama](https://ollama.com/download)** (Windows: `winget install Ollama.Ollama`; macOS: the app or `brew install ollama`; Linux: the script on that page), start it, and run:

```bash
python -m playbook setup-local
```

This checks RAM and GPU, picks the largest [Qwen3-VL](https://ollama.com/library/qwen3-vl) that runs comfortably, checks disk space, asks before downloading, and times a test request:

| Your computer | Model | Download | Screenshots per request |
|---|---|---|---|
| < 3.5 GB RAM free | `qwen3-vl:2b-instruct` | ~1.9 GB | 3, at 896 px |
| 8–15 GB RAM, no big GPU (most laptops) | `qwen3-vl:4b-instruct` | ~3.3 GB | 4, at 1024 px |
| ≥ 16 GB RAM, or a GPU with ≥ 8 GB | `qwen3-vl:8b-instruct` | ~6.1 GB | 6, at 1280 px |
| GPU with ≥ 24 GB, or Apple silicon with ≥ 36 GB | `qwen3-vl:32b-instruct` | ~21 GB | 8, at 1280 px |

On a laptop CPU expect minutes per request, not seconds. Responses are cached, so you pay once per recording. No GPU, Tesseract or separate ffmpeg install is needed: OCR runs on ONNX Runtime and `imageio-ffmpeg` bundles the video encoders.

### Slow or easily overloaded computer: low-power mode

Put `LOW_POWER=true` in `.env` before running `setup-local` (on Windows you can skip Ollama entirely). It uses the smallest model, limits it, OCR and video encoding to half the CPU threads (at most 6; `MAX_THREADS` changes that), runs at below-normal priority so the desktop stays responsive, skips the zoomed click crops (OCR still reads the text near each click), and archives video only with a hardware encoder.

On Windows, low-power mode uses llama.cpp's `llama-server` instead of Ollama (`LOCAL_RUNTIME=llama`): `setup-local` downloads a pinned build and Qwen3-VL 2B Instruct (~1.5 GB, SHA-256 checked), and the server runs only while an analysis does, so it holds no memory in between. It is about twice as fast as Ollama on a CPU: screenshots stay at native size (~450 tokens instead of ~1,040) and the system prompt is reused between requests. On an 8 GB laptop a 30-second recording took about 14 minutes and at most ~2 GB of RAM. While it runs, the server accepts only requests carrying a per-install key, so web pages open in your browser cannot use it. Elsewhere, set `LLAMA_SERVER` to your own llama-server build, or keep Ollama.

### Air-gapped machines

The only network access is the one-time model download. For the llama runtime, copy the `llama` folder from `%LOCALAPPDATA%\WorkflowPlaybook\` on a connected machine to the same place, then run `python -m playbook setup-local --yes`: files that are already present and pass their SHA-256 check are not downloaded again. For Ollama, copy its models folder (`~/.ollama/models`, or `OLLAMA_MODELS`) and keep Ollama bound to `127.0.0.1` (its default; do not set `OLLAMA_HOST=0.0.0.0`).

## Record and analyse

### The UI (recommended)

```bash
streamlit run app.py
```

1. **Capture.** Click *Start recording*, switch to your task, press **Ctrl+Shift+Q** when done (**Ctrl+Shift+P** pauses). Or upload an existing screen recording.
2. **Analyse.** One click; a progress bar shows each segment going to the local model.
3. **Review.** Watch the video beside the steps, jump to any step's timestamp, read why steps were flagged, edit, mark each step **Correct** or **Wrong**, then save or download the Markdown. The labels are kept as data for improving confidence scores (`python -m playbook labels`).

### The command line

```bash
python -m playbook setup-local              # one-time: choose and download a local model
python -m playbook run                      # record → analyse → playbook (Ctrl+Shift+Q to stop)
python -m playbook record                   # just record
python -m playbook import my_recording.mp4  # an existing video (mp4/mov/mkv/webm); no input events
python -m playbook analyze [session|latest] # (re)run the vision analysis
python -m playbook render  [session|latest] # rebuild playbook.md/.html from playbook.json (no model calls)
python -m playbook export  [session|latest] # agent skill: SKILL.md + skill.json   (--judgment adds the decision rules)
python -m playbook list                     # 🔒 = archived
python -m playbook check                    # is the model installed and reachable?
python -m playbook labels                   # export your Correct/Wrong reviews to labels.csv
```

Archive commands (`compact`, `restore`, `migrate`, `key`) are in [privacy-and-archives.md](privacy-and-archives.md); the decision commands are in [tacit-knowledge.md](tacit-knowledge.md).

### Where sessions live

In a per-user local folder, **not** the project folder (which may be inside OneDrive): `%LOCALAPPDATA%\WorkflowPlaybook\sessions\` on Windows, `~/Library/Application Support/WorkflowPlaybook/sessions/` on macOS, `~/.local/share/WorkflowPlaybook/sessions/` on Linux. Each session is a folder `<timestamp>/`, or one encrypted `<timestamp>.pbx` when idle.

| File | What it is |
|---|---|
| `recording.mp4` | the screen video (H.264, plays in any browser) |
| `events.jsonl` | clicks, drags, scrolls, typed text, shortcuts and window switches, with timestamps, the app and window, and (Windows) the UI element, e.g. `Button "New Email"` |
| `keyframes/` | screenshots just before and after each action, and on visual changes |
| `ocr.json` | cached local OCR of the keyframe regions that matter |
| `manifest.json` | the keyframe ↔ timestamp ↔ event mapping |
| `analysis.json` | raw step candidates from the model, per-segment context, dropped steps |
| `playbook.json` / `.md` / `.html` | the playbook: JSON for tools, Markdown for people, a self-contained viewer where clicking a step plays the video from there |
| `decisions.jsonl` | the decision log (see [tacit-knowledge.md](tacit-knowledge.md)) |
| `skill/` | `SKILL.md` + `skill.json` for AI agents |

Open `playbook.html` in a browser for the best experience, or `playbook.md` in VS Code (Ctrl+Shift+V). Markdown timestamp links like `[00:02:13](recording.mp4#t=133)` seek only when the video is opened in a browser.

## Try it without recording

```bash
python -m playbook.evaluate research        # a scripted search → spreadsheet task with a planted typo, analysed locally
python tests/make_sample_video.py sample_workflow.mp4 && python -m playbook import sample_workflow.mp4
```

The first reproduces the [example playbook](../examples/city-population-lookup/playbook.md) (model output varies a little; expect several minutes on a laptop CPU). For the decision tools, `python -m playbook.dashboard --domain triage --visits 40 --seed 1` runs a scripted benchmark through the real recorder and pipeline.

## Tips for good recordings

- Work at a normal, deliberate pace. Pause a beat after important actions so the "after" frame shows the result.
- Keep the relevant window maximised; tiny text is the main cause of low confidence.
- Live capture beats imported video, because clicks and typed text are known exactly.
- One task per recording, 1–10 minutes. For the decision tools, see the note on long recordings of many checks in [tacit-knowledge.md](tacit-knowledge.md).
- Do not record passwords or confidential documents you don't need to; pause with Ctrl+Shift+P, and use `MASK_TYPED_TEXT=true` to keep typed text out of the logs.
