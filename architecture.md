# OpenJobFinder — 架构设计文档

---

## 一、系统概览

OpenJobFinder 是一个三层架构的 AI Agent 系统，在 Boss直聘 上自动化完成「搜索→评分→审核→生成简历→投递→跟进」全流程。

```
┌─────────────────────────────────────────────────────┐
│                   Control Layer（控制层）              │
│   scheduler.py  ─→  orchestrator.py                  │
│   APScheduler 定时触发 / CLI 手动触发                  │
└─────────────────┬───────────────────────────────────┘
                  │ 调用 Tool Registry
┌─────────────────▼───────────────────────────────────┐
│               Intelligence Layer（智能层）             │
│   tools/registry.py                                  │
│   ├── search_jobs      ├── score_job                 │
│   ├── critique_job     ├── generate_resume           │
│   ├── apply_job        └── update_status             │
└─────────────────┬───────────────────────────────────┘
                  │ 调用 Service
┌─────────────────▼───────────────────────────────────┐
│               Execution Layer（执行层）                │
│   services/                                          │
│   ├── browser_agent    ├── llm_client                │
│   ├── llm_parser       ├── tracker                   │
│   ├── resume_manager   ├── resume_parser             │
│   ├── onboarding       ├── logger                    │
│   ├── retry            └── rate_limiter              │
└─────────────────────────────────────────────────────┘
```

---

## 二、三层架构说明

### Control Layer（控制层）

**职责**：定时调度 + 主控循环，决定「何时做什么」。

- `scheduler.py`：使用 APScheduler 配置定时任务
  - 工作日 09:00 触发 `run_once()`（投递循环）
  - 每小时触发 `check_responses()`（回应检查）
  - 捕获 `SessionExpiredError` → 暂停所有 job，发出告警
- `orchestrator.py`：每轮执行逻辑
  - `run_once()`：搜索 → 逐 job 处理，每 job 独立 try/except
  - `_process_job(job)`：评分 → 审核 → 生成简历 → 投递 → 更新状态
  - `check_responses()`：检查聊天列表，批量更新 RESPONDED 状态
  - 每日汇总统计（已投递数、回应数）

### Intelligence Layer（智能层）

**职责**：统一接口封装，屏蔽底层实现差异。Orchestrator 只调 Tool，不直接调 Service。

- `tools/registry.py`：TOOLS 字典，所有 Tool 实例在此注册，`get_tool(name)` 获取
- 每个 Tool 是独立 Python 类，实现 `ToolProtocol`（`execute(**kwargs) -> dict`）
- Tool 负责参数校验、调用底层 Service、格式化返回结果

### Execution Layer（执行层）

**职责**：实际执行 IO 操作（浏览器、LLM、数据库、文件系统）。

- 每个 Service 实现对应的 `ServiceProtocol`（抽象接口）
- Service 不感知业务逻辑，只负责执行单一能力
- 所有对外 IO 调用（Playwright / LLM）均通过 `retry.py` 包裹

---

## 三、模块职责边界

| 模块 | 层次 | 职责 | 不做什么 |
|------|------|------|----------|
| `scheduler.py` | Control | 定时触发、错误暂停 | 不含业务逻辑 |
| `orchestrator.py` | Control | 主控流程、每日限额、错误隔离 | 不直接调 Service |
| `tools/registry.py` | Intelligence | Tool 注册和获取 | 不含执行逻辑 |
| `tools/score_job.py` | Intelligence | 构造 LLM prompt，解析评分结果 | 不直接调 browser |
| `tools/critique_job.py` | Intelligence | 独立审核评分决策 | 不修改 score 结果 |
| `tools/generate_resume.py` | Intelligence | 触发简历生成 | 不操作数据库 |
| `tools/apply_job.py` | Intelligence | 幂等投递守卫 + rate limit | 不含 Playwright 代码 |
| `tools/search_jobs.py` | Intelligence | 封装搜索 + JD 抓取 | 不做评分 |
| `tools/update_status.py` | Intelligence | 状态更新的 thin wrapper | 不含状态机逻辑 |
| `services/browser_agent.py` | Execution | Playwright 全部操作 | 不做 LLM 决策 |
| `services/llm_client.py` | Execution | LLM 调用 + fallback 链 | 不解析 JSON |
| `services/llm_parser.py` | Execution | JSON 提取 + 修复 + 类型强制 | 不调 LLM |
| `services/tracker.py` | Execution | SQLite CRUD + 状态机 | 不含业务规则 |
| `services/resume_parser.py` | Execution | PDF/Word → YAML | 不生成 PDF |
| `services/resume_manager.py` | Execution | YAML patch + PDF 渲染 | 不解析上传文件 |
| `services/onboarding.py` | Execution | 启动检测 + CLI 引导 | 不调度任务 |
| `services/logger.py` | Execution | 结构化日志写入 | 不含业务逻辑 |
| `services/retry.py` | Execution | 指数退避重试装饰器 | 不了解业务 |
| `services/rate_limiter.py` | Execution | 随机等待 + 小时上限 | 不含投递逻辑 |

---

## 四、完整数据 Schema 定义

### Job

```python
@dataclass
class Job:
    job_id: str           # Boss直聘职位唯一 ID（从 URL 提取）
    title: str            # 职位名称
    company: str          # 公司名
    city: str             # 城市
    salary: str           # 薪资范围（原始字符串）
    url: str              # 职位页 URL
    jd_text: str          # 完整 JD 文本（含岗位要求、公司介绍）
    source_keyword: str   # 触发该职位的搜索关键词
    discovered_at: str    # ISO8601 时间戳
    status: str           # 当前状态（对应 AppStatus 枚举）
```

### ScoreResult

```python
@dataclass
class ScoreResult:
    job_id: str
    score: int                      # 0-100 匹配分
    decision: str                   # "apply" | "skip"
    reason: str                     # 决策原因（中文）
    resume_patch: dict              # {"summary": "...", "highlights": [...]}
    raw_response: str               # LLM 原始输出（用于 debug）
    provider_used: str              # 使用的 LLM provider
```

### CriticResult

```python
@dataclass
class CriticResult:
    job_id: str
    verdict: str                    # "approve" | "reject"
    reason: str                     # 独立审核理由（中文）
    raw_response: str               # LLM 原始输出
    provider_used: str
```

### ApplicationRecord

```python
@dataclass
class ApplicationRecord:
    job_id: str
    title: str
    company: str
    url: str
    status: str                     # AppStatus 枚举值
    score: Optional[int]
    decision: Optional[str]
    critic_verdict: Optional[str]
    resume_path: Optional[str]      # 生成的简历 PDF 路径
    applied_at: Optional[str]       # ISO8601
    responded_at: Optional[str]     # ISO8601
    error_msg: Optional[str]
    # 幂等标记
    apply_attempted: bool           # 是否已尝试投递（防重复）
    created_at: str                 # 首次 discovered 时间
    updated_at: str                 # 最后更新时间
```

### StatusUpdate

```python
@dataclass
class StatusUpdate:
    job_id: str
    company: str
    new_status: str                 # "RESPONDED" | "INTERVIEW" | "OFFER" | "REJECTED"
    message: str                    # 对方回复内容摘要
    updated_at: str                 # ISO8601
```

### AppStatus（状态枚举）

```python
class AppStatus(str, Enum):
    DISCOVERED  = "DISCOVERED"   # 搜索到，未扫描 JD
    SCANNED     = "SCANNED"      # JD 已抓取
    SCORED      = "SCORED"       # LLM 评分完成
    APPLIED     = "APPLIED"      # 已投递
    RESPONDED   = "RESPONDED"    # 对方有回应
    INTERVIEW   = "INTERVIEW"    # 进入面试
    OFFER       = "OFFER"        # 收到 Offer
    REJECTED    = "REJECTED"     # 被拒绝
    ERROR       = "ERROR"        # 执行出错
```

---

## 五、Tool Registry 接口规范

### ToolProtocol（抽象接口）

```python
class ToolProtocol(Protocol):
    name: str
    description: str
    def execute(self, **kwargs) -> dict: ...
```

### 各 Tool 输入/输出

| Tool | 输入参数 | 输出字段 |
|------|----------|----------|
| `search_jobs` | `keywords: str, city: str, limit: int` | `{"jobs": List[Job]}` |
| `score_job` | `job: Job, profile: dict` | `{"result": ScoreResult}` |
| `critique_job` | `job: Job, score_result: ScoreResult, profile: dict` | `{"result": CriticResult}` |
| `generate_resume` | `job: Job, score_result: ScoreResult` | `{"pdf_path": str}` |
| `apply_job` | `job: Job, resume_path: str, dry_run: bool` | `{"success": bool, "message": str}` |
| `update_status` | `job_id: str, new_status: AppStatus, **extra` | `{"updated": bool}` |
| `check_responses` | `job_ids: List[str]` | `{"updates": List[StatusUpdate]}` |

---

## 六、LLM Provider 抽象接口

### LLMProviderProtocol

```python
class LLMProviderProtocol(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def complete(self, prompt: str, system: str = "") -> str: ...
```

### 四种 Provider 实现

| Provider | 调用方式 | 适用场景 |
|----------|----------|----------|
| `ClaudeCLIProvider` | `subprocess: claude -p` | 默认，工厂认证下免 API key |
| `OllamaProvider` | `HTTP: localhost:11434` | 本地离线推理 |
| `AnthropicAPIProvider` | `HTTP: api.anthropic.com` | 需要 API key，高质量 |
| `OpenAICompatibleProvider` | `HTTP: 自定义 base_url` | 兼容 OpenAI 接口的各类服务 |

### FallbackChain 设计

```python
class FallbackChain:
    providers: List[LLMProviderProtocol]

    def complete(self, prompt: str, system: str = "") -> tuple[str, str]:
        # 返回 (response_text, provider_name_used)
        for provider in self.providers:
            if provider.is_available():
                try:
                    result = provider.complete(prompt, system)
                    return result, provider.name
                except Exception as e:
                    logger.warning(f"Provider {provider.name} failed: {e}, trying next")
        raise AllProvidersFailedError("All configured providers exhausted")
```

### config.yaml 结构

```yaml
llm:
  providers:
    scoring:                    # 评分任务专用链
      - type: claude_cli
      - type: anthropic_api
        model: claude-sonnet-4-6
        api_key_env: ANTHROPIC_API_KEY
    generation:                 # 简历生成任务专用链
      - type: ollama
        model: llama3.2
        base_url: http://localhost:11434
      - type: ollama
        model: mistral
      - type: claude_cli        # fallback

job_search:
  keywords: []                  # 由 profile.yaml 覆盖
  cities: []
  limit_per_run: 30

apply:
  score_threshold: 72
  daily_limit: 25
  dry_run: false

schedule:
  apply_cron: "0 9 * * 1-5"    # 工作日 9am
  check_responses_interval: 3600  # 秒
```

---

## 七、状态机图

```
                    ┌──────────┐
                    │DISCOVERED│  ← search_jobs 写入
                    └────┬─────┘
                         │ open_job() 抓取 JD
                    ┌────▼─────┐
                    │ SCANNED  │
                    └────┬─────┘
                         │ score_job() LLM 评分
                    ┌────▼─────┐
                    │ SCORED   │──── score < threshold ────→ [skip, 不更新状态]
                    └────┬─────┘
                         │ critique_job() 审核通过
                    ┌────▼─────┐
                    │ APPLIED  │──── critic.reject ─────→ [skip]
                    └────┬─────┘
                         │ check_chat_list() 检测回应
               ┌─────────┼──────────┐
          ┌────▼───┐ ┌───▼────┐ ┌──▼──────┐
          │RESPONDED│ │REJECTED│ │ ERROR   │
          └────┬────┘ └────────┘ └─────────┘
               │
          ┌────▼─────┐
          │INTERVIEW │
          └────┬─────┘
          ┌────┴─────┐
     ┌────▼───┐  ┌───▼────┐
     │ OFFER  │  │REJECTED│
     └────────┘  └────────┘
```

**幂等保护**：
- 进入 APPLIED 前，先设置 `apply_attempted = True`
- 每轮检测：若 `apply_attempted == True` 且状态已为 APPLIED，直接跳过
- 即使程序在 apply 中途崩溃，重启后也不会重复投递

---

## 八、关键设计决策

### 8.1 控制流在代码，LLM 只做评分

LLM 不做工具调用（no function calling），只返回结构化 JSON 评分。所有流程控制（if/else、循环、错误处理）由 Python 代码负责。这避免了 LLM agent 不可预测的行为，保证系统可调试、可回放。

### 8.2 工具层隔离，单向依赖

依赖方向：Control → Intelligence → Execution，严禁反向调用。Orchestrator 只调 Tool，Tool 只调 Service，Service 不互相调用（除 logger、retry 等横切关注点）。

### 8.3 不使用 Anthropic SDK

所有 LLM 调用通过 `claude -p` 子进程（ClaudeCLIProvider）或 HTTP 请求（OllamaProvider、AnthropicAPIProvider、OpenAICompatibleProvider）实现，无需 Python SDK。这与工厂 CLI 认证体系保持一致。

### 8.4 LLM 输出健壮性三层保护

1. **正则提取**：从 LLM 输出中找 ```json ... ``` 代码块
2. **json-repair**：修复常见格式错误（缺逗号、多余引号等）
3. **字段级类型强制**：`score` 字段强转 `int`，`decision` 字段验证枚举值，不合法时使用安全默认值

### 8.5 每日限额 + Rate Limiter 双重保护

- Orchestrator 在 `run_once()` 开始时检查 `count_today() >= 25`，超限直接退出
- `ApplyJobTool` 在每次实际投递前调用 `rate_limiter.wait()`（随机 10-30 秒）
- 两层保护解耦：Orchestrator 管「每日总量」，RateLimiter 管「单次间隔」

### 8.6 Onboarding 阻塞式检查

首次启动时 `onboarding.py` 运行一系列检查，任何阻塞项（无 profile、无简历）会阻止调度器启动。Dashboard 的 onboarding checklist 实时反映各项状态，引导用户完成配置。

### 8.7 Session 管理

- 首次登录：引导用户手动登录，程序检测到登录成功后保存 `session.json`
- 后续启动：Playwright context 直接加载 `session.json`，无需重新登录
- Session 失效检测：Browser Agent 在每次操作前验证登录状态，失效时抛出 `SessionExpiredError`
- Scheduler 捕获此异常 → 暂停所有定时任务 → 输出告警，等待用户重新登录

### 8.8 Dashboard 不阻塞核心流程

Dashboard（FastAPI）是独立进程，通过 SQLite 读取数据，不参与投递流程。即使 Dashboard 停止运行，投递系统照常工作。

---

## 九、三大交互式 Workflow

系统由三个独立 workflow 组成，按顺序依赖：Workflow 1 完成后才能执行 Workflow 2，Workflow 2 产生的投递记录是 Workflow 3 的输入。

---

### Workflow 1 — 环境配置（Onboarding）

**触发**：`python main.py --onboarding`，或首次运行时自动触发（session.json 不存在）

**目标**：确保系统可运行所需的一切就绪。

```
Step 1/4  检查依赖
          ├─ DrissionPage + Chrome 可用？→ 否：提示安装，退出
          └─ 可选依赖缺失（weasyprint 等）→ 警告，继续

Step 2/4  配置 LLM Provider
          ├─ 已配置？→ 询问是否重新配置，默认跳过
          └─ 未配置：依次探测 Claude CLI / Anthropic API / Ollama / OpenAI-compatible
             用户确认后写入 config.yaml

Step 3/4  Boss直聘 登录
          ├─ session.json 已存在？→ 跳过
          └─ 未登录：打开浏览器 → 轮询 URL 检测登录成功 → 写入 session.json

Step 4/4  导入简历
          ├─ resume_base.yaml 已存在？→ 询问是否重新导入，默认跳过
          └─ 未导入：弹出文件选择框 → 用户选择 PDF/DOCX
             → resume_parser 解析 → 写入 data/resume_base.yaml

完成：提示用户进入 Workflow 2
```

**产物**：`config.yaml`、`data/session.json`、`data/resume_base.yaml`

---

### Workflow 2 — 搜索 & 投递（Apply）

**触发**：`python main.py --setup-profile`（首次配置偏好）→ `python main.py --once` 或定时调度

**目标**：根据用户求职偏好搜索职位，经 LLM 评分审核后自动发起会话投递。

```
Phase A  CLI 交互配置求职偏好（首次或 --setup-profile）
         用户输入：
         ├─ 搜索关键词（可多个，如 Python后端工程师）
         ├─ 目标城市（多选：北京/上海/深圳…）
         ├─ 工作经验（多选：应届生/1-3年/3-5年…）
         ├─ 学历要求（多选：大专/本科/硕士…）
         ├─ 薪资范围（单选：5-10K/10-20K/20-50K…）
         └─ 公司规模（多选：0-20人/100-499人…）
         → 保存至 data/profile.yaml

Phase B  搜索职位
         ├─ 打开 Boss直聘，按关键词 × 城市矩阵搜索
         ├─ 带上过滤参数（经验/学历/薪资/规模）构造 URL
         └─ 抓取每条职位的完整 JD 文本

Phase C  LLM 评分
         对每条 Job：
         ├─ ScoreTool：输入 JD + profile → 输出 score(0-100) + decision + resume_patch
         ├─ score < threshold(72) → 标记 SCORED，跳过，不投递
         └─ score ≥ threshold → 进入 Critic 审核

Phase D  Critic 审核
         ├─ CritiqueTool：独立视角复核评分决策
         ├─ verdict=reject → 跳过
         └─ verdict=approve → 进入投递

Phase E  生成简历 & 投递
         ├─ GenerateResumeTool：根据 resume_patch 微调简历，生成 PDF
         ├─ ApplyTool：点击"立即沟通"，发送个性化打招呼语（含候选人姓名）
         ├─ 幂等保护：apply_attempted 标记，防止重复投递
         ├─ Rate Limiter：每次投递随机等待 10-30s，每小时上限 8 次
         └─ 每日上限 25 次，超限停止本轮

完成：在 Dashboard 可查看所有 APPLIED 职位
```

**产物**：`data/profile.yaml`（偏好）、`data/jobs.db`（投递记录）、`output/resumes/{job_id}.pdf`

---

### Workflow 3 — 跟进 & 决策（Follow-up）

**触发**：`python main.py --check`，或定时调度（每小时自动运行）

**目标**：检查 HR 回复，根据回复类型做出不同决策，闭环整个求职流程。

```
Step 1  扫描聊天列表
        ├─ 打开 Boss直聘 /web/geek/chat
        ├─ 遍历最近 20 条会话
        └─ 跳过自己发出的打招呼消息（以"您好，我是"开头）

Step 2  分类 HR 回复
        每条消息分为四类：

        ┌─ 类型 A：平台广告推送
        │   特征：发送方不在 jobs.db 中，或系统消息
        │   决策：忽略，不更新状态
        │
        ├─ 类型 B：已读不回（超时无回复）
        │   特征：APPLIED 状态超过 N 天无新消息
        │   决策：标记 IGNORED，记录日志
        │
        ├─ 类型 C：HR 请求附件简历
        │   特征：消息含"附件简历/发简历/简历发一下"等关键词
        │   决策：
        │   ├─ data/resume_attachment.pdf 存在 → 自动发送附件
        │   └─ 不存在 → Dashboard 提示用户上传附件简历
        │
        └─ 类型 D：实质性回复
            ├─ 含"面试/约时间/面谈/邀请" → 状态更新为 INTERVIEW，Dashboard 高亮提醒
            ├─ 含"不合适/感谢关注/遗憾/婉拒" → 状态更新为 REJECTED
            └─ 其他正常回复 → 状态更新为 RESPONDED

Step 3  更新 tracker
        ├─ 写入新状态 + 时间戳 + 消息摘要
        └─ Dashboard 实时反映最新状态

Step 4  用户可见的待办事项（Dashboard）
        ├─ INTERVIEW：显示公司/职位，提示用户准备面试
        ├─ RESUME_REQUESTED（无附件）：提示上传附件简历
        └─ RESPONDED：显示消息摘要，供用户决策是否手动跟进

完成：jobs.db 状态更新，Dashboard 刷新
```

**产物**：`data/jobs.db`（状态更新）

---

### Workflow 入口总览

```
python main.py --onboarding      # Workflow 1：环境配置（首次必须）
python main.py --setup-profile   # Workflow 2 Phase A：CLI 配置求职偏好
python main.py --once            # Workflow 2 Phase B-E：单次搜索投递
python main.py                   # Workflow 2+3 自动调度（工作日 9am 投递，每小时检查）
python main.py --check           # Workflow 3：仅执行回复检查
python main.py --dry-run         # Workflow 2 演练（不真实投递）

Dashboard: http://localhost:8765  # 可视化查看所有 workflow 的状态和产物
```

<!-- FACTORY:DONE -->
