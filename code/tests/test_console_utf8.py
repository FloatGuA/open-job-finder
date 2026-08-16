"""控制台编码：Windows 上 stdout 默认 GBK，而 agent 的输出里什么字符都可能有。

**这组测试的来历是一次真实的全损**（2026-08-16 首次从 Dashboard 跑 m1）：agent
说了一句带 ✅ 的话，`_trace` 的 print 抛 `UnicodeEncodeError`，异常冒泡打死了
`find_jobs` 节点——**已经找到并 record 的 8 个岗位全部丢失**，库里一条没有。

`scripts/run_layer1.py` 早就有一行 `sys.stdout.reconfigure(encoding="utf-8")`，
但从 Dashboard 跑走的是 uvicorn 进程，没有那一行——同一件事两份实现、其中一份
漏了，正是本项目记过案的形状。
"""
import io

import pytest

from multisite import agent_runtime
from services.console_utf8 import force_utf8_stdout


def _gbk_stream() -> io.TextIOWrapper:
    """一个跟 Windows 默认控制台一样的 GBK 流。"""
    return io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")


class TestForceUtf8Stdout:
    def test_switches_a_gbk_stream_to_utf8(self):
        stream = _gbk_stream()
        force_utf8_stdout(stream)
        assert (stream.encoding or "").lower().replace("-", "") == "utf8"

    def test_emoji_survives_after_the_switch(self):
        stream = _gbk_stream()
        force_utf8_stdout(stream)
        stream.write("✅ 完成")   # 修之前这一行就是崩溃点
        stream.flush()

    def test_is_a_noop_on_a_stream_that_is_already_utf8(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        force_utf8_stdout(stream)
        assert (stream.encoding or "").lower().replace("-", "") == "utf8"

    def test_survives_a_stream_that_cannot_be_reconfigured(self):
        """有些环境里 stdout 不是 TextIOWrapper（被测试框架/日志库换掉了）。
        修编码是**锦上添花**，它自己绝不能成为新的崩溃点。"""
        class Weird:
            encoding = "gbk"

        force_utf8_stdout(Weird())   # 不抛就算过


class TestTraceNeverKillsTheRun:
    """**日志不该有杀死流程的权力。** 这是与编码修复并列的第二道防线：编码修好了，
    换一个终端、换一个重定向目标，照样可能有写不出去的字符。"""

    def test_unencodable_output_does_not_raise(self, monkeypatch, capsys):
        from langchain_core.messages import AIMessage

        monkeypatch.setattr("sys.stdout", _gbk_stream())
        # 不抛就算过：真实场景里这一抛就打死了整个 find_jobs 节点
        agent_runtime._trace(AIMessage(content="✅ 已记录 8 个岗位"), 12)

    def test_normal_output_still_gets_printed(self, capsys):
        from langchain_core.messages import AIMessage

        agent_runtime._trace(AIMessage(content="hello"), 3)
        assert "hello" in capsys.readouterr().out
