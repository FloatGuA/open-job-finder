"""
Intent classifier: uses Ollama (qwen3:8b) to classify user input into structured Intent.
Falls back to rule-based keyword matching when Ollama is unavailable.
"""
import json
from dataclasses import dataclass, field

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"

INTENT_SYSTEM_PROMPT = """\
你是意图识别模块，只输出 JSON，不输出任何其他内容。

可识别的 type：
- apply：用户想搜索和投递职位
- check：用户想查看 HR 聊天回复
- summary：用户想查看今日投递统计
- query：用户想查询某类职位列表，params 包含 status（可选）
- remember：用户明确要求记住某件事，params 包含 fact 和 category（preferences/constraints/context）
- config：用户想修改配置项，params 包含 field 和 value
- chitchat：闲聊、确认、取消等
- unknown：无法识别

输出格式（严格 JSON，不加注释）：
{"type": "...", "params": {}, "confidence": "high"}
"""

RULE_BASED_KEYWORDS: dict[str, list[str]] = {
    "apply": ["投递", "投岗位", "搜索", "投简历", "找工作", "开始投", "投几个", "帮我投"],
    "check": ["检查", "查看回复", "hr回", "有没有回", "应聘进度", "回复", "进度", "有没有消息"],
    "summary": ["统计", "汇报", "投了多少", "状态", "今天投", "多少个"],
    "remember": ["记住", "记一下", "别忘了"],
    "config": ["修改", "改一下", "设置", "更新配置", "把", "改成"],
}

CONFIRM_WORDS = {"好", "是", "可以", "确认", "行", "嗯", "开始", "去吧", "没问题", "ok", "yes", "确定", ""}
CANCEL_WORDS = {"不", "取消", "算了", "停", "不要", "no", "cancel"}


@dataclass
class Intent:
    type: str  # apply | check | summary | query | remember | config | chitchat | unknown
    params: dict = field(default_factory=dict)
    confidence: str = "high"  # high | low


class IntentClassifier:
    def __init__(self, model: str = OLLAMA_MODEL):
        self.model = model
        self._ollama_available: bool | None = None  # None = unknown

    def classify(self, user_input: str) -> Intent:
        """Classify user input. Falls back to rule-based if Ollama unavailable."""
        text = user_input.strip()
        if not text:
            return Intent(type="chitchat")

        if self._ollama_available is not False:
            result = self._classify_llm(text)
            if result is not None:
                self._ollama_available = True
                return result
            self._ollama_available = False

        return self._classify_rules(text)

    def _classify_llm(self, text: str) -> Intent | None:
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {"think": False},
            }
            resp = requests.post(OLLAMA_URL, json=payload, timeout=10)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()
            # Strip markdown code block if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            data = json.loads(content)
            return Intent(
                type=data.get("type", "unknown"),
                params=data.get("params", {}),
                confidence=data.get("confidence", "high"),
            )
        except Exception:
            return None

    def _classify_rules(self, text: str) -> Intent:
        lower = text.lower()
        for intent_type, keywords in RULE_BASED_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return Intent(type=intent_type, params={}, confidence="low")
        return Intent(type="unknown", confidence="low")

    def is_confirm(self, text: str) -> bool:
        return text.strip().lower() in CONFIRM_WORDS or text.strip() == ""

    def is_cancel(self, text: str) -> bool:
        return any(w in text.strip().lower() for w in CANCEL_WORDS)
