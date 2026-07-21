"""
Chat Agent: terminal-based conversational interface for OpenJobFinder.

Architecture:
  User input → Intent Classifier (LLM/rules) → Intent Router (code) →
  Flow Handler (code) → Tool Guard → Workflow Executor → Response

LLM is only used for intent classification and chitchat.
All routing, state management, and workflow execution are code-controlled.
"""
import json
from dataclasses import dataclass, field

import requests

from agent_workflows import (
    WORKFLOW_REGISTRY,
    format_config_for_display,
    read_config,
    update_profile,
)
from services.intent_classifier import IntentClassifier
from services.memory_manager import MemoryManager
from services.tool_guard import ToolGuard

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"

SYSTEM_PROMPT_CORE = """\
你是用户的求职助手，帮助管理 Boss直聘 的自动投递流程。
回复用中文，简洁直接。不要逐行复读原始数据，用一两句话汇报关键结果。
用户说"取消"或"算了"时，停止当前操作。
"""


@dataclass
class ConversationState:
    pending_workflow: str | None = None
    awaiting_confirmation: bool = False
    last_config_shown: str = ""

    def reset(self) -> None:
        self.pending_workflow = None
        self.awaiting_confirmation = False
        self.last_config_shown = ""


class ChatAgent:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.memory = MemoryManager()
        self.classifier = IntentClassifier()
        self.guard = ToolGuard(orchestrator)
        self.state = ConversationState()

        self.long_term = self.memory.load_long_term()
        session = self.memory.load_today_session()
        self.session = session if session is not None else self.memory.new_session()

    # ── Public interface ────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the interactive CLI loop."""
        self._print_welcome()
        try:
            while True:
                try:
                    user_input = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if user_input.lower() in ("exit", "quit", "bye", "再见", "结束", "退出"):
                    break

                response = self.handle(user_input)
                print(f"\n{response}")
        finally:
            self._end_session()

    def handle(self, user_input: str) -> str:
        """Route user input and return a response string. Pure code control flow."""
        self.memory.append_message(self.session, "user", user_input)

        # ── Confirmation state: user is responding to a pre-flight prompt ──
        if self.state.awaiting_confirmation:
            if self.classifier.is_confirm(user_input):
                response = self._execute_pending()
            elif self.classifier.is_cancel(user_input):
                self.state.reset()
                response = "已取消。"
            else:
                # User said something else (e.g. wants to change a config field)
                # Handle it first, then re-show config
                inner = self._route_intent(user_input)
                if inner:
                    config_display = format_config_for_display(self.state.pending_workflow)
                    self.state.last_config_shown = config_display
                    response = f"{inner}\n\n当前配置：{config_display}\n这些参数没问题吗？"
                else:
                    response = self._route_intent(user_input) or '没有理解，请说"好"确认或"取消"放弃。'
        else:
            response = self._route_intent(user_input)

        self.memory.append_message(self.session, "assistant", response)
        return response

    # ── Intent routing ──────────────────────────────────────────────────────

    def _route_intent(self, user_input: str) -> str:
        intent = self.classifier.classify(user_input)

        if intent.type == "apply":
            return self._pre_flight("apply")
        elif intent.type == "check":
            return self._pre_flight("check")
        elif intent.type == "summary":
            return self._run_summary()
        elif intent.type == "query":
            return self._run_query(intent.params)
        elif intent.type == "remember":
            if not intent.params.get("fact"):
                # Rule-based path doesn't extract params; try simple extraction
                for kw in ("记住", "记一下", "别忘了"):
                    if kw in user_input:
                        fact = user_input[user_input.index(kw) + len(kw):].strip().lstrip("，,：: ")
                        if fact:
                            intent.params["fact"] = fact
                            intent.params.setdefault("category", "context")
                        break
            return self._run_remember(intent.params)
        elif intent.type == "config":
            return self._run_config(intent.params)
        elif intent.type == "chitchat":
            return self._run_chitchat(user_input)
        else:
            return "没有理解你的意思，你可以说：投几个岗位 / 检查回复 / 查看统计"

    # ── Flow handlers ───────────────────────────────────────────────────────

    def _pre_flight(self, workflow_key: str) -> str:
        config_display = format_config_for_display(workflow_key)
        wf = WORKFLOW_REGISTRY[workflow_key]
        self.state.pending_workflow = workflow_key
        self.state.awaiting_confirmation = True
        self.state.last_config_shown = config_display

        base = f"[{wf['description']}] 当前配置：\n{config_display}\n\n"

        # For check workflow: run a quick scan to show unread stats upfront
        if workflow_key == "check":
            try:
                scan = self.orchestrator.check_responses(scan_only=True)
                new_hr = scan.get("new_hr_msgs", 0)
                unread = scan.get("unread_count", 0)
                total = scan.get("total_convs", 0)
                if new_hr:
                    companies = "、".join(
                        item["company"]
                        for item in scan.get("needs_sync", [])[:3]
                        if item.get("company")
                    )
                    suffix = "等" if new_hr > 3 else ""
                    base += (
                        f"扫描到 {total} 个会话，{unread} 个未读，"
                        f"{new_hr} 个 HR 有新消息（{companies}{suffix}）。\n"
                        "是否点进这些会话读取完整内容？"
                    )
                else:
                    base += f"扫描到 {total} 个会话，暂无新 HR 消息。是否继续完整检查？"
            except Exception:
                base += '是否继续？（说"好"确认，说"取消"放弃）'
            return base

        return base + '这些参数没问题吗？（说"好"确认，说"取消"放弃）'

    def _execute_pending(self) -> str:
        workflow_key = self.state.pending_workflow
        self.state.reset()

        guard_name = WORKFLOW_REGISTRY[workflow_key].get("guard")
        if guard_name:
            guard_fn = getattr(self.guard, guard_name, None)
            if guard_fn:
                # Pass a temporary state with awaiting_confirmation=True for the guard check
                class _ConfirmedState:
                    awaiting_confirmation = True
                result = guard_fn(_ConfirmedState())
                if not result.ok:
                    return f"无法执行：{result.reason}"

        try:
            if workflow_key == "apply":
                summary = self.orchestrator.run_once()
                return (
                    f"投递完成：搜索 {summary.get('searched', 0)} 个职位，"
                    f"投递 {summary.get('applied', 0)} 个，"
                    f"跳过 {summary.get('skipped', 0)} 个。"
                )
            elif workflow_key == "check":
                result = self.orchestrator.check_responses()
                checked = result.get("checked", 0)
                new_hr = result.get("new_hr_msgs", 0)
                synced = result.get("synced_conversations", [])
                if new_hr:
                    companies = "、".join(c.get("company", "?") for c in synced[:3])
                    suffix = "等" if new_hr > 3 else ""
                    last_msgs = "\n".join(
                        f"  · {c.get('company','?')}：{c.get('last_msg','')[:30]}"
                        for c in synced[:3]
                    )
                    return (
                        f"检查完成：扫描 {checked} 条对话，同步 {new_hr} 个 HR 新消息"
                        f"（{companies}{suffix}）。\n{last_msgs}"
                    )
                return f"检查完成：扫描 {checked} 条对话，暂无新 HR 消息。"
            elif workflow_key == "summary":
                return self._run_summary()
            else:
                return f"未知 workflow: {workflow_key}"
        except Exception as exc:
            return f"执行失败：{exc}"

    def _run_summary(self) -> str:
        try:
            s = self.orchestrator.daily_summary()
            return (
                f"今日投递 {s['applied_today']}/{s['daily_limit']}，"
                f"累计 {s['total_applied']} 个；"
                f"已回复 {s['responded']} 个，面试 {s['interviews']} 个，Offer {s['offers']} 个。"
            )
        except Exception as exc:
            return f"获取统计失败：{exc}"

    def _run_query(self, params: dict) -> str:
        status = params.get("status")
        try:
            from schemas import AppStatus
            if status:
                try:
                    records = self.orchestrator.tracker.get_by_status(AppStatus(status))
                except ValueError:
                    records = self.orchestrator.tracker.get_all()
            else:
                records = self.orchestrator.tracker.get_all()

            if not records:
                return "暂无相关职位记录。"
            lines = [f"{r.company} — {r.title} — {r.status}" for r in records[:10]]
            suffix = f"（共 {len(records)} 条，仅展示前 10）" if len(records) > 10 else ""
            return "\n".join(lines) + suffix
        except Exception as exc:
            return f"查询失败：{exc}"

    def _run_remember(self, params: dict) -> str:
        fact = params.get("fact", "").strip()
        category = params.get("category", "context")
        result = self.guard.check_remember(fact)
        if not result.ok:
            return result.reason
        self.memory.save_long_term(fact, category)
        self.long_term = self.memory.load_long_term()  # refresh
        return f"已记住：{fact}"

    def _run_config(self, params: dict) -> str:
        field_name = params.get("field", "").strip()
        value = params.get("value")
        if not field_name:
            return "请告诉我要修改哪个配置项，例如：把关键词改成 AI 算法"
        success = update_profile(field_name, value)
        if success:
            # If we're mid-confirmation, re-show config
            if self.state.awaiting_confirmation and self.state.pending_workflow:
                return f"已更新 {field_name} = {value}"
            return f"已更新 {field_name} = {value}"
        return f"更新失败，请检查 data/profile.yaml 是否存在。"

    def _run_chitchat(self, user_input: str) -> str:
        """Only path where LLM generates free-form response."""
        try:
            system = SYSTEM_PROMPT_CORE
            if self.long_term:
                system += f"\n\n== 用户记忆 ==\n{self.long_term}"

            context_msgs = self.memory.get_context_messages(self.session)
            messages = [{"role": "system", "content": system}] + context_msgs

            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"think": False},
            }
            resp = requests.post(OLLAMA_URL, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception:
            return "你好！我可以帮你投递职位、检查 HR 回复或查看统计数据。"

    # ── Session lifecycle ───────────────────────────────────────────────────

    def _print_welcome(self) -> None:
        print("\n=== OpenJobFinder 求职助手 ===")
        print("你可以说：投几个岗位 / 检查回复 / 查看统计 / 记住 xxx / exit 退出")
        try:
            s = self.orchestrator.daily_summary()
            print(
                f"今日已投递 {s['applied_today']}/{s['daily_limit']}，"
                f"剩余名额 {s['remaining']} 个。"
            )
        except Exception:
            pass
        if self.session.get("summary") or self.session.get("recent"):
            print("（已加载今日会话记录）")

    def _end_session(self) -> None:
        self.memory.save_session(self.session)
        try:
            s = self.orchestrator.daily_summary()
            print(f"\n再见！今日已投递 {s['applied_today']} 个职位。")
        except Exception:
            print("\n再见！")
