# OpenJobFinder — Technical Notes

> **这份文档只写两种内容**：① 半年后大概率还成立的；② 代码里读不出来、或要翻很多处才拼得出来的。
> 一切有代码权威源的结构（表结构、字段列表、配置项、函数签名）**一律指路不复制**——同一契约写两份必然漂移，本项目已因此吃过四次亏。
>
> 为什么这么做 → `DECISION.md`　|　踩过什么坑 → `PITFALLS.md`　|　做到哪了 → `PROGRESS.md`

---

## 架构概览

```
main.py (CLI: --once/--check/--dry-run；--onboarding 已退役=提示改用 Dashboard。W3 无 CLI 入口)
    └── run_w1() / run_w2() / run_w3()          pipeline runner，两个入口（CLI 与 server）共用
            ├── VerifySessionStep               pipeline/common/：唯一的登录态校验
            ├── ToolRegistry                    工具注册与调用，log_step/log_tool 追踪
            ├── ModelRouter                     capability 路由 fast/balanced/powerful/vision
            ├── W1/W2/W3 Pipeline               Step 编排（见下方数据流）
            ├── ApplicationTracker              SQLite 状态机
            └── RunLogger                       JSONL 结构化日志 + SSE 推送

dashboard/server.py                  FastAPI，独立进程；只做 HTTP 接线，编排下沉 service
services/scheduler_service.py        APScheduler 生命周期 + scheduled 入口
services/workflow_orchestration.py   队列 runner + W1/W2/W3 runner + 限流 + 自检 + 冒烟
services/workflow_queue.py           内存 FIFO + 单守护 worker，串行化所有工作流启动
services/browser_session.py          唯一交互浏览器单例（open-in-browser / 登录 / 检查共用）
services/tracker.py                  状态写操作的唯一权威（见「后端四层约定」第二条铁律）
services/config_manager.py           config.yaml + profile.yaml 统一读写
services/run_log_reader.py           run JSONL 只读解析（列表/明细/回放，纯函数）
services/run_diagnostics.py          run 日志确定性诊断，不调 LLM

多站点 Layer 1（v2.21→，跟上面那条线**浏览器栈完全不同**：chrome-devtools-mcp + LangGraph + 各站独立
profile，不是 DrissionPage；两个 Chrome 实例互不干扰）
multisite/layer1_agent.py    m1=选岗（5 节点）/ m2=勘察申请表（4 节点）；节点内部才是 agent 循环。
                             **m2 只扫描并分类字段，不填也不提交**——填写+提交+存证是尚未做的 m3。
                             阶段表 `M1_STAGES` / `M2_STAGES` 是**前端步骤骨架的唯一权威源**
                             （v2.34.0 起由后端 `stage_names()` 导出，前端不再手抄）
multisite/safe_tools.py      守法 click（提交类点击由代码拒绝，不靠 prompt 叮嘱）
multisite/observability.py   run_scope（一次运行的生命周期）+ traced_stage（一个阶段的记录）；
                             刻意不碰浏览器/LangGraph，否则要开真 Chrome 才测得到

**但它跟 W1/W2/W3 共用两样东西，别再各造一份**（v2.24.0 共用队列 / v2.24.5 共用观测）：
- **同一个 `workflow_queue`**（串行、schedule_log、trigger 归类）——加新 workflow 要同时改
  `VALID_WORKFLOWS`、`run_item` 的 log_wf 映射与分派、**前端 `WorkflowId`**（漏最后一处会让整个 SPA 白屏）
- **同一套 `RunLogger`**（`logs/runs/*.jsonl` + SSE）——run 日志的读者（`run_log_reader` /
  `run_diagnostics` / 前端回放）只认这一种格式

简历子系统（v2.13→v2.31）
services/info_pool.py        信息池：求职者全部信息的主库，高于任何一份简历；写盘前自动快照
services/resume_blocks.py    文档形状权威（sections:[{name,blocks}]，旧五键形状读时自动转换）
services/resume_store.py     **可编辑**简历（data/resumes/{slug}.yaml + index）。v2.31 起它只是
                             「生成器」——导出一次 = 往简历库里加一份成品
services/resume_library.py   **简历库**：data/resumes/library/ 一个文件夹装所有能往外发的 PDF
                             （系统导出的 + 用户自己放的，平起平坐）。所有发简历的出口都从这里选
services/resume_parser.py    PDF → 页面图 → 视觉 LLM 解析

`services/resume_matcher.py` 已于 2026-08-21 删除——按岗位选简历现在是
`ResumeLibrary.pick`（同一套确定性关键词规则，刻意不用 LLM，理由见 DECISION），
输入从"可编辑简历条目"换成了"库里的文件"。
```

## 后端四层约定

新功能**有确定的家**，不要内联手搓：

| 层 | 放什么 | 判据 |
|----|--------|------|
| `tools/` | 对外部系统的**单个副作用操作**（浏览器/DB/LLM），经 `registry.call` 调用，ToolResult 契约，自动 trace/SSE | "是不是一次碰浏览器/DB/LLM 的活儿" |
| `pipeline/`（Step） | 把多个 tool 编排成**工作流的一个阶段** | "是不是某条工作流里的一段"——一次性交互动作不算，别造假 Step |
| `services/` | 共享基建/单例 | "是不是被多处共用的基建" |
| `dashboard/server.py` | **只做 HTTP 接线**：解析请求 → 调 tool/step/service → 序列化返回 | —— |

**铁律一：端点不准内联浏览器/LLM/业务逻辑。** 违反它必然制造两份分叉实现（加固一个漏一个）+ 不可观测（绕开 registry 就没 trace/SSE）。
> 例外：纯读端点（GET `/api/jobs`、`/api/stats`）直接调 `tracker` 序列化即可，不强行 tool 化——tool 契约是为流水线可观测/可重放设计的，仪表盘读取用不上。

**铁律二：一个状态转换只能有一份 SQL。** `tracker` 独占连接、schema、迁移，以及每个写操作的唯一实现；`tools/db/*` 是薄壳（只提供 ToolResult 契约与 registry 的 trace/SSE），**调 tracker 而不是自持 SQL**；端点里一律不出现 SQL。
> 识别判据：**同一列在不同实现里的 CASE 分支不一致**。发现分叉不要两边同步，选正确的那版收敛掉另一版。
> 曾连抓四例同构漂移（含"可能给同一 HR 二次发送"），明细见 `DECISION.md`。
> **反例同样重要**：`upsert_hr_conversation` 的两个实现**不是**分叉，是有意的职责分离（列集不同、调用方不重叠）。判断分叉前先看调用方是否重叠、列集是否相同。

---

## 数据流

Pipeline 数据流（W1 单次投递）：

```
run_w1()
  → VerifySessionStep: navigate → check URL → JS read username
  → ToolRegistry.register(navigate_search_url, extract_card_list, click_card_at, ...)
  → W1Pipeline.run(W1Config)
      → NavigateStep: registry.call("navigate_search_url", url)
      → SearchLoop: registry.call("extract_card_list") → for each card:
          → CardPipeline:
              → registry.call("classify_job_for_w1")   [skip / fetch_jd / apply_only]
              → FetchJDStep: registry.call("click_card_at") + registry.call("extract_jd_text")
              → registry.call("score_job")              [ModelRouter balanced → ollama]
              → ApplyStep: registry.call("click_apply_button") + registry.call("upsert_application")
  → RunLogger.close("done", summary)
```

Pipeline 数据流（W2 单次检查回应）：

```
run_w2()
  → VerifySessionStep
  → ScanStep: navigate_to_chat_list → scroll_chat_list → extract_conversation_list
              → filter_conversations（脏检查 / 超时过滤）→ 返回待处理 conv 列表
  → for each conv:
      → ConversationPipeline:
          → NavigateStep: navigate_to_conversation
          → ReadStep:     read_messages → write_hr_messages（落库）
          → AnalyzeStep:  read_messages 重分类平台提示为 system；
                          会话零 HR 消息时跳过 LLM、不起草（has_hr_message 守门）；
                          否则 analyze_intent [ModelRouter balanced → ollama]
                          → update_hr_analysis（落库 intent / 建议回复，reply_status=pending）
          → ResumeStep:   detect_resume 命中请求时发简历
                          （hr_card 先试 accept_resume_card，否则 / hr_text 走 click_toolbar_send_resume；
                           发送成功唯一判据：聊天框出现含「附件简历」的 item-system 系统消息）
          → upsert_hr_conversation（保留 prior_stage）
          （W2 不再发回复——边界收口到 W3）
  → FinalizeStep: backfill_application_from_conversation（W2→W1：有 job_id 无 application 的会话补 APPLIED）
                  → sync_application_status（按 job_id 硬 JOIN，interview/offer/rejection 提升 + REJECTED→APPLIED 复活）
                  + mark_timeout_statuses（会话 14 天无消息→closed 停滞软标记；不再拒绝 application）
                  + purge_stale_applications（投递满 30 天无进展 → 级联删 application+会话+消息，重走 W1）
  → RunLogger.close("done", summary{..., llm_degraded})
```

Pipeline 数据流（W3 发送已批准回复）：

```
run_w3()
  → VerifySessionStep
  → ScanStep: navigate_to_chat_list；get_approved_replies 取 reply_status IN('approved','revision')
  → for each approved reply:
      → SendReplyPipeline:
          → locate:  search_locate_conversation（输 HR 名 → 结果列表匹配公司名打开会话）
          → send:    send_chat_message（提交动作，proxy 信号）
          → verify:  read_messages 重扫会话（重试等异步渲染）+ write_hr_messages 回写
                     → 重扫结果确认 sender==me 且匹配 reply_text 才算 delivered
          → 仅 verify 通过才 mark_reply_sent（reply_status → sent）；否则保持 approved 下次再试
  → RunLogger.close("done", summary)
```

> **投递验证教训**：旧 `verify_reply_delivered`（已删）只看打开会话时的 DOM、按「我方气泡含 reply_text 前缀」匹配，会撞历史我方气泡假阳性（run 日志 `duration_ms:1` 是红旗）。正解是 send 后重扫会话确认新消息真正落地并回写 DB。验证「动作做没做」≠ 验证「结果发生没发生」。

---

## 三个状态机

状态之间怎么转、什么触发——这部分散在各处 SQL 里，确实读不出来，所以留在这。
**但状态列本身的定义以 `services/tracker.py` 的迁移代码为准。**

### 三个状态机（application status / conversation stage / LLM intent）— 2026-07-03 重构

系统由三套枚举驱动。前端「架构」navigator（`pages/StateMachine.tsx`，2026-07-04 从「状态机」升级）把它们收进**「状态机」Tab**，与「架构」「流程」「数据模型」三个 Tab 并列——整页是一份从前端看懂整个项目的架构可视化（后端四层 / W1·W2 流程 / 三状态机 + 映射 / SQLite 三表 + LLM 路由链）。核心重构：**投递是纯动作、不需要 HR 回复，"投递后无回应"不再判 REJECTED**；REJECTED 只留 HR 明确拒绝；超时改会话软标记 + 30 天清理复活。

**实况叠加**：`GET /api/architecture` → `tracker.get_lifecycle_counts()` 返回 `tables`（三表行数）+ `by_status` + `by_stage` + `running`（当前运行的 workflow）。页面各 Tab 静态结构手维护、与代码同步，实况仅作可选叠加（拉取失败照常渲染静态部分，每 15s 刷新）。

**① application status（`schemas.py` AppStatus，5 值）**

```
FOUND ──投递成功──▶ APPLIED ──▶ INTERVIEWING ──▶ OFFER
                      │              │              │
                      └──────────────┴──────────────┴──▶ REJECTED（仅 HR 明确拒绝）
                      ▲                                        │
                      └────── 复活（会话再活跃）───────────────┘
  非 INTERVIEWING/OFFER 且投递满 30 天 ──▶ 清理删除 ──▶ 重走 W1
```

- `FOUND`：投递前**内存态**（Job/ApplicationRecord 默认值），**从不落 applications 表**。
- `APPLIED`：已投递（含正在沟通）。W1 投递成功 upsert；REJECTED 复活/重投也回 APPLIED。
- `INTERVIEWING` / `OFFER`：`sync` 从会话 stage=interview / offer 提升。
- `REJECTED`：**唯一来源** = `sync` 见会话 stage=closed **且 intent=rejection**（HR 明确拒绝）。超时/陈旧不再进 REJECTED。
- **已移除 `CHATTING` / `SCORED`**（live 从不产生：sync 不映射 active→CHATTING、评分不达标不落库）；tracker init 幂等迁移历史行（CHATTING→APPLIED、SCORED→FOUND）。
- `VALID_TRANSITIONS` 已重写为与实际一致，但**仅作告警文档**：真实转移全走 `sync`/`purge` 的 raw SQL 绕过它，它只在 `upsert()`/`update_status()` 打一条 warning。

**② conversation stage（`conversation_pipeline.py` STAGE_ORDER，6 值）**
`new < active < resume_sent < interview < offer < closed`（秩）。每轮由 intent 重算：interview_invite→interview、offer→offer、rejection→closed，其余→active；发简历→resume_sent。`mark_timeout` 14 天无消息 → closed（停滞软标记，intent 不变）。closed 遇新活动被重处理 → upsert 覆写复活。

**③ LLM intent（`analyze_intent.py` `_VALID_INTENTS`，6 值）**
`interview_invite / offer / rejection / resume_request / general / unknown`。无 HR 消息跳过 LLM=unknown；LLM 全降级=unknown。持久化到 `hr_conversations.intent`，`sync` 靠它区分 closed 的两种含义（真拒 vs 停滞）。

**三者映射**：intent `interview_invite/offer/rejection` → stage `interview/offer/closed(intent=rejection)` → application `INTERVIEWING/OFFER/REJECTED`；`resume_request/general/unknown` → stage `active` → application 不变；14 天静默 → stage `closed`（软）→ application **不变**；会话复活 active + application=REJECTED → APPLIED；投递满 30 天无进展 → 连同会话删除。

### HRConversation.stage 状态流转

```
general → resume_requested → resume_sent → interview → closed
```

- `general`：正常对话，尚未发送简历
- `resume_requested`：检测到 HR 请求附件简历，但尚未确认发送成功（中间状态）
- `resume_sent`：已确认发送成功（`ResumeStep` 确认聊天框出现含「附件简历」的 item-system 系统消息后才写入）
- `interview`：进入面试阶段（待实现，目前手动标记）
- `closed`：两种来源靠 **intent 区分**——① `intent=rejection`（HR 明确拒绝，`sync` 据此把 application 判 REJECTED）；② `mark_timeout` 的**停滞软标记**（14 天无消息，intent 不变，**不连累 application**）。前者是真拒，后者只是沉寂提醒，前端「超时无回应」筛选 tab 筛 `stage=closed 且 intent≠rejection`。
- stage 只升不降：`ConversationPipeline` 在 `upsert_hr_conversation` 前读取 prior_stage，防止降级。**例外（2026-07 加）：`closed` 会话遇新活动会「复活」**——`upsert_hr_conversation` 的 CASE 首条 `WHEN stage='closed' AND excluded.stage!='closed' THEN excluded.stage`。理由：`filter_conversations` 只在有新活动（unread/preview_changed/approved）时才处理 closed 会话，所以"正在 upsert 一个 closed 会话"即证明有新活动（HR 或我方重新发言），让新 stage 覆盖 closed 才符合"重新沟通即复活"；若再次陈旧会自然重新关闭。修复前 closed 是绝对终态，导致陈旧关闭后 HR 回头（甚至换了微信）仍显示"已关闭"、且因 terminal-skip 不再被处理、hr_title 也一直补不上。
- `resume_requested` 在 `filter_conversations` 脏检查中被强制重新入队，即使 last_msg_preview 未变，确保发送失败后下次仍会重试。
- 发送失败时同时清空 `last_msg_preview=""`（双重保障），避免 stage 意外被覆盖后仍被脏检查跳过。

> 注：上为概念流转；实际 `stage` 列取值为 `new/active/resume_sent/interview/offer/closed`（见 `INTENT_STAGE_MAP` 与 `STAGE_ORDER`）。

### reply_status 回复状态机（W2 草拟 → 用户审批 → W3 发送）

```
null ──(W2 AnalyzeStep 起草)──▶ pending ──(用户批准)──▶ approved ──┐
                                  │                                ├─(W3 验证发出)──▶ sent
                                  ├──(用户修改)──▶ revision ────────┘
                                  └──(用户驳回)──▶ dismissed
```

- `null`：无回复（W2 未起草，或会话零 HR 消息被 AnalyzeStep 守门跳过）。
- `pending`：W2 起草了建议回复，等用户在会话页审批。
- `approved` / `revision`：用户批准（原文）/ 修改后保存——两者都进 W3 待发队列（`get_approved_replies` 取 `IN('approved','revision')`）。
- `sent`：W3 发送并**重扫验证落地**后才写入（仅 verify 通过）。
- `dismissed`：用户驳回，不发送。
- **保护**：`update_hr_analysis` 的 CASE 必须把 `approved/revision/sent/dismissed` 都列为终态保护，否则 W2 再分析会把它们覆写回 pending → 重复发送（见"踩坑记录"）。

---

## 数据结构在哪（不在这）

| 想查什么 | 权威源 |
|----------|--------|
| `applications` / `hr_conversations` / `hr_messages` / `scored_jobs` 表结构 | `services/tracker.py` 的 schema 与迁移代码 |
| 简历 / 信息池的文档形状 | `services/resume_blocks.py` 顶部注释 + `clean_sections` |
| 多份简历的存储布局 | `services/resume_store.py` |
| `config.yaml` / `profile.yaml` 三层配置模型与优先级 | `docs/configuration.md` |
| run 日志 JSONL 的字段与读法 | `docs/run-log-guide.md` + `services/run_log_reader.py` |
| 浏览器层收敛过程与分层论证 | `docs/browser-session-convergence.md` |

**这里刻意不复制字段表。** 复制一份就多一个会漂移的契约，而漂移的文档比缺失的文档更危险——它有虚假可信度，且没有任何机制会发现它错了。

---

## 关键约束

- **单线程，不引入 async/await**：DrissionPage 是同步阻塞 API，无法在 asyncio 事件循环中运行。Dashboard 是独立进程。
- **浏览器用 DrissionPage 而非 Playwright**：Boss直聘 检测标准 Playwright CDP。代价是 API 不兼容，切换成本高。
- **登录态在 `data/browser_profile/`**（DrissionPage 的 Chrome user-data 目录），**不是** `data/session.json`（废弃占位）。判断 session 是否有效，唯一权威是跑 `VerifySessionStep`。
- **SSE `done` 事件是 workflow 结束的权威信号**；`stop` 只设标志位，不等待终止。
