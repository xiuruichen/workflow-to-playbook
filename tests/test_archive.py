"""Keyframe codec and encrypted session archives (.pbx)."""

import json
import secrets
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from playbook import archive, tilecodec
from playbook.archive import ArchiveError, Key
from playbook.keyframes import save_jpeg
from playbook.models import Event, Keyframe, Manifest
from playbook.recorder import list_sessions, resolve_session


def screen(variant: int, w: int = 320, h: int = 192) -> np.ndarray:
    """A synthetic 'desktop': fixed chrome plus a content area that depends on `variant`."""
    img = np.full((h, w, 3), 235, np.uint8)
    img[:24] = (60, 60, 60)  # title bar
    img[-20:] = (30, 30, 90)  # taskbar
    cv2.putText(img, f"Window {variant % 2}", (10, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(img, f"value {variant}", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return img


@pytest.fixture
def key():
    return Key("keyring", secrets.token_bytes(32))


@pytest.fixture
def session(settings):
    d = settings.sessions_dir / "20260101-120000"
    (d / "keyframes").mkdir(parents=True)
    kfs = []
    for i, variant in enumerate([0, 1, 2, 0, 3]):  # variant 0 comes back: tiles referenced from frame 0
        rel = f"keyframes/{i:04d}.jpg"
        save_jpeg(screen(variant), d / rel, 320)
        kfs.append(Keyframe(id=i, t=float(i), path=rel, trigger="event_before"))
    Manifest(session_id=d.name, source="live", video="recording.mp4", duration=5.0, width=320, height=192, fps=5,
             created="2026-01-01T12:00:00", keyframes=kfs, events=[Event(t=1.0, kind="type", text="secret value")]).save(d)
    (d / "recording.mp4").write_bytes(b"\x00fake video" * 5000)
    (d / "events.jsonl").write_text('{"t": 1.0, "kind": "type", "text": "secret value"}\n', encoding="utf-8")
    (d / "playbook.json").write_text(json.dumps({"title": "Confidential workflow"}), encoding="utf-8")
    return d


def snapshot(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file() and p.name != archive.STATE_FILE}


def pixels(path):
    return cv2.imread(str(path))


# ---------------------------------------------------------------------- tile codec
def test_tilecodec_round_trip_is_pixel_exact_and_smaller(session):
    frames = [(p.name, p.read_bytes()) for p in sorted((session / "keyframes").glob("*.jpg"))]
    enc = tilecodec.encode(frames)
    idx, blobs = tilecodec.pack(enc)
    assert len(idx) + sum(map(len, blobs.values())) < sum(len(b) for _, b in frames)
    assert enc[0].kind == "jpeg" and any(e.kind == "delta" for e in enc[1:])
    for (name, original), (name2, restored) in zip(frames, tilecodec.decode(tilecodec.unpack(idx, blobs))):
        assert name == name2
        a = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
        b = cv2.imdecode(np.frombuffer(restored, np.uint8), cv2.IMREAD_COLOR)
        assert np.array_equal(a, b)


def test_tilecodec_never_expands_noise():
    rng = np.random.default_rng(0)
    frames = []
    for i in range(3):
        ok, buf = cv2.imencode(".jpg", rng.integers(0, 255, (64, 96, 3), dtype=np.uint8))
        frames.append((f"{i}.jpg", buf.tobytes()))
    enc = tilecodec.encode(frames)
    assert all(e.kind == "jpeg" and e.data == f[1] for e, f in zip(enc, frames))


def test_tilecodec_detects_corruption(session):
    frames = [(p.name, p.read_bytes()) for p in sorted((session / "keyframes").glob("*.jpg"))]
    enc = tilecodec.encode(frames)
    enc[2].sha256 = "0" * 64
    with pytest.raises(ValueError, match="integrity"):
        list(tilecodec.decode(enc))


# ---------------------------------------------------------------------- archives
def test_compact_and_restore_round_trip(settings, session, key):
    before = snapshot(session)
    res = archive.compact(session, settings, key, video="original")
    assert res.archive.exists() and not session.exists()
    raw = res.archive.read_bytes()
    assert b"Confidential" not in raw and b"secret value" not in raw  # contents are encrypted
    assert res.after < res.before

    back = archive.restore(res.archive, settings=settings, key=key)
    after = snapshot(back)
    assert set(after) == set(before)
    for name, data in before.items():
        if name.startswith("keyframes/"):
            assert np.array_equal(pixels(session.parent / back.name / name), cv2.imdecode(np.frombuffer(data, np.uint8), 1))
        else:
            assert after[name] == data, name


def test_wrong_key_is_refused(settings, session, key):
    res = archive.compact(session, settings, key, video="original")
    with pytest.raises(ArchiveError, match="different key"):
        archive.restore(res.archive, settings=settings, key=Key("keyring", secrets.token_bytes(32)))


def test_passphrase_key(settings, session):
    k = Key("passphrase", passphrase="correct horse battery staple")
    res = archive.compact(session, settings, k, video="original")
    with pytest.raises(ArchiveError):
        archive.restore(res.archive, settings=settings, key=Key("passphrase", passphrase="wrong"))
    assert (archive.restore(res.archive, settings=settings, key=k) / "manifest.json").exists()


@pytest.mark.parametrize("where", [0.3, 0.6, 0.9])
def test_tampering_is_detected(settings, session, key, where):
    res = archive.compact(session, settings, key, video="original")
    data = bytearray(res.archive.read_bytes())
    data[int(len(data) * where)] ^= 0x01
    res.archive.write_bytes(bytes(data))
    with pytest.raises(ArchiveError):
        archive.verify(res.archive, key)
    with pytest.raises(ArchiveError):
        archive.restore(res.archive, settings=settings, key=key)
    assert not session.exists() and not session.with_name(session.name + ".restoring").exists()


def test_truncation_is_detected(settings, session, key):
    res = archive.compact(session, settings, key, video="original")
    res.archive.write_bytes(res.archive.read_bytes()[:-100])
    with pytest.raises(ArchiveError):
        archive.restore(res.archive, settings=settings, key=key)


def test_recompaction_reuses_unchanged_parts(settings, session, key):
    res = archive.compact(session, settings, key, video="original")
    back = archive.restore(res.archive, settings=settings, key=key)
    (back / "playbook.json").write_text(json.dumps({"title": "Edited"}), encoding="utf-8")
    res2 = archive.compact(back, settings, key, video="original")
    assert res2.reused >= 3  # video + keyframe blobs + unchanged JSON
    assert "reused" in res2.report()
    again = archive.restore(res2.archive, settings=settings, key=key)
    assert json.loads((again / "playbook.json").read_text(encoding="utf-8")) == {"title": "Edited"}
    assert (again / "recording.mp4").read_bytes() == b"\x00fake video" * 5000


def test_video_can_be_dropped(settings, session, key):
    res = archive.compact(session, settings, key, video="drop")
    back = archive.restore(res.archive, settings=settings, key=key)
    assert not (back / "recording.mp4").exists()
    assert (back / "manifest.json").exists()


def test_summary_and_single_member_without_restoring(settings, session, key):
    res = archive.compact(session, settings, key, video="original")
    info = archive.summary(res.archive, key)
    assert info["session_id"] == session.name and info["title"] == "Confidential workflow" and info["keyframes"] == 5
    assert json.loads(archive.read_member(res.archive, "playbook.json", key)) == {"title": "Confidential workflow"}


def test_archived_sessions_are_listed_and_restored_on_demand(settings, session, key, monkeypatch):
    monkeypatch.setattr(archive, "default_key", lambda *a, **k: key)
    res = archive.compact(session, settings, key, video="original")
    assert list_sessions(settings) == [res.archive]
    hot = resolve_session(session.name, settings)
    assert hot == session and (hot / "manifest.json").exists()
    assert list_sessions(settings) == [session]  # the restored folder takes precedence over the archive


def test_compact_idle_only_touches_old_sessions(settings, session, key):
    assert archive.compact_idle(settings, days=1, key=key) == []
    assert len(archive.compact_idle(settings, days=-1, key=key)) == 1
    assert not session.exists()


def test_video_transcode_keeps_duration(tmp_path):
    ff = archive._ffmpeg()
    src = tmp_path / "in.mp4"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x96:rate=5:duration=2", "-c:v", "libx264",
                    "-crf", "0", "-pix_fmt", "yuv420p", str(src)], check=True)
    out = tmp_path / "out.mp4"
    encoder = archive.transcode_video(src, out)
    if encoder is None:  # nothing beat the original on this machine; that is allowed
        assert not out.exists()
        return
    assert out.stat().st_size < src.stat().st_size
    assert abs(archive.video_duration(out) - archive.video_duration(src)) <= archive.DURATION_TOLERANCE_S


def test_compact_refuses_synced_folder(settings, session, key, tmp_path):
    with pytest.raises(Exception, match="OneDrive"):
        archive.compact(session, settings, key, video="original", dest=tmp_path / "OneDrive - Contoso" / "x.pbx", remove=False)
    assert session.exists()


def test_migrate_moves_and_archives(settings, session, key, tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "default_key", lambda *a, **k: key)
    old = tmp_path / "old_sessions"
    shutil.move(str(session), str(old / session.name))
    assert archive.migrate(settings, [old], status=lambda m: None) == 1
    assert (settings.sessions_dir / f"{session.name}.pbx").exists()
