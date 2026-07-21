import time
from dataclasses import dataclass, field

from pipeline.base import StepOutput, StepStatus

_PERSONAL_URL = "https://www.zhipin.com/web/geek/recommend"
_REDIRECT_TIMEOUT = 12  # seconds to wait for page to settle


@dataclass
class VerifySessionOutput(StepOutput):
    username: str = ""
    reason: str = ""


class VerifySessionStep:
    """Check whether the current Boss直聘 browser session is still logged in.

    Navigates to the personal recommend page and reads window._PAGE.name via JS.
    Returns SUCCESSFUL with username if logged in, FAILED with reason if not.
    """

    def __init__(self, page):
        self._page = page

    def run(self) -> VerifySessionOutput:
        # The browser is a system boundary: a headless Chrome launch/connection can
        # transiently throw a no-message error or load a half-rendered page. That once
        # aborted a W1 run with a MISLEADING empty-reason "session invalid" even though
        # the session was perfectly valid (a headed re-check passed immediately). So:
        #   - a genuine logout (redirected away from the personal page) is returned at
        #     once as `session_expired` and never retried;
        #   - a transient/ambiguous failure (exception, or page loaded without user info)
        #     is retried once, then reported as `verify_error` with a NON-EMPTY reason so
        #     callers can tell "logged out" apart from "browser hiccup".
        last_reason = "verify failed"
        for attempt in range(2):
            try:
                self._page.get(_PERSONAL_URL, timeout=20)
                time.sleep(_REDIRECT_TIMEOUT)

                current_url = self._page.url or ""
                if "geek/recommend" not in current_url:
                    # Record the URL we actually landed on. A logged-in account can be
                    # bounced to a DIFFERENT authenticated path (Boss redesign / activity
                    # page / a slow interstitial), which is NOT a logout — but the old
                    # dead-string reason hid where we went, so a false "expired" was
                    # unfalsifiable. Surfacing the URL makes the next occurrence diagnosable.
                    return VerifySessionOutput(
                        status=StepStatus.FAILED,
                        reason=f"redirected away from recommend page (now at: {current_url or 'unknown'}) — session may be expired",
                        error="session_expired",
                    )

                raw_name = self._page.run_js(
                    "return (window._PAGE && window._PAGE.name != null)"
                    " ? String(window._PAGE.name) : '';"
                )
                username = (raw_name or "").strip()
                if username:
                    return VerifySessionOutput(status=StepStatus.SUCCESSFUL, username=username)

                last_reason = "page loaded but user info not found"
            except Exception as exc:
                msg = str(exc).strip() or f"{type(exc).__name__} (no message)"
                last_reason = f"browser/page error: {msg}"

            if attempt == 0:
                time.sleep(2)  # brief backoff before the single retry

        return VerifySessionOutput(
            status=StepStatus.FAILED,
            reason=last_reason,
            error="verify_error",
        )
