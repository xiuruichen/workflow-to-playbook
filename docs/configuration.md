# Configuration

Every setting has a default; `.env` (copy `.env.example`) is optional. Environment variables override it.

## Where analysis runs

| Variable | Default | Notes |
|---|---|---|
| `PROVIDER` | `local` | `local` (a model on this machine) or `gemini` |
| `ALLOW_CLOUD` | `false` | must be `true` for `PROVIDER=gemini`; without it, requests to anything but this machine or the private network are refused |
| `LOCAL_MODEL` | `auto` | `auto` uses what `setup-local` configured (or picks by RAM/VRAM), or set an Ollama tag such as `qwen3-vl:2b-instruct` |
| `LOCAL_RUNTIME` | `auto` | `llama` (llama-server, faster on a CPU, started only while analysing), `ollama`, or `auto` (llama in low-power mode on Windows) |
| `LLAMA_SERVER` | | path to your own `llama-server` binary (default: the build `setup-local` downloads) |
| `LLAMA_PORT` | `18080` | port llama-server listens on (always 127.0.0.1) |
| `IMAGE_MAX_TOKENS` | `448` | llama runtime: tokens per screenshot; 448 is the native size of an 896 px image |
| `LOCAL_BASE_URL` | `http://127.0.0.1:11434/v1` | must be on this machine or the private network |
| `LOCAL_MAX_TOKENS` | `3000` | cap on each local reply, so a rambling model cannot hold a request for many minutes |
| `LOCAL_TIMEOUT_S` | `1800` | seconds to wait for one local request (CPU inference can take several minutes) |

## Load and capture

| Variable | Default | Notes |
|---|---|---|
| `LOW_POWER` | `false` | smallest model, capped threads, low priority, no zoom crops, hardware-only video encoding |
| `MAX_THREADS` | `0` | CPU threads for the model, OCR and encoders (0 = all; half, at most 6, in low-power mode) |
| `USE_OCR` / `SEND_CROPS` | `true` | local OCR and zoomed click crops (accuracy aids for small models) |
| `CAPTURE_UI_ELEMENTS` | `true` | record the clicked or typed-into UI element (Windows UI Automation) |
| `CAPTURE_WINDOW_TITLES` | `true` | record the focused app and window title with each event (Windows) |
| `CAPTURE_FPS` | `5` | recording frame rate |
| `HEARTBEAT_S` | `10` | idle keyframe interval |
| `CHANGE_THRESHOLD` | `0.02` | fraction of changed pixels that counts as a visual change |
| `MONITOR` | `1` | which monitor to record (1 = primary) |
| `MASK_TYPED_TEXT` | `false` | replace typed text with • (privacy) |

## Review

| Variable | Default | Notes |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `0.70` | review flag cutoff |
| `TOKEN_CERTAINTY_MIN` | `0.30` | local models: flag a step when a token in its target or value is this close to a rival (0 = off). Changing it needs no model call |
| `WINDOW_SIZE` | `0` (auto) | keyframes per vision call; auto = 3–8 by local model size, 10 for Gemini |

Calibration constants are at the top of `analyzer.py` (`PENALTY_*`, `MERGE_LEEWAY`). Lower `CHANGE_THRESHOLD` for subtle UIs such as spreadsheets and raise it if video or animations create noise; `settle_s` in `config.py` can be raised for slow web apps.

## Storage and archives

| Variable | Default | Notes |
|---|---|---|
| `SESSIONS_DIR` / `CACHE_DIR` | per-user local app-data folder | refused inside OneDrive, Dropbox, iCloud or Google Drive unless `ALLOW_SYNCED_DIR=true` |
| `AUTO_COMPACT` | `idle:2` | `idle:<days>`, `after_analysis`, or `off` |
| `ARCHIVE_VIDEO` | `compress` | `compress`, `original`, or `drop` |
| `ARCHIVE_PASSPHRASE` | | only if there is no OS keyring |

## Gemini (opt-in)

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | | only for `PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.5-flash` | any vision model your key can use; `python -m playbook check` shows which have free quota right now |
| `GEMINI_FALLBACK_MODELS` | 3.5-flash, 3.6-flash, 3-flash-preview, then Flash-Lite models | tried in order when a model is unavailable or its free quota is used up; the switch is shown live and noted in the playbook |
| `RPM_LIMIT` | `5` | free-tier limits differ by project; calls are throttled to this |

**Rate limits.** If Google says a model's quota is used up (or is 0 on the free tier), the analyser switches to the next fallback immediately and remembers that until the quota resets (`model_status.json` in the cache folder). Per-minute limits are retried after the wait Google suggests, with a live countdown. `python -m playbook check` re-tests every model and clears remembered blocks for models that work again.

**Usage.** About `keyframes / 9 + 1` requests per recording; a 3-minute task with ~70 keyframes is about 9. Free-tier daily quotas are per model and can be as small as ~20 requests a day, which is why the fallback chain exists. Every response, local or cloud, is cached, so re-running `analyze` after a failure or a quota stop resumes for free.
