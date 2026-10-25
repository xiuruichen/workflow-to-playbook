"""Screen-capture archive (.pbx): compact, encrypted storage for sessions that aren't in use.

A session folder (video, JPEG keyframes, JSON) becomes a single `<session id>.pbx` file and is
restored only when it is needed again (to analyze, re-render or review it).

What each part becomes:
- keyframes: the lossless tile-delta codec (tilecodec.py). They are the analysis input, so
  they restore with bit-identical pixels and re-analysis hits the same cache entries.
- video: re-encoded to AV1 for people watching it. Lossy, but text stays sharp, and every
  frame and timestamp is kept so the playbook's `#t=` links still land on the right moment.
  ARCHIVE_VIDEO=original keeps the original bytes; ARCHIVE_VIDEO=drop leaves the video out.
- everything else (JSON, Markdown, HTML): zstd level 19.

Container layout (all integers little-endian):

    MAGIC | u32 header length | header JSON (version, key id, KDF, salt; no session content)
    record*:  16-byte record id | u32 chunk count | chunk*: u32 length | 12-byte nonce | ciphertext
    u64 offset of the index record | MAGIC

Every chunk (at most 4 MB of plaintext) is sealed with AES-256-GCM. The associated data binds
it to this file's salt, its record id, its position and whether it is the record's last chunk,
so swapping, reordering or truncating anything fails decryption. Record 0 is the session
summary (shown in lists without decrypting the rest); the last record is the index of members.

The key is a random 256-bit master key in the OS keyring (Windows Credential Manager, macOS
Keychain, Secret Service), with a per-file key derived by HKDF from the file's salt. Without a
keyring, ARCHIVE_PASSPHRASE is stretched with scrypt instead. Losing the key means losing the
archives, so `python -m playbook key --export` prints a backup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

import zstandard
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import tilecodec
from .config import Settings, get_settings
from .models import Manifest
from .hardware import be_gentle, cpu_threads
from .security import check_storage

MAGIC = b"PBX\x01"
VERSION = 1
CHUNK = 4 * 2**20
SUFFIX = ".pbx"
STATE_FILE = ".pbx-state.json"  # in a restored folder: hashes of what was restored, for incremental re-compaction
KEYRING_SERVICE = "workflow-playbook"
KEYRING_USER = "archive-key"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
DURATION_TOLERANCE_S = 0.2


class ArchiveError(RuntimeError):
    pass


# ---------------------------------------------------------------------- keys
@dataclass
class Key:
    """Where archive keys come from: a master key (keyring / tests) or a passphrase."""

    kind: str  # "keyring" | "passphrase"
    master: bytes = b""
    passphrase: str = ""

    @property
    def key_id(self) -> str:
        if self.kind == "passphrase":
            return "passphrase"
        return hashlib.sha256(b"pbx key id" + self.master).hexdigest()[:16]

    def file_key(self, salt: bytes) -> bytes:
        if self.kind == "passphrase":
            return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(self.passphrase.encode())
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"pbx v1 file key").derive(self.master)

    def export(self) -> str:
        return base64.urlsafe_b64encode(self.master).decode()


def default_key(settings: Settings | None = None, create: bool = True) -> Key:
    """The keyring master key (created on first use), else ARCHIVE_PASSPHRASE."""
    s = settings or get_settings()
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if stored:
            return Key("keyring", base64.urlsafe_b64decode(stored))
        if create:
            master = secrets.token_bytes(32)
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, base64.urlsafe_b64encode(master).decode())
            return Key("keyring", master)
    except Exception as exc:  # no usable keyring backend (e.g. a headless Linux box)
        if not s.archive_passphrase:
            raise ArchiveError(
                f"No OS keyring is available to hold the archive key ({type(exc).__name__}). "
                "Set ARCHIVE_PASSPHRASE in the environment, or set AUTO_COMPACT=off."
            ) from exc
    if s.archive_passphrase:
        return Key("passphrase", passphrase=s.archive_passphrase)
    raise ArchiveError("No archive key exists yet.")


def import_key(backup: str) -> Key:
    """Install a key printed by `key --export` (e.g. on a new machine)."""
    import keyring

    master = base64.urlsafe_b64decode(backup.strip())
    if len(master) != 32:
        raise ArchiveError("That is not a valid archive key backup.")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, backup.strip())
    return Key("keyring", master)


# ---------------------------------------------------------------------- container
class _Writer:
    def __init__(self, f: BinaryIO, key: Key, salt: bytes):
        self.f, self.salt = f, salt
        self.aes = AESGCM(key.file_key(salt))

    def _aad(self, rid: bytes, n: int, last: bool) -> bytes:
        return self.salt + rid + struct.pack("<I?", n, last)

    def record(self, chunks: Iterator[bytes] | list[bytes]) -> tuple[bytes, int]:
        """Encrypt one record from plaintext chunks; returns (record id, offset)."""
        rid, offset = secrets.token_bytes(16), self.f.tell()
        # Buffer one chunk ahead so the last one can be marked as last.
        sealed, pending, n = [], None, 0
        for chunk in chunks:
            if pending is not None:
                sealed.append(self._seal(rid, n, pending, False))
                n += 1
            pending = chunk
        sealed.append(self._seal(rid, n, pending or b"", True))
        self.f.write(rid + struct.pack("<I", len(sealed)))
        for nonce, ct in sealed:
            self.f.write(struct.pack("<I", len(ct)) + nonce + ct)
        return rid, offset

    def _seal(self, rid: bytes, n: int, data: bytes, last: bool) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        return nonce, self.aes.encrypt(nonce, data, self._aad(rid, n, last))

    def copy_raw(self, raw: bytes) -> int:
        """Append an already-encrypted record from an older version of this archive (same salt)."""
        offset = self.f.tell()
        self.f.write(raw)
        return offset


def _chunks(data: bytes) -> list[bytes]:
    return [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]


def _file_chunks(path: Path) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            yield chunk


class Reader:
    """Random access to an archive's records."""

    def __init__(self, path: Path, key: Key):
        self.path = Path(path)
        self.f = open(self.path, "rb")
        try:
            if self.f.read(4) != MAGIC:
                raise ArchiveError(f"{self.path.name} is not a playbook archive.")
            (hlen,) = struct.unpack("<I", self.f.read(4))
            self.header = json.loads(self.f.read(hlen))
            if self.header.get("version") != VERSION:
                raise ArchiveError(f"{self.path.name} uses archive version {self.header.get('version')}; this is {VERSION}.")
            self.records_start = self.f.tell()
            if self.header["key_id"] != key.key_id:
                raise ArchiveError(
                    f"{self.path.name} was encrypted with a different key ({self.header['key_id']}). "
                    "Import that key with `python -m playbook key --import`."
                )
            self.salt = base64.b64decode(self.header["salt"])
            self.aes = AESGCM(key.file_key(self.salt))
            self.f.seek(-12, os.SEEK_END)
            index_offset, magic = struct.unpack("<Q4s", self.f.read(12))
            if magic != MAGIC:
                raise ArchiveError(f"{self.path.name} is truncated or damaged.")
            self.index = json.loads(self.read_record(index_offset))
        except (ArchiveError, InvalidTag, ValueError, KeyError, struct.error) as exc:
            self.f.close()
            if isinstance(exc, ArchiveError):
                raise
            raise ArchiveError(f"{self.path.name} could not be decrypted: wrong key, or the file was damaged or tampered with.") from exc

    def close(self) -> None:
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def iter_record(self, offset: int) -> Iterator[bytes]:
        self.f.seek(offset)
        rid = self.f.read(16)
        (count,) = struct.unpack("<I", self.f.read(4))
        pos = self.f.tell()
        for n in range(count):
            self.f.seek(pos)
            (clen,) = struct.unpack("<I", self.f.read(4))
            nonce, ct = self.f.read(12), self.f.read(clen)
            pos = self.f.tell()
            try:
                yield self.aes.decrypt(nonce, ct, self.salt + rid + struct.pack("<I?", n, n == count - 1))
            except InvalidTag as exc:
                raise ArchiveError(f"{self.path.name} failed authentication: it was damaged or tampered with.") from exc

    def read_record(self, offset: int) -> bytes:
        return b"".join(self.iter_record(offset))

    def raw_record(self, offset: int) -> bytes:
        """The encrypted bytes of a record, for copying into a new version of this archive."""
        self.f.seek(offset + 16)
        (count,) = struct.unpack("<I", self.f.read(4))
        for _ in range(count):
            (clen,) = struct.unpack("<I", self.f.read(4))
            self.f.seek(12 + clen, os.SEEK_CUR)
        end = self.f.tell()
        self.f.seek(offset)
        return self.f.read(end - offset)

    def summary(self) -> dict:
        return json.loads(self.read_record(self.records_start))


# ---------------------------------------------------------------------- video
def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def video_duration(path: Path) -> float | None:
    import re

    out = subprocess.run([_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


# Tried in order: Intel / NVIDIA / AMD hardware AV1 (seconds), then software AV1, then HEVC.
VIDEO_ENCODERS: list[tuple[str, list[str]]] = [
    ("av1_qsv", ["-c:v", "av1_qsv", "-global_quality", "26", "-preset", "slower"]),
    ("av1_nvenc", ["-c:v", "av1_nvenc", "-cq", "30", "-preset", "p6"]),
    ("av1_amf", ["-c:v", "av1_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "30", "-qp_p", "32"]),
    ("libaom-av1", ["-c:v", "libaom-av1", "-crf", "34", "-b:v", "0", "-cpu-used", "8", "-row-mt", "1",
                    "-tiles", "2x2", "-aom-params", "tune-content=screen"]),
    ("libx265", ["-c:v", "libx265", "-crf", "28", "-preset", "medium", "-x265-params", "log-level=error"]),
]


HARDWARE_ENCODERS = {"av1_qsv", "av1_nvenc", "av1_amf"}


def _gentle() -> dict:
    """subprocess kwargs: below-normal priority (Windows) so encoding doesn't freeze the desktop."""
    return {"creationflags": getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)} if os.name == "nt" else {}


def transcode_video(src: Path, dest: Path, status: Callable[[str], None] = lambda m: None,
                    threads: int | None = None, hardware_only: bool = False) -> str | None:
    """Re-encode for compact storage. Returns the encoder used, or None if nothing beat the original.

    Every frame is kept (no frame dropping), so timestamps are unchanged; the result must
    match the original duration and be smaller, or it is discarded."""
    want = video_duration(src)
    for name, args in VIDEO_ENCODERS:
        if hardware_only and name not in HARDWARE_ENCODERS:
            continue  # low-power mode: software AV1/HEVC would load every core for minutes
        status(f"Compressing video ({name})...")
        cap = ["-threads", str(threads)] if threads else []
        r = subprocess.run([_ffmpeg(), "-v", "error", "-y", *cap, "-i", str(src), *args, *cap, "-pix_fmt", "yuv420p", "-an",
                            "-movflags", "+faststart", str(dest)], capture_output=True, **_gentle())
        if r.returncode != 0 or not dest.exists():
            continue  # encoder not usable on this machine
        got = video_duration(dest)
        if want is not None and (got is None or abs(got - want) > DURATION_TOLERANCE_S):
            continue
        if dest.stat().st_size >= src.stat().st_size:
            break
        return name
    dest.unlink(missing_ok=True)
    return None


def remove_tree(path: Path) -> None:
    """Delete a folder, clearing read-only flags (OneDrive marks folders read-only) and retrying
    briefly if Windows still has a file open (indexer, antivirus, a video player)."""
    import stat

    def clear_and_retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    for attempt in range(5):
        try:
            shutil.rmtree(path, onerror=clear_and_retry)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


# ---------------------------------------------------------------------- compact / restore
@dataclass
class Part:
    name: str
    before: int = 0
    after: int = 0
    note: str = ""


@dataclass
class CompactResult:
    archive: Path
    parts: list[Part] = field(default_factory=list)
    seconds: float = 0.0
    reused: int = 0  # records copied unchanged from the previous archive

    @property
    def before(self) -> int:
        return sum(p.before for p in self.parts)

    @property
    def after(self) -> int:
        return self.archive.stat().st_size if self.archive.exists() else sum(p.after for p in self.parts)

    def report(self) -> str:
        lines = [f"{p.name:<10} {p.before / 1e6:8.2f} MB -> {p.after / 1e6:7.2f} MB  {p.note}" for p in self.parts]
        ratio = self.before / max(self.after, 1)
        lines.append(f"{'total':<10} {self.before / 1e6:8.2f} MB -> {self.after / 1e6:7.2f} MB  "
                     f"({ratio:.1f}x smaller, {self.seconds:.1f}s{f', {self.reused} parts reused' if self.reused else ''})")
        return "\n".join(lines)


def archive_path(session_dir: Path) -> Path:
    session_dir = Path(session_dir)
    return session_dir.parent / (session_dir.name + SUFFIX)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _summary(session_dir: Path, manifest: Manifest | None) -> dict:
    title = None
    try:
        title = json.loads((session_dir / "playbook.json").read_text(encoding="utf-8")).get("title")
    except (OSError, ValueError):
        pass
    return {
        "session_id": session_dir.name,
        "title": title,
        "created": manifest.created if manifest else None,
        "duration": manifest.duration if manifest else None,
        "source": manifest.source if manifest else None,
        "keyframes": len(manifest.keyframes) if manifest else 0,
        "analyzed": (session_dir / "playbook.json").exists(),
        "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def compact(
    session_dir: Path,
    settings: Settings | None = None,
    key: Key | None = None,
    video: str | None = None,
    remove: bool = True,
    dest: Path | None = None,
    status: Callable[[str], None] = lambda m: None,
) -> CompactResult:
    """Compress + encrypt a session folder into `<id>.pbx`, verify it, then delete the folder.

    If the folder was restored from an archive, members that haven't changed since (the
    video, the keyframes) are copied over from the old archive instead of re-encoded."""
    s = settings or get_settings()
    session_dir = Path(session_dir)
    key = key or default_key(s)
    video = video or s.archive_video
    dest = Path(dest) if dest else archive_path(session_dir)
    check_storage(dest.parent, s.allow_synced_dir)
    be_gentle(s)
    t0 = time.time()

    manifest = Manifest.load(session_dir) if (session_dir / "manifest.json").exists() else None
    files = sorted(p for p in session_dir.rglob("*") if p.is_file() and p.name != STATE_FILE)
    rel = {p: p.relative_to(session_dir).as_posix() for p in files}
    kf_names = [k.path for k in manifest.keyframes] if manifest else []
    kf_set = set(kf_names) & set(rel.values())
    kf_names = [n for n in kf_names if n in kf_set]
    video_name = manifest.video if manifest and manifest.video in rel.values() else None

    # Incremental: reuse records whose source file is unchanged since the last restore.
    old: Reader | None = None
    restored: dict[str, str] = {}
    salt = secrets.token_bytes(16)
    state_path = session_dir / STATE_FILE
    if dest.exists() and state_path.exists():
        try:
            old = Reader(dest, key)
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            salt = old.salt  # same salt, so old records stay valid in the new file
        except (ArchiveError, OSError, ValueError):
            old, restored = None, {}
    hashes = {name: _sha(p) for p, name in rel.items()}

    def unchanged(name: str) -> bool:
        return old is not None and restored.get(name) == hashes.get(name) and name in old.index["members"]

    result = CompactResult(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    members: dict[str, dict] = {}
    cctx = zstandard.ZstdCompressor(level=19)
    try:
        with open(tmp, "wb") as f:
            header = json.dumps({"version": VERSION, "key_id": key.key_id, "kdf": key.kind, "salt": base64.b64encode(salt).decode(),
                                 "chunk": CHUNK, "cipher": "AES-256-GCM"}).encode()
            f.write(MAGIC + struct.pack("<I", len(header)) + header)
            w = _Writer(f, key, salt)
            w.record(_chunks(json.dumps(_summary(session_dir, manifest)).encode()))

            def put(name: str, chunks, codec: str, extra: dict | None = None) -> None:
                if unchanged(name):
                    entry = dict(old.index["members"][name])
                    entry["offset"] = w.copy_raw(old.raw_record(entry["offset"]))
                    result.reused += 1
                else:
                    _, offset = w.record(chunks)
                    entry = {"offset": offset, "codec": codec, "sha256": hashes.get(name), **(extra or {})}
                members[name] = entry

            # Keyframes: lossless tile-delta, or copied whole if none changed.
            if kf_names:
                kf_before = sum((session_dir / n).stat().st_size for n in kf_names)
                # (Delta keyframes restore as PNG files, so "unchanged" means "same bytes as restored".)
                if old is not None and old.index.get("keyframes") and all(restored.get(n) == hashes[n] for n in kf_names):
                    kf_index = old.index["keyframes"]
                    kf_index["index"] = w.copy_raw(old.raw_record(kf_index["index"]))
                    for blob in kf_index["blobs"].values():
                        blob["offset"] = w.copy_raw(old.raw_record(blob["offset"]))
                    result.reused += len(kf_index["blobs"]) + 1
                    kf_after = kf_index["size"]
                    note = "lossless, unchanged (reused)"
                else:
                    status(f"Compressing {len(kf_names)} keyframes (lossless)...")
                    enc = tilecodec.encode([(n, (session_dir / n).read_bytes()) for n in kf_names])
                    idx_json, blobs = tilecodec.pack(enc)
                    kf_after = len(idx_json) + sum(len(b) for b in blobs.values())
                    kf_index = {"index": w.record(_chunks(cctx.compress(idx_json)))[1], "size": kf_after,
                                "blobs": {name: {"offset": w.record(_chunks(b))[1]} for name, b in blobs.items()}}
                    deltas = sum(e.kind == "delta" for e in enc)
                    note = f"lossless tile-delta ({deltas}/{len(enc)} frames as deltas)"
                kf_index["names"] = kf_names
                result.parts.append(Part("keyframes", kf_before, kf_after, note))
            else:
                kf_index = None

            # Video.
            if video_name:
                src = session_dir / video_name
                before = src.stat().st_size
                if video == "drop":
                    result.parts.append(Part("video", before, 0, "dropped (ARCHIVE_VIDEO=drop)"))
                elif unchanged(video_name) or video == "original":
                    put(video_name, _file_chunks(src), "raw")
                    note = "unchanged (reused)" if unchanged(video_name) else "original kept"
                    result.parts.append(Part("video", before, members[video_name].get("size", before), note))
                else:
                    small = session_dir / f".{Path(video_name).stem}.compact.mp4"
                    encoder = transcode_video(src, small, status, threads=cpu_threads(s), hardware_only=s.low_power)
                    path = small if encoder else src
                    hashes[video_name] = _sha(path)  # a restore gives back this file
                    put(video_name, _file_chunks(path), "raw", {"size": path.stat().st_size, "encoder": encoder})
                    result.parts.append(Part("video", before, path.stat().st_size,
                                             f"AV1/HEVC via {encoder}, every frame kept" if encoder else "original (re-encoding didn't help)"))
                    small.unlink(missing_ok=True)

            # Everything else.
            other_before = other_after = 0
            for p, name in rel.items():
                if name in kf_set or name == video_name:
                    continue
                if p.suffix.lower() in VIDEO_EXTS | {".jpg", ".jpeg", ".png", ".webp"}:
                    data, codec = p.read_bytes(), "raw"
                else:
                    data, codec = cctx.compress(p.read_bytes()), "zstd"
                put(name, _chunks(data), codec)
                other_before += p.stat().st_size
                other_after += len(data)
            result.parts.append(Part("metadata", other_before, other_after, "zstd"))

            index = {"members": members, "keyframes": kf_index, "video_mode": video}
            index_offset = w.record(_chunks(json.dumps(index).encode()))[1]
            f.write(struct.pack("<Q", index_offset) + MAGIC)
        if old is not None:
            old.close()
            old = None
        status("Verifying the archive...")
        verify(tmp, key, hashes)
        os.replace(tmp, dest)
    finally:
        if old is not None:
            old.close()
        tmp.unlink(missing_ok=True)
    if remove:
        remove_tree(session_dir)
    result.seconds = time.time() - t0
    return result


def _iter_members(r: Reader) -> Iterator[tuple[str, Iterator[bytes] | bytes]]:
    """(relative path, content) for every file in the archive. Keyframes are decoded and pixel-verified."""
    dctx = zstandard.ZstdDecompressor()
    for name, entry in r.index["members"].items():
        if entry["codec"] == "zstd":
            yield name, dctx.decompress(r.read_record(entry["offset"]))
        else:
            yield name, r.iter_record(entry["offset"])
    kf = r.index.get("keyframes")
    if kf:
        idx_json = dctx.decompress(r.read_record(kf["index"]))
        blobs = {name: r.read_record(b["offset"]) for name, b in kf["blobs"].items()}
        for name, data in tilecodec.decode(tilecodec.unpack(idx_json, blobs)):
            yield name, data


def verify(path: Path, key: Key, expected: dict[str, str] | None = None) -> int:
    """Decrypt everything and check integrity; returns the number of files. Raises ArchiveError."""
    n = 0
    with Reader(path, key) as r:
        try:
            for name, content in _iter_members(r):
                n += 1
                entry = r.index["members"].get(name)
                if entry is None:
                    continue  # keyframes: tilecodec already verified the pixels
                h = hashlib.sha256()
                for chunk in ([content] if isinstance(content, bytes) else content):
                    h.update(chunk)
                want = (expected or {}).get(name, entry.get("sha256"))
                if want and h.hexdigest() != want:
                    raise ArchiveError(f"{name} in {path.name} doesn't match the original.")
        except ValueError as exc:  # keyframe integrity check
            raise ArchiveError(str(exc)) from exc
    return n


def restore(archive: Path, dest: Path | None = None, settings: Settings | None = None, key: Key | None = None,
            keep_archive: bool = True) -> Path:
    """Decrypt + decompress `<id>.pbx` into a session folder (by default next to it)."""
    s = settings or get_settings()
    archive = Path(archive)
    key = key or default_key(s, create=False)
    dest = Path(dest) if dest else archive.with_suffix("")
    if dest.exists() and any(dest.iterdir()):
        raise ArchiveError(f"{dest} already exists; it is already restored.")
    tmp = dest.with_name(dest.name + ".restoring")
    shutil.rmtree(tmp, ignore_errors=True)
    state: dict[str, str] = {}
    try:
        with Reader(archive, key) as r:
            for name, content in _iter_members(r):
                out = tmp / name
                out.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with open(out, "wb") as f:
                    for chunk in ([content] if isinstance(content, bytes) else content):
                        h.update(chunk)
                        f.write(chunk)
                state[name] = h.hexdigest()
        (tmp / "keyframes").mkdir(exist_ok=True)
        (tmp / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
        if dest.exists():
            dest.rmdir()
        os.replace(tmp, dest)
    except ValueError as exc:
        raise ArchiveError(str(exc)) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not keep_archive:
        archive.unlink()
    return dest


def summary(archive: Path, key: Key | None = None, settings: Settings | None = None) -> dict:
    with Reader(archive, key or default_key(settings, create=False)) as r:
        return r.summary()


def read_member(archive: Path, name: str, key: Key | None = None, settings: Settings | None = None) -> bytes | None:
    """One file from an archive (e.g. playbook.json) without restoring the session."""
    with Reader(archive, key or default_key(settings, create=False)) as r:
        entry = r.index["members"].get(name)
        if entry is None:
            return None
        data = r.read_record(entry["offset"])
        return zstandard.ZstdDecompressor().decompress(data) if entry["codec"] == "zstd" else data


# ---------------------------------------------------------------------- policy
def idle_days(settings: Settings) -> float | None:
    """Days from AUTO_COMPACT=idle:<days>, else None."""
    if settings.auto_compact.startswith("idle:"):
        try:
            return float(settings.auto_compact.split(":", 1)[1])
        except ValueError:
            raise ArchiveError(f"AUTO_COMPACT={settings.auto_compact!r}: expected idle:<days>, e.g. idle:7") from None
    return None


def last_used(session_dir: Path) -> float:
    return max((p.stat().st_mtime for p in Path(session_dir).rglob("*") if p.is_file()), default=0.0)


def compact_idle(settings: Settings, days: float, key: Key | None = None,
                 status: Callable[[str], None] = lambda m: None) -> list[CompactResult]:
    """Compact every session folder not touched for `days` days."""
    cutoff = time.time() - days * 86400
    results = []
    if not settings.sessions_dir.exists():
        return results
    for d in sorted(settings.sessions_dir.iterdir()):
        if (d / "manifest.json").exists() and last_used(d) < cutoff:
            status(f"Archiving {d.name}...")
            results.append(compact(d, settings, key, status=status))
    return results


def migrate(settings: Settings, old_dirs: list[Path], compact_after: bool = True,
            status: Callable[[str], None] = print) -> int:
    """Move sessions out of old (e.g. cloud-synced) folders into the local data folder."""
    moved = 0
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    check_storage(settings.sessions_dir, settings.allow_synced_dir)
    for old in old_dirs:
        if not old.exists() or old.resolve() == settings.sessions_dir.resolve():
            continue
        for d in sorted(old.iterdir()):
            is_session = (d / "manifest.json").exists() or d.suffix == SUFFIX
            if not is_session:
                continue
            target = settings.sessions_dir / d.name
            if target.exists() or (settings.sessions_dir / (d.name + SUFFIX)).exists():
                status(f"skip {d.name}: already in {settings.sessions_dir}")
                continue
            try:
                os.replace(d, target)  # same drive: instant
            except OSError:  # another drive: copy, then delete the original
                (shutil.copytree if d.is_dir() else shutil.copy2)(d, target)
                remove_tree(d) if d.is_dir() else d.unlink()
            moved += 1
            if compact_after and d.suffix != SUFFIX:
                res = compact(target, settings)
                status(f"moved + archived {d.name}: {res.before / 1e6:.1f} MB -> {res.after / 1e6:.1f} MB")
            else:
                status(f"moved {d.name}")
    return moved


def bench(session_dir: Path, settings: Settings | None = None, key: Key | None = None,
          status: Callable[[str], None] = lambda m: None) -> str:
    """Compact a copy of a session, restore it, and check the keyframes come back pixel-identical."""
    import tempfile

    import cv2
    import numpy as np

    s = settings or get_settings()
    session_dir = Path(session_dir)
    key = key or default_key(s)
    with tempfile.TemporaryDirectory(dir=s.data_dir if s.data_dir.exists() else None) as tmp:
        out = Path(tmp) / (session_dir.name + SUFFIX)
        res = compact(session_dir, s, key, remove=False, dest=out, status=status)
        t = time.time()
        back = restore(out, Path(tmp) / "restored", s, key)
        t_restore = time.time() - t
        m = Manifest.load(session_dir)
        same = all(
            np.array_equal(cv2.imread(str(session_dir / k.path)), cv2.imread(str(back / k.path)))
            for k in m.keyframes if (session_dir / k.path).exists()
        )
    return res.report() + f"\nrestore {t_restore:.1f}s · keyframes pixel-identical after restore: {'yes' if same else 'NO'}"


__all__ = ["ArchiveError", "Key", "default_key", "import_key", "compact", "restore", "verify", "summary", "bench",
           "read_member", "compact_idle", "idle_days", "migrate", "archive_path", "SUFFIX", "STATE_FILE"]
