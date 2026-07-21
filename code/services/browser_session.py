"""Single owner of the interactive automation browser.

The dashboard's interactive endpoints (open a conversation in Boss, browse a
URL) used to each spin up / reuse a legacy ``BrowserAgent`` with its OWN browser
launch and its OWN ``_assert_logged_in`` check — a second, divergent copy of
logic that already lived (hardened) in the W1/W2 pipeline path. That duplication
is exactly why a fix to one path (e.g. the retrying, expired-vs-hiccup-aware
``VerifySessionStep``) never reached the other, and why "session expired" was
reported when the session was perfectly valid.

``BrowserSession`` collapses that: ONE browser launch (reuses
``browser_context.open_browser`` — the same one the pipelines use) and ONE
session check (``VerifySessionStep`` — the same hardened one). Interactive
endpoints go through here instead of touching DrissionPage / BrowserAgent
directly, so a fix lands in one place for everyone.
"""
import logging
from pathlib import Path

from pipeline.base import StepStatus
from pipeline.common.verify_session import VerifySessionStep
from services.browser_context import close_browser, open_browser

logger = logging.getLogger(__name__)


class BrowserSession:
    """Owns a single, lazily-opened interactive ChromiumPage.

    Headed by default: interactive actions (open this conversation) are meant to
    be watched by the user. The page is reopened transparently if it died — e.g.
    a pipeline run's ``_kill_stale_chrome`` reclaimed the shared profile.
    """

    def __init__(self, data_dir: Path, headless: bool = False):
        self._data_dir = data_dir
        self._headless = headless
        self._page = None

    def is_open(self) -> bool:
        """Whether a live browser is currently open (no side effects)."""
        return self._is_alive()

    def _is_alive(self) -> bool:
        if self._page is None:
            return False
        try:
            _ = self._page.url
            return True
        except Exception:
            return False

    def get_page(self):
        """Return a live ChromiumPage, (re)opening the shared browser if needed."""
        if not self._is_alive():
            self._page = open_browser(self._data_dir, headless=self._headless)
        return self._page

    def verify(self) -> dict:
        """Hardened logged-in check, shared with W1/W2.

        Returns ``{ok, code, reason, username}``. ``code`` is "" when logged in,
        else ``session_expired`` (real logout) or ``verify_error`` (browser/page
        hiccup) so callers can show the user an accurate message instead of a
        blanket "session expired".
        """
        out = VerifySessionStep(self.get_page()).run()
        ok = out.status == StepStatus.SUCCESSFUL
        return {
            "ok": ok,
            "code": "" if ok else (out.error or "verify_error"),
            "reason": out.reason,
            "username": out.username,
        }

    def close(self) -> None:
        if self._page is not None:
            close_browser(self._page)
            self._page = None
