# Privacy, security and archives

## What the software guarantees

- **Nothing leaves the machine.** Analysis, OCR and UI Automation run locally. Before any request the endpoint is checked: anything that is not loopback or a private-network address is refused unless `ALLOW_CLOUD=true`. A network watcher logging every connection by Python and Ollama during a local run recorded none leaving the machine.
- **No cloud-synced storage.** Sessions and the response cache live in a local app-data folder, and recording into a OneDrive, Dropbox, iCloud or Google Drive folder is refused (`ALLOW_SYNCED_DIR=true` overrides). `python -m playbook migrate` moves sessions out of the old `./sessions` folder.
- **Encrypted at rest when idle** (below).
- **The UI is local-only.** `.streamlit/config.toml` binds Streamlit to `127.0.0.1` and turns off its usage statistics.
- **The local model server is closed to web pages.** The llama runtime accepts only requests that carry a per-install key, so pages open in your browser cannot use it or read its replies.

## What is still up to you

- Turn on full-disk encryption (BitLocker, FileVault, LUKS): sessions that are in use are ordinary files.
- If the project folder used to be in OneDrive, OneDrive keeps deleted files in its recycle bin and version history; empty those after `migrate`.
- Back up the archive key (`python -m playbook key --export`).
- **If you opt in to Gemini** (`PROVIDER=gemini`, `ALLOW_CLOUD=true`), screenshots are sent to Google, and on the free tier Google may use submitted data to improve its products.
- In every mode, do not record passwords, personal data or confidential documents you do not need to. **Ctrl+Shift+P** pauses (paused time is blanked in the video and no keyframes or events are captured). `MASK_TYPED_TEXT=true` keeps typed text and field values out of the logs and prompts. Window titles and UI element names (which can contain document names or email subjects) are recorded too; `CAPTURE_WINDOW_TITLES=false` and `CAPTURE_UI_ELEMENTS=false` turn that off.
- The decision log stores the numbers and words that were on screen at each pause, and the pilot log stores what a person typed. Treat both as sensitive.

## Archives

Screen recordings are mostly static: the same window chrome and a small region that changes. The `.pbx` format uses that.

| Part | How it is stored | Exact? |
|---|---|---|
| keyframes (the analysis input) | **tile-delta codec**: 16×16 tiles aligned with JPEG blocks; unchanged tiles cost nothing, tiles seen before (switching back to a window) are references, new tiles go into a lossless WebP canvas. A frame is never stored larger than its original JPEG. | **bit-exact pixels**, SHA-256 checked on restore, so re-analysis gives identical requests (cache hits) |
| video (for people watching) | re-encoded to AV1: Intel/NVIDIA/AMD hardware encoder if present, else software AV1, else HEVC. Every frame is kept, so `#t=` links still land right. `ARCHIVE_VIDEO=original` keeps it as is, `drop` leaves it out. | lossy, text stays sharp (42–47 dB PSNR in testing) |
| JSON / Markdown / HTML | zstd level 19 | exact |

Everything is encrypted with **AES-256-GCM** in 4 MB authenticated chunks bound to their position, so a wrong key, a flipped bit, reordering or truncation all fail loudly. The key is a random 256-bit key in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service), with a per-file key derived from each archive's salt. Without a keyring, set `ARCHIVE_PASSPHRASE` (stretched with scrypt). **If you lose the key, the archives cannot be opened:** run `python -m playbook key --export` and keep the backup somewhere safe (`key --import` restores it on another machine).

By default a session is archived once it has been untouched for 2 days (`AUTO_COMPACT=idle:2`, checked when the CLI or app starts). `analyze`, `render` and the UI restore archived sessions on demand. Packing a restored session away again only rewrites what changed.

```bash
python -m playbook compact [session|--all|--idle-days N]   # compress and encrypt into .pbx archives
python -m playbook compact --bench latest                  # measure compression on a copy; the session is untouched
python -m playbook restore <session>                       # decrypt and restore
python -m playbook migrate                                 # move sessions from the old ./sessions folder
python -m playbook key --export                            # back up the encryption key
```

Measured on a real 3-minute session (70 keyframes):

| | Before | After |
|---|---|---|
| keyframes | 8.47 MB | 2.27 MB (lossless) |
| video | 9.20 MB | 2.18 MB (AV1, Intel Quick Sync) |
| metadata | 0.14 MB | 0.02 MB |
| **total** | **17.8 MB** | **4.5 MB (4.0× smaller)**; 26 s to pack, 4.7 s to restore |

Restored keyframes are PNG while a session is in use (exact pixels, larger than the original JPEGs). Archived videos are AV1, which current browsers play; `ARCHIVE_VIDEO=original` avoids re-encoding for older players.
