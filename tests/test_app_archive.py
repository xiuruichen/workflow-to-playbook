"""Streamlit sidebar: archive and restore a session."""

import secrets
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from playbook import archive
from playbook.archive import Key
from tests.test_archive import session  # noqa: F401  (fixture)

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(settings, session, monkeypatch):  # noqa: F811
    (session / "playbook.json").unlink()  # the fixture's stub isn't a full Playbook
    key = Key("keyring", secrets.token_bytes(32))
    monkeypatch.setattr(archive, "default_key", lambda *a, **k: key)
    monkeypatch.setattr("playbook.config.get_settings", lambda: settings)
    return AppTest.from_file(APP, default_timeout=60)


def click(app, label):
    next(b for b in app.sidebar.button if label in b.label).click().run()
    assert not app.exception, app.exception


def test_archive_then_restore_from_sidebar(app, settings, session):  # noqa: F811
    app.run()
    click(app, "Archive session")
    assert (settings.sessions_dir / (session.name + ".pbx")).exists() and not session.exists()
    click(app, "Restore session")
    assert (session / "manifest.json").exists()


def test_missing_keyframes_are_repaired_from_archive(app, settings, session):  # noqa: F811
    app.run()
    click(app, "Archive session")
    click(app, "Restore session")
    lost = sorted((session / "keyframes").iterdir())[1:4]  # e.g. wiped by a concurrent restore
    for p in lost:
        p.unlink()
    assert archive.repair(session, settings) == [f"keyframes/{p.name}" for p in lost]
    assert all(p.exists() for p in lost)
    assert archive.repair(session, settings) == []


def test_concurrent_restores_dont_clobber_each_other(app, settings, session):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor

    app.run()
    click(app, "Archive session")
    arc = archive.archive_path(session)
    def restore_once(_):
        try:
            return archive.restore(arc, settings=settings)
        except archive.ArchiveError:  # the other one finished before this one started
            return session

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(restore_once, range(2))) == [session, session]
    assert len(list((session / "keyframes").iterdir())) == 5
    assert not list(settings.sessions_dir.glob("*.restoring"))


def test_failed_restore_error_stays_visible(app, settings, session):  # noqa: F811
    app.run()
    click(app, "Archive session")
    (session / "leftover").mkdir(parents=True)  # e.g. a half-deleted folder
    (session / "leftover" / "x").write_text("x")
    click(app, "Restore session")
    assert any("Couldn't restore" in e.value for e in app.sidebar.error)
