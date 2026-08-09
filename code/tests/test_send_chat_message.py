"""Unit coverage for SendChatMessage.execute() -- the tool that decides whether a
W3 reply actually gets typed and submitted. Previously zero coverage: the only two
test files that mention it (test_chat_input_selector_convergence, test_w3_send_pipeline)
stub its ToolResult at the registry boundary and never exercise execute() itself, so
none of the branches below (input-not-found / text-not-set / button-vs-Enter submit)
were ever actually run by CI.
"""
from unittest.mock import MagicMock

import pytest

import tools.browser.w2.send_chat_message as scm
from tools.browser.w2.send_chat_message import SendChatMessage


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(scm, "_human_pause", lambda *a, **k: None)


def test_send_chat_message_browser_not_initialized():
    result = SendChatMessage(browser=None).execute(text="hi")
    assert result.ok is False
    assert result.error == "browser not initialized"


def test_send_chat_message_input_not_found(monkeypatch):
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: None)
    result = SendChatMessage(browser=MagicMock()).execute(text="hi")
    assert result.ok is False
    assert result.error == "chat input not found"


def test_send_chat_message_text_not_set_after_insert(monkeypatch):
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: MagicMock())
    page = MagicMock()
    # 1st run_js: insertText (return value unused); 2nd: textContent readback -> empty
    page.run_js.side_effect = [None, ""]
    result = SendChatMessage(browser=page).execute(text="hi")
    assert result.ok is False
    assert result.error == "text not set in input field"


def test_send_chat_message_submits_via_button(monkeypatch):
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: MagicMock())
    page = MagicMock()
    # insertText(unused) -> textContent readback("hi") -> button click(True) -> post-submit textContent("")
    page.run_js.side_effect = [None, "hi", True, ""]
    result = SendChatMessage(browser=page).execute(text="hi")
    assert result.ok is True
    assert result.data == {"submit": "button", "input_cleared": True}
    page.actions.key_down.assert_not_called()


def test_send_chat_message_falls_back_to_enter_when_button_unavailable(monkeypatch):
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: MagicMock())
    page = MagicMock()
    # button click JS returns False (no `button.btn-send`, e.g. older layout)
    page.run_js.side_effect = [None, "hi", False, ""]
    result = SendChatMessage(browser=page).execute(text="hi")
    assert result.ok is True
    assert result.data["submit"] == "enter"
    page.actions.key_down.assert_called_once_with("Enter")
    page.actions.key_down.return_value.key_up.assert_called_once_with("Enter")


def test_send_chat_message_input_not_cleared_after_submit(monkeypatch):
    """Proxy signal only -- caller's VerifyReplyDelivered is authoritative, but a
    non-empty box after submit (multi-line Enter inserted a newline instead of
    sending, the exact false-success this tool's docstring warns about) must still
    surface in the result data rather than being silently reported as delivered."""
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: MagicMock())
    page = MagicMock()
    page.run_js.side_effect = [None, "hi", True, "hi"]
    result = SendChatMessage(browser=page).execute(text="hi")
    assert result.ok is True
    assert result.data["input_cleared"] is False


def test_send_chat_message_unexpected_exception_is_caught(monkeypatch):
    monkeypatch.setattr(scm, "_ele_any", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = SendChatMessage(browser=MagicMock()).execute(text="hi")
    assert result.ok is False
    assert "boom" in result.error
