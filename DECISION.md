# OpenJobFinder — Decisions

> 记录**为什么这么做，以及为什么不那么做**。
> 代码只保留活下来的东西——被否掉的方案在代码里零痕迹，最容易被后来者推翻重做，这份文档就是为了防止那件事。
>
> **新增条目格式**（追加在对应分区末尾）：
> ```
> ## <结论，一句话>
> - 日期 / 版本：
> - 背景：什么问题逼出了这个选择
> - 选了什么：
> - 否掉了什么，为什么：  <- 最重要的一行，别省
> - 代价 / 已知不足：
> - 什么情况下该重新考虑：  <- 给未来的自己一个推翻的条件
> ```
> 下面的历史条目是 2026-08-05 从 `TECHNICAL.md` 原样迁入的，格式较松（当时无此规范），**内容未作改写**。新条目按上面的格式写。

---

## 历史决策（自 TECHNICAL.md 迁入，2026-08-05）

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

## Dashboard 不加访问控制

- 日期 / 版本：2026-08-09
- 背景：全项目扫视审计发现 `dashboard/server.py` 104 个端点零认证、且官方启动命令绑定 `0.0.0.0`——同局域网设备理论上能让 agent 对真实 HR 批准/发送回复、远程重启后端、改配置。审计报告按严重程度把这条排在最前面。
- 选了什么：不加认证，维持现状。
- 否掉了什么，为什么：加一个共享密钥 header 中间件（工作量小-中）——用户明确判定局域网只有本人使用，当前威胁模型下这层认证不产生实际防护收益，加了只是形式主义。
- 代价 / 已知不足：如果未来局域网环境变化（多人共享网络、暴露到公网、接入不受信任的 IoT 设备等），这个风险敞口会重新变得真实。
- 什么情况下该重新考虑：部署环境从"个人独占局域网"变成"多方共享网络"或考虑公网访问时，必须先加认证再开放。

## 面试卡片的分类用 `kind` 平铺字段，不用 `sections` 嵌套

- 日期 / 版本：2026-08-09，v2.19.2.16
- 背景：面试准备内容要从"只有项目问答"扩到"项目问答 + 通用八股"，同一个岗位下需要分组展示。
- 选了什么：**用户拍板**——卡片加一个 `kind: project | basics` 字段，`roles[].cards[]` 的平铺结构不动。
- 否掉了什么，为什么：`roles[] → sections[{name, cards}]` 的动态分区（就是简历模块用的那套形状），分区名可以自由到"语言基础/数据库/并发"这种粒度。否掉是因为它要改 loader 的嵌套解析、改前端的两层渲染，且**现有内容得整体转换**，而实际需要的只是二分。灵活性是真的，但这次没有需求要它。
- 代价 / 已知不足：分组粒度被锁死在两类。想按"数据库/并发/语言"细分就得再改数据形状。另外 `kind` 缺省 `project` 是历史兼容用的（老卡片一个字没改），这个缺省值本身是个隐式约定。
- 什么情况下该重新考虑：某个岗位的八股堆到二三十张、需要按主题再分组时——那时改成 `sections` 是对的，转换脚本也好写（按 `kind` 先切两组即可）。

## 面试卡片答案默认折叠

- 日期 / 版本：2026-08-09，v2.19.2.16
- 背景：同一份材料有两种用法——考前通读，和临场自测（先看问题、自己答一遍再对答案）。
- 选了什么：**用户拍板**——卡片默认只显示问题，点开才出答案/证据/别这么说；顶部一个"全部展开/收起"照顾通读。折叠状态是前端本地状态，不落库。
- 否掉了什么，为什么：保持原来的全展开（改动最小，就是把 tab 搬成独立页）——但那样自测就没法做，一眼扫过去答案全在那儿。也否掉了"折叠 + 掌握度标记（会了/再看看）"，那要多一层交互和持久化状态，这次工作量明显变大，等真的用起来发现需要再说。
- 代价 / 已知不足：切岗位会重置展开状态（key 是按岗位划分的，不重置会半开）；刷新页面也会丢，因为没做持久化。
- 什么情况下该重新考虑：如果实际用下来发现"每次都要点全部展开"，说明通读才是主用法，那默认值应该反过来。

## 黑名单状态用独立字段，不复用 stage='closed'

- 日期 / 版本：2026-08-09（设计阶段，未实现）
- 背景：设计多级黑名单机制（覆盖 W1+W2），需要决定 W2 端如何标记一个会话"已被拉黑、不再处理"。`hr_conversations.stage` 里已经有一个语义相近的终态 `closed`。
- 选了什么：新增独立字段（如 `hr_conversations.blacklisted`），`filter_conversations` 单独检查，优先级高于 `too_old`。
- 否掉了什么，为什么：复用 `stage='closed'`——**否掉，因为语义相反**。`closed` 是"沉寂但可能复活"的软状态（见本文件"陈旧会话关闭"相关条目，`closed` 遇新活动会复活），而黑名单的意图是"永远不想再理这家/这人，新消息来了也不该复活"。复用会被现有的"closed 遇新活动复活"逻辑直接打脸——HR 一旦再发消息，被拉黑的会话又活了。
- 代价 / 已知不足：多一个字段，`filter_conversations` 判断分支多一层；黑名单的两种触发场景（新会话 vs 加规则时库里已有的匹配会话）需要分别处理，后者要主动回扫现有数据，不能只指望"下次扫描自然跳过"。
- 什么情况下该重新考虑：如果以后发现用户确实希望被拉黑的公司"隔一段时间自动解封"，那时候语义就和 `closed` 趋同了，可以重新评估要不要合并。

## 黑名单"岗位类型"不单独建 match_type，并入关键词匹配

- 日期 / 版本：2026-08-09（设计阶段，未实现）
- 背景：黑名单五级粒度里用户提出"岗位类型"要分层匹配（如"销售"应比"电话销售"更宽泛）。Boss 岗位数据是否有结构化分类字段决定这层怎么实现。
- 选了什么：查了库里 331 个真实 title，确认 Boss **没有结构化岗位分类字段**，但 title 文本本身有"核心岗位词/技术领域修饰/雇佣性质修饰"三层非结构化模式。据此判定"岗位类型"匹配和"关键词"匹配是同一套子串匹配机制，`blacklist_rules` 表不单独建 `job_category` 这个 `match_type`，用 `keyword` 类型 + 用户自己控制填词粒度（填"销售"宽、填"电话销售"窄）来实现分层。
- 否掉了什么，为什么：单独建一张"岗位分类"表或 `job_category` match_type——否掉，因为没有真实结构化数据支撑，会变成又一套自造的分类体系，且和 `keyword` 类型在执行逻辑上完全重复。
- 代价 / 已知不足：如果用户想在 UI 上把"按岗位类型拉黑"和"按关键词拉黑"做成两个视觉上独立的入口（即便后端是同一逻辑），前端要自己维护这个语义分组，不是数据库告诉你的。
- 什么情况下该重新考虑：如果 Boss 未来在页面上暴露出真正结构化的岗位分类字段，可以把这层单独抽出来做精确匹配而非子串猜测。

## 扩展到应届生网：只接投递，不接会话追踪

- 日期 / 版本：2026-08-10
- 背景：评估把 OpenJobFinder 扩展到应届生网（yingjiesheng.com）的可行性，作为"扩展到 Boss 以外站点"的第一个实地案例。
- 选了什么：只考虑迁移 W1 投递能力；W2/W3（HR 会话追踪 + 回复）对该站点不做。
- 否掉了什么，为什么：曾设想复用 Boss 现有的 W2/W3 架构——**否掉，因为真机验证**"先聊聊"（详情页）和"和HR聊聊"（个人中心投递反馈列表）两个入口点击后 100% 弹出 App 下载引导框，PC 网页端没有内嵌 IM 界面。这是产品层面锁死，不是技术难度或选择器没摸对的问题。
- 代价 / 已知不足：该站点只能做粗粒度状态轮询（个人中心"投递反馈"页展示的 已投递/已查看/HR对你感兴趣/不合适），拿不到聊天内容，也回复不了 HR。
- 什么情况下该重新考虑：应届生网上线网页版 IM 功能，或决定投入做 Android App 自动化（见下一条，已否决）。

## 不做 Android 模拟器路线去够 App 内的 HR 聊天

- 日期 / 版本：2026-08-10
- 背景：应届生网的 HR 聊天被锁定在手机 App 内，评估用 Android 模拟器（Appium/uiautomator2）绕过这个限制，接上 W2/W3。
- 选了什么：不做，维持只用 PC 网页自动化（DrissionPage）。
- 否掉了什么，为什么：技术上可行（Appium/uiautomator2 是成熟框架），但代价太大——① `tools/browser/*` 整层要重写，原生 UI 自动化（无障碍树/resource-id/手势）跟 DrissionPage 的 CDP 同步 API 完全不兼容，等于重做一遍浏览器层；② 大厂 App 常见模拟器检测/设备指纹，反自动化大概率比网页版更严，不是更松；③ 需要新增一台常驻的模拟器基础设施，运维模型跟现有"Windows 机器 + Chrome profile"完全不同；④ App 登录常绑定短信验证码，这一步没法自动化（agent 代填验证码本就是禁止动作）。综合判断投入产出比不划算，对个人求职工具这个体量尤其不值。
- 代价 / 已知不足：放弃这条路线意味着"应届生完整 W1+W2+W3"这个目标不可达，该站点长期只能做投递。
- 什么情况下该重新考虑：出现明确的高价值目标网站、其 HR 沟通只存在于 App 内，且愿意承担重建整个浏览器层的成本时。

## 多站点扩展走 Adapter 契约模式，不做运行时通用 agent 逐步点击执行

- 日期 / 版本：2026-08-10（设计阶段，未实现）
- 背景：讨论怎么让投递流程支持多个招聘网站，同时不为每个网站写互相独立、互不复用的代码。
- 选了什么：定义一份"网站能力契约"（`JobSiteAdapter` Protocol：搜索/抓卡片/查JD/去重/检测表单字段/投递/校验成功/可选 IM），每个网站实现同一份契约，Boss 直聘退化成第一个实现。新网站接入时，用 Claude Code + `claude-in-chrome` 做**一次性、人在场核实**的侦察（不是运行时组件），产出结构化"能力矩阵报告"，人工确认后手写成确定性代码实现该契约。详见 `docs/multi-site-expansion-design.md`。
- 否掉了什么，为什么：① 否掉"运行时通用 computer-use agent 逐步点击执行投递"——慢、贵（每个动作都要过模型推理），且投递是不可逆动作（简历真发给真实HR），出错代价高，违背项目"models judge, code decides"的既有原则（判断用 LLM，执行用确定性代码）；② 否掉"声明式配置，运行时解释执行选择器"——"投递是否真成功"这类判定历史上需要真机反复迭代校准（Boss 的案例改了好几版），纯声明式配置表达不了这种需要持续验证的逻辑。
- 代价 / 已知不足：Adapter 契约要在至少两个真实网站上实现过才能验证设计得对不对；Boss 现有的 `tools/browser/w1/*` 大概率需要重构才能套进这份契约，这本身是不小的改动，尚未启动；维护成本随站点数量线性增长（每站点一份独立实现，网站改版要跟着改）。
- 什么情况下该重新考虑：如果契约在第二个网站的实现中发现设计跟 Boss 耦合太深（某个方法签名假设了 Boss 特有的行为），回来改契约设计，不要死守第一版没验证过的草案。

## 网申表单字段：人口学字段规则填，开放问题字段 LLM 填 + 人工审批

- 日期 / 版本：2026-08-10（设计阶段，未实现）
- 背景：部分招聘网站投递不是单击，而是要填一个表单——姓名/学校这类标准字段，加期望薪资/自我评价这类开放性问题——设计怎么自动填。
- 选了什么：字段分两类处理。人口学字段（姓名/学校/电话/学历）走确定性规则映射（读 `profile.yaml`）；开放问题字段（跟 JD 相关、没有标准答案的）由 LLM 生成候选值。两类字段都先写库为 `pending` 状态，经人工审批确认后才真正提交——复用现有 W2/W3 已验证的"装填→待发→人工批准→再执行"模式。
- 否掉了什么，为什么：曾设想复用牛客网申助手这类现成 Chrome/Edge 扩展——**否掉**，原因两条：① 调研其技术博客确认它是纯规则字段映射（预解析表单结构建映射库），不处理开放性问题，我们真正需要的能力（LLM 结合 JD 推理）它完全没有；② 它是闭源商业产品、用户手动点击触发、无编程接口，DrissionPage 能把它当扩展装进浏览器 profile，但没法脚本化驱动它的填充动作——反而是多绕一层、多一层选择器风险，不省事。
- 代价 / 已知不足：需要新增"待确认投递"审批队列和对应 UI，工作量不小；对牛客插件技术实现的判断是从其官方技术博客和产品页推断的，不是逆向源码验证，可信度有限。
- 什么情况下该重新考虑：如果发现某类"开放问题"字段实际高度模板化（比如绝大多数岗位都问"期望薪资"，可以用规则/范围推断），可以把这部分也降级成规则处理，减少 LLM 调用。

## 新增轻量二分类打分模式，不替代现有 5 维度评分器

- 日期 / 版本：2026-08-10（设计阶段，未实现）
- 背景：讨论给新站点冷启动/低配置成本场景提供一个更简单的打分方式——给用户 profile + 用户自己写的 task prompt + JD，让 LLM 直接输出投/不投的二分类判断。
- 选了什么：新增一个跟现有 5 维度加权评分器平级的简化打分模式（`tools/llm/score_job_simple.py`），实现同一个"打分"能力契约，按站点/按用户选择用哪个，不改动现有评分器。
- 否掉了什么，为什么：否掉"用二分类模式替换现有 5 维度评分器"——本文件已有明确记录（见"结构化维度评分而非 LLM 整体判断"条），当初就是因为"LLM 整体判断不稳定、不可解释、难以调参"才改成结构化维度评分的，二分类本质是同一类整体判断，重走回头路会连带失去现有围绕结构化分数搭的基础设施（`score_threshold` 三级配置、`scored_jobs` eval 采集、precision/recall 校准）。
- 代价 / 已知不足：两套打分逻辑并存，维护面变宽；轻量模式没有维度拆解，出问题时更难排查是哪个环节判断错了。
- 什么情况下该重新考虑：如果轻量模式实际使用后效果不比结构化版本差很多，且用户更喜欢它的简单配置，可以考虑让它成为默认，5 维度版本降级为高级选项。

## 不做"自动测评"类工具

- 日期 / 版本：2026-08-10
- 背景：用户听说牛客网有"自动测评"插件（Edge 端），问 Chrome 上有没有类似的可以拿来复用。
- 选了什么：不调研细节实现、不协助寻找、不做这类功能，只聚焦"自动网申"（表单投递）。
- 否掉了什么，为什么：调研发现牛客网自己在重点打击这类行为——上线了"严肃笔试客户端"，检测虚拟机/多屏/远程控制，抓到会标记作弊并通报给招聘企业。这类工具本质是代替用户完成筛选考核（真实能力评估），不是投递效率工具，性质上更接近作弊，且账号风险由用户承担。
- 代价 / 已知不足：无（用户已认可这条边界）。
- 什么情况下该重新考虑：不应重新考虑，除非未来出现明确合规的"复习辅助"类功能（例如仅用于考前刷题库，不涉及考试过程中代答），且需要重新单独评估合规边界。

## Apple 不适合做多站点扩展的 MVP 目标

- 日期 / 版本：2026-08-10
- 背景：为验证 Adapter 契约设计，挑 MVP 目标网站实地侦察，试了 Apple 招聘官网（jobs.apple.com）的投递流程。
- 选了什么：Apple 排除在 MVP 候选之外。
- 否掉了什么，为什么：Apple 详情页"Submit Resume"点击后跳转到 `idmsa.apple.com`——这是 Apple 账号统一认证系统，跟 iCloud/App Store/Apple Pay 共用同一套登录；页面邮箱框已自动预填真实邮箱，说明浏览器本就登录着真实 Apple 账号。自动化这个登录面的风险敞口不是"投错一份简历"，而是牵连整个 Apple 账号资产，且这类系统大概率有强 2FA（新设备/新地点登录触发信任验证码），验证码类操作本就不该由 agent 代填。在登录页停住，未继续。
- 代价 / 已知不足：Apple 的搜索和 JD 抓取部分其实做得很干净（`jobs.apple.com/en-us/details/{role_number}/{slug}` 结构化 URL、纯文本可抓），但投递环节走不通，整体放弃，浪费了这部分可用信息。
- 什么情况下该重新考虑：几乎不会，除非 Apple 招聘系统未来换成跟 Apple ID 无关的独立求职账号体系。

## 华为选定为多站点扩展 MVP 验证对象

- 日期 / 版本：2026-08-10
- 背景：银行候选（建行/工行 2026 春招已实质关闭、农行无在招岗位、中行本轮已结束且页面纯图片渲染无法文本抓取）和 Apple（认证风险，见上条）都不合适后，实地摸了华为校招（career.huawei.com）。
- 选了什么：华为作为 MVP 验证对象，继续往下做 recon。
- 选择理由：72 个活跃岗位、更新到会话当天；列表页/详情页 URL 结构干净可脚本化（`career.huawei.com/cn/job-details?advertisementId={id}`）；登录走独立的 Uniportal 求职账号体系（非绑定式身份，风险量级远低于 Apple）；投递表单有真实复杂度——岗位意向下拉选择后 JD 正文动态换内容、部门意向是两级联动下拉——比 Boss/应届生的"单击即投"更有验证价值，能真正测试 adapter 契约里 `detect_form_fields` 这块设计。
- 代价 / 已知不足：级联字段 + 动态 JD 意味着"抓一次 JD 存起来"不够用，得按岗位意向的每个分支各抓一次；这个复杂度目前还没有在 adapter 契约设计里体现，需要补充。
- 什么情况下该重新考虑：注册/投递过程中如果撞上强反爬或验证码等目前技术手段处理不了的障碍。

## 表单字段填写简化：优先复用目标网站自带的简历解析，不自建全量字段识别

- 日期 / 版本：2026-08-12
- 背景：真机走完华为投递流程后发现，点"申请"实际跳到的是"简历解析"页面——上传 PDF 触发对方系统自动解析并回填基本信息/教育经历/工作经历等结构化字段，用户指出这是成熟招聘网站的常见能力。
- 选了什么：adapter 的表单填写职责收窄为"上传简历（借力对方站点的解析能力）→ 扫描解析后仍为空的必填字段 → 只填这些缺口"，不重新实现一遍完整的字段识别/分类逻辑。
- 否掉了什么，为什么：**取代**本文件"网申表单字段：人口学字段规则填，开放问题字段 LLM 填 + 人工审批"一条里"我们自己识别所有字段并分类判断怎么填"的原始设想——否掉原因是重复造轮子没必要（多数成熟网站已有解析能力），且用户明确指出**解析质量本身不需要苛求**：面试官最终参考的是上传的原始 PDF，结构化字段只是网站流程要求，不是信息的唯一权威来源，我们不必对齐到"结构化字段 100% 准确"这个不必要的高标准。原条目里"人口学字段规则填/开放问题字段 LLM 填"的分类思路仍然成立，只是应用范围从"全部字段"收窄到"解析后的缺口字段"。
- 代价 / 已知不足：这个简化依赖"目标网站有靠谱的简历解析功能"这个前提——不是所有候选网站都有（应届生网、Boss 都没有这种上传即解析的流程），华为有不代表通用，仍需 recon 阶段逐站验证这项能力是否存在。
- 什么情况下该重新考虑：换到没有简历解析功能的网站时，仍需回退到"全量字段识别 + 分类填充"的原始设计。

## DeepSeek 替换 balanced 档，vision 档不动，fast/powerful 档确认零生产调用

- 日期 / 版本：2026-08-12，v2.19.2.19
- 背景：用户拿到 DeepSeek API key，希望不再依赖本地 ollama，把"所有需要大模型的地方"换成 DeepSeek。
- 选了什么：只改 `balanced` 档（`config.yaml`）——从 `ollama qwen3:8b` 换成 DeepSeek（`openai_compatible` provider，`model=deepseek-chat`，走 `services/llm_client.py` 现成的 `OpenAICompatibleProvider`）；`vision` 档维持 `codex_cli`+`claude_cli` 不变；`fast`/`powerful` 档配置内容不动。
- 否掉了什么，为什么：① 否掉"vision 也换成 DeepSeek"——这是硬约束不是选择，`OpenAICompatibleProvider.complete()` 遇到 `images` 参数直接 `raise RuntimeError`，DeepSeek 走这条 provider 结构性无法处理图片输入。② 一开始以为要在"powerful 全换 DeepSeek vs 保留 claude_cli 订阅免费额度做兜底"之间取舍，查证后发现是假问题——`grep capability=` 全库确认 `fast`/`powerful` 在生产代码里零调用（`score_job`/`analyze_intent`/`generate_reply`/`info_pool`/`resume_blocks`/`resume_tailor`/`selfcheck` 全部走 `balanced`），改不改这两档都不影响任何实际行为，无需纠结。
- 代价 / 已知不足：`balanced` 档从本地免费的 ollama 换成按 token 计费的 DeepSeek API，需要用户自己承担调用成本（用户已知情认可）。
- 什么情况下该重新考虑：`fast`/`powerful` 未来被实际接线使用时，需要重新决定这两档该配什么 provider；DeepSeek 出现稳定性问题时，可能要重新给 `balanced` 引入本地兜底。

## 新增 .env 文件支持，与既有 shell export 方式并存

- 日期 / 版本：2026-08-12，v2.19.2.19
- 背景：DeepSeek 切换后用户问能不能用 `.env` 文件管理 API key，而不是原来"手动 export 到 shell 并自己想办法持久化"的方式。
- 选了什么：加 `python-dotenv` 依赖，`services/llm_client.py` 模块顶部调用 `load_dotenv()`（`.env` 文件不存在时静默跳过，不报错）；新增 `code/.env.example` 模板；`.gitignore` 本来就已覆盖 `.env`/`*.env`，未改动。
- 否掉了什么，为什么：没有否掉旧的 shell export 方式——两者并存。`load_dotenv()` 只是把 `.env` 文件内容灌进 `os.environ`，不移除任何已有的读取路径（所有 provider 仍统一走 `os.environ.get(...)`），谁先设置以哪个为准由 `dotenv` 库的默认行为决定（不覆盖已存在的环境变量）。
- 代价 / 已知不足：无明显代价，仅新增一个可选的便利层。

## 多站点执行层引入 agent 作为默认路径，adapter 降级为可选优化——部分修正"不做运行时通用 agent 逐步点击执行"

- 日期 / 版本：2026-08-12（设计阶段，未实现；recon 会话延伸出的架构讨论）
- 背景：华为/Hytera 两次真机 recon 之后，讨论"要不要用 LangGraph + Chrome MCP + DeepSeek 做一个通用 agent 来执行投递"，而不是每个网站手写确定性 adapter。这个提案表面上跟本文件更早的"多站点扩展走 Adapter 契约模式，不做运行时通用 agent 逐步点击执行"一条正面冲突。
- 选了什么：**把"判断"和"执行"拆成两层，而不是简单地"agent 还是代码"二选一**——① Layer 1（识别/判断）：agent（LangGraph+Chrome MCP+DeepSeek）负责定位岗位、扫描表单字段、分类（demographic/open_question/government_id）、为前两类生成候选值，**允许犯错**，写入 `pending_application` 记录，不直接执行任何写入或提交。② Layer 2（人工审批）：人看候选值、编辑/批准，government_id 字段由人亲自填，批准即显式 go 信号。③ Layer 3（分派，纯代码不做判断）：有该网站的确定性 adapter 就用 `CodeExecutor`，没有就退化到 `AgentExecutor`（同样是 agent 驱动，但只执行 Layer 2 已批准的值，不再判断填什么）；两条执行路径共享同一组安全边界（government_id 永远不进执行层、提交永远要求外部 go 信号），这组边界长在分派之前统一强制，不在每条执行路径里各自实现一次。④ Layer 4：`verify_apply_success` 独立校验。详见 `docs/multi-site-expansion-design.md`"核心思路：四层运行时架构"。
- 否掉了什么，为什么：**没有推翻"不做运行时通用 agent 逐步点击执行"这条旧决策，是收窄了它的适用范围**——旧决策否的是"用 agent 的判断力去决定该不该点、点哪里、要不要提交"，这条否决**依然成立**：Layer 1 的 agent 判断结果必须经过 Layer 2 人工批准才能流向真实世界，这一步没有变。新收进来的是"用 agent 去执行已经被人批准过的动作"——这是纯操作层面的不确定性（会不会点错元素），跟"要不要投这个岗""该填什么身份信息"这类会被真实后果放大的判断错误不是一回事，允许它承担这部分工作不违反原决策的精神。同时否掉"每个网站强制写 adapter"——demographic 字段的值解析（"姓名"→"余佩其"）从设计上就是通用的，不属于 adapter；真正因网站而异的只是交互细节（选择器/点击顺序/日期精度），而这恰好是 AgentExecutor 能通用处理的部分，所以 adapter 从"必需品"降级为"高频网站才值得投入的可选优化"，缓解了旧决策记录的"维护成本随站点数量线性增长"代价。
- 代价 / 已知不足：需要新建 Layer 2 的审批队列 + Dashboard UI（目前完全不存在，是这套架构里唯一不可选的必建项）；两套 executor 共享的安全边界代码是单点关键路径，如果被绕过（未来有代码跳过 Layer 3 分派直接调用某个 executor）保护就失效，需要专门测试守门；AgentExecutor 实际使用的自动化技术（Chrome MCP/DrissionPage 等）是否会被目标站点反自动化检测，完全未验证——这次 recon 用的 `claude-in-chrome` 顺利跑通不能作为"不会被拦"的证据，两者自动化特征不同。
- 什么情况下该重新考虑：如果 AgentExecutor 在真实网站上的操作出错率高到连"点错元素"这类操作层面的失误都频繁到不可接受（哪怕已经过人工批准的值也经常被填错地方），需要重新评估是不是要收紧成"只有写了确定性 adapter 的网站才允许执行"，把 AgentExecutor 降级为纯 recon 工具而非运行时执行者。

## 政府证件号码类字段写入 adapter 契约作为硬约束，不经 LLM/规则判断是否代填

- 日期 / 版本：2026-08-12（设计阶段，未实现；recon 会话产出）
- 背景：华为、Hytera（Moka 平台）两次真机 recon 都撞到"证件号码"必填字段。填表助手（不管是 Claude 现场操作还是以后的自动化 agent）该不该代填这类字段？
- 选了什么：政府证件号码（身份证/护照等）在 `JobSiteAdapter`/`FieldSpec` 设计里定为**永远 pending_manual_input**——`detect_form_fields` 识别到这类字段直接标记为必须人工现场填写，不进入"人口学字段规则填 / 开放问题字段 LLM 填"的常规分类流程，不给 LLM 或规则引擎判断空间。
- 否掉了什么，为什么：否掉"当作人口学字段，从本地 profile 存储里读值自动填入"——即使字段值本身就存在本地（且已加密/gitignore 保护），代填这个动作本身就是不可接受的：这类字段是身份识别的重要依据，一旦自动化流程出错（填错、填串号），后果是身份冒用/资格纠纷级别，跟填错"期望薪资"完全不是一个量级。这不是能力问题（技术上完全能做到），是产品边界问题。
- 代价 / 已知不足：多站点自动投递永远无法做到"从头到尾全自动"，遇到需要证件号码的网站，流程会在这一步卡住等人工，打断连续性。
- 什么情况下该重新考虑：不应重新考虑——这条边界比"要不要用 LLM 判断"更底层，是产品安全边界，不是效率权衡。
- 什么情况下该重新考虑：不需要。

## Layer 2 审批队列不预留公开创建端点，只用 seed 脚本造测试数据

- 日期 / 版本：2026-08-12，v2.20.0.0
- 背景：实现 `pending_applications` 表 + 审批页（Layer 2 最小实现）时，需要决定要不要顺手建一个 `POST /api/pending-applications` 创建端点，方便以后 Layer 1 直接调用，也方便现在造测试数据。
- 选了什么：不建创建端点，只写 `scripts/seed_pending_application.py` 直接调 `tracker.add_pending_application()` 造样例数据。
- 否掉了什么，为什么：否掉"预留一个公开创建端点"——Layer 1（识别/写入的 agent）完全没有实现，不知道它未来会以什么形态产生数据：直接调 `tracker`？包成 tool 经 `registry.call`（这样才有 pipeline 的 trace/SSE）？现在猜一个端点的参数形状，等 L1 真正落地时大概率要推倒重写，不如先不建，避免"接口形状和 L1 实际需要不匹配还得再改一次"的返工。
- 代价 / 已知不足：seed 脚本只能造 Python 里写死的样例数据，不能从 UI 或外部系统临时插入一条测试记录，调试时不够灵活。
- 什么情况下该重新考虑：Layer 1 的技术形态定下来之后，按它实际需要的接口重新设计创建路径（可能是端点，也可能是 L1 直接调用 tracker/tool，不一定要走 HTTP）。

## Layer 2 审批端点（approve/reject）直接调 tracker，不走 tools/db 薄壳

- 日期 / 版本：2026-08-12，v2.20.0.0
- 背景：项目「后端分层铁律」要求副作用操作走 tool 经 `registry.call` 获得 trace/SSE。新增的 `/api/pending-applications/{id}/approve` 等端点该不该照此建一层 `tools/db` 薄壳？
- 选了什么：端点直接调 `tracker.decide_pending_application()` 等方法，不建 `tools/db` 薄壳。
- 否掉了什么，为什么：分层铁律是为 W1/W2/W3 **pipeline** 的可观测性/可重放设计的——tool 化的价值在于挂在某次 run 上、可在 run 日志里回放。Layer 2 的审批动作目前不挂在任何 pipeline run 上，跟既有的 `approve-reply`/`dismiss-reply`/`queue-resume` 等会话交互端点是同一类（纯交互动作，不是 pipeline step），这些先例也都是直接调 `tracker`。比照先例，不额外包一层没有实际观测收益的薄壳。
- 代价 / 已知不足：如果以后 Layer 1 真的把"识别→审批→分派"接成一条 pipeline（比如 recon/识别阶段本身要走 registry 记 trace），届时 approve/reject 这两步要不要一起纳入同一套可观测机制，需要重新评估——现在的直调 tracker 不是最终结论，只是"目前没有 pipeline 可挂"这个前提下的合理选择。
- 什么情况下该重新考虑：Layer 1 真正实现、且识别→审批→分派被设计成同一条可回放的 pipeline 时。

## 多站点跨站点投递审批页新建独立 Navigator，不挂在 Jobs 页面下

- 日期 / 版本：2026-08-12，v2.20.0.0
- 背景：Layer 2 审批页是全新概念（跨站点，字段是动态 FieldSpec 数组），需要决定挂在侧栏哪里。
- 选了什么：新建独立 Navigator「跨站点投递」，与 Jobs/Chat/Resume 等平级。
- 否掉了什么，为什么：否掉"挂在 Jobs 页面下再加一个 tab"——Jobs 页是 Boss 直聘专属的投递记录结构（`applications` 表，固定字段），跟多站点审批（`pending_applications` 表，动态字段数组、多站点标识）语义上不是一回事，混进同一个页面的不同 tab 会让 Jobs 页背负它本不该有的复杂度。这是用户在 AskUserQuestion 里明确选择的（"新建一个独立 Navigator" vs "挂在 Jobs 页面下一个 Tab"）。
- 代价 / 已知不足：侧栏导航项又多了一项（当前 9 项）。
- 什么情况下该重新考虑：如果 Boss 直聘本身也被收编进这套多站点架构（`docs/multi-site-expansion-design.md`"风险与开放问题"第 3 条尚未确认），届时 Jobs 页和这个新页面的关系需要重新设计，可能会合并。

## "L2 结构上不可替代"不等于"建设顺序上应该先做 L2"——两个判断被混用了，需要拆开记

- 日期 / 版本：2026-08-13
- 背景：L2 验收完，用户追问"为什么要拆四层""之前说 L2 不可替代，现在看不太对，光弄了个闸门出来还是空中楼阁"。这是个合理的质疑，不是简单重申旧结论能打发的。
- 选了什么：把两个判断拆开、分别确认——①**结构必要性**：四层架构最终形态里，不管选哪个网站、写不写 adapter，"人工批准"这道闸门永远躲不掉（没有它，Layer 1 识别出的候选值没地方落地审批，整条链路走不通），这个判断依然成立，不推翻。②**建设顺序价值**：拿①去为"现在就该先做 L2"背书是偷换概念——L2 可以独立于 L1/L3 建成不假，但独立建成的东西也独立于真实数据。这次的真机验证靠的是 `scripts/seed_pending_application.py` 手工造的假数据，没有一条记录真正来自扫描一个真实网页；验证证明的只是"`pending_applications` 表结构和审批页的增删改查逻辑正确"，不是"这套字段设计（`FieldSpec` 三分类：demographic/open_question/government_id）匹配真实场景"——后者完全没被验证过。现在转向做 Layer 1。
- 否掉了什么，为什么：否掉"L2 已经完整验证、可以不用管了"这个错觉——不推翻已完成的 L2 实现本身（结构依然正确、18 个测试依然有效、真机走过审批/驳回全流程），但明确"验证过逻辑"和"验证过真实场景匹配度"是两个不同层级的验证，不能混为一谈。
- 代价 / 已知不足：Layer 1 落地、真实数据开始流经这道闸门后，`pending_applications` 的字段 schema / `FieldSpec` 分类 / 审批页交互有较大概率需要调整——这部分返工量在最初评估"先做 L2 风险低"时没有被计入，不是失败，是走这条顺序时就该预料到的代价。
- 什么情况下该重新考虑：不适用——这是记录一次认识上的教训，供以后判断"结构必要"和"建设顺序优先级"时分开论证，不要用前者替后者背书。

## 首次在 Python 依赖之外引入 Node.js 运行时依赖（chrome-devtools-mcp）

- 日期 / 版本：2026-08-13，Layer 1 实现阶段
- 背景：Layer 1 按设计文档走 LangGraph + Chrome MCP + DeepSeek 技术路线（用户已确认，见"多站点执行层引入 agent 作为默认路径"）。Chrome MCP 生态（浏览器自动化的 MCP server）目前主流实现是 Node.js 包（Google 官方 `chrome-devtools-mcp`），没有对应的原生 Python 包。
- 选了什么：Python 侧用 `langchain-mcp-adapters` 通过 stdio 子进程（`npx chrome-devtools-mcp@latest`）连接这个 Node.js MCP server，桥接成 LangGraph 可用的工具。`requirements.txt` 加了 `langgraph`/`langchain-openai`/`langchain-mcp-adapters`/`mcp` 四个新 Python 包；Node 依赖不体现在 requirements.txt 里，靠 npx 按需下载，没有走 package.json 锁版本（用的是 `@latest`）。
- 否掉了什么，为什么：否掉"等一个 Python 原生的 CDP-MCP 实现"——目前生态里没有功能对等的选择，且这条技术路线是用户明确要求直接按设计文档搭建的，不是这次临时决定的。也否掉"把 chrome-devtools-mcp 版本锁定在 package.json 里管理"——这个包只在 Layer 1 这一条边缘路径用到，不值得为它引入 Node 包管理基础设施，用 `npx --yes chrome-devtools-mcp@latest` 现场拉取足够。
- 代价 / 已知不足：①用 `@latest` 意味着这个包升级后行为可能漂移（tool 名称、a11y 快照文本格式变化），没有版本锁定的可复现性；②这是项目第一次要求运行环境里必须有 Node.js/npx，之前的技术栈（DrissionPage/Playwright/FastAPI 等）全是纯 Python，多了一个环境前置条件；③引入的是一套跟项目其余部分（DrissionPage）完全不同的浏览器自动化技术栈（Chrome MCP 底层是 Puppeteer/CDP），意味着 DrissionPage 特意规避的 CDP 检测风险，在 Layer 1 这条新路径上是重新暴露的——这正是设计文档"反自动化验证"仍未完成的那个未知风险，Layer 1 这次真跑本身会是第一手非正式信号，但不能替代专门的验证。
- 什么情况下该重新考虑：chrome-devtools-mcp 升级后若出现破坏性行为变化导致 Layer 1 频繁失败，需要把版本锁定下来（这次开发验证过的是 `chrome-devtools-mcp@1.7.0`）；若真机验证发现华为站点对 CDP/Puppeteer 类自动化有明显拦截，需要重新评估整条技术路线是否可行。

## Layer 1 的 DeepSeek 调用不走项目自己的 ModelRouter，改用 LangChain 原生绑定

- 日期 / 版本：2026-08-13，Layer 1 实现阶段
- 背景：项目现有 LLM 调用统一走 `services/llm_client.py` 的 `ModelRouter.complete()`（返回原始文本 + provider 名，DeepSeek 走的 `OpenAICompatibleProvider` 会直接忽略 `output_schema` 参数，结构化程度全靠 prompt 措辞 + `safe_parse_json` 兜底解析）。LangGraph 的用法习惯要求一个 LangChain 原生的 `BaseChatModel` 对象。
- 选了什么：`code/multisite/layer1_agent.py` 里单独用 `langchain_openai.ChatOpenAI` 绑定 DeepSeek（`base_url=https://api.deepseek.com`，复用同一个 `DEEPSEEK_API_KEY` 环境变量），用 `.with_structured_output(ClassifyFieldsOutput)` 做结构化输出（DeepSeek 支持 function calling，这条路径比项目自己的手工 JSON 解析更可靠）。
- 否掉了什么，为什么：否掉"复用 ModelRouter，在外面手写一层 LangChain BaseChatModel 包装它"——包装的价值不大，ModelRouter 的 FallbackChain 多 provider 容灾、capability 路由这些能力对 Layer 1 这条独立路径没有实际意义（目前只用一个 provider，不需要 fallback 语义），硬套上去反而要多写一层适配代码。也否掉"继续用项目的 safe_parse_json 手工解析 JSON"——LangChain 原生结构化输出对这个场景更合适，没理由绕远路。
- 代价 / 已知不足：Layer 1 是目前唯一一处 LLM 调用完全游离于项目 `ModelRouter`/`FallbackChain` 之外的地方，provider_used 追踪、fallback 容灾这些项目级能力在这里都没有——DeepSeek 挂了 Layer 1 就直接失败，没有降级路径。
- 什么情况下该重新考虑：Layer 1 未来需要支持多 provider 容灾（比如 DeepSeek 限流时切到其他模型）时，需要重新评估要不要把它接回 ModelRouter 体系，或者给 ModelRouter 补一层 LangChain 兼容接口。

## personal_info 与 info_pool 去重：姓名/电话/邮箱唯一真源在 info_pool，身份事实单独存 identity.yaml

- 日期 / 版本：2026-08-13，v2.21.1.2
- 背景：Layer 1（多站点识别 agent）这次新建了 `data/personal_info/{basic,identity}.yaml` 存自动填表用的身份事实，但项目里早就有一套「信息池」（`data/info_pool.yaml`，简历系统的主库）也存了姓名/电话/邮箱。用户发现前端根本没有「个人信息」这个 Navigator，提出应该做一个，同时指出"这两个做的地方其实高度重合"，要求先讨论怎么实现。
- 调查发现（先查真实数据再下结论，不是凭概念猜）：两边**只有姓名/电话/邮箱三个字段真正重叠**。`info_pool.basic_info` 有 name/phone/email/city/degree/target_title（简历抬头概念）；`personal_info` 有 name/phone/email + gender/birth_date/id_country/id_type（政府表单身份概念）。gender/birth_date/证件类字段**在 info_pool 的 schema 里完全不存在**（grep「性别/出生/证件」零命中）。而且真实数据里**电话号码只有 personal_info 有、info_pool 是空的**——去重前必须先迁移，不然会丢数据。
- 选了什么：**分层去重，不是整体合并**。①姓名/电话/邮箱的唯一真源定为 `info_pool.basic_info`，`load_personal_info()` 读的时候去池里取这三个字段，`personal_info/basic.yaml` 整个文件退役删除（迁移时先把真实电话值通过 `info_pool.save_pool` API 写进池，走正规 API 保留快照，不手改 YAML）。②性别/出生日期/证件国家/证件类型等身份事实**继续单独存 `identity.yaml`**，不并进 info_pool。③新建独立的「个人信息」Navigator（`pages/PersonalInfo.tsx`）——姓名/电话/邮箱在这个页面**只读展示**，明确标注"来自简历信息池，去「简历」页编辑"；只有 identity.yaml 那部分可编辑。④审批时自动保存的新事实（`save_new_facts`）也改成一律写 identity.yaml，不碰 info_pool。
- 否掉了什么，为什么：①**否掉"把身份字段并进 info_pool"**——info_pool 的语义是"简历内容主库"，会被 LLM 读取和整体重写（`build_pool` 让 LLM 重排 sections、`compose` 按 JD 挑块生成简历）；性别/证件类型不是简历内容、不该参与这套 LLM 加工流程。而且 government_id 硬约束之所以好守住，正是因为 personal_info 这个模块足够小、足够独立、跟 LLM 生成流程隔开——混进去会让这条安全边界的守护面积大幅扩大。②**否掉"两边都保留姓名/电话/邮箱，不去重"**——同一份数据两个写入口必然漂移，跟本项目「一个状态转换只能有一份 SQL」是同一条纪律（那条铁律的历史教训是一次审查连抓四例同构漂移）。③**否掉"在新页面里也做姓名/电话/邮箱的编辑"**——那等于又开第二个写入口，跟②同理；info_pool 那边已经有完整编辑 UI + 快照/回滚，新页面没理由重复一套。
- 代价 / 已知不足：①用户想改姓名/电话/邮箱得去「简历」页，不在「个人信息」页——多一次跳转，换来的是不会出现两处数据打架。②`personal_info_loader` 现在依赖 info_pool 的文件格式（读 `basic_info` 那一节），简历系统未来改 schema 这里会跟着坏——已通过 `_POOL_IDENTITY_KEYS` 常量集中，且有单测覆盖（`test_pool_non_identity_fields_are_not_included` 等）。③identity.yaml 没有 info_pool 那样的快照/回滚，误删只能手动恢复——这次先不做，字段少且页面上删除需要显式点保存才生效。
- 什么情况下该重新考虑：identity.yaml 的字段数量增长到跟 info_pool 一个量级（比如自动保存积累了几十个字段），或者出现"同一字段两边都有但语义不同"的新情况时，重新评估要不要给 identity 也上快照机制、或干脆把两套存储统一到一个带版本管理的框架下。

## Layer 1 的导航/找入口/选岗交给 agent 自主决策，填写层同时保留 agent 与代码两套工具

- 日期 / 版本：2026-08-13，决策记于 v2.21.2；**实现落地时升 Y 到 v2.22.0**（多站点 Layer 1 从"站点适配器"改回"识别 agent"，是架构方向的改变，够得上 Y 位）
- 背景：Layer 1 首版已真机跑通（拓竹，`pending_applications id=6`，字段分类正确、government_id 正确留空）。但用户审阅后指出"你在做的和我想做的有一些分歧"，并要求先对齐再动代码。**分歧是实现方偏离了设计文档，不是用户改了主意**：`docs/multi-site-expansion-design.md` 写明 Layer 1 是"agent 识别/判断层，允许出错"（因为 Layer 2 人工审批在后面兜底），而实际落地的 `layer1_agent.py` 是四个 Python 写死顺序的节点、每步调哪个 chrome MCP 工具也写死（`_find_uid_by_label(snapshot, ["申请","apply","投递"])` 这类硬编码 label 匹配），**全链路只有"字段分类"一处真的交给模型判断**。LangGraph 在其中只起状态机编排作用，没有 agent 循环、没有自由 tool-calling。这等于做成了"披着 LangGraph 外壳的站点适配器"，而"每站点一个适配器"正是设计文档明确否掉的路线。
- 选了什么：**按层拆分自主度，而不是全链路统一**。①**导航 / 找投递入口 / 选岗 = agent 自主决策**——给它浏览器工具 + 求职偏好，由它决定点哪里、翻不翻页、某个岗位算不算数、入口找不到怎么绕。②**填写层做两套工具并存**：agent 填写（应对没见过的表单）与确定性代码填写（应对已知字段/已知控件类型），由调用方选择。③**提交前一律走 Layer 2 人工审批**——这条边界不变。④SDK 继续用 LangGraph（用户拍板）。⑤求职偏好（应届 / 日常实习 / 城市 / 方向 / 排除有经验要求）统一进 `data/profile.yaml`，不新开文件。
- 否掉了什么，为什么：①**否掉"换成 Anthropic SDK 的 Tool Runner"**——技术上我推荐它（浏览器 agent 恰好踩在 DeepSeek 最弱的两点：长程 tool-calling 稳定性、大上下文管理；a11y 快照单次几十 KB，DeepSeek 64k 上下文跑十几步必爆；Tool Runner 还自带逐轮审批钩子，卡"不许点提交"比 prompt 叮嘱可靠）。**用户明确否掉，理由是本人正在求职 agent 开发方向的岗位，亲手做一遍 LangGraph 工程本身就是目标之一**——这是产品/个人目标层面的决定，不是技术推导能推翻的，后续会话不要自作主张换掉。②**否掉"把现有 layer1_agent.py 整个推倒"**——字段分类、值解析、government_id 强制留空这些确实该是确定性代码，且已真机验证过，保留。③**否掉"填写层只做 agent 一套"**——已知字段用确定性代码更可控也更省 token，两套并存是用户明确要求。④**否掉"用户给的搜索 URL 当输入"**——实测那个 URL 的 `project=` 参数把日常实习过滤掉了（87 条 vs 去掉后 134 条），说明"偏好"不该以 URL 形式存在，应该由 agent 按偏好自己构造搜索。
- 代价 / 已知不足：①DeepSeek 在长程浏览器循环上的上下文与稳定性风险是**真实且已预见**的，大概率需要在快照裁剪/分步摘要上额外做工程量——这部分成本是为"亲手做一遍"付的学费，接受。②agent 自主导航必然比写死选择器更不稳定、更难复现，调试成本上升；这正是 Layer 2 人工审批存在的意义，但也意味着**审批队列里会开始出现"选错岗位"这类新的错误类型**，而不只是"字段填错"。③两套填写工具意味着同一件事有两条实现路径，有漂移风险——必须靠"工具契约唯一、调用方选择"来约束，不能两边各写一套字段处理逻辑。
- 什么情况下该重新考虑：①如果 DeepSeek 在真机长循环上反复失败到工程量明显超过学习收益（用户的目标已经达成），重新评估 SDK；②如果两套填写工具开始出现行为不一致（同一表单两条路径填出不同结果），说明契约没守住，应当收敛成一套。

## 身份事实与求职偏好没有归属层，是配置散落的真因（不是"文件太多"）

- 日期 / 版本：2026-08-13，v2.21.2
- 背景：用户问"既然现在有 profile.yaml，为什么感觉个人信息管理存档什么的这么混乱？有很多个地方需要求职偏好和个人信息，这个本质上应该是放在一块地方的东西。"
- 调查发现（查了全部真实文件内容，不是凭印象）：`docs/configuration.md` 里的**三层模型（系统配置 / 用户偏好 / 运行参数）本身是清晰的、有文档、也被遵守着**。真正的问题是**"我是谁"这类身份事实从来没有被纳入这个模型**——于是每个需要它的模块就近自己存了一份：简历系统为了生成简历存进 `info_pool.basic_info`（姓名/电话/邮箱/城市/学历/目标岗位），多站点 Layer 1 为了填表单存进 `personal_info/identity.yaml`（性别/生日）。`profile.yaml` 里那个空的 `name: ""` 是同一问题的残留物（`docs/configuration.md` 已明说投递流程不消费 name）。
- 另有两处真实的同名不同义，是"感觉混乱"的直接来源：**`degree`** 在 `profile.yaml` 是筛选条件（`["本科","硕士"]`，我愿意投的学历档），在 `info_pool.basic_info` 是身份事实（`"硕士"`，我的学历）；**`city` / `cities`** 同理（想去的城市 vs 我在哪）。两者都不是重复存储，是**两个概念恰好共用了一个词**。
- 选了什么：**先只做归位，不做大重构**。①求职偏好（含应届/日常实习）进 `profile.yaml`，它本来就是"用户画像"层，语义正确；②身份事实维持现状分层（姓名/电话/邮箱在 info_pool，其余在 identity.yaml，见上一条决策）；③把"身份事实是第四类数据、目前无归属层"这件事显式写进文档，让后来者知道这不是失误而是待补的空缺；④`profile.yaml` 里残留的空 `name` 字段清掉。
- 否掉了什么，为什么：①**否掉"把六个配置文件合并成一个"**——三层模型是按"谁拥有 / 能不能改 / git 跟不跟踪"分的，合并会把出厂默认（git 跟踪）和用户数据（gitignore）混进一个文件，是倒退；用户感到的混乱不来自文件数量。②**否掉"现在就把身份事实抽成第四层"**——这要动简历系统的主库 schema（`info_pool` 有快照/回滚/LLM 重写等一整套机制挂在上面），改动面远超本轮范围，且当前只有两个模块消费它，收益不足以支撑风险。③**否掉"把 degree/city 改名消歧"**——`profile.yaml` 的字段名直接喂 `services/boss_search_url.py` 拼 Boss 搜索 URL，改名要连带改搜索链路，属于为了可读性去动能跑的东西。
- 代价 / 已知不足：①身份事实仍然分居两处，`personal_info_loader` 继续承担"跨两个文件拼一份扁平 dict"的粘合职责；②`degree`/`city` 的同名不同义**依然存在**，只是被写进文档而不是被消除——下一个不知情的人仍可能在这里困惑一次，这是刻意接受的代价。
- 什么情况下该重新考虑：出现第三个消费身份事实的模块时（比如网申之外再来一个需要学校/专业/绩点的场景），"无归属层"的成本就会明显超过重构成本，那时应当正式把身份事实抽成独立的一层并给它快照机制。

## Layer 1 选岗结果用 `record_job` 工具边找边落袋，不靠 agent 最后一次性输出

- 日期 / 版本：2026-08-14，v2.22.0
- 背景：Layer 1 改成 agent 自主选岗后，真机连跑两次都撞 `GraphRecursionError`。第一次是在筛选器上无限打转；加了"最多点 N 次筛选器"的预算之后，**换成在翻页上打转**（2→3→4→2→4→2……），每次都说"让我分析当前页面的岗位"然后继续翻。两次都不是没能力找到岗位——它筛选筛得很对，就是不肯收尾。
- 选了什么：给选岗 agent 一个 `record_job(url, title, company, why)` 工具，**每找到一个符合条件的岗位就立刻记一条**，结果落进 Python 侧的 sink；`find_jobs` 节点从 sink 取结果，并 catch `GraphRecursionError` **采用已记录的部分结果**而不是向上抛。
- 否掉了什么，为什么：①**否掉"继续加 prompt 约束"**——第二次失败证明了这是治标：约束只把打转的位置从一个维度挪到另一个维度，因为"答案必须最后一次性给出"这个结构本身在逼模型继续探索（它永远可以认为还没看够）。②**否掉"提高 recursion limit"**——那只是让它多烧一会儿再失败，而且 DeepSeek 64k 上下文撑不住更多轮快照。③**否掉"超限就整体失败"**——那等于把"找到 3 个但第 4 页开始打转"退化成"什么都没有"，而前 3 个是完全可用的。④**否掉"换更强的模型"**——用户已明确 SDK/模型选型是他的学习目标，不能因为技术理由自作主张换掉（见上一条决策）。
- 代价 / 已知不足：①agent 仍然可能打转，只是打转不再等于全损——**"跑满步数上限"变成了一种正常结局**，日志里会看到"达到步数上限，采用已记录的 N 个岗位"，需要人知道这不一定是故障。②`record_job` 的去重只按 URL，同一岗位换个 URL 形式（带不带 query 参数）会重复记。③真机这次 6 个岗位**全是秋招，一个日常实习都没有**，而偏好里两者都要——不确定是筛选器把实习筛掉了还是它提前收工，待观察。④agent 记录的标题与页面实际标题有出入（把「软件AI方向」记成「智能AI方向」），URL 是对的所以不影响下游，但说明它的自述不能当事实源。
- 什么情况下该重新考虑：如果"记满即停"导致它总是只找前几个而不做全面比较（比如永远只投第一页的岗位），需要改成"先全部记录再排序取前 N"，那时 `max_jobs` 的语义要从"记满就停"改成"最终保留几个"。

## Layer 1 的提交防线从"不给工具"改成"点击工具自己拒绝"

- 日期 / 版本：2026-08-14，v2.22.0
- 背景：旧版 Layer 1 的安全边界是"工具集里根本没有提交能力"——代码写死点哪个 uid，agent 没有决定点什么的余地。改成 agent 自主导航后**这条守法自动失效了**：`click` 成了它可以任意调用的工具，而"提交/投递"在投递页上就是个普通按钮，同一个工具既能点「申请」也能点「提交」。
- 选了什么：`safe_tools.make_guarded_click` 包一层——点击前从最近一张快照里取该 uid 的 label，命中终局关键词（提交/下一步/确认投递/……）就**拒绝并返回一段给 agent 看的说明文本**（不是抛异常，agent 需要知道"这条路堵了、换个方式"，抛异常会把可恢复情况变成硬失败）。工具名仍叫 `click`，对 agent 透明。
- 否掉了什么，为什么：①**否掉"靠 prompt 叮嘱 agent 别点提交"**——项目里反复记过安全边界靠不给能力、不靠指令约束；prompt 里也写了，但那是第二道，不是唯一一道。②**否掉"关键词表里放「申请」「投递」「apply」"**——这些是**入口**词，拦掉它 Layer 1 连表单都进不去，表现为"什么都识别不到"，比拦不住更难查；表里只放终局短语（「确认投递」「立即投递」在，光「投递」不在）。特别地 `apply now` 刻意不加：英文招聘站上它通常是入口按钮。③**否掉 fail-closed**（取不到 label 就拒绝）——a11y 快照里大量可交互元素压根没有 accessible name（上传按钮和三个必填 combobox 都是），fail-closed 会让 agent 寸步难行。
- 代价 / 已知不足：①**fail-open**：uid 不在快照里、或元素没有名字时放行。真正的兜底是四层架构本身——Layer 1 的产出只是一条待审批记录。②关键词表是中英文硬编码，遇到别的语言的站点会漏；③宁可误伤：如果哪个站点的入口按钮真叫「确认申请」，Layer 1 会进不去那个站，需要人看日志里的 `REFUSED` 才知道。
- 什么情况下该重新考虑：接入非中英文站点时，或出现"入口按钮被误拦"的真实案例时，需要把关键词表改成可按站点配置。

## Layer 1 是「纯执行 agent」：刻意不接全局 prompt 注入、不接 system.md

- **日期 / 版本**：2026-08-14，v2.22.1
- **背景**：查证发现 Layer 1 的 prompt 链路跟项目其余部分是断开的——`multisite/layer1_agent.py` 里是裸的 `PromptManager()`，而 `w1_runner.py` / `w2_runner.py` 都是 `PromptManager(injection=profile.prompt_injection)`。后果：①用户在设置页写的**全局注入对 Layer 1 一个字都没进去**；②三个 Layer 1 模板（`layer1_find_jobs` / `layer1_open_application` / `classify_field`）不在 `EDITABLE_PROMPTS` 白名单里，前端编辑不到；③`system.md` 只有 `tools/llm/score_job.py` 和 `analyze_intent.py` 通过 `load_system()` 加载，Layer 1 从没调用过。**这个现状原本是疏漏，不是设计**——写 Layer 1 时没接这条链。
- **选了什么**：**保持不接，并把它转为有意的设计**（用户 2026-08-14 拍板）。用户的判断：「这条链路其实是一个纯粹的执行 Agent，整个项目应该做成多 Agent 合作的模式，这个 Agent 不管别的很多东西，只用专注于选岗即可。」即：Layer 1 的 agent 只需要"求职偏好 + 当前页面"两样输入，不需要项目级的人设/语气/全局补充指令——那些是给对外沟通类 agent（W2 回复 HR、简历生成）用的。
- **否掉了什么，为什么**：①**否掉"顺手补上 `injection=`"**（一行改动，很有诱惑力）——全局注入的内容是用户为**对 HR 说话**写的（语气、强调什么、别提什么），灌进一个浏览器操作 agent 只会挤占本来就紧张的 64k 上下文，还可能干扰它的工具调用决策；改完还得重新真机验证 agent 行为，成本远大于"少了个功能"。②**否掉"把三个模板加进 `EDITABLE_PROMPTS`"**（这轮）——`save_override` 的占位符校验会拿它当普通模板管，但 `layer1_find_jobs.md` 里的 `{{max_filter_clicks}}` 之类是**运行参数**不是上下文，让用户在 prompt 编辑器里改它会和未来的"参数面板"打架，两个入口改同一个东西就是分叉。③**否掉"把 Layer 1 也接进 `system.md`"**——`system.md` 是 Boss 直聘求职助手的人设，跟"在企业招聘站上翻页选岗"不是同一个角色。
- **代价 / 已知不足**：①用户想调 Layer 1 的行为，目前**只能改 `prompts/*.md` 源文件**，没有前端入口，也没有"恢复默认"；②"多 Agent 合作模式"目前只是方向，没有任何承载它的结构（没有 agent 注册表、没有各 agent 的能力/输入声明），所以"这个 agent 只管选岗"现在靠的是**没接线**而不是**有边界**；③项目里因此存在两套 prompt 治理方式（W1/W2/简历走 PromptManager 全套；Layer 1 只用它读文件），看代码的人会以为是漏了。**本来打算在前端「跨站点投递」页把"全局注入：未接入（有意）"标出来，但那个页面已被用户回滚**（2026-08-14，理由：架构讨论走 CLI 更直接），所以现在唯一的提示就是这条决策记录和 `multisite/layer1_agent.py` 的模块 docstring——**下一个人极可能"顺手补上 injection="**，这是已知且未消除的风险。
- **什么情况下该重新考虑**：①真的开始做多 Agent 合作结构时（那时"每个 agent 吃什么 prompt"应该有统一声明，不再是各接各的）；②出现"确实需要跨 agent 生效的全局约束"时（比如某条法律/隐私红线要所有 agent 都遵守）——那种东西不该走用户自由文本注入，应该是代码级约束，参见 `make_guarded_click` 的做法。

## Layer 1 的 MCP 工具从黑名单透传改为按节点分发的白名单

- **日期 / 版本**：2026-08-14，v2.22.1
- **背景**：用户问"纯 DeepSeek 没有多模态，agent 怎么判断图片"，顺着查实际工具面才发现的。dump 出来的事实：`chrome-devtools-mcp` 暴露 **29 个**工具，`build_agent_toolset` 的透传写法是黑名单 `[t for t in tools if t.name not in {"take_snapshot", "click"}]`，于是**其余 27 个全部交给了 agent**。
- **问题**：①`evaluate_script`（任意 JS）一行 `document.querySelector(...).click()` 就绕过 `make_guarded_click`——守法点击形同虚设；②`press_key` 在输入框里回车通常等于提交；③`take_screenshot` 返回图像块，**DeepSeek 没有视觉**，而且 `agent_runtime._BULKY_TOOLS` 里没有它，图像块一旦进历史就永远不会被裁剪，卡死 64k 上下文；④`fill`/`fill_form`/`type_text`/`upload_file` 在选岗阶段完全不该有（prompt 里写了"不要填写任何表单"，但那是叮嘱不是边界）。
- **为什么这条重要**：上一条决策（守法 click）和 `layer1_agent.py` 模块 docstring 都声称"提交防线是**代码强制**，不是 prompt 叮嘱"。**在修掉之前那句话是不成立的**——不是 guarded click 有问题（它有测试、做过变异验证），是它旁边开着 `evaluate_script` 这扇门。**黑名单挡不住"同一件事换个工具做"，而且 MCP 上游每加一个新工具，黑名单就自动漏一个。**
- **选了什么**：改**白名单**，且**按节点分发**——`_PASSTHROUGH_FIND_JOBS = (navigate_page, wait_for)`；`_PASSTHROUGH_OPEN_APPLICATION = (navigate_page, wait_for, upload_file)`。两个节点都拿不到 `evaluate_script`。白名单取工具走 `chrome_mcp_client.get_tool`（点名取、取不到就抛）而不是过滤，这样 MCP 改工具名会当场炸，而不是静默少给一个工具、表现为"agent 莫名其妙不会翻页了"。
- **否掉了什么，为什么**：①**否掉"两个节点共用一份白名单"**——`upload_file` 是对真实企业系统的真实动作，选岗阶段（纯浏览、零副作用）不该具备这个能力；共用一份就等于把"select-only 是零副作用"这个保证降级成了运气。②**否掉"保留黑名单，只把 evaluate_script 加进去"**——那只堵了今天知道的那个洞，`chrome-devtools-mcp` 下次升级加的工具照样自动漏进来。③**否掉"给 open_application 也放 fill/type_text"**——它只需要上传简历，填表是 Layer 3 审批之后的事；真需要时再加，比先给了再收回安全。
- **代价 / 已知不足**：①**`open_application` 节点从来没真机验证过**（`--select-only` 只跑到 find_jobs），这次又收窄了它的工具集——**下次真机跑如果它卡住，第一个要怀疑的就是缺了某个工具**，`get_tool` 的报错帮不上忙（它只在名字不存在时抛，不在"agent 想要但没给"时抛）。②白名单是手维护的，加节点时容易忘配。③`hover` / `list_pages` 之类可能在某些站点确实需要，现在一律没有。
- **验证**：`tests/test_safe_tools.py::TestAgentToolsetWiring` 加了 6 个断言（含 6 个危险工具的参数化拒绝测试、两个白名单精确相等、`upload_file` 只在导航节点、未知名字要抛）。**做了变异验证**：把 `allowed = [...]` 改回黑名单，测试退出码 1、`evaluate_script`/`take_screenshot` 等当场变红；还原后全绿。
- **什么情况下该重新考虑**：真机跑 `open_application` 时如果 agent 明确卡在"我需要 X 工具但没有"，按需往对应白名单加**一个**，并在这里补记为什么需要它——不要图省事改回黑名单。

## AI 方向的产品经理归 AI NATIVE，不归产品

- **日期 / 版本**：2026-08-14，v2.23.0（**用户拍板**）
- **背景**：给选岗 agent 加了"职责出现 LLM / 大模型 / Agent / 多模态 / AIGC 就归 AI NATIVE"的消歧规则之后，真机跑时它把「CyberBrick 产品经理 - 软件AI方向」从「产品」拉到了「AI NATIVE」。这是规则的副作用，不是 bug，但需要人来定这算不算对。
- **选了什么**：**算对**。AI 方向的产品岗归 AI NATIVE，「产品」那一类留给不带 AI 的常规产品岗。规则写进 `prompts/layer1_find_jobs.md`。
- **否掉了什么，为什么**：①**否掉"AI NATIVE 只放技术岗"**——那样这一类就退化成"算法工程师"的同义词，而用户设这一类是按**做的事情属于 AI 原生方向**划的，不是按职能划的。②**否掉"两边都算，占两份名额"**——名额是互斥分配的，一个岗位占两个类别的额度会让配额彻底失去意义。
- **代价 / 已知不足**：「产品」这一类会明显变小（拓竹站上 3 个产品经理里至少 1 个被划走）。如果以后发现常规产品岗因此被挤没了，说明这条规则太宽，要收窄成"职责主体是 AI 能力本身"而不是"提到了 AI"。
- **什么情况下该重新考虑**：产品类长期招不满而 AI NATIVE 长期溢出时；或用户开始把这两类投向不同公司时（那说明它们在用户心里是两条独立赛道，划分标准要重新谈）。

## Layer 1 的 agent 步数耗尽必须显式检测，不能靠 GraphRecursionError

- **日期 / 版本**：2026-08-14，v2.23.0
- **背景**：`layer1_agent.find_jobs` 一直有个 `except GraphRecursionError` 兜底，注释还写着"兜圈子超限不再是全损"。第四次真机跑才发现**这个分支从来没执行过**：LangGraph 的 `create_react_agent` 在步数快用完时**不抛异常**，而是往 messages 里塞一句固定文案 `"Sorry, need more steps to process this request."` 然后正常返回（`langgraph/prebuilt/chat_agent_executor.py:689/716`，已核对安装的包，不是从日志猜的）。
- **后果有多严重**：两种结局的返回值**结构完全相同**——都是正常返回、最后一条是 AI 文本消息。所以"所有分类桶都扫完了"和"扫到第二个桶第 4 页没步数了"在日志里长得一模一样。**前三次真机跑得出的"agent 主动收尾"结论因此全都不可靠**，其中至少第三次实际上是半途而废（产品/运营 0 个不是站上没有，是压根没扫到）。
- **选了什么**：`agent_runtime.hit_step_limit(state)` 显式匹配那句 sentinel，`run_agent` 检测到就打 `[!!]` 警告，`find_jobs` 再补一句"名额没满的类别可能只是没扫到，不代表站上没有"。`MAX_STEPS` 40 → 60。
- **否掉了什么，为什么**：①**否掉"只调大 MAX_STEPS 就算了"**——调多大都可能不够，真正的问题是**不知道够没够**；能观测比能跑完更重要。②**否掉"自己数轮次判断"**——LangGraph 的 `_are_more_steps_needed` 还会看模型是否要调工具，自己数会跟它的判定错位，出现"我以为没超它以为超了"。③**否掉"删掉那个 except 分支"**——留着当第二道，万一上游换回抛异常的实现，已记录的岗位仍然不能全丢。
- **代价 / 已知不足**：**耦合了 LangGraph 的内部文案**，升级版本时可能失效——而失效的表现正是它要修的那个坑（静默截断）。缓解：`tests/test_agent_runtime.py::TestHitStepLimit` 用字面量断言，字符串变了会红；但那只在我们跑测试时才发现，不是运行时保护。
- **什么情况下该重新考虑**：LangGraph 升级后测试变红时；或它以后提供了正式的"是否达到步数上限"API（那时应该立刻换过去）。

## m1/m2 复用 W1/W2/W3 那套 run 日志 + SSE，粒度做到节点级，但不做专属前端面板

- **日期 / 版本**：2026-08-16，v2.24.5
- **背景**：m1/m2 自 v2.24.0 起跟 W1/W2/W3 共用同一个队列，但**一次 `start_workflow`/`finish_workflow` 都不发、一行 run 日志都不写**（只有失败路径在 `run_item` 里发了个 finish，给一个从没 start 过的 workflow）。后果是跑 m1/m2 时 Dashboard 只知道"忙"，看不到卡在哪一步；事后 `logs/runs/` 里也没有能回放的记录，只剩 `schedule_log` 一行——而那个日志本身已经记过案（71% 幻影 success）。
- **选了什么**（v2.24.6 按 TDD 重写后的形态）：新模块 `multisite/observability.py`，两个东西——`run_scope(workflow, emitter)` 管一次运行的生命周期（run_start / **无论如何都写 run_end** / SSE 的 start 与 done），`traced_stage(name, fn, logger, summarize)` 管一个阶段的记录。两者**都不碰浏览器、不碰 LangGraph**。图组装改成「阶段表 + 循环 add_node」，包装因此不是每加一个节点都要记得做的手工动作。前端只把 m1/m2 加进已有的通用 run 列表/回放（`Logs.tsx` 的 pipeline 过滤 + `WorkflowId`）。
- **为什么是这个形状**：它是被测试逼出来的。第一版（v2.24.5，测试事后补）把生命周期手写在 `run_layer1` 的 try/except 里、把摘要做成一个认识全部六个阶段输出形状的 `_summarize_node` 大 if-else——两者都要开真 Chrome 才跑得到，于是**失败路径一条测试都没有**。TDD 第一个问题「这个行为怎么测」直接把这两块从浏览器里拆了出来。
- **否掉了什么，为什么**：
  ①**否掉"多站点自己写一套观测"**——多站点确实是另一条轨道（chrome-devtools-mcp / LangGraph / 各站独立 profile，跟 DrissionPage 那条线毫无共用），但**观测契约是全局的**：run 日志的读者（`run_log_reader`、`run_diagnostics`、前端回放）只认这一种格式，自己写一份等于让这些工具对多站点集体失明。"某功能有自己的执行路径"在本项目是记过案的坏味道。
  ②**否掉"只发 emitter 的 start/finish（粗粒度）"**——那样 Dashboard 上仍然只有"开始/结束"两点，`open_application` 卡住和 `find_jobs` 没找到岗位长得一样；而且不落 JSONL，事后无法回放。**JSONL 是完整数据源、SSE 只是实时镜像**，命令行 `--direct` 跑的那次同样要留下记录，所以 RunLogger 无条件建、emitter 可为 None。
  ③**否掉"给 WorkflowTrack 加 m1/m2 专属面板 + 骨架"**——手维护的 `SKELETON` 静态模板已经被记过一次（迁步骤后必然漂移，真实骨架的权威源是 run JSONL）。m1/m2 的形态还在动（Layer 3 未做），现在定骨架是给一个会变的东西上石膏。
  ④**否掉"在每个节点内部手写计时+落日志"**——六份几乎一样的样板，加第七个节点时漏一份不会有任何东西变红，表现为 Dashboard 上那一段莫名不显示，跟"卡住了"一模一样（W1 的 LOOP_STEP 栽过）。
- **代价 / 已知不足**：`multisite/` 由此依赖 `pipeline/`（此前完全独立）。这条依赖是单向的、只指向那个跟 Boss 线无关的 logger 适配器，可以接受；但如果哪天要把多站点拆成独立服务，这是要先切断的一根线。另外节点级是**图节点**粒度，agent 循环内部那几十步仍然只进 stdout 追踪，Dashboard 上看不到。
- **什么情况下该重新考虑**：m1/m2 形态稳定（Layer 3 落地）之后，可以再判断要不要给它做专属的前端骨架视图；或者 agent 内部步数也需要在 Dashboard 上看到时——那时该考虑把 `agent_runtime._trace` 也接进 `log_tool`。

## 事后补测试 vs TDD：同一块代码写两遍的实测差异

- **日期 / 版本**：2026-08-16，v2.24.5（事后补）→ v2.24.6（TDD 重写）
- **背景**：v2.24.5 的测试是代码写完之后补的，违反全局规则 11 与 superpowers 的
  iron law。用户要求「先 commit 这一版做基线，然后重写，对比效果」——所以两版
  在 git 里都在（`e854ae1` 是事后补测试的那版）。
- **量到的差异**（不是感受，是两版代码本身）：
  1. **测的东西不同**。事后补的那版测了两个辅助函数（`_summarize_node`、
     `resolve_source_job_id`）——都是我记得自己写过的东西；**包装器本身零测试**
     （计时、失败时也要落日志、异常必须重抛，一条都没有），**回指有没有真的落到
     库里也没测**（只测了"算得对"）。TDD 版测的是"JSONL 里有什么""库里那条记录的
     `source_job_id` 是多少"。
  2. **TDD 逼出两处拆分**：run 生命周期从 `run_layer1` 里拆成 `run_scope`；两个
     不碰浏览器的阶段（`record_candidates` / `record_application`）从图的闭包里
     提到模块级。理由都一样——**"这个行为怎么测"问不出答案时，是设计在挡路**。
  3. **TDD 当场抓到一个缺口**：`source_job_id` 写进去了但 `PendingApplication`
     读不出来，测试直接 AttributeError。事后补的那版是我写完顺手想到才补的读侧，
     没有任何机制保证我会想到。
  4. **摘要的形状被"我希望怎么调用"决定**：从「包装器认识每个阶段的输出形状」
     变成「摘要跟着阶段走」，加阶段不再需要改两处。
- **必须打的折**：**这个对比被污染了**——重写时我记得第一版的实现，"delete means
  delete / don't look at it"对 LLM 只能做到不回看文件、不复制，做不到没见过。
  最明显的例子：`test_link_survives_the_whole_m2_path`（url 去重每次命中、所以不能
  用新插入的 id）这条测试是**知道那个陷阱才写得出来**的，是记忆的功劳不是 TDD 的。
  所以上面第 1、2、3 条可信（它们是结构性的），"TDD 版质量更高"这个整体结论要打折。
- **代价**：重写一轮的时间；`multisite/layer1_agent.py` 多了一次结构变动（两个阶段
  搬家）。
- **什么情况下该重新考虑**：不该。这条记的是"规则 11 不是仪式"的实测证据，下次想
  说"这次先写代码后补测试"时回来读第 1 条。

## m1 的控制台入口：参数走 workflow「设为默认」，不进 profile，也不先做站点管理

- **日期 / 版本**：2026-08-16，v2.24.7
- **背景**：m1 此前只能命令行触发，而审批、看结果都在 Dashboard——唯独"开始找岗位"要开终端。补入口时卡在一个问题上：m1 需要 `site` + 入口页 URL，而这两样**每次都一样**，让人每次手打一遍是最容易出错的一环（URL 打错的表现是 agent 在一个不存在的页面上兜圈子到步数耗尽）。
- **选了什么**：`config.yaml` 加 `m1:` 节（`site` / `search_url` / `max_pages`），复用 W1/W2 已有的「设为默认」机制（写 `data/user_settings.yaml`，`_DEFAULTABLE_WORKFLOWS` 白名单）。控制台里 M1 与 W1/W2/W3 并列；WorkflowTrack 加 m1/m2 两个 tab，但**不写 SKELETON/LOOP_STEPS 条目**。
- **否掉了什么，为什么**：
  ①**否掉"存进 `profile.yaml` 的 `site_overrides`"**——那里是**求职偏好**（哪些类别、跳过什么），入口页是**运行参数**（这次从哪儿进）。塞进去会让"偏好"这个概念开始混装操作参数，而 v2.22.0 刚把"偏好不该以 URL 形式存在"这条立起来。
  ②**否掉"先做站点管理页"**（增删站点、每站配入口页/名额/登录态）——目前只有一个站，做出来是给一个假想的规模建索引；用户明确"以后再做"。真有第二个站时这个决定该重新考虑。
  ③**否掉"控制台放 M2"**（用户拍板）——批准 Checkpoint 1 就已经自动入队 m2 了，控制台里的 M2 只剩"补跑/重跑"这一个用途，而那个需求还没真正出现过。m2 的 tab 仍然加了（要看得到过程）。
  ④**否掉"给 m1/m2 写详细 step 骨架"**（用户明确"先不做，留着以后"）——`SKELETON` / `LOOP_STEPS` 是手维护的静态模板，已经因为跟真实步骤漂移记过一次案；留空时页面照常显示真实收到的事件，等 m1/m2 形态稳定了再填。
- **代价 / 已知不足**：`site` 是个自由文本框（配 placeholder），填错了不会有任何提示，只会跑到一个没登录的浏览器里干等——这正是站点管理该解决的问题，欠着。
- **什么情况下该重新考虑**：出现第二个站点时（那时"每次改文本框"会立刻变难受），或者 Layer 3 落地后 m2 需要独立重跑入口时。

## agent 追踪日志用 `safe_print` 吞掉编码异常——这是 fail fast 的一个例外

- **日期 / 版本**：2026-08-16，v2.24.8
- **背景**：一次 m1 全损，根因是追踪用的 `print` 抛 `UnicodeEncodeError`，打死了整个 `find_jobs` 节点（详见 `PITFALLS.md` 对应条目）。
- **选了什么**：`services/console_utf8.safe_print()`——写不出去就退化成 `backslashreplace` 再打一次，**绝不向调用方抛异常**。agent 追踪的三处 print 全部改用它。
- **为什么这不违反"内部路径不写防御性兜底"**：全局原则说的是**不要吞掉业务失败**——那会让 bug 变得不可见。而这里吞掉的是**日志自身的失败**，它跟业务结论没有任何关系：一个字符打不出来，不代表选岗失败了。判据是"这个异常携带的信息，是不是调用方需要据以改变行为的"：`record_job` 写不进去是（该失败），"这句话显示不出来"不是。
- **否掉了什么，为什么**：
  ①**否掉"只修 stdout 编码就够了"**——那是根因不假，但它是**进程级**设置，下一个入口（定时任务、别的脚本、CI）照样可能漏掉；而漏掉的代价是打死一条跑了几分钟、花了 API 费用的 run。两道防线的成本差不多，就都要。
  ②**否掉"在 `_trace` 外面包一层 try/except"**——那会把"这一步的追踪失败"扩大成"这一步的追踪整段消失"，而且每个调用点都要记得包。放在打印函数里，一处生效。
  ③**否掉"追踪改成写文件而不是 print"**——stdout 是 uvicorn 日志的自然出口，改写文件等于再造一套日志通道，而 run 日志（JSONL）已经在做结构化留存了；追踪的定位就是"人盯着终端看它在干嘛"。
- **代价 / 已知不足**：极端情况下终端里会出现 `\u2705` 这样的转义而不是字符本身——可读性略降，但这正是"尽力而为"的含义。另外 `safe_print` 只兜 `UnicodeEncodeError`：别的 IO 错误（管道断开）仍然会抛，那类问题该暴露。
- **什么情况下该重新考虑**：如果发现有别的日志异常也在打死流程（比如管道断开），那说明"日志不该杀死流程"这条要提升成更普遍的机制，而不是继续一个个打补丁。

## m2 发哪一份简历：按岗位匹配 + PDF 必须不旧于简历，选不出可用的就拒绝

- **日期 / 版本**：2026-08-16，v2.25.0
- **背景**：m2 原本用 `latest_export_path()`——"最近导出的那份"。真实数据里三份简历只有一份导出过，于是它成了**所有岗位**的唯一选择；而那份 PDF 还比简历最后修改早 10 分钟。用户问"现在传的这个简历是哪里来的"时，答案是"一个跟岗位无关的时间属性"。
- **用户给的设计哲学（拍板依据）**：「Agent 自己生成是我们做好了但是拦住了的窗口，**目前往外发尽量还是用人工做的精美简历**，这里也一样。」——对外发送的东西优先用人工确认过的产物，这跟 AI 组合简历（`/api/resume/compose`）做了但收在默认关开关后，是同一条原则。
- **选了什么**：①`resume_matcher` 按岗位标题/描述挑一份（判断依据回到岗位本身）；②要求它有一份 `ready` 的 PDF（不早于简历最后修改）；③**否则拒绝跑 m2**，错误信息说清是哪一份、为什么不可用、该去做什么；④简历列表 API 与 UI 显示 `ready/stale/missing` 三态徽章。
- **否掉了什么，为什么**：
  ①**否掉"选中的不可用就改发另一份可用的"**——这是最容易顺手写出来的兜底，也是最危险的：发错一份的后果是它**躺在企业的申请表里**。对照 W2 那条线，它允许回退站内简历（`adapted_resume_fallback`），因为 Boss **有站内简历兜底**；多站点没有兜底，两边的正确答案因此相反。
  ②**否掉"后端自己渲染 PDF"**——A4 排版的唯一实现在前端 `src/lib/resumeHtml.ts`，后端再写一份就是同一契约两份实现，必然漂移。这条约束是既有的，本次沿用。
  ③**否掉"批准时前端现场渲染导出"**（当时给过这个选项）——它能免掉人工导出这一步，但要在批准流程里插一段"渲染 + 上传"，还得处理渲染失败、页面必须开着等状态。与①的哲学也不符：人工导出正是"人确认过这一份"的动作。
  ④**否掉"只判断有没有 PDF"**——那会把 `stale` 报成可用，正是这次踩的坑。
- **代价 / 已知不足**：**改完简历必须重新导出一次，否则 m2 不跑**（会明确告诉你缺哪一份）。当前三份简历全都不可用（两份没导出、一份过期），也就是说这条规则一上线，m2 立刻全线停摆直到人去导出——这是有意的，它反映的是真实状态。
- **什么情况下该重新考虑**：如果"每次改完简历都要手动导出"在实际使用中成为主要摩擦，再考虑③（前端在装填时批量渲染缺失的那几份）。

## 批准与填表解耦：批准只标记，填表由站点级按钮一次性装填

- **日期 / 版本**：2026-08-16，v2.25.1
- **背景**：Checkpoint 1 原本「批准即入队 m2」。用户实测发现：点下第一个岗位的批准，浏览器立刻被 m2 占住，**剩下 15 个岗位连看都没法看**——因为多站点只有一个 Chrome 实例，而队列是串行的。
- **真正的问题不是"太快"，是两种节奏被绑在了一起**：审批是「逐个判断」（人一条条看、可能改类别、可能驳回），填表是「批量执行」（机器一个个跑，每个几十秒）。绑在一起等于强迫人一次只能审一个。
- **选了什么**：①批准/批量批准只写状态，**不再入队**；②站点信息条上加「开始填表 N」按钮，点一次把该站**所有已批准且还没填过表**的岗位排进队列；③N 由后端算并随列表返回。
- **否掉了什么，为什么**：
  ①**否掉"给批准端点加一个 enqueue=false 开关"**（当时代码里真有这个参数）——那是把决定权留在调用方，于是"批准会不会立刻开跑"取决于谁调、传了什么，同一个动作有两种行为。删掉它，语义变成唯一的：批准就是批准。
  ②**否掉"前端自己算待填数量"**——差集规则（已批准 − 已填过 − 已在队列）在 start-fill 里已经有一份，前端再算一遍就是同一规则两份实现，必然漂移。抽成 `_jobs_awaiting_fill()`，列表接口取它的长度、start-fill 取它的内容。
  ③**否掉"只看 pending_applications 判断填没填过"**——已经排在队列里、还没跑到的岗位那时**还没有**回指记录，只看这一个来源会让连点两次按钮把同一岗位排两遍，而那等于**再往企业系统传一次简历**。所以队列快照也要算进去（有测试守）。
- **代价 / 已知不足**：多了一次点击。另外「开始填表」目前是站点级的全量装填，没有"只跑选中的这几个"——真需要时再说，先不猜。
- **什么情况下该重新考虑**：如果以后多站点能并行跑多个浏览器（现在刻意共享一个队列、一个实例），"填表占住浏览器"这个前提就没了，那时可以重新讨论要不要恢复自动触发。

## 字段分类补第四档 `unknown_fact`，而不是去调 prompt

- **日期 / 版本**：2026-08-17，v2.25.3
- **背景**：Checkpoint 2 真机跑出的五个字段 kind **全是 `open_question`**，其中「学校名称」拿到的"答案"是一句「请填写您的学校名称（例如：XX大学…）」——填写说明冒充答案。
- **真因不是 prompt 写得不好**：kind 只有三档，`demographic` 的判据是"能在 personal_info 里找到 key"，而那里只有 5 个 key（姓名/邮箱/电话/性别/生日）。学校、城市、日期、公司名这些事实性字段**按排除法**只能落进 `open_question`，而 `open_question` 的指令就是"生成一段候选文本"。**taxonomy 的兜底桶动作是"生成"，那它必然产出编造。**
- **选了什么**：加第四档 `unknown_fact`（事实性字段，已知资料里没有 → 留空，由本人填），并把"只有 `open_question` 允许带生成的值"写成代码闸 `_enforce_no_invented_values`（分类节点 + 落库各调一次，规则只有一份实现）。前端加对应徽章（橙色「资料里没有」），并把「必须人来填」这个判据从 `government_id` 一处扩成共用的 `needsHumanValue()`——列表徽章和批准闸共用它。
- **否掉了什么，为什么**：
  ①**否掉"把 prompt 写得更严厉"**（比如"不许编造"）——没有可去的桶时，越严厉的措辞越只是让它换一种方式编。结构缺陷不能靠措辞补。
  ②**否掉"干脆不让 LLM 生成任何值"**——真正的开放问题（自我评价、为什么应聘）起草是有价值的，那是"做好了但拦在开关后面"的能力，不是本次要砍的东西。被砍掉的只是**对事实的编造**。
  ③**否掉"用 `load_candidates(field)` 有没有命中来自动定 kind"**——信息池能覆盖学校/专业这类，但覆盖不了「意向城市」，会留下一半靠代码一半靠 LLM 的分叉判据。
- **代价 / 已知不足**：审批时人要多填几个格（`unknown_fact` 且必填的字段现在会挡住批准按钮）。这是有意的——放行一条必填项空着的申请，代价更大。
- **什么情况下该重新考虑**：如果以后 personal_info / 信息池覆盖到大部分事实字段，`unknown_fact` 会自然变少；那时可以重新讨论要不要让它参与自动填充。

## 简历信息池语义检索：只设计检索能力本身，不连同 Copywriter agent 一起设计

- **日期 / 版本**：2026-08-17（设计阶段，未实现）
- **背景**：`data/info_pool.yaml`（简历信息池）现在只有一种消费方式——整份塞进 LLM 上下文。池子只会越攒越大，而正在规划中的"网申开放问题字段生成"能力（见「网申表单字段：人口学字段规则填，开放问题字段 LLM 填 + 人工审批」条）需要的是"跟这条 JD/这个问题最相关的几段经历"，是检索问题，不是"塞更多上下文"能解决的。此次设计的直接动因是用户在准备"Agent 开发工程师"方向的简历，不是当前业务的紧急需求——不影响设计质量，但解释了下面几处偏工程完整性的选择为何优先于精简。
- **选了什么**：①范围只设计检索能力本身，不设计消费方（Copywriter agent 的角色划分、如何接入 LangGraph、和 Filler 节点如何交接）——留给下一次设计。②检索最小单元用整个 block（不用单条 bullet），跟现有拖拽单位一致，检索结果自带上下文。③Embedding 用 OpenAI `text-embedding-3-small`（API），不用本地 Ollama——用户明确选的，需新增 `OPENAI_API_KEY`（项目目前只有 `DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY`）。④向量存储用缓存索引 `data/info_pool_embeddings.json`，按 block 内容指纹（`content_fingerprint`）失效，不是每次现算。⑤排序算法用暴力 cosine 相似度，不引入 faiss/chroma——池子只有几十个 block，专门的向量库是过度设计。⑥代码分层：`tools/llm/embed_text.py`（单个外部调用，ToolResult 契约）+ `services/pool_retriever.py`（编排），不并入 `resume_matcher.py`。⑦现在就建正式 eval harness（Recall@k/MRR），沿用意图 eval 的三条硬约束（金标 PII 只落 `data/eval/` gitignore、eval 忠实生产签名、ground truth 人标），尽管还没有真实消费方校准"检索准不准"。spec 见 `docs/superpowers/specs/2026-08-17-info-pool-semantic-retrieval-design.md`。
- **否掉了什么，为什么**：①**否掉"连 Copywriter agent 一起设计"**——范围太大，且 agent 角色划分依赖检索能力先验证过效果，顺序应该是先做基础能力。②**否掉"本地 Ollama 做 embedding"**——虽然免费离线且不新增 provider，但用户明确选了 API 方案。③**否掉"在 `resume_matcher.py` 里加向量相似度 tie-break"**——这次只做池子语义检索这一个方案，`resume_matcher` 保持"确定性关键词匹配、不用 LLM/向量"的既有决策不变。④**否掉"先不建 eval，等 Copywriter 建好再评测"**——用户认为现在建 eval harness 本身就是想要的经验积累，不必等下游。
- **代价 / 已知不足**：新增 `OPENAI_API_KEY` 依赖，是项目第一次引入 OpenAI 作为 provider；eval 金标集样本量会很小（预计 10-20 条，受限于池子本身规模），不足以支撑统计意义上的阈值判断，harness 只报数不设强制通过线。
- **什么情况下该重新考虑**：Copywriter agent 真正设计/实现时，需要回来看这份检索能力的接口是否够用；如果 OpenAI embedding 的成本或网络依赖成为问题，需要重新评估本地 Ollama 方案。

## m1/m2 的第 3 层用独立时间线，不复用 W1/W2 的层级树

- **日期 / 版本**：2026-08-18，v2.26.0
- **背景**：m1/m2 的 LangGraph 节点级进度早就进了 run 日志，但**节点内部的 agent 循环几十步一条都没落盘**——只有 `_trace` 打到 uvicorn 的 stdout。而 m1/m2 恰恰是唯一一条内部不确定的流程，最需要看清楚的那条反而最看不见。
- **选了什么**：三层视图。第 3 层是**独立的 append-only 时间线**，不挂进现有 `buildTree` 的层级树。
- **否掉了什么，为什么**：
  ①**否掉「把 agent 步挂进现有 `buildTree`」**——它按 tool 名存 `Map`、后来者覆盖（注释写着 "Latest event wins"）。W1/W2 每步每个 tool 只调一次所以够用；ReAct 是序列，真机那次 `take_snapshot` 调了 13 次、`record_job` 18 次，挂进去会**塌成一个节点**。这不是配置问题，是数据结构不匹配。
  ②**否掉「给 m1/m2 手写 SKELETON 静态骨架」**——W1/W2 的 `SKELETON` 是手维护模板，已经因漂移记过一次案（Dashboard 上有一站永远不亮，跟"卡住了"一模一样、测不出来）。m1/m2 的骨架从 `build_graph` 的阶段表导出，并在**建图时当场对账**，漂移在结构上不可能。
  ③**否掉「第 1 层画跨 run 的真实状态」**——那要以「岗位」为主体，用 `pending_job_id` 把 m1 run / 人工审批 / m2 run 串起来，等于先把 layer 之间的状态流转定死。而那正是用户明确说「还没想清楚、要单独理」的部分（后来确实单独理了，见 `2026-08-18-m1-m2-m3-split-design.md`）。第 1 层因此只画静态链、高亮当前段。
  ④**否掉「a11y 快照每张都存」**——一次 run 几十张、每张 10KB+。改成只记摘要（字符数 + 首行），**失败时**才把当时最近一张全文落进 `logs/runs/{run_id}/`。判据：成功的 run 要看的是"它调了什么、说了什么"，只有出错才需要"它到底看到了什么"。
- **顺带确立的一条通则**：**run 产物按寿命分，不按类型分。** run 证据（失败快照）进 `logs/runs/{run_id}/`，跟 run 同生死、可整目录删干净（那些文件装着真实公司/HR 的 PII，分两处删会留孤儿）；业务数据（Checkpoint 2 的表单截图、将来 Layer 3 的已投递存证）留在 `data/`，寿命由数据库记录决定——放进 run 目录会让清理旧日志把审批页的图删掉。
- **代价 / 已知不足**：`agent_step` 让一次 run 的 JSONL 多约 60KB。第 1 层没有真实状态，只是方位感。
- **spec**：`docs/superpowers/specs/2026-08-17-m1-m2-visualization-design.md`

## 「没跑完」必须有自己的状态，不能报 successful

- **日期 / 版本**：2026-08-18，v2.26.0
- **背景**：`create_react_agent` 步数耗尽时**不抛异常**，只往 messages 里塞一句固定文案就正常返回——两种结局的返回值一模一样。原来两处 `hit_step_limit` 分支都只是 `print`，阶段照报 `successful`。
- **选了什么**：节点把 `truncated` 写进 state，`traced_stage` 翻译成新的 `partial` 状态（前端黄色）。
- **否掉了什么，为什么**：**否掉「复用 `degraded`/`skipped`」**——`_UI_STATUS` 已有 `degraded → skipped`，而前端把 `skipped` 当绿色的 done。并进去等于把"没干完"画成成功。
- **为什么值得单开一档**：它会跟「名额过早填满」叠加成一个**错误结论**——看到「游戏 0/2」自然推断"这站没有游戏岗"，真相可能是步数用完压根没扫到。**一个错误的结论比一个明显的失败危险得多。**

## agent 的死循环用代码拦，不写进 prompt

- **日期 / 版本**：2026-08-19，v2.27.0
- **背景**：m1 首次跑新站点 join.qq.com，agent 对一个点不动的筛选项 uid **连点 29 次**，
  中间夹着 30 次重新截图，四分钟烧光 60 步预算，一个岗位都没找到。61 次工具调用里 59 次是废动作。
- **选了什么**：`safe_tools.make_repeat_failure_guard` —— 同一工具 + 同一组参数**连续**失败 2 次后，
  第 3 次不执行，直接返回一段说明「这条路堵死了、换个办法」的文本。在 `build_agent_toolset` 里
  **逐个工具**包上（循环是 agent 的行为模式，不是 `click` 的属性；换成 `navigate_page` 一样会发生）。
- **否掉了什么，为什么**：
  ① **否掉「往 prompt 里写『不要重复失败的动作』」**——它的 think 里已经写着
  "Let me take a fresh snapshot to get current uids" 然后照样点回旧 uid。
  **不是提示不到位，是它看不见自己的循环模式**。而「这次调用跟上次是不是同一个」是纯比对，
  不需要判断力——models judge / code decides 的教科书情形。
  ② **否掉「调大 MAX_STEPS」**——预算不够和循环是两回事。前两次真机的循环（筛选器打转、翻页打转）
  已经证明过：加预算只是让它换个地方犯同一个错。
  ③ **否掉「按『重复调用』拦，不看成败」**——同一轮里 `take_snapshot({})` 也被调了 30 次、参数
  完全相同，但它每次都成功。按重复拦会挖掉 agent 的眼睛，比原来的循环严重得多。
  所以判据必须是**连续失败**，且**成功即清零**。
- **一处刻意收窄**：失败判定只认返回文本**开头**的 `Error`，不做全文包含匹配。
  页面正文里出现 "Error" 是常事（404 页、报错文案），全文匹配会在一个完全正常的页面上
  把 `take_snapshot` 判成连续失败并锁死。
- **代价 / 已知不足**：拦截只保证不再空转，**不保证它能换出一条对的路**。
  uid 为什么点不动（腾讯校招的筛选器是自定义控件 / 被遮挡 / 在折叠面板里）没有查清，
  m1 在这个站上到底能不能用筛选器仍是开放问题。

## 整轮 run 的状态不能比它最差的那一步更乐观

- **日期 / 版本**：2026-08-19，v2.27.0
- **背景**：同一份真机日志里 `step find_jobs partial {"truncated": true}` 紧跟着 `run_end done`。
  上一版（v2.26.0）修的是阶段这一层，`run_scope` 收尾仍写死 `done`。
- **选了什么**：`RunLogger` 记住这一轮出现过 `partial` 步骤，`run_scope` 据此收尾成 `partial`；
  SSE 的 `finish_workflow` 用同一个状态。
- **否掉了什么，为什么**：**否掉「只改 SSE、日志照旧」**——两边不一致的表现是
  「实时看着绿的、翻历史是黄的」，而这种不一致没有任何东西会报错。
- **连带确认**：`run_diagnostics._OK_END_STATUSES` 只认 done/successful/completed，
  所以 `partial` 会被诊断器如实标成异常——这是想要的，不用改它。
  前端 `App.tsx` 判 workflow 结束看的是 `event.step === 'done'` 而非 status，不受影响。
- **通则**：修「子层级不许谎报」时**顺着往上问一层**——父层级的状态是从哪来的？
  如果是写死的常量，这个修就只做了一半。

## 手册轻校验的判据②只检测「选项消失」，不检测「新增」

- **日期 / 版本**：2026-08-19，计划 A（分支 `m1-manual-foundation`）
- **背景**：spec §3.5 原本承诺"筛选项**增删**"双向检测，而实现是单向差集
  `missing = want - have`。最终评审判为 Important：spec 是权威，实现没达到它。
- **选了什么**：**不改代码，改 spec 的措辞**——如实描述判据②只检测消失。
- **否掉了什么，为什么**：**否掉「直接加反向差集」**。当前实现的 `have` 取自**整份快照的
  所有节点文本**（导航栏、岗位标题都在内），加 `extra = have - want` 会 **100% 命中**，
  校验永远失败 → 持久化形同虚设 → 每轮白付一次全量重探。
- **代价对比（裁决依据）**：漏检"新增选项"＝**少扫**一个新分桶的岗位，可恢复，且人在
  Checkpoint 1 看得到全部候选；强行双向＝每轮多烧 15 步。后者严重得多。
- **一处必须记的更正**：我最初给的理由是"a11y 快照里没有分组包裹节点，所以结构上做不到"，
  **这条是错的**。最终评审指出：本站的 tab 节点自带
  `description="应届毕业生 checkbox-group 实习生 checkbox-group …"`，**分组成员就写在父节点的
  description 属性里**，只是 `_NODE_RE` 把 description 丢了；另有按 role 过滤 checkbox/radio
  这一档（role 已经在正则里捕获）。**结论对但理由错，会让下一轮继承一个假的不可能性判断。**
- **留给计划 B（按优先级）**：① `_NODE_RE` 保留 `description`，从父节点直接读分组成员；
  ② 按 role 过滤把 `have` 限定到 checkbox/radio；③ 实在不行才退到"记选项个数"。

## 闭集枚举必须满足「过了校验就代表代码能执行」

- **日期 / 版本**：2026-08-19，计划 A
- **背景**：`row_split` 的闭集含 `container_per_row`，`from_dict` 接受它，但执行器一碰就
  `NotImplementedError`。
- **选了什么**：设计空间（`ROW_SPLITS`）与已实现集（`IMPLEMENTED_ROW_SPLITS`）分开，
  `from_dict` 按后者拒绝，错误信息写明"还没有对应的执行器"。
- **为什么不能留着**：让 LLM 填结构化字段时，prompt 几乎一定会把**枚举的全部取值**列给它挑
  ——挑中未实现的那个就是运行中途崩溃，而且**绕开了 spec §7「所有执行器都不匹配 → 诚实报
  搞不定」那个专门设计的出口**。另外它也是 `validate_manual` 唯一的契约破口：函数宣称返回
  `(bool, str)`，对一份 `container_per_row` 的存量手册却会抛异常。
- **连带**：为此修改了一条既有测试的断言（从"接受"改成"拒绝并说明原因"）。**这是设计变更，
  不是弱化断言**——两者的区别在于：前者改的是被测行为本身，后者是在同样的行为下降低要求。

## `job_url_online` 暂不返回 JD，留给计划 B 与 harvest 一起定形状

- **日期 / 版本**：2026-08-19，计划 A
- **背景**：spec §5.1 用"取 URL 和取 JD 是**同一次访问**"来论证"总是取 JD"这个决定便宜。
  而 `job_url_online` 拿到 URL 立刻关掉标签页，JD 一个字没读。最终评审列为
  "最值得在接线前定的接口问题"。
- **选了什么**：**不现在改签名**，只在 docstring 里写明这个缺口并指向 spec §5.1，
  列为计划 B 的第一个 task。
- **否掉了什么，为什么**：否掉"现在就把返回值改成 `(url, detail_snapshot)`"。理由：
  **它唯一的消费方（harvest）还没写**，现在定形状就是在没有消费方的情况下设计接口——
  正是 YAGNI 警告的事，而且大概率要返工。
- **代价**：若计划 B 动手时 harvest 已写了一半才改，要改两处而非一处。接受。
- **注意**：这条的代价是**真的**——按 spec 自己的估算，若计划 B 选择"每个岗位再导航一次"
  而不是改签名，run 时长直接翻倍（`候选数 × 8 秒` → ×16）。所以它必须是计划 B 的**第一个** task。

## m1 拆成三个节点，ReAct 只留在真正需要试探的两段

- **日期 / 版本**：2026-08-20，v2.29.0（计划 B）
- **背景**：m1 原本是**一个巨大的 ReAct 节点** `find_jobs`，里面混着三件性质完全不同的事：
  摸清站点结构（探索）、决定打哪几个桶（纯判断）、逐条读岗位判类别落袋（机械+判断）。
  三件事共享一个步数预算、一个上下文、一个完成判据——**一段跑飞就把整轮预算吃光**，
  前端也只能看到"find_jobs 卡住了"。
- **选了什么**：
  `ensure_ready → survey_structure(ReAct) → plan_buckets(非 ReAct) → scan_buckets(ReAct) → write_pending_jobs`
  抓取与分类交给代码（`harvest.py` / `classify.py`），agent 只管导航与桶策略。
- **为什么 `plan_buckets` 和 `classify_jobs` 不做成 ReAct**：它们不碰浏览器，
  输入是文本、输出是结构化结果，**没有「观察 → 行动」的循环可言**。
  做成普通 LLM 调用换来的是**可单测、可 eval**——而 ReAct 循环基本没法这么测。
- **成本论证**：一页 10 个岗位，每个要「点开→读 URL→读 JD→关掉」。
  交给 agent 就是 40 次工具调用、40 个 ReAct 轮次，而整轮预算只有 60 步。
  `harvest_current_page` 把这些压成 agent 的**一次**工具调用。
- **否掉了什么**：
  ①**否掉「拆成独立的勘察 agent + 选岗 agent」**——「哪些桶跟我相关」是**目标依赖**的判断，
  不是中性的站点知识；勾筛选器和读岗位在真实操作里是**交织**的。
  ②**否掉「不加节点、只加工具 + 改 prompt」**——没有阶段级的预算隔离和完成判据，
  前端也看不出卡在哪一步。

## 「取 URL」和「取 JD」必须是同一次访问

- **日期 / 版本**：2026-08-20，v2.29.0
- **背景**：目标站点的岗位卡片是 `window.open`，本来就必须点开详情页才能拿到 URL。
- **选了什么**：`job_url_online` 返回 `(url, detail_snapshot)`——既然已经在那一页上了，
  顺手读走快照近乎免费。
- **代价对比**：分成两次访问会让 run 时长**翻倍**（每个岗位 ≈8 秒 → ≈16 秒）。
  按 `候选数 × 8 秒` 估，一个 15 条的桶就是 2 分钟 vs 4 分钟。
- **连带**：`jd` 在 **harvest 边界**截断到 3000 字（不是在拼 prompt 时截）——
  截在后面的话 `pending_jobs.jd` 会存一堆带 uid 的原始标记，而且一页 15 条全文
  会撑爆 deepseek-chat 的 64k 上下文 → 整页丢弃 → found=0。

## `container_per_row` 执行器：用 url 子串识别岗位容器，不硬编码 role

- **日期 / 版本**：2026-08-20
- **背景**：bambulab 真机跑 `survey_structure` 诚实报"还差 row_split"——这个站每个
  岗位就是**一个 link 节点**（标题/地点/部门/JD 全拼在 accessible name 里），没有
  join.qq.com 那种平铺 StaticText + "必现且仅现一次的锚点文本"可用，`anchor_text`
  无从下手。`container_per_row` 当时在 `ROW_SPLITS` 里但没有执行器（见上一条决策），
  这是它第一次被真实站点撞上，补执行器的时机到了。
- **选了什么**：
  1. **复用 `row_anchor` 字段**表示"容器节点 url 属性必须包含的子串"（bambulab 是
     `/position/`），而不是新增一个字段。`anchor_text` 下它是"节点 name 精确匹配"，
     两种含义不同但都要求非空，`from_dict` 校验合并处理。
  2. **识别判据是"节点带 url 属性且 url 命中子串"**，不检查 `role == "link"`。
     bambulab 同一页 15 个 link，10 个岗位 + 5 个导航（"职位"/"产品官网"/
     "招聘官网首页"/"社会招聘"/"校招FAQ"），标题、role、缩进层级三者岗位和导航
     完全一样，唯独 url 不同——岗位详情页带 `/position/`，导航链接不带。
  3. `job_url_source=link_in_row` 配合这个 row_split 时，`job_url_offline` 直接按
     `row.anchor_uid` 取该节点自己的 url，不复用 `anchor_text` 那套"窗口内搜索"
     ——容器模式下行本身就是那个 link，没有"窗口"这个概念。
- **否掉了什么，为什么**：
  ①**否掉新增独立字段**（如 `row_container_url_contains`）——bambulab 是目前唯一的
  真实样本，只有一个字段"必须非空、含义由 row_split 决定"比"两个字段、一个永远
  留空"更省，且和 `anchor_text` 的先例一致（同一字段、不同 row_split 下含义不同）。
  ②**否掉硬编码 `role == "link"` 过滤**——虽然 bambulab 唯一的真实样本里容器碰巧
  都是 link，但判据本身（"带 url 属性 + url 命中子串"）已经天然只命中带 url 的
  节点，不需要额外限定 role；限定了反而是给一个只有一个数据点的假设强行加边界。
- **代价 / 已知不足**：如果将来某站的容器根本没有 url 属性（标题和链接分离到两个
  子节点），这条判据完全用不上——那是另一种几何，需要新的 row_split 执行器，
  不是往这里加分支。目前没有这样的真实站点，不提前设计。
- **连带**：`test_site_manual.py::TestAnchorTextRequiresAnAnchor` 里原来"container_per_row
  应该被 from_dict 拒绝"的测试（连同它的 docstring 已注明"实现后该删/改"）替换成
  "接受非空 row_anchor、拒绝空 row_anchor"；`test_executors_rows.py` 里同理替换
  `TestContainerPerRowIsNotImplementedYet`。fixture `bambulab_job_list.txt` 由脚本
  从真机快照 `logs/runs/m1_20260820_1437/survey_structure_snapshot.txt` 生成（剔除
  页面上一处已打码的电话号码行，其余原样保留——招聘列表页公开信息，扫描确认无 PII）。

## `link_in_row` 离线路径补 `jd`：直接用 `row.text`，不标来源、不加字段

- **日期 / 版本**：2026-08-20，commit `a6f5f32`
- **背景**：上一条决策补完 `container_per_row` 执行器后，bambulab 真机端到端跑通，
  但落库的 5 条岗位 `jd` 长度全是 0——`harvest.py` 的 `job_url_offline` 分支（拿不到
  详情页快照的站点）此前把 `jd` 硬编码成空串，是写 harvest 时记下的设计边界，但
  导致这一整类站点没有 JD，`layer1_classify_jobs.md`"职责里出现 xx 就归类"的规则
  无 jd 可读。
- **选了什么**：offline 分支下 `jd = row.text[:_JD_MAX_CHARS]`——容器模式下 `row.text`
  就是那个 link 节点的 accessible name，标题/地点/类型/JD 摘要全挤在一起；这段文本
  在 `layer1_agent.py` 里早就被映射成分类 prompt 的 `title` 用了，只是没被同时接到
  `jd` 上。复用已有的 `_JD_MAX_CHARS`（3000），不新开截断点。
- **否掉了什么，为什么**：**否掉给 jd 加"来源标记"或新增字段**（比如区分"详情页全文"
  vs "列表卡片摘要"）。三点理由：①分类 LLM 在这次修复之前就已经在读 `row.text` 的
  全部内容（被标成 `title`），这次修复不是给分类引入一个新的、更低质量的信息源，
  分类侧的实际输入内容修复前后完全一样，只是 `jd` 这个字段本身从空变成有内容；
  ②`jd` 字段从没承诺过是"详情页全文"——`new_tab_on_click` 那条路的 jd 也早就是
  `_JD_MAX_CHARS` 截断过的 a11y 摊平文本，不是网页原文；两条路径产出的都是"精度
  不同的摘要"，不是"全量 vs 缺失"的二元对立；③目前没有任何消费方（分类 prompt/
  Checkpoint 1 审批页/eval）需要按"jd 精度"分支处理，加字段/加标记是没有使用者
  的能力，属于过度设计。
- **代价 / 已知不足**：`anchor_text` 分支（非 container 模式）下 `row.text` 只是窗口
  内节点 name 的拼接，信息密度低于 container 模式；这次只验证了 container_per_row
  真实场景（bambulab），`anchor_text` + offline 组合暂无真实站点样本佐证质量是否
  够用，出现新站点时留意。
- **连带**：`tests/test_harvest.py` 新增 `TestHarvestPageOfflineJd` / 
  `TestHarvestPageOfflineJdTruncation`（4 例，真实 fixture `bambulab_job_list.txt` +
  一份合成超长快照测截断）；`new_tab_on_click` 分支未改动。

## 等详情页渲染完，用 `navigate_page` 重新导航，而不是自造"快照稳定"判据

- **日期 / 版本**：2026-08-21，v2.29.1
- **背景**：`job_url_online` 点开新标签页、`select_page` 之后立刻 `take_snapshot`，
  截到的是**导航外壳**（1514 字，岗位关键词 0 次），而 `jd` 非空、长度正常、
  条条不同（页脚嵌着各自的 URL），所有表面指标都正常。
- **否掉的方案（写完并测过才否的）**：「连截几张快照，直到内容不再变化」。
  它有完整 TDD——3 条测试、先看红、变异验证 2 条变红、全量绿。
  **真机 52 条只修好 5 条**：两张连续的**外壳**快照彼此相等，会被判成"已稳定"
  直接返回外壳。我的探针恰好撞上"外壳→正文"那一瞬（1514 → 3066），
  于是把**一次时序巧合当成了规律**。
- **也否掉了看快照里的 `busy` 标志位**：实测那张纯外壳快照 `busy=False`，
  而更早一批落库的外壳 `busy=True`——同一种失败在两次观察里给出相反的标志位。
- **选了什么**：切过去之后**对刚拿到的 URL 再 `navigate_page` 一次**，
  借这个工具自带的"等加载完"语义。实测 4/4：修前 1514–1519 字 / 关键词 0 次，
  修后 2858–3076 字 / 关键词 6–9 次，代价 +0.4 秒。
- **一般判据**：**能用一个语义明确的现成机制，就别自己造近似判据。**
  近似的边界得自己负责，而我漏了最常见的那条。
  判据类的东西要拿「**什么情况下它会误判**」来验，不是拿「它工作时对不对」来验。

## `jd` 存可读正文，转换点在 harvest 边界、截断之前

- **日期 / 版本**：2026-08-21，v2.29.2
- **背景**：`jd` 原本存 a11y 快照转储。两个消费方——Checkpoint 1 审批页、
  分类 prompt——**都吃不下它**：前者渲染出来是一屏 `uid=`，后者 3000 字的额度
  大半花在 `uid=` / 角色名 / `url=` 上。
- **选了什么**：`snapshot_to_text()` 在 `harvest_page` 里转换，**在 `_JD_MAX_CHARS`
  截断之前**。顺序反了的话，按标记算的 3000 字里转换完只剩一千出头。
  真机：3076 字快照 → 1007 字正文，关键词命中 9 次。
- **为什么不在渲染时转**：那样库里存的还是转储，分类 prompt 也还是吃标记；
  两个消费方都要各转一次，就是同一规则两份实现。
- **实现上的坑**：多行正文的 accessible name 里是**真实换行**（开引号在 `uid=`
  那一行，闭引号在两三行之后），所以必须对**全文** `finditer` 而不是逐行匹配。
  逐行版单测全绿、真机只提取出 303 字——**我编的 fixture 把整段正文写在了一行里，
  形状错了，测试就只是在验证我的误解。**

## 清一个站的候选池必须**真删行**，不能标记成拒绝

- **日期 / 版本**：2026-08-21，v2.29.5
- **背景**：多站点候选池此前只有 `scripts/reset_multisite.py` 一条清理路径，
  而它是全站清空，会连别的站和 `pending_applications`（真实投递记录）一起删。
- **选了什么**：`delete_pending_jobs_for_site`——删 `pending` + `rejected` 的行，
  **已批准的一行不动**（`pending_applications.source_job_id` 回指它们，
  删掉就断了"这个申请从哪个岗位来"）。
- **为什么不能用"标记成拒绝"代替删除**：`known_urls` 取的是 `pending_jobs` 的
  **全部** URL、**不看状态**。标记成拒绝的岗位会被下一次 m1 永久跳过——
  看起来清干净了，实际是把它们永久排除了。**「软删除」在有去重集的地方
  不等于删除。**
- **UI 两步确认**：删除不可逆，按钮又在站点标题旁边，误点的代价是整个站的
  候选池没了、还得重跑一次 m1。第一下只切状态、绝不发请求（有测试守着）。
