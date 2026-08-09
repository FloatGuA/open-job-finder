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
