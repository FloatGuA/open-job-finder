# Pipeline Architecture Refactor — 总体计划

## 背景

本次重构是对现有 Boss直聘自动化 Agent 的结构化移植（structured port），不是功能扩展。
现有代码能跑，但架构扁平：orchestrator.py 直接驱动 browser_agent.py，工具逻辑散落在 tools/ 下，
没有清晰的层边界，日志体系混乱，LLM 提示词硬编码在 Python 字符串里。

重构目标：
- 建立 Tool / Step / Pipeline 三层架构，职责清晰，可独立测试
- 引入 ToolRegistry，为未来 LLM 自主决策工具调用做准备
- Prompt System 独立管理，提示词版本化
- 结构化 JSONL 日志（Trace event + Business event）
- Memory 分层设计（Static / Episodic / Reflection 占位）

## 核心概念

**Tool**：原子 IO 操作，继承 BaseTool，有 name / description / input_schema，
execute(**kwargs) → ToolResult(ok, data, error)。data 对应日志里的 tool.data 字段。

**Step**：有意义的业务阶段，有 dataclass 输入输出，输出继承 StepOutput(status, error)，
有独立 on_error 策略（ABORT_WORKFLOW / SKIP / CONTINUE_DEGRADED）。

**Pipeline**：W1Pipeline（搜索+投递）、W2Pipeline（会话检查+回复），
管理 Step 执行顺序和错误处理，不做业务判断。

**ToolRegistry**：统一持有所有 Tool 实例，管理共享资源注入（browser / db / llm / prompts），
Pipeline 通过 registry.get(name).execute(...) 调用工具。

**Trace event**：每个 Step / Tool 执行后框架自动发出，记录是否成功、耗时、debug 数据。
**Business event**：由产生业务状态变化的 Step 或 Pipeline 手动发出，记录决策结果。
Pipeline 负责跨 Step 的业务决策事件（如 stage_advanced）；Step 负责自身内部明确完成的业务事件（如 intent_analyzed 由 AnalyzeStep 发，reply_sent 由 ReplyStep 发）。

## 设计文档索引

理解某个 Task 之前，先读对应设计文档：

| 文档 | 内容 |
|------|------|
| design/db_schema.md | 三张表结构、状态机、字段说明 |
| design/tools_catalog.md | 所有 Tool 的输入输出契约 |
| design/w1_pipeline.md | W1 Step 设计、执行顺序、停止条件 |
| design/w2_pipeline.md | W2 Step 设计、ScanStep 脏检查、Stage 推导 |
| design/logging.md | Trace / Business event 格式、每个 Tool 的 data 规格 |

## 现有代码索引

重构时的主要参考来源（不是直接复用，是理解现有逻辑后重写）：

| 文件 | 对应新架构 |
|------|-----------|
| code/services/browser_agent.py | → W1/W2 BrowserTools |
| code/services/tracker.py | → DB Tools |
| code/services/llm_client.py | → LLM Client（保留，调整接口） |
| code/tools/score_job.py | → ScoreJob LLMTool |
| code/tools/check_responses.py | → W2 Pipeline 的 AnalyzeStep 相关 |
| code/orchestrator.py | → W1Pipeline + W2Pipeline |
| code/config.yaml | → 配置来源（score_threshold 等） |
| code/data/profile.yaml | → ProfileLoader 读取对象 |

---

## Task 清单

### Task 030 — DB 迁移
**对应看板**：T1

**要做什么**：
按 design/db_schema.md 重写三张表，删除 actions 表。
- applications 表：删除 7 个旧字段（decision / critic_verdict / resume_path / apply_attempted / error_msg / updated_at / responded_at）
- hr_conversations 表：删除旧字段，新增 last_msg_preview / reply_text，更新 stage 枚举和 reply_status 枚举
- hr_messages 表：新建（id / conv_id / sender / text / msg_time / created_at + UNIQUE 约束）
- actions 表：删除
- conv_id hash 公式更新：sha256(hr_name|company|hr_title)[:12]
- 写迁移脚本处理现有数据（data/jobs.db）

**预期产出**：
- `code/services/tracker.py` 中所有 SQL 更新到新 schema
- `code/scripts/migrate_030.py` 一次性迁移脚本
- `data/jobs.db` 结构符合新 schema

**验收**：
- 迁移脚本在现有 jobs.db 上跑通不报错
- `pytest tests/` 中 tracker 相关测试通过

**参考**：design/db_schema.md

---

### Task 031 — 核心框架
**对应看板**：T2

**要做什么**：
新建三个基础设施组件，后续所有 Task 都依赖这里。

1. Step 基类（`code/pipeline/base.py`）：
   StepStatus 枚举 + StepOutput dataclass

2. RunLogger（`code/services/run_logger.py`）：
   JSONL 写入 logs/runs/{run_id}.jsonl，五个方法：
   log_run_start / log_run_end / log_step / log_tool / log_business_event

3. Tool 基础设施（`code/tools/base.py` + `code/tools/registry.py`）：
   ToolResult dataclass + BaseTool ABC + ToolRegistry
   ToolRegistry 初始化时注入 browser / db / llm_client / prompt_manager / logger

**预期产出**：
- `code/pipeline/base.py`（StepStatus, StepOutput）
- `code/services/run_logger.py`（RunLogger）
- `code/tools/base.py`（ToolResult, BaseTool）
- `code/tools/registry.py`（ToolRegistry）
- 旧的 `code/services/event_log.py` 引用全部移除

**验收**：
- 可以实例化 ToolRegistry，register 一个 mock Tool，get 后 execute 拿到 ToolResult
- RunLogger 写一条 log_tool 后，logs/runs/ 下出现对应 JSONL 文件，内容符合 design/logging.md 格式

**范围边界**：T031 只实现 RunLogger 能力和最小测试，不要求接入所有 Step/Tool（这是 T040 的工作）。T031 完成时 RunLogger 可用即可，不验证全量埋点覆盖率。

**参考**：design/logging.md（格式规范）

---

### Task 032 — Prompt System
**对应看板**：T17

**要做什么**：
建立独立的提示词管理层，提示词从 Python 字符串移到文件。

1. 创建 `prompts/` 目录，写三个模板文件：
   - `prompts/system.md`：Agent 身份、目标、行为准则
   - `prompts/score_job.md`：ScoreJob 评分模板，含 5 维度 rubric 和输出 JSON 格式约束，
     占位符：{{title}} {{company}} {{jd_text}} {{profile_summary}}
   - `prompts/analyze_intent.md`：HR 意图分析模板，
     占位符：{{company}} {{job_title}} {{messages}}

2. PromptManager（`code/services/prompt_manager.py`）：
   load(name) / render(name, context: dict) → str

**预期产出**：
- `prompts/system.md`
- `prompts/score_job.md`
- `prompts/analyze_intent.md`
- `code/services/prompt_manager.py`

**验收**：
- `PromptManager().render('score_job', {'title': 'Python工程师', ...})` 返回完整 prompt 字符串，无未替换占位符

**注意**：提示词内容需要从现有 `code/tools/score_job.py` 和
`code/tools/check_responses.py` 中提取当前硬编码的 prompt，迁移过来，不要凭空写。

---

### Task 033 — Memory Interface
**对应看板**：T18

**要做什么**：
封装 Agent 静态知识读取层，为 Reflection Memory 留扩展接口。

1. ProfileLoader（`code/services/profile_loader.py`）：
   load() → Profile dataclass（name / keywords / cities / experience / salary / extra_notes）
   读取并验证 data/profile.yaml，字段缺失时给合理默认值

2. Reflection Memory 占位（`code/memory/`）：
   - `code/memory/base.py`：ReflectionMemory 抽象基类（read / write / summarize，全部 raise NotImplementedError）
   - `code/memory/null_memory.py`：NullReflectionMemory（所有方法 no-op）
   - `code/memory/design.md`：设计意图说明，标注"待实现"

**预期产出**：
- `code/services/profile_loader.py`
- `code/memory/base.py`
- `code/memory/null_memory.py`
- `code/memory/design.md`

**验收**：
- `ProfileLoader().load()` 在 data/profile.yaml 存在时返回完整 Profile 对象
- `NullReflectionMemory().read()` 返回 None 不报错

**参考**：data/profile.yaml（现有字段），code/schemas.py（现有 Profile 相关定义）

---

### Task 034 — W1 Browser Tools
**对应看板**：T3

**要做什么**：
从 browser_agent.py 拆分出 7 个 W1 专用 BrowserTool，每个继承 BaseTool。

- NavigateSearchUrl
- ExtractCardList
- ScrollSearchResults
- ClickCardOpenPanel
- ReadPanelJD（输出 salary_raw，不做解码）
- ClickApplyButton（result 含 rate_limited）
- HandleApplyDialog

每个 Tool 放在 `code/tools/browser/w1/` 下，在 ToolRegistry 中注册。

**预期产出**：
- `code/tools/browser/w1/*.py`（7 个文件）
- ToolRegistry 注册代码更新

**验收**：
- 每个 Tool 可通过 registry.get(name).execute(...) 调用
- 返回的 ToolResult.data 字段符合 design/logging.md 里对应 Tool 的 data 规格

**参考**：
- design/tools_catalog.md（BrowserTools W1 专用 章节）
- design/logging.md（Trace Tool data 规格 W1 BrowserTools 表格）
- code/services/browser_agent.py（现有实现，理解后重写为 Tool 形式）

---

### Task 035 — W2 Browser Tools
**对应看板**：T4

**要做什么**：
从 browser_agent.py 拆分出 9 个 W2 专用 BrowserTool，每个继承 BaseTool。

- NavigateToChatList
- ExtractConversationList（含 hr_title 字段，用于 conv_id hash）
- ScrollChatList
- NavigateToConversation（URL 直跳优先，降级 JS 点击）
- ReadMessages
- SendChatMessage
- AcceptResumeCard（含跨境弹窗处理）
- ClickToolbarSendResume
- UploadResumeFile

每个 Tool 放在 `code/tools/browser/w2/` 下，在 ToolRegistry 中注册。

**预期产出**：
- `code/tools/browser/w2/*.py`（9 个文件）
- ToolRegistry 注册代码更新

**验收**：同 Task 034，data 字段符合 design/logging.md W2 BrowserTools 规格

**参考**：
- design/tools_catalog.md（BrowserTools W2 专用 章节）
- design/logging.md（Trace Tool data 规格 W2 BrowserTools 表格）
- code/services/browser_agent.py

---

### Task 036 — W1 非浏览器 Tools
**对应看板**：T11

**要做什么**：
实现 W1 专用的 LLM Tool、BusinessLogic Tool、DB Tool，共 4 个。

- ScoreJob（LLMTool）：调用 PromptManager.render('score_job') 构建 prompt，
  5 维度独立打分，Python 端加权求和，返回 score / dimensions / reason / provider_used。
  不含 above_threshold（Pipeline 做比较）。
- DecodeJobSalary（BusinessLogicTool）：PUA Unicode 解码，纯函数
- ClassifyJobForW1（DBTool）：查 applications 表判断走哪条路径
- UpsertApplication（DBTool）：写/更新 applications 表

**预期产出**：
- `code/tools/llm/score_job.py`
- `code/tools/biz_logic/decode_salary.py`
- `code/tools/db/w1/*.py`（2 个文件）
- ToolRegistry 注册代码更新

**验收**：
- ScoreJob.execute(jd_text=..., profile=...) 返回包含 score(int) 和 reason(str) 的 ToolResult
- UpsertApplication 写入后可从 DB 查到对应记录

**参考**：
- design/tools_catalog.md（ScoreJob / ClassifyJobForW1 / UpsertApplication 章节）
- prompts/score_job.md（Task 032 产出）
- code/tools/score_job.py（现有实现参考）
- code/services/tracker.py（现有 SQL 参考）

---

### Task 037 — W1 Pipeline
**对应看板**：T12

**要做什么**：
实现完整 W1Pipeline，驱动 SearchLoop + CardPipeline。

- W1Pipeline.run(url, profile, config)
- NavigateStep → on_error: ABORT_WORKFLOW
- SearchLoop：seen_card_ids 跨轮维护，5 个停止条件
- CardPipeline（per card）：
  ClassifyJobForW1 → ClickCardOpenPanel → FetchJDStep → ScoreJob
  → （score >= threshold 判断）→ ApplyStep → UpsertApplication
  should_stop = ApplyStep.result == rate_limited
- Business events：job_scored / job_applied / job_skipped（CardPipeline 层发出）

**预期产出**：
- `code/pipeline/w1/pipeline.py`
- `code/pipeline/w1/steps/navigate.py`
- `code/pipeline/w1/steps/fetch_jd.py`
- `code/pipeline/w1/steps/apply.py`
- `code/pipeline/w1/card_pipeline.py`

**验收**：
- dry_run=True 时跑完 SearchLoop 不真实投递，日志里出现 run_start / run_end
- CardPipeline 在 score < threshold 时写 REJECTED 到 DB，发出 job_skipped business event

**参考**：
- design/w1_pipeline.md（完整 Step 设计）
- design/logging.md（Business Events 清单）
- code/orchestrator.py（现有 run_once 逻辑参考）

---

### Task 038 — W2 非浏览器 Tools
**对应看板**：T19

**要做什么**：
实现 W2 专用的 LLM Tool、BusinessLogic Tools、DB Tools，共 10 个。

LLMTool：
- AnalyzeHRIntent：调用 PromptManager.render('analyze_intent')，
  返回 intent / confidence / needs_reply / suggested_reply / provider_used

BusinessLogicTools（纯函数）：
- DetectResumeRequest：检测消息列表中的简历请求，防重复发送
- FilterConversations：脏检查过滤，排除终态会话，返回需处理列表

DBTools（7 个）：
- UpsertHRConversation（stage 只升不降约束）
- WriteHRMessages（UNIQUE 跳过重复）
- UpdateHRAnalysis（CASE 保护 approved 不降级）
- GetApprovedReplies
- GetConversationStates
- SyncApplicationStatusFromConversations
- MarkTimeoutRejections

**预期产出**：
- `code/tools/llm/analyze_intent.py`
- `code/tools/biz_logic/detect_resume.py`
- `code/tools/biz_logic/filter_conversations.py`
- `code/tools/db/w2/*.py`（7 个文件）

**验收**：
- FilterConversations 对 stage=closed 的会话正确排除
- UpdateHRAnalysis 在 reply_status=approved 时不覆写（CASE 保护验证）

**参考**：
- design/tools_catalog.md（W2 相关所有章节）
- design/db_schema.md（hr_conversations / hr_messages 结构）
- code/services/tracker.py / code/tools/check_responses.py

---

### Task 039 — W2 Pipeline
**对应看板**：T14

**要做什么**：
实现完整 W2Pipeline，驱动 ScanStep + ConversationPipeline + FinalizeStep。

- ScanStep：全量扫描聊天列表，内部顺序执行：
  NavigateToChatList → ExtractConversationList + ScrollChatList 循环 → GetApprovedReplies → GetConversationStates → FilterConversations（纯函数）
  概念上：ScanStep = 页面扫描；FilterConversations = 业务筛选（内部调用，职责独立）。
  返回 conversations_to_process + approved_replies。
- ConversationPipeline（per conv）：
  NavigateStep → ReadStep → AnalyzeStep → ResumeStep（条件）→ ReplyStep（条件）→ UpsertHRConversation
  Stage 推导在 AnalyzeStep 之后由 ConversationPipeline 控制层执行
- FinalizeStep：SyncApplicationStatusFromConversations → MarkTimeoutRejections（同时处理
  applications no_response → REJECTED 和 hr_conversations stale → closed），
  遍历结果逐条发 conv_timeout_closed / job_no_response_rejected business events

**预期产出**：
- `code/pipeline/w2/pipeline.py`
- `code/pipeline/w2/scan_step.py`
- `code/pipeline/w2/steps/navigate.py`
- `code/pipeline/w2/steps/read.py`
- `code/pipeline/w2/steps/analyze.py`
- `code/pipeline/w2/steps/resume.py`
- `code/pipeline/w2/steps/reply.py`
- `code/pipeline/w2/finalize_step.py`
- `code/pipeline/w2/conversation_pipeline.py`

**验收**：
- ScanStep 在 stage=closed 的会话上正确跳过（FilterConversations 验证）
- approved_reply 存在时 ReplyStep 发送消息，DB reply_status 更新
- FinalizeStep 超时会话正确发出 conv_timeout_closed business event

**参考**：
- design/w2_pipeline.md（完整设计）
- design/logging.md（Business Events 清单）
- code/tools/check_responses.py（现有 W2 逻辑参考）

---

### Task 040 — 日志埋点
**对应看板**：T15

**要做什么**：
在 W1 / W2 所有 Step 和 Tool 上挂 RunLogger，实现 Trace + Business event 双轨日志。

- 每个 Step 执行前后：log_step（status / duration_ms / data / error）
- 每个 Tool 执行前后：log_tool（status / duration_ms / data / error）
  data 字段内容见 design/logging.md「Trace Tool data 规格」表格
- 各 Step / Pipeline 关键节点：log_business_event
  W1（CardPipeline 层）：job_scored / job_skipped
  W1（ApplyStep 成功后）：job_applied
  W2（AnalyzeStep）：intent_analyzed
  W2（ResumeStep）：resume_sent
  W2（ReplyStep）：reply_sent
  W2（ConversationPipeline 控制层，UpsertHRConversation 后）：stage_advanced
  W2（FinalizeStep）：conv_timeout_closed / job_no_response_rejected

废弃 event_log.py 的最后引用。

**预期产出**：
- W1 / W2 所有 Step 和 Tool 含埋点代码
- 一次完整 dry_run 后，logs/runs/ 下出现 JSONL 文件
- JSONL 内容包含 run_start / step / tool / business event / run_end

**验收**：
- 对 JSONL 文件 `grep '"event": "job_scored"'` 能找到对应条目
- 每条 tool 日志的 data 字段符合 design/logging.md 规格，无多余大字段（jd_text / messages）

**参考**：design/logging.md（全文）

---

### Task 041 — Dashboard Logs 页
**对应看板**：T16

**要做什么**：
按新 JSONL 格式重写 Dashboard Logs 页面（后端 API + 前端 React 组件）。

后端（server.py）：
- GET /api/runs：列表，解析每个 run_end 的 summary
- GET /api/runs/{run_id}：详情，返回 steps[] + tools[]（按 step 分组）+ business_events[]

前端（Logs.tsx）：
- 左栏：run 列表（pipeline 类型 / 状态 / 时长 / summary 关键数字）
- 右栏两个 Tab：
  Flow（Trace）：Step 时间线 + Tool 展开（Tool 默认折叠）
  Decisions（Business）：按 event 类型分组的业务决策时间线
- 保留 w1/w2 筛选

**预期产出**：
- `code/dashboard/server.py`（两个新 endpoint）
- `code/dashboard/frontend/src/pages/Logs.tsx`（重写）

**验收**：
- 有真实 JSONL 数据时，Dashboard Logs 页能正确渲染 run 列表和详情
- Flow tab 展示 Step 时间线，Decisions tab 展示 business event 列表

**参考**：
- design/logging.md（日志格式 / Dashboard 消费章节）
- 现有 Logs.tsx（理解当前结构后重写）
- 现有 server.py（了解 FastAPI 路由风格）

---

## 执行顺序

```
T030 DB迁移
T031 核心框架（StepOutput + RunLogger + ToolRegistry）
T032 Prompt System                    T033 Memory Interface
         ↓                                     ↓
T034 W1 Browser Tools    T035 W2 Browser Tools
T036 W1 非浏览器 Tools   T038 W2 非浏览器 Tools
         ↓                                     ↓
T037 W1 Pipeline                    T039 W2 Pipeline
                   ↓           ↓
                  T040 日志埋点
                       ↓
                  T041 Dashboard
```

T032/T033 可与 T034/T035 并行。
T036 需要 T030（schema）+ T032（prompts）完成后开始。
T038 需要 T030 + T032 完成后开始，不需要等 T037。
T037 需要 T031 + T034 + T036 + T033 完成。
T039 需要 T031 + T035 + T038 + T033 完成。
