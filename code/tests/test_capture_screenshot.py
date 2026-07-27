"""Tests for the capture_screenshot browser tool (apply-failure diagnostics)."""
from tools.browser.w1.capture_screenshot import CaptureScreenshot, _safe


def test_safe_sanitizes_unsafe_chars():
    assert _safe("job/../etc") == "job____etc"  # / . . / -> 4 underscores
    assert _safe("abc-123_XY") == "abc-123_XY"
    assert _safe("") == "shot"
    assert len(_safe("x" * 200)) <= 60


def test_no_browser_returns_error():
    res = CaptureScreenshot(browser=None).execute(label="j1")
    assert not res.ok
    assert "browser not initialized" in res.error


class _FakeWindow:
    def __init__(self, page):
        self._page = page

    def max(self):
        self._page.maximized = True


class _FakeSetter:
    def __init__(self, page):
        self.window = _FakeWindow(page)


class _FakePage:
    def __init__(self):
        self.calls = []
        self.maximized = False
        self.set = _FakeSetter(self)

    def get_screenshot(self, path=None, name=None, full_page=False):
        self.calls.append((path, name, full_page))
        return f"{path}/{name}"


def test_captures_and_returns_filename(tmp_path, monkeypatch):
    import tools.browser.w1.capture_screenshot as mod
    monkeypatch.setattr(mod, "_SHOT_DIR", tmp_path / "apply_failures")
    page = _FakePage()
    res = CaptureScreenshot(browser=page).execute(label="job_42")
    assert res.ok
    name = res.data["screenshot"]
    assert name.startswith("job_42_") and name.endswith(".png")
    assert (tmp_path / "apply_failures").is_dir()
    assert page.calls and page.calls[0][1] == name
    # Window is maximized and the shot is full-page (so the apply button is in frame).
    assert page.maximized is True
    assert page.calls[0][2] is True


def test_screenshot_failure_is_caught(tmp_path, monkeypatch):
    import tools.browser.w1.capture_screenshot as mod
    monkeypatch.setattr(mod, "_SHOT_DIR", tmp_path / "apply_failures")

    class _BoomPage:
        def get_screenshot(self, **kw):
            raise RuntimeError("cdp down")

    res = CaptureScreenshot(browser=_BoomPage()).execute(label="j1")
    assert not res.ok
    assert "screenshot failed" in res.error
