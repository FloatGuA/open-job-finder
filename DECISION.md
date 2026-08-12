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
