# Task 014 — Chat Agent（终端对话式求职助手）

## 目标

为 OpenJobFinder 添加 `python main.py --chat` 终端对话模式。用户用自然语言驱动求职工作流，系统具备分层记忆（短期/长期）。

核心原则：**LLM 只做意图识别和文本生成，所有调度和控制流由代码实现。**

---

## 新增文件

### 1. `services/intent_classifier.py`

意图识别模块，调用 Ollama（qwen3:8b），输出结构化 Intent。

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Intent:
    type: str          # apply | check | summary | query | remember | config | chitchat | unknown
    params: dict = field(default_factory=dict)
    confidence: str = "high"   # high | low


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

RULE_BASED_KEYWORDS = {
    "apply": ["投递", "投岗位", "搜索", "投简历", "找工作", "开始投"],
    "check": ["检查", "查看回复", "HR回", "有没有回", "应聘进度", "回复"],
    "summary": ["统计", "汇报", "投了多少", "今天", "状态"],
    "remember": ["记住", "记一下", "别忘了"],
    "config": ["修改", "改一下", "设置", "更新配置"],
}
```

实现 `classify(user_input: str, ollama_client) -> Intent`：
1. 调用 Ollama（model=qwen3:8b，options={"think": False}），解析 JSON 输出
2. 解析失败或 Ollama 不可用时，走规则匹配兜底（遍历 RULE_BASED_KEYWORDS，任意关键词命中即返回对应 type，confidence="low"）
3. 都不匹配返回 `Intent(type="unknown")`

Ollama 调用使用 `requests` 库直接调 `http://localhost:11434/api/chat`，不引入额外 SDK。

---

### 2. `services/memory_manager.py`

长/短期记忆读写。

```python
import json
import yaml
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path("data/memory")
LONG_TERM_PATH = MEMORY_DIR / "long_term.yaml"
SESSIONS_DIR = MEMORY_DIR / "sessions"
MAX_RECENT = 20          # recent 超过此值触发压缩
COMPRESS_BATCH = 10      # 每次压缩最早的 N 轮
```

**MemoryManager 类**，实现以下方法：

`load_long_term() -> str`
- 读取 long_term.yaml，格式化为纯文本块（供 system prompt 注入）
- 文件不存在时返回空字符串

`save_long_term(fact: str, category: str) -> None`
- category 必须是 preferences / constraints / context 之一，否则默认 context
- 追加写入，格式：`{fact: ..., added_at: YYYY-MM-DD, source: user_stated}`
- 首次调用时自动创建文件和目录

`new_session() -> dict`
- 返回空 session 对象：`{session_id, started_at, summary: "", recent: []}`
- session_id 格式：`YYYY-MM-DD_HH-MM-SS`

`load_today_session() -> dict | None`
- 扫描 SESSIONS_DIR，找今天（YYYY-MM-DD 前缀）最新的 session 文件
- 找到则加载并返回，找不到返回 None

`append_message(session: dict, role: str, content: Any) -> None`
- 追加到 session["recent"]，content 可以是 str 或 dict
- 触发检查：if len(recent) > MAX_RECENT，调用 _compress(session, ollama_client=None)

`_compress(session: dict, ollama_client=None) -> None`
- 取 recent 最早的 COMPRESS_BATCH 轮
- 如果 ollama_client 不为 None，调用 LLM 生成摘要，合并到 session["summary"]
- 如果 ollama_client 为 None，直接把这几轮拼成文本追加到 summary
- 从 recent 中删除这 COMPRESS_BATCH 轮

`save_session(session: dict) -> None`
- 写入 SESSIONS_DIR/{session_id}.json

`get_context_messages(session: dict) -> list[dict]`
- 返回供 Ollama 调用的 messages 列表（OpenAI 格式）
- 如果 summary 非空：插入一条 role=assistant 的摘要消息（"[之前的对话摘要] ..."）
- 追加 recent 中的所有消息

---

### 3. `services/tool_guard.py`

副作用操作执行前的权限校验。

```python
from dataclasses import dataclass

@dataclass
class GuardResult:
    ok: bool
    reason: str = ""

    @staticmethod
    def OK() -> "GuardResult":
        return GuardResult(ok=True)

    @staticmethod
    def BLOCKED(reason: str) -> "GuardResult":
        return GuardResult(ok=False, reason=reason)
```

**ToolGuard 类**，接收 `orchestrator` 和 `state`（ConversationState）：

`check_apply(state) -> GuardResult`
- state.awaiting_confirmation 为 False → BLOCKED("请先确认配置后再执行")
- orchestrator.tracker.count_today() >= orchestrator.daily_limit → BLOCKED(f"今日投递已达上限 {limit} 个")
- rate_limiter.is_exceeded()（如果存在）→ BLOCKED("已超过频率限制")
- 全部通过 → OK

`check_responses(state) -> GuardResult`
- state.awaiting_confirmation 为 False → BLOCKED("请先确认配置后再执行")
- 全部通过 → OK

`check_remember(fact: str) -> GuardResult`
- fact 为空 → BLOCKED("没有可记录的内容")
- 全部通过 → OK

---

### 4. `agent_workflows.py`（放在 code/ 根目录）

Workflow 注册表 + pre_flight 读取配置的工具函数。

```python
import yaml

WORKFLOW_REGISTRY = {
    "apply": {
        "description": "搜索并自动投递职位",
        "trigger_intents": ["apply"],
        "config_source": "profile",
        "config_fields": [
            "keywords", "cities", "job_type", "experience",
            "degree", "salary", "boss_online", "score_threshold"
        ],
        "requires_confirmation": True,
        "guard": "check_apply",
    },
    "check": {
        "description": "检查 HR 聊天回复并更新状态",
        "trigger_intents": ["check"],
        "config_source": "config",
        "config_fields": ["check_responses_days", "check_responses_max"],
        "requires_confirmation": True,
        "guard": "check_responses",
    },
    "summary": {
        "description": "查看今日投递统计",
        "trigger_intents": ["summary"],
        "config_source": None,
        "requires_confirmation": False,
        "guard": None,
    },
}


def read_profile() -> dict:
    """读取 data/profile.yaml，不存在时返回空 dict。"""
    path = "data/profile.yaml"
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def update_profile(field: str, value) -> bool:
    """更新 profile.yaml 中的单个字段，返回是否成功。"""
    ...


def read_config() -> dict:
    """读取 config.yaml，返回 schedule 和 apply 相关字段。"""
    ...


def format_config_for_display(workflow_key: str) -> str:
    """
    读取指定 workflow 所需的配置，格式化成人类可读的文本。
    例如 workflow_key="apply" 时返回：
    关键词：AI / 城市：深圳 / 类型：实习 / 学历：硕士 / score_threshold：50 / 仅活跃HR：是
    """
    ...
```

---

### 5. `services/chat_agent.py`

对话主循环 + 状态机。

```python
from dataclasses import dataclass, field

@dataclass
class ConversationState:
    pending_workflow: str | None = None   # "apply" | "check" | None
    awaiting_confirmation: bool = False
    last_config_shown: dict = field(default_factory=dict)
```

**ChatAgent 类**，构造函数接收 `orchestrator`：

`__init__(self, orchestrator)`
- 初始化 MemoryManager、IntentClassifier、ToolGuard
- 加载长期记忆
- 加载今天的 session（没有则新建）
- 初始化 ConversationState

`run(self) -> None`
- 打印欢迎语（展示当前基本状态：今日投递数、是否有待检查回复等，用 daily_summary 获取）
- 进入循环：`while True: input("> ")`
- 用户输入 exit/quit/bye/再见/结束 → 调 `_end_session()` 退出
- 否则调 `handle(user_input)`，打印返回的响应

`handle(self, user_input: str) -> str`
- 核心路由方法，返回要展示给用户的字符串
- 逻辑：

```
if state.awaiting_confirmation:
    if 用户说肯定词（好/是/可以/确认/行/嗯/开始/去吧）:
        return _execute_pending()
    elif 用户说否定词（不/取消/算了/改一下）:
        state 清零, return "已取消。"
    else:
        # 用户在确认阶段说了其他话（如修改配置）
        # 先处理用户的话，再重新展示配置等待确认
        pass

intent = classifier.classify(user_input)

if intent.type == "apply":
    return _pre_flight("apply")
elif intent.type == "check":
    return _pre_flight("check")
elif intent.type == "summary":
    return _run_summary()
elif intent.type == "query":
    return _run_query(intent.params)
elif intent.type == "remember":
    return _run_remember(intent.params)
elif intent.type == "config":
    return _run_config(intent.params)
elif intent.type == "chitchat":
    return _run_chitchat(user_input)
else:
    return "没有理解你的意思，你可以说：投几个岗位 / 检查回复 / 查看统计"
```

`_pre_flight(self, workflow_key: str) -> str`
- 从 WORKFLOW_REGISTRY 读取 workflow 配置
- 调用 `format_config_for_display(workflow_key)` 读取当前配置
- 设置 state.pending_workflow / state.awaiting_confirmation = True
- 返回配置展示文本 + "这些参数没问题吗？（直接回车或说"好"确认）"

`_execute_pending(self) -> str`
- 取 state.pending_workflow，运行对应 guard
- guard BLOCKED → 返回 blocked reason，state 清零
- guard OK → 执行 workflow，格式化结果返回，state 清零

`_run_summary(self) -> str`
- 调用 orchestrator.daily_summary()
- 格式化返回（不走 LLM，直接模板化）

`_run_query(self, params: dict) -> str`
- 调用 tracker.get_by_status(params.get("status")) 或 get_all()
- 最多展示 10 条，格式：`公司名 — 职位名 — 状态`

`_run_remember(self, params: dict) -> str`
- ToolGuard.check_remember(fact)
- OK → memory_manager.save_long_term(fact, category)
- 返回 "已记住：{fact}"

`_run_config(self, params: dict) -> str`
- 调用 update_profile(field, value)
- 返回 "已更新 {field} = {value}"

`_run_chitchat(self, user_input: str) -> str`
- 用 Ollama 生成自然语言回复（带长期记忆上下文）
- 这是唯一一个"纯聊天"路径，LLM 可以自由发挥

`_end_session(self) -> None`
- save_session(session)
- 打印 "再见！今日已投递 N 个职位。"

---

## 修改文件

### `main.py`

在 argparse 中加 `--chat` 参数：

```python
parser.add_argument("--chat", action="store_true", help="启动对话式 Agent")
```

处理逻辑（在现有 if/elif 链中加）：

```python
if args.chat:
    from services.chat_agent import ChatAgent
    orchestrator = _build_orchestrator(config, tracker, llm_clients)
    agent = ChatAgent(orchestrator)
    agent.run()
```

其中 `_build_orchestrator` 是从现有 main.py 提取的 Orchestrator 构造逻辑（如果已有则直接复用）。

---

## 依赖

`requests` 已在 requirements.txt 中（DrissionPage 依赖它）。无需新增依赖。

---

## 不需要实现的

- Ollama 流式输出（非必需）
- Session 结束时自动提取长期记忆（设计上禁止）
- Dashboard 聊天界面（本 task 只做 CLI）

---

## 验收标准

1. `python main.py --chat` 启动，打印欢迎语和今日统计
2. 用户说"检查回复" → 展示当前 check_responses 配置 → 用户确认 → 执行 orchestrator.check_responses() → 打印结果摘要
3. 用户说"帮我投岗位" → 展示 profile 配置 → 用户修改关键词 → 重新展示 → 用户确认 → 执行 run_once() → 打印结果
4. 用户说"记住我不考虑外包" → long_term.yaml 新增对应条目
5. 用户说 exit → 保存 session，正常退出
6. Ollama 不可用时，意图识别降级为规则匹配，不崩溃
7. 连续执行两次 apply，第二次被 daily_limit guard 拦截（dry_run 下模拟）
