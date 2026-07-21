"""GenerateReply drafts an HR reply with think=True (deliberate wording), separate
from intent classification which runs think=False. Also guards that OllamaProvider
threads the think flag into its request payload."""
from unittest.mock import MagicMock, patch

from services.llm_client import OllamaProvider
from services.prompt_manager import PromptManager
from tools.llm.generate_reply import GenerateReply


class _FakeLLM:
    def __init__(self, reply="好的，我明天下午三点准时到，谢谢您。"):
        self.reply = reply
        self.calls = []

    def complete(self, prompt, system="", capability="balanced",
                 provider_name=None, output_schema=None, think=False):
        self.calls.append({"prompt": prompt, "system": system, "think": think})
        return self.reply, "ollama_qwen3:8b"


def test_generate_reply_uses_think_true_and_returns_draft():
    llm = _FakeLLM()
    tool = GenerateReply(llm, PromptManager())
    res = tool.execute(
        conv_id="c1",
        messages=[{"sender": "hr", "text": "明天下午三点来面试方便吗？"}],
        company="某公司",
        intent="interview_invite",
        job_title="工程师",
    )
    assert res.ok
    assert res.data["suggested_reply"] == llm.reply
    assert res.data["provider_used"] == "ollama_qwen3:8b"
    # reply drafting must deliberate over wording -> think=True
    assert llm.calls[0]["think"] is True
    # self-contained prompt, no job-agent system (which would demand JSON output)
    assert llm.calls[0]["system"] == ""
    # HR message + intent made it into the rendered prompt
    assert "明天下午三点" in llm.calls[0]["prompt"]
    assert "interview_invite" in llm.calls[0]["prompt"]


def test_generate_reply_empty_reply_fails():
    tool = GenerateReply(_FakeLLM(reply="   "), PromptManager())
    res = tool.execute(conv_id="c1", messages=[{"sender": "hr", "text": "hi"}], company="X")
    assert not res.ok
    assert "empty" in res.error


def test_ollama_provider_threads_think_into_payload():
    provider = OllamaProvider("qwen3:8b")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "hi"}

    with patch("services.llm_client.requests.post", return_value=mock_resp) as mp:
        provider.complete("p", think=True)
    assert mp.call_args.kwargs["json"]["think"] is True

    with patch("services.llm_client.requests.post", return_value=mock_resp) as mp:
        provider.complete("p")  # default
    assert mp.call_args.kwargs["json"]["think"] is False
