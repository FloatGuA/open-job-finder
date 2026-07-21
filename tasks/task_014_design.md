# Task 014 — Chat Agent 设计文档（v2）

## 核心原则

LLM 只做：意图识别、文本生成、局部决策（score/critic）
LLM 不做：调度、控制流、关键决策

---

## 正确分层架构

```
User Input
    ↓
[LLM] Intent Classifier     ← 只输出结构化 intent JSON，不执行任何操作
    ↓
Intent Router (代码)         ← 决定走哪个分支，完全由代码控制
    ↓
Flow Handler (代码)
    ├── pre_flight()         ← 读取配置，展示给用户
    ├── State Machine        ← 追踪 pending_action / confirmed 状态
    └── Tool Guard           ← 校验权限、频率限制后才执行
            ↓
        Workflow Executor    ← 调用现有 Orchestrator 方法
            ↓
        [LLM] Response Formatter  ← 仅将结果转成自然语言（复杂时才调用）
```

LLM 在整条链路中出现两次，但职责完全不同：
- 第一次：理解用户意图（输入自然语言，输出结构化 JSON）
- 第二次：格式化结果（输入工具返回数据，输出人话）
- 两次之间的所有逻辑全部是代码

---

## 意图层（Intent Layer）

### Intent 数据结构

```python
@dataclass
class Intent:
    type: str        # apply | check | summary | query | remember | config | chitchat | unknown
    params: dict     # 意图携带的参数，由 LLM 从用户输入中提取
    confidence: str  # high | low
```

### Intent 分类示例

| 用户说 | type | params |
|--------|------|--------|
| 帮我投几个岗位 | apply | {} |
| 投 AI 方向的岗位 | apply | {"hint": "AI 方向"} |
| 有没有 HR 回我 | check | {} |
| 检查最近 3 天的 | check | {"days": 3} |
| 今天投了多少 | summary | {} |
| 有哪些岗位在等待 | query | {"status": "applied"} |
| 记住我不考虑外包 | remember | {"fact": "不考虑外包公司", "category": "constraints"} |
| 把关键词改成 AI 算法 | config | {"field": "keywords", "value": ["AI 算法"]} |
| 你好 | chitchat | {} |

### LLM 调用方式（意图识别）

- 模型：qwen3:8b，think=False
- 输出格式：强制 JSON（在 prompt 中约定）
- Fallback：LLM 失败或解析失败 → 规则匹配（关键词匹配兜底）

```python
INTENT_SYSTEM_PROMPT = """
你是意图识别模块，只输出 JSON，不输出任何其他内容。

可识别的 type：
- apply：用户想搜索和投递职位
- check：用户想查看 HR 聊天回复
- summary：用户想查看今日投递统计
- query：用户想查询某类职位列表
- remember：用户明确要求记住某件事
- config：用户想修改某个配置项
- chitchat：闲聊或其他
- unknown：无法识别

输出格式：{"type": "...", "params": {...}, "confidence": "high|low"}
"""
```

---

## 对话状态机（Conversation State Machine）

每个 session 维护一个状态对象，防止多轮对话错乱：

```python
@dataclass
class ConversationState:
    pending_action: str | None = None   # 等待用户确认的操作 ("apply" | "check" | ...)
    pending_params: dict = field(default_factory=dict)
    awaiting_confirmation: bool = False
    last_config_shown: dict = field(default_factory=dict)  # 上次展示给用户的配置快照
```

### 状态流转

```
[idle]
  ↓ 用户触发 apply intent
[showing_config]     ← pre_flight：读取 profile.yaml，展示配置，等待确认
  ↓ 用户确认
[confirmed]          ← guard 通过后执行 workflow
  ↓ 执行完成
[idle]

用户在任意状态说"算了"/"取消" → 立即回到 [idle]
```

---

## Tool Guard 层

所有有副作用的操作在执行前必须经过 Guard：

```python
class ToolGuard:
    def check_apply(self, state: ConversationState) -> GuardResult:
        if not state.awaiting_confirmation or not state.confirmed:
            return GuardResult.BLOCKED("需要用户确认后才能执行投递")
        if rate_limiter.is_exceeded():
            return GuardResult.BLOCKED("已超过频率限制，请稍后再试")
        if tracker.count_today() >= daily_limit:
            return GuardResult.BLOCKED(f"今日投递已达上限 {daily_limit} 个")
        return GuardResult.OK

    def check_responses(self, state: ConversationState) -> GuardResult:
        if not state.awaiting_confirmation or not state.confirmed:
            return GuardResult.BLOCKED("需要用户确认")
        return GuardResult.OK
```

---

## Workflow 注册表（替代 Prompt 硬编码）

```python
WORKFLOW_REGISTRY = {
    "apply": {
        "description": "搜索并自动投递职位",
        "trigger_intents": ["apply"],
        "config_source": "profile",     # pre_flight 从哪里读配置
        "config_fields": ["keywords", "cities", "job_type", "experience",
                          "degree", "salary", "boss_online", "score_threshold"],
        "handler": "orchestrator.run_once",
        "requires_confirmation": True,
        "guard": "check_apply",
    },
    "check": {
        "description": "检查 HR 聊天回复并更新状态",
        "trigger_intents": ["check"],
        "config_source": "config",
        "config_fields": ["check_responses_days", "check_responses_max"],
        "handler": "orchestrator.check_responses",
        "requires_confirmation": True,
        "guard": "check_responses",
    },
    "summary": {
        "description": "查看今日投递统计",
        "trigger_intents": ["summary"],
        "config_source": None,
        "handler": "orchestrator.daily_summary",
        "requires_confirmation": False,
        "guard": None,
    },
}
```

新增 workflow 只需在 registry 里加一条，不需要改 prompt 或其他代码。

---

## 记忆分层设计

### 短期记忆（Session Memory）

**位置**：`data/memory/sessions/YYYY-MM-DD_HH-MM-SS.json`

**结构（带压缩）**：

```json
{
  "session_id": "2026-03-22_14-30-00",
  "started_at": "2026-03-22T14:30:00",
  "summary": "用户检查了 HR 回复，发现 2 条新消息，投递了 6 个 AI 算法岗位",
  "recent": [
    {"role": "user",      "content": "开始吧"},
    {"role": "assistant", "content": "本次投递 6 个职位，今日累计 6/25。"}
  ]
}
```

- `summary`：前 N 轮对话压缩成一段文字（当 recent 超过 20 轮时触发压缩）
- `recent`：最近 20 轮，原始格式

**压缩规则**：当 `recent` 超过 20 轮，把最早的 10 轮喂给 LLM 生成摘要，合并到 `summary`，然后从 `recent` 删除。

**注入 Ollama 的顺序**：`[system_prompt, summary_message(if any), ...recent]`

### 长期记忆（Long-term Memory）

**位置**：`data/memory/long_term.yaml`

**写入规则（严格）**：

| 触发条件 | 允许写入 | 说明 |
|----------|----------|------|
| 用户明确说"记住 xxx" | ✅ | Intent = remember，立即写入 |
| 用户修改了 profile 字段 | ✅ | 结构化事实，写入 context |
| Session 结束自动提取 | ❌ 默认禁止 | 容易产生幻觉，需用户手动开启 |
| LLM 推断用户偏好 | ❌ 永久禁止 | 会越用越错 |

**结构**：

```yaml
preferences:
  - fact: "不考虑外包公司"
    added_at: "2026-03-20"
    source: user_stated

constraints:
  - fact: "每天投递上限 25 个"
    added_at: "2026-03-21"
    source: user_stated

context:
  - fact: "在读硕士，找深圳 AI 方向实习，score_threshold=50"
    added_at: "2026-03-22"
    source: user_stated

history_summary:
  - date: "2026-03-22"
    summary: "投递 7 个，2 个 HR 回复，1 个面试邀约"
```

---

## System Prompt 拆分

避免一个超长 prompt 导致模型注意力分散：

```python
# 静态部分（每次 session 固定不变）
SYSTEM_PROMPT_CORE = """
你是求职助手，帮用户管理 Boss直聘 自动投递流程。
回复用中文，简洁直接。不要复读原始数据，用一句话汇报关键结果。
用户说"取消"或"算了"时，停止当前操作。
"""

# 动态部分（每轮对话前更新）
def build_context_block(memory, config_snapshot=None) -> str:
    parts = []
    if memory:
        parts.append(f"== 用户记忆 ==\n{memory}")
    if config_snapshot:
        parts.append(f"== 当前配置 ==\n{config_snapshot}")
    return "\n\n".join(parts)
```

两部分分开注入：`messages = [core_system, context_message, ...recent_messages]`

---

## 统一 Tool 返回格式

所有工具返回值统一为：

```python
@dataclass
class ToolResult:
    status: str          # "success" | "error" | "cancelled"
    data: dict           # 原始数据
    message: str         # 人类可读的一句话摘要（简单场景直接输出，跳过第二次 LLM）
```

**双 LLM 调用优化**：

```python
if tool_result.status == "error" or len(str(tool_result.data)) > 500:
    # 复杂结果 → 走 LLM 格式化
    response = llm.format_result(tool_result)
else:
    # 简单结果 → 直接用 message 字段，不调 LLM
    response = tool_result.message
```

---

## 典型交互流程（修正后）

```
用户：帮我投几个岗位
    ↓
[LLM] intent = {type: "apply", params: {}}
    ↓
Intent Router → apply flow
    ↓
pre_flight(): 读取 profile.yaml
    ↓
[代码] 格式化配置展示给用户
Agent：当前配置：关键词=AI，城市=深圳，类型=实习，score≥50，仅活跃HR
       要调整吗？（直接回车确认）
    ↓
State: pending_action="apply", awaiting_confirmation=True
    ↓
用户：可以，开始
    ↓
[LLM] intent = {type: "chitchat"} ← 但 state 是 awaiting_confirmation
    ↓
Intent Router: 检测到 pending + 用户肯定词 → 确认
    ↓
ToolGuard.check_apply() → OK
    ↓
orchestrator.run_once()
    ↓
ToolResult(status="success", data={...}, message="搜索 28 个，投递 6 个")
    ↓
result.message 直接输出（跳过第二次 LLM）
Agent：搜索 28 个职位，通过评分并投递 6 个，今日累计 6/25。
    ↓
State: idle
```

---

## 文件结构

```
code/
├── services/
│   ├── memory_manager.py     # 新建：长/短期记忆读写 + 压缩
│   ├── chat_agent.py         # 新建：对话主循环 + 状态机
│   ├── intent_classifier.py  # 新建：LLM 意图识别 + 规则兜底
│   └── tool_guard.py         # 新建：副作用操作的权限校验
├── agent_workflows.py        # 新建：workflow registry + flow handlers
├── data/
│   └── memory/
│       ├── long_term.yaml
│       └── sessions/
└── main.py                   # 修改：加 --chat 入口
```

---

## 已确认参数

- Ollama 模型：qwen3:8b，think=False
- session 窗口：最近 20 轮，超出时压缩最早 10 轮
- 长期记忆自动提取：默认关闭
- Tool Guard：所有有副作用的工具必须有 guard
