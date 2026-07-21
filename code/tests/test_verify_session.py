"""Unit tests for VerifySessionStep.

Guards the fix for a misleading failure: a no-message browser/page error in a
headless run reported an EMPTY-reason "session invalid", which looked like a
logout (it was not -- a headed re-check passed). The step must now:
  - return a username when logged in,
  - report a genuine logout (redirect) as `session_expired` without retrying,
  - report a transient/ambiguous failure as `verify_error` with a NON-EMPTY
    reason, after retrying once.
"""
import pytest

import pipeline.common.verify_session as vs
from pipeline.common.verify_session import VerifySessionStep
from pipeline.base import StepStatus

_RECOMMEND = "https://www.zhipin.com/web/geek/recommend"
_LOGIN = "https://www.zhipin.com/web/user/?ka=header-login"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(vs.time, "sleep", lambda *a, **k: None)


class FakePage:
    def __init__(self, url=_RECOMMEND, name="浮瓜", get_exc=None):
        self._url = url
        self._name = name
        self._get_exc = list(get_exc) if get_exc else None  # per-attempt exception or None
        self.get_calls = 0
        self.url = url

    def get(self, url, timeout=None):
        i = self.get_calls
        self.get_calls += 1
        if self._get_exc and i < len(self._get_exc) and self._get_exc[i] is not None:
            raise self._get_exc[i]
        self.url = self._url

    def run_js(self, script):
        return self._name


def test_valid_session_returns_username():
    out = VerifySessionStep(FakePage(name="浮瓜")).run()
    assert out.status == StepStatus.SUCCESSFUL
    assert out.username == "浮瓜"


def test_redirect_is_session_expired_and_not_retried():
    page = FakePage(url=_LOGIN, name="")
    out = VerifySessionStep(page).run()
    assert out.status == StepStatus.FAILED
    assert out.error == "session_expired"
    assert page.get_calls == 1  # a confirmed logout must not be retried


def test_empty_message_exception_yields_nonempty_verify_error():
    class _Boom(Exception):
        def __str__(self):  # the actual culprit: a no-message browser error
            return ""

    page = FakePage(get_exc=[_Boom(), _Boom()])
    out = VerifySessionStep(page).run()
    assert out.status == StepStatus.FAILED
    assert out.error == "verify_error"          # NOT session_expired
    assert out.reason.strip()                    # reason is never empty
    assert "no message" in out.reason
    assert page.get_calls == 2                   # retried once


def test_transient_error_then_success_via_retry():
    page = FakePage(name="浮瓜", get_exc=[RuntimeError("net glitch"), None])
    out = VerifySessionStep(page).run()
    assert out.status == StepStatus.SUCCESSFUL
    assert out.username == "浮瓜"
    assert page.get_calls == 2
