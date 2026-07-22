# OpenJobFinder — Technical Notes

## 架构概览

```
main.py (CLI 入口: --once/--check/--onboarding/--dry-run；注意 W3 无 CLI 入口，仅 Dashboard/API 触发)
    └── OnboardingChecker       (首次配置引导)
    └── run_w1() / run_w2() / run_w3()   (pipeline runner，替代旧 Orchestrator)
            ├── VerifySessionStep          (pipeline/common/: 验证 Boss 登录态)
            ├── ToolRegistry              (工具注册与调用，log_step/log_tool 追踪)
            ├── ModelRouter               (capability-based LLM 路由 fast/balanced/powerful)
            ├── W1Pipeline / W2Pipeline / W3Pipeline   (Step 编排)
            │     ├── W1: NavigateStep → SearchLoop → CardPipeline
            │     │     └── CardPipeline: FetchJDStep → ScoreJob(Tool) → ApplyStep
            │     ├── W2: ScanStep → ConversationPipeline × N → FinalizeStep
            │     │     └── ConvPipeline: NavigateStep → ReadStep → AnalyzeStep → ResumeStep （W2 不发回复）
            │     └── W3: ScanStep（取已批准回复）→ SendReplyPipeline × N
            │           └── SendReplyPipeline: locate(search) → send → verify(重扫+回写) → mark_reply_sent
            ├── ApplicationTracker        (SQLite 状态机)
            └── RunLogger                 (JSONL 结构化日志 + SSE 推送)

dashboard/server.py  (FastAPI，独立进程；只做 HTTP 接线，编排下沉 service；2026-07-22 减重 2638→2038 行)
services/scheduler_service.py       (SchedulerService：APScheduler 生命周期 + scheduled 入口，跨簇依赖注入)
services/workflow_orchestration.py  (OrchestrationService：队列 runner + W1/W2/W3 runner + 限流 + 自检 + 冒烟，get_state 访问器)
services/run_log_reader.py          (run JSONL 只读解析：列表/明细/回放，纯函数)
services/run_diagnostics.py         (run 日志确定性诊断：是否收尾/参数生效/外发落库，不调 LLM)
services/workflow_queue.py  (WorkflowQueue 单例：内存 FIFO + 单守护 worker，串行化所有工作流启动)
services/config_manager.py  (ConfigManager 单例，config.yaml + profile.yaml 统一读写)
services/browser_session.py (BrowserSession 单例：唯一交互浏览器，open-in-browser/登录/检查共用)
services/selfcheck.py   (自检探针：browser+session / db / llm 轻量健康检查)
services/resume_blocks.py  (简历+自我描述 → 可排列组合的"段落块"，LLM 分类 + 逐块摘要)
services/resume_tailor.py  (岗位特化简历/招呼语生成 + Chromium CDP 渲染 PDF)
services/onboarding.py  (浏览器登录引导；浏览器方法已桩化退役，待重写为 W-onboarding workflow)
```

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

## 模块说明

### pipeline/ — W1/W2/W3 流程编排（替代旧 orchestrator.py）

> 旧 `orchestrator.py` / `scheduler.py` 已删除。W1/W2/W3 均为 Step 模式 pipeline，`w1_runner.py` / `w2_runner.py` / `w3_runner.py` 组装 ToolRegistry + ModelRouter + Tracker 后运行；`main.py`（仅 W1/W2）与 `dashboard/server.py`（W1/W2/W3）共用此入口。

- **W1**（`pipeline/w1/`）：`pipeline.py`（NavigateStep → SearchLoop）+ `card_pipeline.py`（逐卡片：classify → FetchJDStep → score_job → ApplyStep）+ `steps/{navigate,fetch_jd,apply}`。`score_threshold<=0` 快速路径跳过 score_job LLM 调用直接投（纯流程验证用）。profile.yaml 的 `score_threshold` 在运行时覆盖 config 默认值。
- **W2**（`pipeline/w2/`）：`pipeline.py` + `scan_step.py`（命脉：导航 + 滚动抓取会话列表，空列表按失败处理，详见"已知限制"）+ `conversation_pipeline.py`（逐会话 navigate→read→**wechat**→analyze→resume→upsert）+ `finalize_step.py`（**2026-07-03 重构**：sync 状态同步含 REJECTED→APPLIED 复活 → mark_timeout 会话停滞软标记 → purge 30 天无进展清理；不再有"投递后无回应→REJECTED"）+ `steps/{navigate,read,wechat,analyze,resume}`。`llm_degraded` 计数：全 provider 失败时 intent 诚实降级 unknown 并告警。**W2 不再发回复**（边界收口到 W3）；`steps/reply.py` 已不被 conversation_pipeline 调用，属待清理死代码。AnalyzeStep 守门：会话零 HR 消息时跳过 LLM、不起草（避免对没说过话的 HR 臆造回复）。
  - **WechatStep**（`steps/wechat.py`，2026-07-01 新增）：在 ReadStep 之后、非 dry-run 时调用 `accept_wechat_card` 工具，自动点「HR 请求交换微信」卡片上的「同意」（与自动接受简历卡片同构）。点同意成功后 `_rescan_and_persist` 带重试重扫 `read_messages` + `write_hr_messages` 落库——因为 HR 点同意后**立刻以卡片形式发来微信号**（`[卡片] X的微信号\n<id>`），而 ReadStep 在点同意前就读完了，不重扫会漏。决策：换微信**不改 stage**（避免污染 offer 语义），去加微信的强提醒由前端从消息派生。无卡片时静默 no-op（不入监控骨架、不记 skipped 噪音）。
- **W3**（`pipeline/w3/`）：`pipeline.py`（W3Pipeline：ScanStep 取 reply_status IN('approved','revision')）+ `send_pipeline.py`（SendReplyPipeline：locate→send→verify→mark_reply_sent）。复用 W2 工具 + 1 个 W3 专用 tool `search_locate_conversation`（输 HR 名→结果匹配公司名打开会话）。投递验证 = `read_messages` 重扫会话确认我方新消息落地 + `write_hr_messages` 回写 DB，仅通过才 `mark_reply_sent`（reply_status→sent），否则保持 approved 下次再试。W3 目前无 CLI 入口、未接入定时调度，仅 Dashboard/API 触发。
- 投递幂等：`upsert_application` + `actions` 表 `apply_attempted` 标记防重复投递，即使崩溃重启也不重复投。

### services/workflow_queue.py — 工作流队列（并发模型，2026-07-06）

- 职责：把「所有工作流启动」串行化。**原并发模型**是单例互斥（`emitter.current_workflow`）——手动触发撞在跑的 → 409 拒绝；定时/自检撞上 → 跳过漏跑。**现改为**「一个队列 + 一个顺序 worker」：手动 trigger、定时 `_scheduled_run`、自检 `_run_selfcheck_cycle`、前端编排链（W1→W2）全部 `enqueue`，FIFO 顺序执行，不再丢。
- 关键实现：
  - `WorkflowQueue`（内存 FIFO + 守护线程 worker，`threading.Condition`）：`enqueue`（+`coalesce`：同 workflow+source 已在队列则不重复入，防定时堆积）/ `remove` / `move` / `reorder`（拖拽任意改序）/ `clear` / `pause` / `resume` / `snapshot`。worker 单线程 `while True`：取队首 → 调注入的 `runner(item)`（**同步阻塞到工作流跑完**）→ 收尾。「上一个完成」是**结构性保证**（单线程 + 同步调用），无需显式确认。
  - **解耦**：`runner` 与 `is_busy` 是注入参数（纯逻辑，可用假 runner 单测，不依赖 FastAPI/浏览器）。`is_busy` = `emitter.current_workflow` 非空时让位（交互浏览器 open-in-browser / 自检探针独占 Boss profile 时不启动新工作流）。
  - **worker 在锁外跑工作流**（只在取项/收尾时短暂持锁），保证跑长任务时 API 端点仍能加队/看快照/改序。
  - **暂停 ≠ 中止**：暂停后当前项跑完、不接下一个（`pause` 只设标志，worker 等待条件加 `paused`）；中止是停当前工作流（`emitter.request_stop`）。
- server 侧接线：`_queue_runner(item)` 派发到 `_run_apply/check/reply_workflow` + 写调度日志 + **出错清 `current_workflow` 锁**（runner 仅成功时清）；`_initialize_state` 装配队列；9 个端点 `GET/POST /api/workflow/queue`、`/batch`、`DELETE /{id}`、`/clear`、`/move`、`/reorder`、`/pause`、`/resume`。前端队列面板在控制台 CONTROL 下（当前运行 + 待执行拖拽改序/移除/时间戳 + 最近完成 + 暂停·继续）；WorkflowPanel 按钮去「运行时禁用」→ 常亮即入队，⚡W1+W2 改 `enqueueWorkflowChain`（删掉旧的盯 SSE 事件再触发 W2 的脆弱前端链）。

### 浏览器层 — browser_context + BrowserSession + tools/browser + VerifySessionStep

> **旧单体 `services/browser_agent.py`（~2400 行）已于 2026-06-16 删除**（浏览器收敛 Phase 1–3）。浏览器能力按职责拆为四块，不再有单体：
> - `services/browser_context.py`：`open_browser` / `close_browser`，流水线用的 DrissionPage 启动与关闭。
> - `services/browser_session.py`：`BrowserSession` 单例——唯一「交互浏览器主人」，承载 Dashboard 的 open-in-browser/browse-url、登录、检查 session 等交互动作。
> - `tools/browser/{w1,w2,w3}/`：各 Boss直聘 页面操作独立 Tool（见下方 tools 章节），经 `registry.call` 调用。
> - `pipeline/common/verify_session.py`：`VerifySessionStep`，唯一登录态校验入口（避免分叉误报 session 过期）。
> - `services/onboarding.py` 的浏览器方法已桩化退役，整体待重写为 W-onboarding workflow。

- 沉淀到各 Tool / helpers 的通用领域经验：
  - DrissionPage（非 Playwright）绕过 CDP 反爬，启动参数 `--disable-blink-features=AutomationControlled` + JS 注入隐藏 `navigator.webdriver`（新版 Chrome 该属性不可配置时会抛 TypeError，需 try/except 包裹）。
  - **PUA Unicode 解码**：Boss直聘 对薪资数字使用私用区字符（`\ue031`=0 至 `\ue03a`=9）进行字体混淆，由 `tools/biz_logic/decode_salary.py` 解码。
  - **JS 替代 DrissionPage selector**：Boss直聘 SPA 动态渲染的 Vue 子节点 `eles()` 返回 0，一律改用 `page.run_js("document.querySelectorAll(...)")` 直接操作 DOM。
  - **`_ele_any` timeout 语义 / `search_with_panel` 投递成功对话框假阳性**：详见下方"已知限制 — 踩坑记录"。

### services/chat_agent.py — CLI Chat Agent（已禁用）

- `--chat` 入口在 `main.py` 中已停用（打印 "temporarily unavailable, pending migration to new pipeline architecture"）。文件保留但不参与现行流程，待迁移到新 pipeline 架构后再决定启用或删除。

### services/llm_client.py — ModelRouter + 多 Provider LLM

- 职责：按能力级别路由 LLM 调用，每级内部多 Provider 顺序 Fallback。
- 关键实现：
  - **ModelRouter**（新）：持有三个 `FallbackChain`（fast/balanced/powerful），`complete(prompt, system, capability)` 路由到对应链；capability 不存在时 fallback 到 balanced，再不存在时取第一个可用链。
  - **FallbackChain**：按序尝试各 provider，第一个 `is_available()=True` 且不抛异常的即返回，同时返回 provider 名称。
  - **ClaudeCLIProvider**：`claude -p <prompt>` 是 Claude Code print-mode，不支持独立 system prompt，任何 "You are..." 开头的 system 内容会触发 Claude Code 的 prompt-injection 拒绝。解决方案：忽略 system 参数，仅发送 prompt 本身（prompt 模板已足够自包含）。subprocess 使用 bytes 模式 + `env={PYTHONUTF8:1}` 确保 Windows UTF-8 输出，不使用 `shell=True`（injection 防护）。
  - **CodexCLIProvider**（2026-07-07 更新）：`codex exec -s read-only --skip-git-repo-check --ephemeral -c model_reasoning_effort="low" <prompt>`（codex 0.13x；旧 `codex -q` 已废）。**Windows 已可用**：`shutil.which("codex")` 拿到 `.CMD` 全路径，list-form subprocess 能跑。它是**云端 OpenAI**（非本地），走完整 agent harness → ~20s + ~14.4k token/次不可约基础开销（agent 系统提示+工具 schema），故仅作 emergency fallback。传入 `output_schema` 时写临时 JSON Schema 文件 + `--output-schema <FILE>` 约束输出。
  - **OllamaProvider**：HTTP `/api/generate`，`is_available()` 检查模型名是否出现在 `/api/tags` 响应中。传入 `output_schema` 时用 `payload.format`=JSON Schema 强制**结构化输出**（不降准确性）。**关键**：payload 恒带 `think: false` 关闭 qwen3 的推理 token 生成——这才是修 180s 超时的根本（推理 trace 太慢），非推理模型不受影响。
  - **output_schema 穿透（2026-07-07）**：`ModelRouter.complete` / `FallbackChain.complete` / 5 个 provider `complete` 加 optional `output_schema`；仅 ollama（`format`）、codex（`--output-schema`）使用，其余接受即忽略，`safe_parse_json` 仍作解析安全网。`analyze_intent` 传意图 schema（intent enum + confidence/needs_reply/suggested_reply）。
  - `build_model_router(config)` 从 `config.llm.capabilities` 构建 ModelRouter，`build_llm_client()` 保留为 deprecated 兼容函数。
  - 支持的 provider 类型：`claude_cli`、`codex_cli`、`ollama`、`anthropic_api`、`openai_compatible`。
  - **全失败行为**：所有 provider 失败时 `FallbackChain` raise `AllProvidersFailedError`（不静默造假）；上层 `AnalyzeStep` 接住 → `status=DEGRADED` + `intent="unknown"`（诚实降级），W2 pipeline 累计 `llm_degraded` 计数并发 `llm_degraded` 事件告警，summary 含 `llm_degraded` 字段。
  - **W2 analysis（balanced 链）现状（2026-07-07 更新）**：链 = ollama(**qwen3:8b, think=false**) → codex_cli。根因：qwen3 是推理模型，默认生成长思考 token，负载下 180s 读超时 → 全链失败降级 unknown。修法**不换模型**（换 qwen2.5 非推理会掉准确性、爱兜底 unknown——intent 准确是 analyze 唯一职责，不能拿速度换），而是 `think=false` 关掉推理：真实 analyze_intent 工具 + 富模板实测 6/6 全对、每个 ~0.9s、走本地不降级。ollama 超时并降到 90s（快速 fail 到 codex 云端兜底）。

### services/config_manager.py — 配置统一管理（新模块）

- 职责：统一读写 config.yaml 和 profile.yaml，提供全局单例访问入口。
- 关键实现：
  - `ConfigManager(config_path, profile_path)` 在 `__init__` 时加载两个文件；`get_system_config()` / `get_profile()` 返回深拷贝，防止调用方修改内部状态。
  - `save_profile(updates)` 合并写入（不删除未提及的 key）；`save_system_config(section, updates)` 禁止写入 "llm" section（抛 ValueError），防止误操作破坏 capabilities 结构。
  - `get_config_manager()` 全局单例；若以不同 path 参数多次调用，仅第一次生效并打印 warning。
  - Dashboard 的 `/api/config/llm` POST 端点需直接写 yaml（绕过 save_system_config 的 llm 禁写），写完后热重载 `app.state.model_router`，无需重启服务。

### services/selfcheck.py — 自检探针（新模块）

- 职责：对系统三大外部依赖做轻量健康检查，供「自检」navigator 与 12h 定时自检使用。
- 关键实现：
  - 三个探针——**browser+session**（创建独立 browser → `VerifySessionStep` 验登录态 → 关闭）、**db**（连 SQLite 跑探测查询）、**llm**（按 capability 路由发一个极短 prompt，确认至少一条 provider 可用）。每个探针返回 `{ok, detail, duration_ms}`。
  - 探针是「轻量」层；「完整自检周期」（`server._run_selfcheck_cycle`）= 探针 + 真跑一轮 W1（默认 10 卡）+ W2（默认 300 会话），结果落 `data/selfcheck_history.jsonl`。
  - 自检只覆盖需常态化自动运行的 W1/W2，**不含 W3**（W3 仅手动触发）。

### services/resume_blocks.py — 简历段落块（新模块，简历功能①）

- 职责：把用户上传的简历（`data/resume_base.yaml`）+ 自我描述文本，解析成可排列组合的「段落块」，供前端 FlowCV 式编辑器编辑。
- 关键实现：
  - `BLOCK_CATEGORIES = ["education", "internship", "project", "skills", "awards"]` 固定类别；`_BASIC_FIELDS = ["name", "phone", "email", "city", "degree", "target_title"]` 基础信息字段。
  - `build_blocks(resume_base, self_description, model_router)`：LLM 把原始内容**分类**到固定类别，并对非基础块**逐块生成摘要**（一段经历 = 一个块）；走 `safe_parse_json` 容错。
  - `empty_blocks()` / `load_blocks()` / `save_blocks()`：存 `data/resume_blocks.yaml`，前端可手动增删改、排序。`is_available()` 判定是否已构建。

### services/resume_tailor.py — 岗位特化生成（新模块，简历功能②）

- 职责：按目标岗位重组段落块，生成「岗位特化简历」与「招呼语」，并渲染 PDF。
- 关键实现：
  - **预制模板**（`data/resume_templates.yaml`）：如「游戏策划类」模板，含关键词列表；`match_template(templates, job_title, jd_text)` 按命中关键词数最多者胜出，作为生成起点。
  - **组合方案**（`data/resume_plans.yaml`）：per-job 持久化已生成的简历/招呼语各部分（`load/save/get_plan`、`_set_plan_part`），按需渲染，不预生成全部。
  - `generate_resume_sections` / `generate_greeting`：LLM 以匹配到的模板为起点微调（模板兜底 → LLM 精修）。
  - `render_resume_html` + `render_html_to_pdf(html, out_path, port=9920)`：**用 Chromium CDP `Page.printToPDF` 渲染 PDF**（临时 profile，独立端口），替代 WeasyPrint。
  - 简历功能③（发送）尚未实现：招呼语规划走 W1 投递成功后入审批队列→ W3 发送；简历附件上传待调研 Boss 上传机制（见"已知限制"）。

### pipeline/common/verify_session.py — Session 验证 Step（新模块）

- 职责：验证 Boss直聘 浏览器 session 是否有效，W1/W2 runner 在 open_browser 后立即调用。
- 关键实现：
  - `VerifySessionStep(page).run()` 导航到 `https://www.zhipin.com/web/geek/recommend`，等待 12s，检查 URL 是否被重定向到登录页；再通过 `window._PAGE.name` JS 读取用户名。
  - 返回 `VerifySessionOutput(status, username, reason)`：SUCCESSFUL 时含用户名，FAILED 时含失败原因。
  - W1/W2 runner 检测到 FAILED 则 `raise RuntimeError` 中止 pipeline（browser 在 finally 块正常关闭）。
  - Dashboard `/api/check/session` 同样使用此 Step，创建独立 browser → 验证 → 关闭。

### services/llm_parser.py — JSON 解析

- 职责：从 LLM 响应文本中提取并解析 JSON，容错处理格式不规范的输出。
- 关键实现：三层解析：
  1. 正则提取 ` ```json ... ``` ` 代码块，或查找第一个 `{...}` 块。
  2. `json.loads()` 直接解析；失败则调用 `json_repair.repair_json()` 修复后再解析（处理中文文本中的未转义引号等问题）。
  3. `required_fields` 类型校验与强制转型。
- 注意：json-repair 的导入名为 `repair_json`，非 `repair`（包 API 变更）。

### tools/ — 工具层（四层分包，registry.call 统一调用）

工具按职责分四个子包，全部经 `ToolRegistry.call()` 调用（统一日志 / 错误契约，见"设计决策 — 统一的 Tool 错误契约"）：

- **tools/llm/** — 需 LLM 判断的工具
  - `score_job.py`（`ScoreJob`，`capability="balanced"`）：LLM 按固定 JSON schema 返回 5 维度独立得分（0-100），Python 端加权 `skill×0.40 + experience×0.25 + city×0.15 + salary×0.10 + growth×0.10`；硬过滤（`hard_filters`：城市不符 / 学历不足）强制 `decision="skip"`，无论总分多高。LLM 不做整体判断（models judge, code decides）。
  - `analyze_intent.py`（`AnalyzeHRIntent`，`capability="balanced"`）：分析 HR 会话意图，`_VALID_INTENTS` = interview_invite / offer / rejection / resume_request / general / unknown（**无 chatting**），输出建议回复草稿（需审批后由 W3 发送）；全 provider 失败时上层降级 `intent="unknown"`。
- **tools/browser/** — DrissionPage 页面操作；含 `verify_current_url`、`helpers`（`count_resume_delivered_markers` / `wait_resume_delivered` 等共享函数）
  - `w1/`：`navigate_search_url` / `scroll_search_results` / `extract_card_list` / `click_card_open_panel` / `read_panel_jd` / `click_apply_button` / `handle_apply_dialog` / `capture_screenshot`（投递失败时截当前浏览器画面存 `data/apply_failures/<job_id>_<ts>.png`，诊断验证码/风控/跳转；异常全 guard）
  - `w2/`：`navigate_to_chat_list` / `scroll_chat_list` / `extract_conversation_list`（抓 hr_title=HR 职位）/ `navigate_to_conversation` / `read_messages` / `accept_resume_card` / `accept_wechat_card`（点 `.dialog-icon.weixin` 卡上的「同意」，DOM 层幂等——同意后 Boss 移除按钮、重跑 no-op，绝不重复同意）/ `click_toolbar_send_resume` / `send_chat_message` / `upload_resume_file`
- **tools/db/** — SQLite 持久化，全部委托 `ApplicationTracker`，禁止在 tool / pipeline 层直写 SQL
  - `w1/`：`classify_job_for_w1`（skip / fetch_jd / apply_only 分类）/ `upsert_application`
  - `w2/`：`get_conversation_states` / `get_approved_replies` / `upsert_hr_conversation`（含遇到遗留软键行「即时吸收」再 key，跨表迁移用 UPDATE OR IGNORE 保幂等）/ `write_hr_messages` / `update_hr_analysis` / `mark_reply_sent` / `record_locate_attempt`（W3：连续 N 次定位失败即 dismiss 回复，会话被手动移除后不再无限重试）/ `mark_timeout_statuses`（**现只做会话 14 天停滞软标记 stage=closed，不再拒绝 application**；注册键仍叫 mark_timeout_rejections 保持兼容）/ `sync_application_status`（closed→REJECTED 仅 intent=rejection；新增 REJECTED+会话活跃→APPLIED 复活）/ `purge_stale_applications`（投递满 N 天且 status∉{INTERVIEWING,OFFER} → 级联删 application+hr_conversations+hr_messages，按 hr_name+company）
- **tools/biz_logic/** — 纯逻辑（无 IO）：`decode_salary` / `detect_resume`（简历请求 + already_sent 判定）/ `filter_conversations`（脏检查 + 超时过滤）/ `url_parsers`

> 投递幂等：`upsert_application` + `applications` / `actions` 表的 `apply_attempted` 标记保证同一 job 不重复投递；`dry_run=True` 时 `ApplyStep` 跳过实际点击只记日志。
> **Critic 二次审核（旧 `critique_job`）与简历 PDF 生成（旧 `generate_resume`）已在 pipeline 重构中移除**，相关链路（含 resume_path）一并撤线。

### services/tracker.py — 状态机

- 职责：SQLite 持久化所有求职记录和 HR 会话缓存，强制状态转换合法性。
- 关键实现：
  - `VALID_TRANSITIONS`（**2026-07-03 重写**）：只剩 4 个 live 态 + FOUND 入口（FOUND→APPLIED→INTERVIEWING/OFFER/REJECTED、REJECTED→APPLIED 复活、OFFER→REJECTED）。**仅作告警文档**——`_validate_transition` 只在 `upsert()`/`update_status()` 打一条 warning、不阻止转移；真实转移全走 `sync`/`purge` 的 raw SQL 绕过它。已删死态 CHATTING/SCORED，tracker init 幂等迁移历史行（`UPDATE ... CHATTING→APPLIED / SCORED→FOUND`，避免 `get_stats` 遍历枚举时 KeyError）。
  - `update_status()` 内部走 get → modify → upsert 路径，存在 read-modify-write 竞争（已知技术债，单线程场景无实际影响）。
  - 两张主表：`applications`（投递记录）和 `actions`（幂等标记，UNIQUE(job_id, action)）。
  - **hr_conversations 表**：缓存 HR 会话消息和 stage 状态；自动 schema 迁移（检测缺失列后 ALTER TABLE 补充，不 DROP）+ conv_id re-key 迁移（有 job_id 的旧行 conv_id→job_id）。写入路径有两条且**故意不合并**：①tool `upsert_hr_conversation`（W2 扫描 + W1 apply 占位的权威写入，写 identity/stage/job_id/last_msg_ts，并对遇到的遗留软键行「即时吸收」re-key；不碰 intent/reply）；②`tracker.upsert_hr_conversation()` 方法（仅 onboarding 播种用，额外写 intent/reply_status/reply_text）。两者列集与调用方不同，非重复。
  - `reset_hr_conversation_stage(conv_id, stage="general")`：将指定会话的 stage 重置，供数据修复脚本使用（如旧版代码误标 resume_sent 的会话）。

### services/onboarding.py — 首次配置与引导

- 职责：检查各项依赖就绪状态，引导用户完成初始配置。
- 关键实现：
  - `run_setup_profile()` 使用 `questionary` 库提供交互式 TUI（箭头键选择、空格勾选）。
  - 共 9 步：关键词、城市、工作类型、薪资、经验、学历、公司规模、Boss最近活跃过滤、评分阈值。
  - 第 5 步（`_step5_scan_history`）：首次运行时可扫描历史聊天，回溯标记 `stage="resume_sent"` 的会话（依据 `_has_sent_resume` 检测结果）。
  - **登录态实际存于 `data/browser_profile/`**（DrissionPage user-data 目录）；`_session_is_valid()` 仍引用的 `data/session.json` 是废弃占位。是否登录的权威判断是 `VerifySessionStep`（访问 `geek/recommend` 读 `window._PAGE.name`），而非 session.json。

### dashboard/server.py — FastAPI Dashboard（接线层，2026-07-22 减重 -600 行）

- 职责：**只做 HTTP 接线**——解析请求 → 委托 tool/step/service → 序列化返回。调度、队列执行、自检、限流、run 日志解析等**编排逻辑已下沉为独立 service**（见下三节），server.py 从 2638 行降到 2038 行。
- 减重前 server.py 混进了大量有状态编排（A 视角审视标为 High）；三批下沉后端点回归薄接线，编排可脱离 FastAPI 单测。构造用懒加载（`_get_scheduler()`/`_get_orch()`），依赖注入方式按「有无状态」选。
- 关键实现：
  - PDF 上传同时保存为 `data/resume_attachment.pdf`（用于聊天附件发送）和解析后的 `data/resume_base.yaml`。
  - 上传文件大小限制 10MB，超限返回 HTTP 400。
  - `/api/conversations` 支持 `stage` 查询参数（general/resume_sent/interview），前端过滤 chip 使用 stage-based 分类。序列化每个会话时派生 `wechat_id`（从 `[卡片] X的微信号\n<id>` 号码卡抽取，收紧为「必须 `[卡片]` 前缀 + id 形如 `^[A-Za-z0-9][A-Za-z0-9_-]{4,29}$`」以排除含"微信号"的拒绝文本误报）、`wechat_pending`（有微信号且未点掉）、`wechat_dismissed`。
  - **加微信提醒 API**：`GET /api/conversations/wechat-pending`（返回待加微信会话列表 + 微信号，供 Dashboard 强提醒卡 + 「待加微信」筛选）；`POST /api/conversations/{conv_id}/dismiss-wechat`（点掉/已添加 → 置 `wechat_dismissed=1`）。
  - **Workflow SSE 推送**：`/api/workflow/stream` 使用 Server-Sent Events，`ProgressEmitter` 单例持有当前 workflow 状态（`current_workflow`、`stop_requested`）。前端通过 SSE 接收 `step`/`status`/`message` 字段更新线路图。
  - **停止 workflow**：`POST /api/workflow/stop` 检查 `emitter.current_workflow` 是否为 None——为 None 时返回 `{"ok": false, "detail": "..."}`，不返回 ok:true，防止前端误等永远不会到来的 SSE done 事件。
  - **调度器**：APScheduler 的所有权已下沉 `SchedulerService`（见下）。server.py 在 startup 钩子经 `_get_scheduler().rebuild(...)` 装配；`/api/schedule` 经 `service.next_run_times()` 取下次运行时间，不再直接遍历 scheduler 内部。触发模式仍是 `CronTrigger`（指定时间点）+ `IntervalTrigger`（固定间隔），China 时区。
  - **队列统一执行**：所有 workflow 启动（手动/定时/自检/冒烟）都经 `WorkflowQueue` 排队，单 worker 顺序跑，runner 回调是 `OrchestrationService.run_item`（见下）。不再有绕过队列的第二条执行路径。
  - **调度配置持久化**：`data/schedule.yaml`（PyYAML；`_load_schedule_config`/`_save_schedule_config` 留在 server.py，因 7 处端点共用，作为 `load_config` 注入 SchedulerService）。
  - **调度运行记录**：`data/schedule_log.jsonl`（追加写，append 模式；Python GIL 保证多线程追加安全）。
  - **新 API 端点**：`GET /api/schedule`（返回配置 + `_next_runs` + `_scheduler_running`）；`PUT /api/schedule`（接收 `SchedulePayload`，热重载 scheduler，返回 `{ok, config}`）；`GET /api/schedule/log?limit=N`（倒序读取 JSONL，返回 `{log, total}`）。
  - **调度 selfcheck**：`_SCHEDULE_DEFAULTS` 除 apply/check 外新增 `selfcheck`（`enabled` / `interval_minutes=720`（12h）/ `w1_max=10` / `w2_max=300` / `with_probes`），与 apply/check 一起走 schedule 的 load/build/PUT 全链路；`_scheduled_selfcheck` 经 `_run_selfcheck_cycle` 触发，同样受 `current_workflow` 冲突检测保护。
  - **自检 API 端点**：`POST /api/selfcheck`（只跑探针，返回三项健康状态）；`POST /api/selfcheck/cycle`（完整周期：探针 + 真跑 W1/W2，落 `data/selfcheck_history.jsonl`）；`GET /api/selfcheck/history`（倒序读历史记录）。
  - **简历 API 端点**：`/api/resume/blocks` GET/PUT + `/api/resume/blocks/build`（LLM 解析）；`/api/resume/templates` GET/PUT；`/api/resume/tailor/resume`、`/api/resume/tailor/greeting`（岗位特化生成）；`/api/resume/plan/{job_id}` GET、`/api/resume/plan/{job_id}/pdf`（`FileResponse` 返回渲染好的 PDF）。
  - **每日投递上限**：`daily_limit`（Boss直聘 硬上限 150）从自动化页挪到 Dashboard 可编辑；`/api/stats` 与 `/api/schedule` 经 `resolve_params("w1")` 读取，写回走 workflow defaults。
  - **run 事件回放 / 列表 / 明细**：`GET /api/runs`、`/api/runs/{id}`、`/api/runs/{id}/events` 全部委托 `run_log_reader`（见下），传 `RUNS_DIR`。回放跳过 `visible is False` 与 `filter_decision` 噪声事件，做类 live 可读视图。`_validate_run_pipeline`（抛 HTTPException）留在 server.py——请求校验不属读取。
  - **run 诊断**：`GET /api/runs/{id}/diagnose`、`/api/runs/diagnose/recent` 委托 `services/run_diagnostics.py`，从 run JSONL 得确定性健康判决（见「模块说明」）。
  - **run 元信息**：`run_start` 的 `meta={trigger, params}`。`trigger` 由队列按 item.source 映射（manual/scheduled/selfcheck/smoke/smoke_live），`OrchestrationService.run_item` 组装并传给 `run_w1/w2`；run_diagnostics 据此定位冒烟自己的 run。
  - **投递失败截图（2026-07-03）**：`GET /api/apply-failure/{name}`（`FileResponse`，只允许裸 `.png` 名、防路径穿越）读 `data/apply_failures/`，供前端点开「投递失败截图」。W1 投递技术失败（button_not_found/dialog_blocked/error）经 `card_pipeline` 发可见 `job_apply_failed` 事件（带 result + 截图名）、返回 `FAILED`（**不再误计入 applied**，pipeline 新增 `errors` 计数）。
  - 前端为 React 18 SPA，构建产物输出到 `dashboard/static/`，server.py 无需改动。

### services/scheduler_service.py — SchedulerService（server.py 减重 A-1，2026-07-22）

- 职责：APScheduler 生命周期 + 两个 scheduled 入口（`_scheduled_run`/`_scheduled_selfcheck`），从 server.py 下沉。
- 关键实现：持有 `_scheduler` + 锁；跨簇依赖（入队/限流检查/自检/调度日志/配置读/last_run_time）作为 callable **注入**，故不依赖 app.state、可 fake 测试。`rebuild(cfg, restore_interval_times)`（重建并启动）、`next_run_times()`（给 `/api/schedule` 的下次运行时间，端点不再摸内部）。有状态 → 用 service 类。

### services/workflow_orchestration.py — OrchestrationService（server.py 减重 A-2，审计 High 本体）

- 职责：工作流的实际执行——队列 runner（`run_item`）、三个 W1/W2/W3 runner、Boss 日限流态、自检周期、冒烟驱动。这是 live 冒烟真正走的路径。
- 关键实现：对 app.state 的耦合不可避免（需 tracker/config/model_router/emitter/队列），故收 `get_state` 访问器**在调用时**读 app.state（此时 `_initialize_state` 已填充），而非 import app。`run_item` 是 `WorkflowQueue` 的 runner 回调：设 emitter 互斥 → 按 workflow 分派 runner → 写 schedule 日志 → 错误清互斥并 re-raise。`is_rate_limited_today`/`mark_rate_limited_today`（限流态）、`run_selfcheck_cycle`（探针→入队 W1/W2）、`submit_and_wait`（冒烟的队列钩子，enqueue + 阻塞等 item 完成）、`run_regression_smoke`（冒烟后台任务，走队列不自持互斥）。
- **同一转换只能有一份 SQL**：整改中连抓四例「同一转换多份实现」漂移（mark_reply_sent/update_hr_analysis/upsert_application applied_at/冒烟自持执行路径），均收敛。识别判据：同一列在不同实现里的 CASE 分支不一致。

### services/run_log_reader.py — run JSONL 只读解析（server.py 减重 B）

- 职责：run 列表摘要 / 分组 step+tool+业务事件明细 / 扁平化 ProgressEvent[] 回放，供「日志」navigator。
- 关键实现：**纯函数 + runs_dir 传参**（无状态 → 不用 service 类，依赖注入方式按有无状态选）。`iter_run_files`/`summarize_run_file`/`find_run_file`/`parse_run_detail`/`parse_run_events`/`iso_to_epoch`。与 `run_diagnostics.py` 是姊妹（都读 run JSONL，但后者产出健康判决、前者产出展示形状），刻意分开不强并。

### services/run_diagnostics.py — run 日志诊断器（冒烟可信化，2026-07-21）

- 职责：从 run JSONL 得**确定性**健康判决——是否收尾、参数是否真生效、外发是否落库、step/失败统计。可诊断任意历史 run（不只冒烟自己的）。
- 关键实现：全程 code decides **不调 LLM**（是否有 run_end、35 是否等于 35 都有唯一答案）；`diagnose_run(run_id)` / `render_report(diag)` / `check_params_applied` / `find_runs`；脏日志（未配对 surrogate/非法字节）做边界净化，否则恰在最该诊断的崩溃 run 上失败。读日志三条铁律见 `docs/run-log-guide.md`（run_id 是 UTC / 无 run_end 可能只是还在写 / run_end 用 done,step 用 successful 是两套词汇表）。

### 隐私防护 — pre-commit PII 扫描器 + gitignore 整目录（2026-07-22）

- 职责：防止个人数据（真实 HR 姓名/公司/聊天/头像 URL）误提交到公开 repo。三道防线互补。
- 关键实现：`scripts/precommit_pii_scan.py`——**内容**扫描（硬模式：头像 CDN URL/手机/邮箱/微信号 + 从 jobs.db 实时读真实姓名公司比对，误报压到 0，测试夹具/知名雇主降级）+ **位置**护栏（`check_staged_locations`：暂存文件落在 `code/data/`、`logs/` 等运行时根目录即拦，靠位置拦整个 .db/二进制）。`scripts/install_hooks.py` 装薄 shim。`.gitignore` 黑名单枚举收敛为整目录 `/logs/`、`/data/`（枚举子路径会漏新建子目录，正是历史泄露成因）。

### dashboard/frontend/ — React 前端

- 职责：Dashboard 单页应用，React 18 + Vite + Tailwind CSS v3，编译后替代原 app.js/style.css。
- 目录结构：
  - `src/api/index.ts`：所有 fetch 调用封装（17 个端点），类型化请求/响应接口；新增 `ScheduleWorkflowConfig`、`ScheduleConfig`、`SchedulePayload`、`ScheduleLogEntry` 类型，以及 `getSchedule()`、`updateSchedule()`、`getScheduleLog()` 三个方法
  - `src/hooks/useWorkflowStream.ts`：EventSource SSE 订阅（`/api/workflow/stream`）+ 连接中断自动重连
  - `src/context/app-context.tsx`：AppContext，全局共享 page / workflowRunning / progressEvents / isPaused / refreshControlStatus
  - `src/components/layout/`：Sidebar（导航）、Topbar（glassmorphism 顶栏）
  - `src/components/workflow/`：WorkflowPanel（参数配置 + 触发按钮）、WorkflowTrack（Metro 进度轨道）
  - `src/pages/`：Dashboard / Jobs（职位）/ Chat（会话，含「超时无回应」筛选 tab = `stage=closed 且 intent≠rejection` 客户端筛）/ Logs（日志，含"概览" tab 用 RunView 类 live 视图）/ Automation（自动化）/ SelfCheck（自检：ProbeCard + ScheduledCard + HistoryCard）/ Resume（简历：FlowCV 式编辑器 + TemplatesCard + TailorCard）/ **StateMachine（状态机：三个状态机全枚举值表 + 转移 + 映射的静态文档页，2026-07-03 新增）** / Settings（设置）
  - `src/components/workflow/interpret.ts`：run 事件解读层（STEP_LABELS / TOOL_LABELS / INTENT_LABELS / STAGE_LABELS / SKIP_REASON_LABELS + `interpretEvent`），把后端领域事件翻译成中文可读文案；`WorkflowTrack.tsx` 抽出 `RunView` 共享组件供监控面板与「日志-概览」复用。
- 关键实现：
  - **全流程串联**：WorkflowPanel 用 `useRef<'idle'|'waiting_for_apply_done'>` 追踪全流程阶段；`useEffect` 监听 `progressEvents`，apply workflow 的 `step=done && status=done` 事件触发自动发起 check workflow，期间 pending 状态从 'all' 持续到 check 完成。
  - **停止按钮常驻**：WorkflowPanel 中的停止按钮始终渲染，`disabled={stopping || workflowRunning === null}`，无 workflow 运行时以 `opacity-40` 视觉降调但不隐藏，保证用户始终可见该控件。
  - **WorkflowTrack**：`buildStepStates` 函数遍历 `progressEvents`，按 `workflow` 字段分流到 W1（apply）和 W2（check），最后一个 event 的 status 覆盖该步骤状态，支持 pending/running/done/skipped/error 五态。组件始终渲染（无事件时所有步骤显示为 pending 灰色）。布局为两张独立全宽卡片（W1 一行、W2 一行）；卡片内左侧 `HorizontalMetro`（水平地铁线路图）+ 右侧 `DetailPanel`（活跃步骤详情）。`HorizontalMetro` 用 `Fragment` 循环：每个节点列宽 96px（dot h-6 w-6 + 标签），节点间插入 32px × 2px 水平连接线（`marginTop: 11px` 使连接线精确对齐 24px 圆点中心）。W1_STEPS 3 步：`['navigate', 'fetch_jd', 'apply']`；W2_STEPS 5 步：`['navigate', 'read', 'analyze', 'resume', 'reply']`（与 `pipeline/w2` 实际 step 顺序一致）。每张 `WorkflowCard` 接受 `workflowId` prop，标题栏内置独立停止按钮，`disabled` 条件为 `workflowRunning !== workflowId`。**W2 卡片（`showRunSummary`）** 在地铁图下方展示最近一次 done run 的 summary chips（处理会话 / 发简历 / 发回复 / 状态变更，数据取自 `GET /api/runs?pipeline=w2` 的 `summary` 字段，于 run 结束 `isRunning` 边沿刷新），并在 `summary.llm_degraded > 0` 时显示橙色告警条（本次 N 个会话 LLM 降级、intent 诚实降级为 unknown）。
  - **搜索配置页（Profile）**：表单状态 `FormState` 包含 `salary`（string，单值）、`keywords`（string）、`cities/experience/degree/job_types/financing/scale`（string[]）、`industries`（string）。通用 `ChipSelect` 组件处理多选（`multi=true`）和单选（`multi=false`）两种模式；各字段选项集（`CITY_OPTIONS`、`EXPERIENCE_OPTIONS`、`DEGREE_OPTIONS`、`SALARY_OPTIONS`、`JOB_TYPE_OPTIONS`、`FINANCING_OPTIONS`、`SCALE_OPTIONS`）与 `boss_search_url.py` 中的 code maps 键名严格对应，保证前端选择直接可被 URL builder 查找。薪资范围单选，存储为 `string`（直接传给 `SALARY_CODES.get()`）。预览搜索 URL 功能调用 `POST /api/preview/search`，后端基于已保存的 profile 构造 URL（含 Chrome 打开），前端展示结果并提供复制/外链操作。
  - **加微信提醒（`Chat.tsx` + `Dashboard.tsx`）**：`isWechatCard` 认「我想要和您交换微信」请求卡 + 「微信号」号码卡（均要求 `[卡片]` 前缀），都渲染成独立绿卡；`wechatIdFrom(messages)` 从号码卡抽真实微信号（同后端收紧：`[卡片]` 前缀 + id 正则校验）。三处提醒：① Chat 会话顶部强提醒横幅动态显示「HR 微信号：<id>，请尽快添加」+「已添加」点掉按钮；② Chat 会话列表「待加微信」筛选 tab（按 `wechat_pending` 客户端过滤）；③ Dashboard `WechatReminderCard` 绿色强提醒卡（拉 `/api/conversations/wechat-pending`，逐条 公司·HR·微信号 +「在 Boss 打开」+「已添加」，含卡内文字筛选）。点掉走 `POST .../dismiss-wechat` 持久化 `wechat_dismissed`，乐观更新后全端不再提醒。会话标题（MessageThread header）显示 `公司 · HR名 · HR职位`（`Conversation` 类型加 `hr_title/wechat_id/wechat_pending/wechat_dismissed`）。前端 CJK 一律 `\uXXXX`（Edit 工具写 `\uXXXX` 会被 JSON 解码，可靠做法是放 ASCII 占位符再用 Python 字节级 replace 成转义）。
  - **10s 轮询补偿**：App.tsx 内 `setInterval` 每 10s 同时调用 `getWorkflowStatus` 和 `getControlStatus`，在 SSE 断连后补偿前端状态同步。
  - **自动调度卡片**（`ScheduleCard`）：Dashboard 页底部新增，W1/W2 两栏并列；`load()` 用 `useCallback([])` 包裹保证引用稳定，30s `setInterval` effect 依赖 `[load]`；首次挂载时调用 `Promise.all([getSchedule(), getScheduleLog(20)])` 拉取初始数据。`WorkflowScheduleSection` 子组件持有 `runNow` 和 `newTime` 本地 state，通过 `onApply(runNow)` 回调上报父组件；所有 API 调用集中在 `ScheduleCard.handleApply`，职责分离。UI 元素：启用/禁用开关、时间点标签管理（输入 HH:MM 添加/点击删除）、间隔小时输入、下次触发时间预览（`formatNextRun`）、近期运行记录（✓/▷/✕ 图标）、"保存后立刻启动一次"复选框、"应用"按钮。
  - **构建产物**：`vite.config.ts` 的 `outDir: '../static'` 和 `emptyOutDir: true`，每次 build 替换全量静态文件；当前产物约 204KB JS（gzip 约 60KB）+ 14.8KB CSS。

### Apple 设计系统令牌（tailwind.config.ts）

- 背景色：`bg.page=#000000`、`bg.card=#1c1c1e`、`bg.card2=#2c2c2e`、`bg.hover=#3a3a3c`（iOS 系统层级）
- 唯一强调色：`brand=#0071e3`（Apple Blue）、`brand.bright=#2997ff`（深色背景链接）、`brand.dim=rgba(0,113,227,0.15)`（active 背景）
- 文字层级：`text.1=#ffffff`、`text.2=#adadb8`（次要）、`text.3=#6e6e73`（三级/标签）
- 阴影：`shadow-card = rgba(0,0,0,0.22) 3px 5px 30px 0px`（Apple 弥散阴影，唯一一层，卡片无边框）
- 字体：`-apple-system, SF Pro Display, SF Pro Text, Helvetica Neue, Arial, sans-serif`（optical sizing 自动切换）
- 负字间距：通过 `style` 属性内联（`-0.374px` body / `-0.224px` caption / `-0.12px` micro），Tailwind arbitrary value 对负数支持不一致，内联更可靠
- Topbar glassmorphism：`background: rgba(0,0,0,0.8); backdrop-filter: saturate(180%) blur(20px)`，通过 `style` 属性而非 Tailwind class（`backdrop-saturate` 和 `backdrop-blur` 组合在部分浏览器需 `-webkit-` 前缀，内联可同时设置）

### tests/ — 自动化测试套件

- 职责：覆盖核心服务和 API 端点的正确性，无需真实浏览器或真实 LLM。
- 主要文件（`pytest` 在 `code/` 下运行）：
  - 状态机 / DB：`test_tracker.py`、`test_hr_conversation_tracker.py`、`test_upsert_hr_conversation_tool.py`、`test_update_hr_analysis_tool.py`、`test_mark_reply_sent_tool.py`、`test_finalize_w2_tools.py`
  - W2 Tool / pipeline：`test_read_messages.py`、`test_scroll_chat_list.py`、`test_navigate_to_conversation.py`、`test_detect_resume.py`、`test_filter_conversations.py`、`test_conversation_pipeline_preview.py`
  - LLM / 路由：`test_model_router.py`、`test_llm_parser.py`、`test_intent_classifier.py`、`test_agent_workflows.py`、`test_chat_agent.py`
  - URL / 配置 / 基础设施：`test_boss_search_url.py`、`test_config_manager.py`、`test_run_logger_and_registry.py`、`test_tool_guard.py`、`test_memory_manager.py`
  - API 集成：`test_server.py`（FastAPI TestClient，覆盖各 API 端点）
- `test_server.py` 隔离策略：
  - `client` fixture 用 `monkeypatch.setattr` 将 `dashboard.server` 的 `DATA_DIR`、`CONTROL_PATH`、`PROFILE_PATH`、`CONFIG_PATH`、`ATTACHMENT_RESUME_PATH`、`BOSS_*_PATH` 重定向到 `tmp_path`，并重置 `app.state.tracker = None` 强制 startup 以临时路径重新初始化。
  - LLM 客户端构造替换为 `MagicMock`，避免真实调用；workflow 触发测试中 runner 替换为 stub（TestClient 内 `BackgroundTask` 同步运行，不 mock 会触发真实浏览器）。
  - `_check_session_via_browser`、`subprocess.Popen`、`parse_resume_file` 在对应测试中各自 mock；409 并发保护测试直接设 `app.state.emitter.current_workflow = "apply"` 模拟运行中状态。

---

## 数据结构

### profile.yaml（用户求职偏好）

```yaml
keywords:
  - 产品经理
cities:
  - 深圳
job_types:
  - 全职
salary: 10-20K           # 单值字符串，必须严格匹配 SALARY_CODES 键（3K以下/3-5K/5-10K/10-20K/20-50K/50K以上）
experience:
  - 3-5年
degree:
  - 本科
scale:
  - 100-499人
boss_online: true        # 仅显示最近活跃的 HR（Boss直聘 bossOnline=1 参数）
score_threshold: 60      # 高于此分数才进入 Critic + 投递流程（profile 优先于 config.yaml）
```

### config.yaml（系统配置 + workflow 运行参数出厂默认）

采用三层模型（Layer 1 系统配置 / Layer 2 用户偏好 `data/profile.yaml` / Layer 3 workflow 运行参数）。完整说明、优先级链见 `docs/configuration.md`。本文件结构：

```yaml
llm:                      # [W1+W2] 按 capability 路由的 fallback 链
  capabilities:
    fast:                 # 分类 / 简单判断
    - {type: ollama, model: qwen3:8b, base_url: http://localhost:11434}
    balanced:             # W1 score_job + W2 analyze_intent
    - {type: ollama, model: qwen3:8b, base_url: http://localhost:11434}
                          # 注：claude_cli（rate-limit）/ codex_cli（Windows .cmd shim 不可用）
                          # 本机均不可用，balanced 现精简为仅 ollama
    powerful:
    - {type: claude_cli}
    - {type: anthropic_api, model: claude-opus-4-8, api_key_env: ANTHROPIC_API_KEY}
  tool_providers: {score_job: null, analyze_intent: null}  # null = 用 capability 路由
dashboard:
  port: 8765
w1:                       # 投递流程运行参数出厂默认（前端可覆盖 / 设为默认）
  score_threshold: 60     # 低于此分不投递（profile.yaml 优先）
  max_cards: 0            # 0 = 不限本次处理卡片数
  daily_limit: 150
  dry_run: false
  headless: true
w2:                       # 检查回应流程
  max_conversations: 200
  no_response_days: 14    # 会话 N 天无新消息 → 打「停滞」软标记 stage=closed（不再拒绝 application）
  stale_conv_days: 30     # 投递满 N 天且无进展(排除面试/offer) → 清理数据(级联删岗位+会话+消息)重走流程
  dry_run: false
  headless: true
```

### SQLite applications 表

```sql
CREATE TABLE applications (
    job_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    url             TEXT NOT NULL,
    status          TEXT NOT NULL,       -- AppStatus 枚举值
    score           INTEGER,             -- 0-100
    decision        TEXT,                -- "apply" | "skip"
    critic_verdict  TEXT,                -- "approve" | "reject"
    resume_path     TEXT,
    applied_at      TEXT,                -- ISO8601
    responded_at    TEXT,
    error_msg       TEXT,
    apply_attempted INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

### SQLite hr_conversations 表

```sql
CREATE TABLE hr_conversations (
    conv_id          TEXT PRIMARY KEY,   -- job_id（有则用之）否则 sha256(hr_name|company)[:12]，见 derive_conv_id
    hr_name          TEXT,
    company          TEXT,
    job_id           TEXT,               -- == Boss encryptJobId == applications.job_id，两表硬关联主键（2026-07-06）
    stage            TEXT,               -- new/active/resume_sent/interview/offer/closed
    boss_conv_id     TEXT,               -- Boss 会话 d-c 属性（导航定位用）
    intent           TEXT,               -- LLM 意图：interview_invite/offer/rejection/resume_request/general/unknown
    reply_status     TEXT,               -- W3 回复状态机（见下）
    reply_text       TEXT,               -- 建议/已批准回复正文
    last_msg_preview TEXT,               -- 列表页摘要，用于脏检查（次要信号）
    hr_title         TEXT DEFAULT '',    -- HR 自身职位（如"人力资源岗"），2026-07 加列（ALTER 迁移，仿 content_hash）
    wechat_dismissed INTEGER DEFAULT 0,  -- 用户点掉「去加微信」提醒（2026-07 加列）
    last_msg_ts      INTEGER DEFAULT 0,  -- getGeekFriendList.lastTS 毫秒时间戳，filter 脏检查主信号（2026-07-06 加列）
    locate_fail_count INTEGER DEFAULT 0, -- W3 连续定位失败次数，达 3 自动 dismiss 回复（2026-07-07 加列）
    created_at       TEXT
);
-- 注意：消息正文已拆到独立 hr_messages 表（conv_id, sender, text, msg_time, created_at），
-- 不再用本表的 JSON 列存储；ReadStep/W3 verify 经 write_hr_messages 落库（INSERT OR IGNORE 去重）。
-- hr_messages UNIQUE = (conv_id, sender, text) 3 列（2026-07-07 从旧 4 列含 msg_time 迁移）：Boss 的
--   msg_time 是不稳定相对显示串（「刚刚 09:55」vs「06-10 09:55」同消息重扫拿不同 time），4 列约束会
--   让同消息累积重复；改按内容去重，_init_db 检测旧 schema 幂等 rebuild+去重。任何跨 conv_id 迁移
--   hr_messages 必须 UPDATE OR IGNORE（否则撞 UNIQUE 回滚整事务，见 upsert_hr_conversation 吸收逻辑）。
-- hr_title：extract_conversation_list 从 getGeekFriendList API 抓不到（API 的 title 是岗位名非 HR 角色），
--   API 路径下为空；仅 DOM 兜底路径能填。
-- 会话身份（2026-07-06 硬关联升级）：conv_id = derive_conv_id(job_id, hr_name, company)，即 job_id 优先、
--   无 job_id 才退化 sha256(hr_name|company)[:12]。存量迁移：①_init_db 一次性把有 job_id 的旧行 conv_id
--   re-key 成 job_id（级联 hr_messages）；②upsert_hr_conversation 在写入时对遇到的遗留软键行「即时吸收」
--   （按 hr_name+company 找 job_id 空的旧行，re-key + 迁消息），逐步收敛历史无 job_id 的软键会话。
```

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

### data/schedule.yaml（调度配置）

```yaml
apply:
  enabled: false
  times: []          # ["09:00", "14:00"] 等 HH:MM 列表，对应 CronTrigger
  interval_hours: 0  # >0 时追加一个 IntervalTrigger
  params: {}         # 透传给 run_once() 的额外参数（如 dry_run, apply_limit）
check:
  enabled: false
  times: []
  interval_hours: 0
  params: {}
selfcheck:
  enabled: false
  interval_minutes: 720   # 12h；自检走固定间隔（不用 times/cron）
  w1_max: 10              # 每次自检真跑 W1 的卡片上限
  w2_max: 300             # 每次自检真跑 W2 的会话上限
  with_probes: true       # 周期是否先跑轻量探针
```

每次 `PUT /api/schedule` 时全量覆写，`_rebuild_scheduler` 读此文件重建 APScheduler jobs。

### data/resume_blocks.yaml（简历段落块，功能①）

```yaml
basic_info:               # _BASIC_FIELDS：不参与 LLM 摘要
  name: ...
  phone: ...
  email: ...
  city: ...
  degree: ...
  target_title: ...
self_description: ...      # 用户自我描述原文
blocks:                    # 按 BLOCK_CATEGORIES 分组，每组多个块
  education: [{title, detail, summary}, ...]
  internship: [...]
  project: [...]
  skills: [...]
  awards: [...]
```

### data/resume_templates.yaml / data/resume_plans.yaml（岗位特化，功能②）

```yaml
# resume_templates.yaml — 预制模板（关键词匹配起点）
- name: 游戏策划类
  keywords: [游戏, 策划, 数值, 关卡]
  sections: {...}         # 简历各部分模板文案

# resume_plans.yaml — per-job 组合方案（按需生成、持久化）
<job_id>:
  job_title: ...
  company: ...
  resume_sections: {...}  # 生成的简历各部分
  greeting: ...           # 生成的招呼语
```

### data/selfcheck_history.jsonl（自检历史）

每行一次自检记录（探针结果 + 真跑 W1/W2 的 summary），倒序读取展示在「自检」navigator 的 HistoryCard。

### data/schedule_log.jsonl（调度运行记录）

每行一个 JSON 对象，追加写（最新条目在文件末尾，读取时用 `reversed()` 取最新 N 条）：

```json
{"triggered_at": "2026-05-19T09:00:00+08:00", "workflow": "apply", "result": "started"}
{"triggered_at": "2026-05-19T10:00:05+08:00", "workflow": "apply", "result": "skipped"}
{"triggered_at": "2026-05-19T11:00:00+08:00", "workflow": "check", "result": "started"}
```

`result` 字段值：`"started"`（成功发起 BackgroundTask）、`"skipped"`（当时有其他 workflow 运行，冲突跳过）、`"error"`（启动异常）。

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

### ScoreResult（评分维度 JSON）

```json
{
  "dimensions": {
    "skill_match":       { "score": 0-100, "matched": [...], "missing": [...] },
    "experience_match":  { "score": 0-100, "jd_requires": "3-5年", "candidate_has": "3年" },
    "city_match":        { "score": 0 或 100, "match": true/false },
    "salary_match":      { "score": 0-100, "offered": "20K", "expected": "18K" },
    "growth_potential":  { "score": 0-100, "reason": "..." }
  },
  "hard_filters": {
    "city_excluded": false,
    "degree_insufficient": false
  },
  "resume_patch": { "summary": "...", "highlights": ["..."] },
  "overall_reason": "..."
}
```

最终分 = `skill×0.40 + experience×0.25 + city×0.15 + salary×0.10 + growth×0.10`，Python 端计算，LLM 不参与加权。

---

## 设计决策

- **DrissionPage 而非 Playwright**：Boss直聘 对标准 Playwright CDP 协议有检测，DrissionPage 使用不同的接入方式可绕过。代价是 API 与 Playwright 不兼容，切换成本较高。

- **JS querySelectorAll 替代 DrissionPage eles()**：DrissionPage 的 `eles(".selector")` 对 Boss直聘 Vue 动态渲染的子节点返回 0。改用 `page.run_js("document.querySelectorAll(...)")` 绕过此限制。凡是需要读取 SPA 动态内容（消息气泡、列表项子节点），一律用 JS。

- **conv_id = job_id 优先，sha256(hr_name|company)[:12] 退化**（2026-07-06 硬关联升级，`derive_conv_id`）：早期结论是"Boss SPA 不暴露会话唯一 ID，只能以 (hr_name, company) 做 hash"。真机后推翻——会话列表 API `getGeekFriendList` 每项都带 `encryptJobId`（== `applications.job_id` == 岗位详情 URL 片段，真机 100% 覆盖），它才是稳定的跨表硬关联主键。故会话身份改为 job_id 优先；仅在极少数拿不到 job_id 时才退回旧的 sha256 软键。这让 W1 投递与 W2 会话从投递时刻起就共享同一身份，`sync_application_status` 得以按 job_id 硬 JOIN（软键 JOIN 历史 35 次全 0 行）。

- **脏检查在 ScanStep（filter_conversations），不在逐会话阶段**：ScanStep 只读列表（不 click），代价低；ConversationPipeline 点入会话，代价高。将脏检查提前到 scan 阶段，可在进入会话前过滤无变化条目，减少不必要的页面操作。

- **微信交换卡片：自动同意不改 stage，用「点后重扫落库」+ 前端派生提醒**：自动点「同意」与自动接受简历卡片同构（各自一个幂等 tool + 一个 step）。选择不给「换微信」新增 stage 或复用 offer——offer 语义是面试后拿 offer，混入会污染 offer 统计；去加微信的强提醒改由前端从消息（微信卡片文本）派生，零 schema 改动。HR 点同意后**立刻以卡片形式发来微信号**，而逐会话流程在点同意前已 read 完，故 WechatStep 点同意成功后必须**重扫会话再落库**（同 W3「发送后重扫确认落地」的模式），否则微信号漏抓、当轮前端看不到。放弃的替代：模糊检测「是否已同意」——不可靠，改由 tool 的 DOM 幂等（同意后按钮消失→重跑 no-op）兜底。

- **stage 字段而非独立状态表**：HR 会话状态变化不频繁，不需要完整历史追踪，在 hr_conversations 加 stage 列足够。stage 只升不降（prior_stage 保护），**唯一例外是 closed 遇新活动复活**（见"数据结构 — HRConversation.stage 状态流转"）。

- **resume_requested 中间状态**：原设计只有 general/resume_sent，标记时机早于实际发送，网络超时或 UI 变化导致发送失败时 stage 已写死，会话永久被跳过。引入 resume_requested 把"检测到请求"和"确认发送成功"分开，失败保持 resume_requested，scan 强制重试，不丢失任何 HR 的简历请求。

- **发简历仅在检测到请求时**：`ResumeStep` 仅当 `detect_resume` 在会话中命中 HR 简历请求（system_notification / hr_card / hr_text）时才发；旧的"积极模式"（`aggressive_resume`，双方回复后主动发）已随重构移除。

- **结构化维度评分而非 LLM 整体判断**：LLM 整体打分结果不稳定、不可解释、难以调参。改为强制 LLM 按固定 schema 返回各维度分数，Python 端做加权求和，可独立调整权重和阈值，行为可预期。

- **score_threshold 三级优先级**：profile.yaml > config.yaml > 代码默认值（60）。profile 优先是因为阈值属于用户个人偏好（投多少），config 属于系统部署配置，两者语义不同。

- **SSE done 事件作为 workflow 结束的权威信号**：HTTP POST `/api/workflow/stop` 只是设置标志位（`stop_requested=True`），不代表 workflow 已终止。前端恢复按钮状态的唯一时机是收到 SSE `step="done"` 事件（由 `finish_workflow()` 发出）。如果 `/api/workflow/stop` 返回 `ok:true` 而实际没有 workflow 在运行，前端会永久等待永远不会到来的 done 事件，导致按钮卡死；因此 `current_workflow` 为 None 时必须返回 `ok:false`。

- **JS/HTML 中 CJK 字符一律 `\\uXXXX` escape**：Windows 上部分工具（含 codex）在读写文件时会以 GBK 而非 UTF-8 处理，裸中文字符串会被静默损坏且难以批量恢复（损坏后每个字符都变为 2-3 个乱码字符，字节长度变长，sed/replace 难以精确定位）。`\\uXXXX` 是纯 ASCII，对任何编码工具链均安全，这是从两次编码损坏事故中得到的教训。

- **json-repair 作为二层兜底**：LLM（尤其是 claude -p CLI）输出的 JSON 偶尔包含未转义的中文双引号，导致 `json.loads` 失败。json-repair 可自动修复此类常见错误，不依赖 LLM 输出完全规范。

- **APScheduler BackgroundScheduler 而非 AsyncIOScheduler**：DrissionPage 使用同步阻塞 API，无法在 asyncio 事件循环中运行；`BackgroundScheduler` 在独立线程池中执行 job，与 uvicorn 的 asyncio event loop 完全隔离。`AsyncIOScheduler` 要求 job 是 coroutine，不适用。代价：需手动通过 FastAPI `startup`/`shutdown` lifecycle hook 管理调度器生命周期，且 job 执行时不在 asyncio 上下文中（不能直接 await）。

- **React + Vite 替代原生 JS**：原 app.js 约 3400 行，状态散落在全局变量和 DOM 中，添加新功能（headless toggle、generate_resume、W1/W2 详细进度）需在多处同步修改。React Context + useState 解决状态管理问题；Vite HMR 提升开发体验；Tailwind 工具类消除手写 CSS 维护成本。构建产物通过 `outDir: '../static'` 直接落入 FastAPI 静态文件目录，服务端零改动。

- **Apple 设计系统而非自定义深蓝主题**：原主题（#0B0D17 背景、#5B7FFF 强调色、卡片有边框）视觉层级混乱，强调色与蓝色文字链接难以区分。Apple 设计原则：纯黑底 + 单一强调色（#0071e3）+ 无边框卡片（用弥散阴影代替）+ SF Pro 字体负字间距，层级清晰，可复用性强。卡片无边框是刻意选择，阴影提供足够的空间感。

- **负字间距通过 style 属性而非 Tailwind 自定义 class**：Tailwind 对 `tracking-[-0.374px]` 等 arbitrary value 在不同版本行为不一致；`letterSpacing` 是 React inline style，跨版本稳定，且 IDE 有类型提示，代价是更冗长。

- **ModelRouter capability 路由替代三链式 llm_clients dict**：原设计为 scoring/generation/analysis 三条独立链，工具必须在注册时被绑定到对应链，无法按任务复杂度动态选择 provider。新设计：工具声明 `capability = "fast/balanced/powerful"`，调用 `router.complete(prompt, capability=...)` 路由，config 按能力级别组织 provider 列表，语义更清晰，日后新增工具无需修改链配置。

- **ClaudeCLIProvider 忽略 system 参数**：`claude -p` 运行在 Claude Code 的 print-mode 下，拥有 Claude Code 自己的 system prompt，用户消息中的 "You are a job screener..." 类角色声明会触发 Claude Code 的 prompt-injection 拒绝。解决方案：忽略 system 参数，只发 prompt 本身。工具的 prompt 模板（PromptManager 渲染）已足够自包含，不需要独立 system prompt。其他 provider（anthropic_api、ollama）正确支持 system 参数。

- **FallbackChain 多 Provider**：单一 Provider 出现限流或宕机时自动切换，对调用方透明。provider_used 字段记录实际使用者，便于追踪。

- **幂等投递**：Boss直聘 不允许重复投递同一职位，actions 表的 UNIQUE(job_id, action) 约束在数据库层面保证投递幂等，即使程序崩溃重启也不会重复投递。

- **status 词表分离：文件日志（领域语义）vs SSE 推送（展示语义）**：后端有一套领域 status 词表（`StepStatus` 枚举值 `successful/failed/degraded/skipped`，加 emitter 的 `running/done/info/stopping`），前端 `WorkflowTrack` 的 `StepStatus` 类型是另一套展示词表（`pending/running/done/skipped/error/blocked`）。两者此前被直接画等号，导致 `successful` 步骤节点不变绿、`failed` 不变红（前端 `as StepStatus` 是编译期断言，运行时落 default → 灰色"等待"）。解决方案是在 `pipeline/run_logger.py` 加 `_ui_status()` 映射（`successful→done`、`failed→error`、`degraded→skipped`），**仅在构造 SSE `ProgressEvent` 时翻译**；写入 JSONL 文件的日志仍保留领域词。这样做的理由：文件日志服务于排查分析，需要保留语义精度（能区分 `failed` 硬失败与 `degraded` 软降级）；SSE 服务于 UI 上色，只需展示词。转换收口在 run_logger 边界一处，后端业务代码只说领域词，不提前耦合 UI 词。注意 `message` 字段仍保留原始领域词（如 `Step reply: failed`），彩色 chip 用映射词上色、文字消息保精度。

- **控制流与状态标签解耦（reply 发送失败标 FAILED）**：reply step 回复发送失败时，控制流上"跳过继续处理下一会话"是一个决策，"这一步在日志/UI 记成什么"是另一个决策，两者独立。此前发送失败返回 `DEGRADED`（经上面的映射变灰色 skipped），等于因为"流程选择跳过"就把真实失败的标签降格，掩盖了问题。现改为返回 `FAILED`（变红 error）：流程照样跳过（下游 `conversation_pipeline` 只读 `ReplyStepOutput.sent`，不读 `.status`，控制流不受影响），但标签如实反映失败。原则：control flow 决定"下一步做什么"，status label 决定"这一步记成什么"，不应互相绑架。

- **W2 ScanStep 健壮性：scan 是命脉，空列表按失败处理**：ScanStep（导航聊天列表 + 滚动抓取会话）是 W2 的命脉——`filter_conversations` 只遍历抓取到的会话列表，若 scan 抓不到任何会话，下游所有操作（包括已审批待发的 HR 回复）都无法进行。三项保护：① **重试**：navigate+scroll 最多 3 次，重试时调 `navigate_to_chat_list(force=True)` 强制重载（绕过"已在聊天页则短路不重载"逻辑）+ `2s×attempt` 退避——空列表通常是瞬时失败（DOM 未就绪 / 页面漂移 / SPA 晚渲染）。② **空到底=可见硬失败**：重试耗尽仍空则返回 `StepStatus.FAILED`，复用 W2Pipeline 既有 `scan_failed` 通路（close logger failed + summary error）。空账号（真无会话）也按失败处理——对该产品可接受，能跑 W2 者通常已有会话，与其静默成功掩盖选择器失效，不如显式报错。③ **待审批回复会话漏抓告警**：已审批待发的回复，其会话必然在之前的 run 中被抓到过（否则不会进 DB 拿到审批）；若本轮 scan 未抓到该 conv_id，说明会话异常消失，而 `filter_conversations` 会静默丢弃其回复 → 发 `status=failed` 告警事件让其在 UI 显眼。

- **日志大字段过滤（`_LARGE_FIELDS` 黑名单）**：`ToolRegistry.call()` 写 tool 日志时会剔除 `_LARGE_FIELDS` 黑名单中的字段，避免重数据 / 隐私落盘。`ExtractConversationList` 返回的 `items`（整个会话列表，含 HR 姓名 / 公司 / 消息预览）已加入黑名单——此前因 key 名不在黑名单，滚动循环里每抓一屏就把整列表完整写入一次日志，既爆量又泄露隐私。新增 tool 若返回大数组 / 敏感数据，需同步把其 data key 加入黑名单。

- **统一的 Tool 错误契约（raise vs ok=False）+ Step 必须检查 .ok**：tool 层混用两种失败风格会让调用方无所适从（曾导致 DB 读失败既不记日志也可能被静默忽略）。规则统一为：
  - **系统/意外错误**（DB 失败、编程 bug 等"不该发生"的）→ **raise**，不在 tool 内 try/except 吞掉。`ToolRegistry.call()` 在 except 里先 `log_tool(failed)` 再 re-raise——既保证失败进 tool trace，又保持 fail-fast 不吞异常。
  - **预期内、调用方需要分支处理的结果**（元素未找到、弹窗不存在、简历卡片不在）→ **return `ToolResult(ok=False)`**。
  - **Step 责任**：对"会返回 ok=False"的调用必须检查 `.ok`，按语义分支或上报为 step 失败（发可见红色事件），**不可直接读 `.data` 而忽略 ok=False**，否则把失败变成静默吃空数据。例：ScanStep 现在检查 `extract_conversation_list.ok`（失败 → `stop_reason="extract_error"` 截断为 degraded）；ConversationPipeline 检查 `upsert_hr_conversation.ok`（失败 → 红色 step 事件 + 跳过该会话，已发出的 reply/resume 仍计数）。
  - **"是否立刻终止"是独立决策**：scan 抓取失败 = 截断本轮但用已有数据继续；单会话 upsert 失败 = 跳过该会话、循环继续；只有 ScanStep 整体失败才中止整个 W2。失败粒度由 step/pipeline 决定，与"失败要可见"两回事。

- **W2 发简历三策略（当前只接线两条）**：HR 索要简历有三种应答路径——① `accept_resume_card`（点 HR 卡片"同意"，含境外二次确认）② `click_toolbar_send_resume`（点工具栏"发简历"，双方回复后才解锁）③ `upload_resume_file`（文件上传兜底）。`DetectResumeRequest` 能识别 `system_notification / hr_card / hr_text` 三类请求，但 `ResumeStep` 当前只接线策略 ① 和 ②（card 类先试 ①，否则走 ②；hr_text 直接走 ②）。策略 ③（上传）已撤线（其 resume_path 链路一并移除）。**已验证（2026-06-11，真实站点 30 会话）**：策略 ② 按钮 `[d-c="62009"]` 正确；两条策略的发送成功统一锚定唯一真相——发送后聊天框出现 `.message-item.item-system` 且含「附件简历」的系统消息（境内"…已发送给Boss"、境外"附件简历请求已发送"，实测 15/15）。判据下沉到 tool 内（`helpers.count_resume_delivered_markers` + `wait_resume_delivered` poll，发送前后 marker 增量），`ResumeStep` 只读 `sent`——杜绝旧的"按钮可点/框消失即成功"误报（境外卡在跨境二次确认框 `.panel-resume.sentence-popover`→`.btn-sure-v2` 时简历未发出却谎报成功的 bug）。`DetectResumeRequest.already_sent` 同源（限定 `sender=='system'` 且含「附件简历」，避免 HR 索要文本误判）。

---

- **简历 PDF 用 Chromium CDP `Page.printToPDF` 而非 WeasyPrint**：WeasyPrint 在 Windows 上依赖 GTK 原生库（`libgobject-2.0-0` 等），`pip install` 成功但运行期 `OSError: cannot load library` —— 本机无 GTK 不可用。项目已内置 DrissionPage（Chromium），复用其 CDP `Page.printToPDF` 渲染 HTML→PDF（临时 profile + 独立端口 9920），零新增系统依赖。代价：每次渲染要起一个无头 Chromium，比纯库渲染重，但稳定可用且与现有浏览器栈一致。

- **陈旧会话关闭按「最后一条消息时间」而非 `created_at`**：旧逻辑用 `hr_conversations.created_at` 判 30 天陈旧——会话创建早但近期仍有往来时会被误关。改为 `COALESCE((SELECT MAX(m.created_at) FROM hr_messages m WHERE m.conv_id=...), created_at)`，以最近一条消息时间为准（无消息才退回 created_at）。语义对齐「真正沉寂的会话才关」。

- **投递是纯动作、超时是流程问题不是拒绝（2026-07-03 重构）**：旧设计把三件事混进 `REJECTED`——① HR 明确拒绝 ② 投递后 N 天无回应 ③ 会话陈旧关闭。但投递（打招呼）**不需要 HR 回复即成立**，"HR 没回"不等于被拒。重构后：`REJECTED` 只留 ①（intent=rejection）；② 彻底移除（投递后无回应不再改 application 状态）；③ 改为会话 `stage=closed` 停滞**软标记**（不连累 application）。投递动作本身的技术失败（找不到按钮/点击未确认/跳转异常）则作为**错误单独报出**（`job_apply_failed` + 截图 + `errors` 计数），不再静默吞掉或误计成"投递成功"。放弃的替代：给超时新增 EXPIRED 态——用户判定超时不该是状态流转而是"该重来"，故走清理而非新态。

- **30 天自动复活 = 清理数据而非改状态**：Boss 岗位「最后沟通一个月后自动复活」重新出现在搜索页。对应我方：投递满 30 天且无实质进展（排除 INTERVIEWING/OFFER）的 job，`purge_stale_applications` **级联删除** application + 会话 + 消息（按 hr_name+company）。岗位再现时 `classify` 查无 → 当新岗位重走完整 W1。选清理而非"改回可投状态"：省事、彻底、天然联动会话；代价是丢历史（但 30 天无进展的记录价值低）。另有即时复活：`REJECTED` 的 application 若会话又收到 HR 消息复活为 active，`sync` 把它恢复 APPLIED（raw SQL 覆写跨状态机）。

- **run 元信息（trigger + params）贯穿 live 与回放**：`run_start` 记 `meta={trigger, params}`，经 `emitter.start_workflow(meta)`（live SSE 的 start 事件 detail）与 `_parse_run_events`（回放）两路都送到前端，Live 面板标题栏显示「谁触发的（手动/定时/自检/命令行）+ 本次参数」。trigger 由调用方经 `overrides["_trigger"]` 标注，params 由 runner 自组，两路共用同一 meta 保证一致。评分反馈按 `above_threshold` 绿/红着色（`liveMsgCls`）。

- **自检只覆盖 W1/W2，不含 W3**：自检的目的是保障**需常态化自动运行**的流程健康；W3（发已批准回复）按设计仅手动触发、无定时调度，纳入自检会在无人值守时自动发出回复，违背「发送需人审批」边界。故 `_run_selfcheck_cycle` 只真跑 W1+W2。

- **岗位特化简历：模板兜底 + LLM 精修，按需生成**：纯 LLM 从零生成简历不稳定、慢、难复用；纯模板又无法贴合具体 JD。折中为「关键词匹配预制模板作起点 → LLM 在模板基础上微调」，且 per-job **按需生成并持久化**（`resume_plans.yaml`），不预生成全部岗位，省 LLM 调用。

- **每日投递上限放 Dashboard 而非自动化页**：`daily_limit=150` 是 Boss直聘 平台**硬上限**（投满即封当日入口），属用户需随时知晓/调整的关键约束，归在主 Dashboard 比埋在自动化设置里更合适；读写统一经 `resolve_params("w1")`，与其他 workflow 参数同源。

- **并发模型：工作流队列取代单例互斥（2026-07-06）** → 原 `emitter.current_workflow` 单锁：手动触发撞在跑的 → 409 拒绝、定时/自检撞上 → 跳过漏跑。改为「一个内存 FIFO 队列 + 一个顺序 worker」，所有工作流启动统一 enqueue、FIFO 顺序执行。放弃的替代：①callback 链式（上一个完成回调触发下一个）——重入/竞态复杂，队列用「单线程 + 同步阻塞调用」让「上一个完成」成为结构性保证；②持久化队列——v1 内存足够（重启清空只多一次会重新入队的机会）。机制放 services（注入 runner/is_busy 可单测），接线留 server。
- **意图准确性优先于速度：qwen3:8b + think=false，不换 qwen2.5（2026-07-07）** → W2 analyze 唯一职责是判 intent，准确性不能拿速度换。qwen3(推理) 慢的根因是生成思考 token（180s 超时降级），非模型本身；`think=false` 关推理后又快(~0.9s)又保留强模型准确性（真实模板 6/6）。放弃的替代：换 qwen2.5(非推理) 提速——实测模糊 HR 消息上明显更弱、爱兜底 unknown（对流水线最没用）。
- **LLM 结构化输出：optional output_schema 穿透（2026-07-07）** → 给 ModelRouter/FallbackChain/provider.complete 加 optional `output_schema`，ollama 用 `format`、codex 用 `--output-schema` 约束 JSON，其余接受即忽略、`safe_parse_json` 仍兜底。选 optional kwarg 穿透（标准、非 hacky）而非给 provider 硬编码 schema（不同工具 JSON 形状不同）。
- **hr_messages 按内容去重（3 列 UNIQUE）** → Boss 的 msg_time 是不稳定相对显示串，含 msg_time 的 4 列 UNIQUE 会让同消息重扫累积重复；改 (conv_id,sender,text) 3 列按内容去重。放弃「保留 msg_time 精确去重」——重扫噪声大于精确价值。
- **count_today 排除 backfill 重构行** → `AND score IS NOT NULL`：backfill_application_from_conversation 补录历史投递时 score=NULL、applied_at=now()，会灌水「今日投递」（一次补 96 条→147 vs 真 51）；真 W1 投递 score 恒非 NULL，据此干净分离。
- **一个状态转换只能有一份 SQL（2026-07-22）** → tracker 独占连接/schema/迁移与每个写操作的唯一实现，`tools/db/*` 是薄壳调 tracker（提供 ToolResult 契约与 registry trace/SSE），端点一律无 SQL。整改中连抓四例「同一转换多份实现」漂移：mark_reply_sent 三份两义（一份写 NULL 而非 'sent' → 可能二次发送）、update_hr_analysis 双实现（tracker 版缺 last_analyzed_ts）、upsert_application 的 applied_at 语义相反（保留首次 vs 更新为最后）、冒烟自持执行路径。识别判据：**同一列在不同实现里的 CASE 分支不一致**。发现分叉不两边同步，选正确那版收敛。放弃的旧措辞「禁止 tool 层直接执行 SQL」——与 `tools/db` 全部复用 tracker.conn 的 sanctioned 形态冲突，读起来像被集体违反。
- **server.py 减重：依赖注入方式按「有无状态」选（2026-07-22）** → 编排从「接线层」下沉三个 service。有状态的（SchedulerService 持 scheduler+锁、OrchestrationService 持限流态+队列引用）用 **service 类 + 跨簇依赖注入**（callable/`get_state` 访问器，不 import app，可 fake 测）；无状态的（run_log_reader 纯文件读）用**纯函数 + 路径传参**。放弃一刀切统一为 service 类——无状态逻辑用纯函数更简单最好测。`OrchestrationService` 用 `get_state` 而非 import app：在调用时读 app.state（`_initialize_state` 已填充），保留对懒填充的依赖又解耦 FastAPI。
- **冒烟测试可信化：covered 独立于 ok（2026-07-21）** → 「本轮没投没发」旧逻辑直接 ok=True = 门形同虚设。加 `covered` 维度独立于 `ok`，验收看 `fully_covered` 而非 `ok`。覆盖判据必须选「能被主动触发的路径」（W1 有 score_threshold 旋钮可强制投；W2 发简历依赖 HR 索要、无旋钮 → 覆盖改看主链路 convs_processed，发送分支的落库断言在真发生时仍从严）。断言基于 run log 而非内存报告——log 每行 flush、崩溃仍在（`run_diagnostics`）。放弃发明 force_apply 开关——复用既有 score_threshold 旋钮。

## 协作基础设施

本项目由 Claude Code（架构/审查）和 Codex（实现）共同维护，两份元文件记录协作约定和当前上下文：

- **AGENTS.md**：两个 agent 共同遵守的约定，包含编码规范（CJK 用 `\uXXXX`）、文件改动纪律、自检清单、冲突处理流程。
- **COLLAB.md**：异步沟通频道，每次做了对方需要知道的改动后追加一条记录（Time / Author / Scope / Change / Risk/Follow-up）。work-logger 写完 worklog.md 后自动联动写入。

---

## 已知限制与可改进方向

> **2026-07-22 整改收口**：四路独立审视的 High/Med/Low + server.py 减重已全部处理（明细见 `docs/audit-remediation-log.md`）。审查中确认两处「双实现」是**有意设计**非缺陷、维持原样：`upsert_hr_conversation`（工具版=运行时身份/stage、tracker 版=onboarding 播种，列集与调用方不重叠）、`filter_conversations` 的 `too_old` 优先于 `unanalyzed`（分析两月前死线程无收益，真机 909 会话靠此窗口收敛到约 12）。剩余可选项：server.py 减重批 C（session helpers，31 行，收益小）。

**必须改（影响正确性）**

- `update_status()` 走 read-modify-write 路径，多线程/多进程场景存在竞争（当前单线程不影响，引入并发后需改为直接 SQL UPDATE）。
- `datetime.utcnow()` 已废弃，需全局迁移到 `datetime.now(timezone.utc)`。

**待真实环境验证**

- `send_chat_message` 的输入框选择器（`.input-area div[contenteditable='true']` 等候选项）未充分验证，Boss直聘 实际 DOM 结构可能变化。
- 未读 badge selector 未验证（测试期间所有会话均已读，badge 未出现）。
- `extract_conversation_list` 的 `boss_conv_id` 取自会话卡片 `.friend-content` 的 `d-c` 属性，但已知 Boss直聘 的 `d-c` 普遍是用户自身 ID 而非会话唯一 ID；其在 `navigate_to_conversation` 中的实际用途与有效性待确认。
- W2 会话卡片解析（`extract_conversation_list`）全部使用 CSS class 选择器（`.friend-content-warp`、`.name-text` 等），Boss直聘 改版易碎，已配 fallback 链缓解，待真实环境验证命中率。
- `accept_resume_card` 的境外跨境二次确认框选择器（旧 `.boss-dialog__button`）未实测，靠「附件简历」marker 兜底（详见"设计决策 — W2 发简历策略"；2026-06-11 已实测 toolbar 主动发送路径 15/15，accept 路径靠 marker 自验证）。

**可选改进**

- `apply()` 选择器使用 CSS class（`.job-card-wrap`），Boss直聘 前端更新后可能失效；建议改为 data-* 属性或更稳定的选择器。
- `_classify_message()` 中英文关键词匹配逻辑不一致（Chat Agent W1）。
- Chat Agent：_execute_pending 中 Guard 的 state 传入方式脆弱（内部匿名类伪造），Ollama 失败后 `_ollama_available` 永久禁用本次 session。
- ~~`job_id` 关联目前靠 company 名模糊匹配~~（2026-07-06 已解决）：两表现按 `job_id`（encryptJobId）硬关联，同公司多岗位不再误配。仅历史无 job_id 的软键会话仍走 hr_name+company 兜底，随重扫「即时吸收」逐步收敛。
- **简历功能③（发送）未实现**：招呼语规划走「W1 投递成功 → 生成 → 进审批队列 → W3 发送」，简历附件的发送目前无流程——需先调研 Boss直聘 附件简历上传机制（`upload_resume_file` tool 已撤线）再接线。`/api/stats` 的 `attachment_resume.ready=false` 即此状态。
- **资源历史/方案文件无清理**：`data/selfcheck_history.jsonl` / `resume_plans.yaml` 持续追加/累积，暂无 GC，长期运行需加上限或归档。

**踩坑记录**

- **DrissionPage 4.1.x 键盘 API**：`ChromiumElement` 和 `ChromiumPage` 均无 `.key` 属性，调用会直接抛 `AttributeError`。唯一正确键盘操作入口是 `page.actions.key_down('Enter').key_up('Enter')`（`Actions` 类，通过 `page.actions` 获取）。
- **`update_hr_analysis` CASE 保护范围**：`CASE WHEN reply_status IN ('approved','revision') THEN reply_status ELSE ?` 若不包含 `'sent'` 和 `'dismissed'`，W2 AnalyzeStep 触发 LLM 再分析时会把已发送（sent）或已忽略（dismissed）的状态覆写回 pending，导致同一条回复被重复发送。保护列表必须包含所有"终态"：`('approved','revision','sent','dismissed')`。

- **ClaudeCLIProvider prompt injection 拒绝**：`claude -p` 运行在 Claude Code 的 print-mode 下，用户消息中以 "You are a..." 开头的角色声明（含通过 `System: ...` 拼接的 system 内容）会触发 Claude Code 的 prompt-injection 拒绝，返回中文警告文本，不执行任务。正确做法：忽略 system 参数，仅发 prompt；prompt 模板应足够自包含（不依赖外部 system 角色定义）。

- **claude -p 输出编码（Windows）**：subprocess 用 `text=True, encoding="utf-8"` 时，Windows 上 Claude CLI 的中文响应会被 GBK 误解码为乱码。正确做法：用 bytes 模式读取 stdout，手动 `.decode("utf-8", errors="replace")`，并在 env 中设置 `PYTHONUTF8=1`。
