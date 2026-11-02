"""New-version notice and download, criteria UP1–UP5 (docs/PLAN.md §4-65). GitHub is never asked:
every answer comes from a fake opener."""

import hashlib
import io
import json

import pytest

import imquant
from imquant.ui import updates

DL = updates.DOWNLOADS + "v1.0.4/LuXcale-1.0.4-setup.exe"
PAYLOAD = b"MZ" + bytes(range(256)) * 300  # stands in for an installer
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def release(tag="v1.0.4", digest=f"sha256:{SHA}", body="", url=DL, size=len(PAYLOAD)):
    asset = {"name": "LuXcale-1.0.4-setup.exe", "browser_download_url": url, "size": size}
    if digest:
        asset["digest"] = digest
    return {"tag_name": tag, "assets": [asset], "body": body}


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(api=None, file=PAYLOAD, fail=None):
    asked = []

    def opener(request, timeout):
        asked.append(request.full_url)
        if fail is not None:
            raise fail
        if request.full_url == updates.LATEST:
            return Answer(api if isinstance(api, bytes) else json.dumps(api).encode())
        return Answer(file)
    opener.asked = asked
    return opener


def test_UP1_versions():
    v = updates.version
    assert v("v1.0.4") > v("1.0.3") and v("v1.0.3") == v("1.0.3") and v("v1.0.10") > v("v1.0.9")
    assert v("latest") is None and v("v1.0") is None and v("1.0.3-beta") is None


def test_UP2_only_a_newer_release_is_offered():
    assert updates.latest("1.0.3", opener_for(release())).version == "1.0.4"
    for answer in (release("v1.0.3"), release("v1.0.2"), release("nightly"), b"<html>", [1, 2]):
        assert updates.latest("1.0.3", opener_for(answer)) is None
    for error in (OSError("offline"), TimeoutError()):
        assert updates.latest("1.0.3", opener_for(fail=error)) is None


def test_UP2_sha_from_the_release_notes_when_github_gives_none():
    notes = f"…\nSHA-256 (LuXcale-1.0.4-setup.exe): `{SHA.upper()}`\n"
    up = updates.latest("1.0.3", opener_for(release(digest=None, body=notes)))
    assert up.sha256 == SHA and up.url == DL


def test_UP3_download_checks_size_and_sha(tmp_path):
    up = updates.latest("1.0.3", opener_for(release()))
    seen = []
    path = updates.download(up, tmp_path, opener_for(file=PAYLOAD), progress=lambda d, t: seen.append((d, t)))
    assert path is not None and path.read_bytes() == PAYLOAD and seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    for bad in (PAYLOAD[:-1], PAYLOAD[:-1] + b"X"):
        assert updates.download(up, tmp_path / "bad", opener_for(file=bad)) is None
        assert not list((tmp_path / "bad").glob("*"))  # nothing kept


def test_UP3_only_the_releases_address(tmp_path):
    up = updates.latest("1.0.3", opener_for(release(url="https://example.com/LuXcale-1.0.4-setup.exe")))
    assert up.url is None  # the button opens the Releases page instead
    opener = opener_for(file=PAYLOAD)
    assert updates.download(up, tmp_path, opener) is None and opener.asked == []
    no_sha = updates.latest("1.0.3", opener_for(release(digest=None)))
    assert no_sha.sha256 is None and updates.download(no_sha, tmp_path, opener) is None


QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(imquant, "_TOOLS", tmp_path / "data")
    return tmp_path / "data"


def test_UP4_not_asked_when_not_installed(app, data, monkeypatch):
    from imquant.ui import i18n, wb_app

    monkeypatch.setattr(updates, "latest", lambda *a, **k: pytest.fail("GitHub was asked"))
    win = wb_app.window()
    try:
        assert not win.update_button.isVisible() and win.update is None
    finally:
        win.close()
        i18n.set_language("en")


def test_UP2_UP5_button_and_download(app, data, monkeypatch):
    from imquant.ui import i18n, wb_app

    win = wb_app.window(check_updates=False)
    win.show()
    try:
        wb_app.show_update(win, updates.latest("1.0.3", opener_for(release())))
        assert win.update_button.isVisible() and win.update_button.text() == "새 버전 1.0.4 받기"
        i18n.set_language("en")
        assert win.update_button.text() == "New version 1.0.4 – download"
        started, quit_ = [], []
        monkeypatch.setattr(wb_app, "run_installer", started.append)
        monkeypatch.setattr(QtWidgets.QApplication, "quit", staticmethod(lambda: quit_.append(1)))
        wb_app.get_update(win, opener=opener_for(file=PAYLOAD), background=False)
        app.processEvents()
        assert len(started) == 1 and started[0].read_bytes() == PAYLOAD and started[0].parent == data / "updates"
        assert quit_
        wb_app.show_update(win, None)
        assert not win.update_button.isVisible()
    finally:
        win.close()
        i18n.set_language("en")


def test_UP3_a_bad_download_runs_nothing(app, data, monkeypatch):
    from PySide6 import QtGui
    from imquant.ui import i18n, wb_app

    win = wb_app.window(check_updates=False)
    try:
        wb_app.show_update(win, updates.latest("1.0.3", opener_for(release())))
        started, opened = [], []
        monkeypatch.setattr(wb_app, "run_installer", started.append)
        monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
        monkeypatch.setattr(QtWidgets.QMessageBox, "information", staticmethod(lambda *a, **k: None))
        wb_app.get_update(win, opener=opener_for(file=PAYLOAD + b"tampered"), background=False)
        app.processEvents()
        assert started == [] and opened == [updates.PAGE] and not list((data / "updates").glob("*"))
    finally:
        win.close()
        i18n.set_language("en")
