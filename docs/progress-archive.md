# OpenJobFinder — Progress Archive

> `PROGRESS.md`「已完成」的历史条目，**v2.12.x 及以前（2026-07-30 及更早）**。
> 2026-08-05 从 PROGRESS.md 迁出，内容原样未改。
> 2026-08-22 又迁入一组**非「已完成」**的历史条目（文末的 factory 时代 ChatAgent 遗留 Warnings）。
> 这里的条目可能引用已删除的文档（`AGENTS.md` / `COLLAB.md` / `spec.md` 等 factory 流程残留）——归档如实保留当时的表述。

---

- 前端可编辑 system/task prompt 模板（覆盖层 + 恢复默认 + 改动提醒 + 占位符护栏）（2026-07-29，v2.12.2.1，628 passed，build 绿）
  - **需求**：注入是"往模板尾部加"，用户还想直接**改模板本体**。加显示/编辑/恢复默认/改动提醒。
  - **覆盖层机制（不动 git 资产、可恢复）**：编辑存 `code/data/prompts_override/{name}.md`（data/ 已 gitignore）；`PromptManager.load()` 改为**覆盖层优先、否则回落默认 `prompts/`**；恢复默认=删覆盖文件；改动提醒=覆盖文件存在即标「已修改」。
  - **⚠️ 占位符护栏**：`save_override` 校验**占位符集必须与默认一致**（不许删不许加未知）——否则 render 时未替换的 `{{x}}` 会抛错让 W1/W2 挂。校验不过 → 400 + 前端提示，不写入。
  - **改动**：`prompt_manager.py`（override_dir + `EDITABLE_PROMPTS` + get_default/is_modified/extract_placeholders/save_override/reset_override）/ `server.py`（GET `/api/prompts`、POST `/api/prompts/{name}`、POST `.../reset`）/ 前端 `api/index.ts`（PromptTemplate 类型 + 3 方法）+ `Settings.tsx` 新增「Prompt」tab（4 个可编辑 textarea + 恢复默认 + 已修改 badge + 占位符提示）。测试 +6（`test_prompt_override.py`）。
  - **真机层面验证注入生效**：刻意强注入"一律判 interview_invite"→ 15 条金标 14 条被带偏，证明注入进 prompt 且被 LLM 遵循。
  - 与注入独立叠加：render = 用户改过的模板 + 注入块，两者都保留。

- eval 阶段2 地基：W1 评分数据采集（scored_jobs 表，投+跳两侧）（2026-07-29，622 passed；后端无 build，版本未升）
  - **背景**：阶段2（score_job eval）在现有数据上跑不了——applications 无 JD、跳过样本被删、score 多为 0。要评当前评分得能重打分（需 JD）+ 两侧样本（校准阈值）。
  - **方案（用户拍板：两侧都采、独立表）**：`card_pipeline` 评分成功后、阈值判断前采集一条 → **投递的和被跳过的都记**。独立 `scored_jobs` 表（不塞 applications：语义是"投过的"、很多查询依赖；不塞 run 日志：JD 是 PII 会扩大泄露面）。字段 job_id/title/company/jd_text/score/dimensions/reason/provider_used/threshold/above_threshold/created_at，滚动上限 2000 防涨。
  - **改动**：`tracker` 加表+迁移+`record_scored_job`(唯一 SQL，滚动修剪)+`get_scored_jobs`(dimensions 解析回 dict) / `tools/db/w1/record_scored_job.py`(薄壳调 tracker，**按正确分层，不自持 SQL**) + 注册 / `card_pipeline` 接一行(非致命，registry.call 不抛) / 测试 +4（tracker 往返/滚动上限/两侧都采）。真实库迁移已验证安全（表建起、为空）。
  - **今天没数据可评**：地基。得跑真实 W1（`score_threshold>0`）攒一阵，再写阶段2 的 score eval harness + 网页标注器（标"这岗想不想要"）。

- LLM eval 闭环首跑 + 意图 prompt 调优（2026-07-29，v2.12.1.1，618 passed）
  - **闭环首次跑通**（用户标注 58/61 金标后）：harness 出总准确率 + 混淆矩阵；诊断脚本 `diagnose_needs_reply.py` 补上**needs_reply 层面**评估（更贴近生产决策）。
  - **核心发现**：**intent 准确率 ≠ needs_reply 准确率**——intent 53.4% 但 needs_reply 89.7%。因为 14 条 `general_notice→resume_request` 误判 100% 有 `already_sent=True`，被 `resume_request+简历已发→不回` 派生逻辑救回、**不造成误回**。intent 标签难看多是观测性问题，不是决策问题。
  - **用户痛点定位**：「发完简历后误回」在新架构下只剩 **4 条**，全是 `general_notice→general_inquiry`（客套被读成询问）。
  - **prompt 调优实验**（加「按 HR 最近消息判、别因历史简历判 resume_request」+ 收紧 notice/inquiry）：intent 准确率 53.4%→**65.5%**（resume 过判 14→7 砍半），但 **needs_reply 87.9%（噪声内持平）、4 条误回纹丝未动**——qwen3:8b 分不清那 4 条客套/询问，prompt 拧不动（小模型细微语义上限）。**结论：改动改的是标签好看度，非痛点解药。**
  - **重新定性 + 决策（用户选 a）**：这 4 条误回**是待审批草稿、不是错发给 HR**（回复须批准才发）——审批门把「误回」降级为「草稿噪声」，4/58≈7% 手动驳即可，危害低。**接受现状 + 留 prompt 改动**（intent 标签提升对观测有用，needs_reply 在噪声内）。
  - **遗留认知**：金标 58 条、稀有类样本少（interview_invite 3/resume_request 2）指标抖动大——想继续调需扩样本；痛点若要再压，杠杆是换 powerful 模型跑意图（未做）。产物 `diagnose_needs_reply.py` 保留可复用。

- 意图 taxonomy 重构：needs_reply 折叠进 intent（general 拆 inquiry/notice；LLM 不再自由输出 needs_reply）（2026-07-29，v2.12.1.1，618 passed，build 绿）
  - **动机**：做意图 eval 时发现设计瑕疵——`intent` 和 `needs_reply` 是 LLM 输出的**两个独立字段**，会打架（如 rejection 却 needs_reply=true）且要单独标/评。审视联动发现：**除 general 外，其余 5 类的 needs_reply 几乎由 intent 唯一决定**。用户提议把 needs_reply 折叠进 intent（general 拆成"需回"/"不回"两类）。
  - **新设计（models judge / code decides）**：LLM 只判**语义 intent**（7 类）；`needs_reply` 由 code 查表得出，不再问 LLM。
    - 枚举 6→7：`general` 拆成 `general_inquiry`（HR 询问/需回应）+ `general_notice`（客套/通知/无需回应）。
    - 查表 `default_needs_reply`：interview_invite/offer/general_inquiry → 回；rejection/general_notice/unknown/resume_request → 不回。
    - `resume_request` 的 needs_reply **完全由运行时检测派生**（不看查表默认）：简历发得出/已发→不额外回；仅检测漏判（简历发不出）时破例起草文字回复兜底。取代旧「抑制闸」（语义等价、方向更顺）。
    - rejection 默认**不回**（用户确认：被拒静默、不打扰）。
  - **改动**：`prompts/analyze_intent.md`（枚举+去 needs_reply 字段）/ `tools/llm/analyze_intent.py`（`_VALID_INTENTS` 7 类 + `_NEEDS_REPLY_INTENTS` 查表 + `_OUTPUT_SCHEMA` 去 needs_reply）/ `pipeline/w2/steps/analyze.py`（resume_request 派生 needs_reply）/ 前端 `intentMeta.ts`+`interpret.ts`（补 2 新标签，保留旧 general 兼容存量）/ eval 三件套枚举 + 标注器重生成。测试 +1（查表守门）、改 3（旧 general→inquiry、resume mock needs_reply）。
  - **存量兼容**：DB 历史 `general`（177 条）不迁移——新代码不再写它，filter/前端 fallback 都容得下，与已有 greeting/info_request 等历史值共存（同 [[w1-w2-status-revival]] 思路）。
  - **联动 eval**：golden label 空间同步为新 7 类；标注器选项已换（general→一般询问·需回 / 一般通知·不回）。**待用户标注**。

- LLM eval 阶段1：意图分类金标 + eval harness（2026-07-29，617 passed；未升版本——纯 dev 工具、无前端 build）
  - **动机**：刚加的 prompt 注入无 eval 就是盲改。先调研 LLM eval 方法论（金标集从真实生产来 / 精度≠可靠性两维 / LLM-as-judge 须先对齐人标 / 回归当质量闸），得出关键洞察——**本项目 3 个 LLM 判断点可评估性完全不同**：`analyze_intent`（6 类分类，最客观，混淆矩阵）＞`score_job`（评"投/跳"决策而非分数）＞`generate_reply`（开放文本，须 rubric/judge，但审批动作是免费人标）。**从最客观、真实数据现成的 analyze_intent 起步。**
  - **数据现成**：jobs.db 有 365 个含真实 HR 消息的会话（general 177/resume_request 92/interview_invite 41/rejection 40/unknown 14/offer 1）。
  - **产物（`code/scripts/eval/`，代码进 git）**：
    - `export_intent_golden.py`：按已存 intent 分层抽样（稀有/高代价类过采）→ 导出待标注 JSONL。已跑，61 条。
    - `run_intent_eval.py`：忠实复刻生产（只传 conv_id/messages/company，**不传 job_title**）跑 `analyze_hr_intent` → 总准确率 + 逐类 P/R + 混淆矩阵 + **高代价错误专项**（漏判 resume_request=简历发不出 / 误判 rejection=放弃活线索 / 漏判 interview_invite）。支持 `--baseline` 关注入做 A/B。报告渲染已用合成数据验证正确。
    - `build_annotator.py`：读金标 → 生成本地网页标注器 `data/eval/annotate_intents.html`（聊天气泡渲染 HR/我/系统 + 点按钮选意图 + localStorage 暂存 + 导出回 JSONL）——解决"手改 JSONL 太累"。⚠️ 含 PII，**本地打开、不用 Artifact/不上传**。
  - **⚠️ PII 隔离**：金标数据落 `code/data/eval/`（整目录已 gitignore）——含真实公司/HR/消息，**只有 eval 代码进 git，数据永不进 git**。
  - **协作断点（待用户做）**：金标 ground truth 必须**人工标注**——`model_intent` 仅是模型历史判断（拿它当金标=模型自评，无意义）。用户需打开 `data/eval/intent_golden.jsonl` 逐行填 `human_intent`（六选一），再跑 harness 出真实精度 + 给注入做 A/B。

- Prompt 注入可配置化 + 注入分级（系统层 global + 任务层 per-task；删 extra_notes）（2026-07-29，v2.12.0.1，617 passed，build 绿）
  - **背景/动机**：评分/意图/回复三条工作链的 prompt 都是 `PromptManager` 加载的固定模板，用户无法在不改代码的前提下往里注入自定义指令（「我是应届生别高估经验」「远程岗位加分」「回复语气更主动」等）。
  - **调研先行**：①全项目 LLM 调用点摸清——核心 3 个走 PromptManager 的工作 tool（`score_job`/`analyze_hr_intent`/`generate_reply`）+ 休眠的简历生成 prompt（内联字符串，不纳入本次）+ selfcheck 探针（无关）；②研 Agent prompt 通行范式——分层架构（稳定→易变：system 策略/任务模板/**用户偏好注入**/运行时数据）、Claude Code 的 `heron_brook`/CLAUDE.md「服务端可控注入槽」模式、小而专优于一坨大 blob、可信指令 vs 不可信上下文要区分。
  - **「分级」= 作用域分级（与用户对齐后定）**：`global` 系统层（注入进全部 3 条链）+ 3 个任务层（`score_job`/`analyze_intent`/`generate_reply` 各自只进同名 prompt），渲染叠加。否掉「强度分级 hard/soft」（LLM 已能从措辞辨强弱，加 level 是过度工程）与「运行时粒度 每职位/每 HR」（配置面爆炸、无真实需求），simplicity first。
  - **extra_notes 删除（非升格）**：旧 `extra_notes` 实质是「只喂评分的单一注入口」，在 global+per-task 齐全后能表达的都被覆盖 → 冗余，删。当前值为空，零迁移。落点：`profile.yaml` 删字段加 `prompt_injection` 块 / `Profile` dataclass 删 `extra_notes` 加 `prompt_injection: dict` / `score_job._profile_summary` 删 `Notes:` / `/api/profile` 读写 + Settings 表单 → 4 段注入框。
  - **渲染接法（改动集中在 PromptManager）**：构造多接 `injection` dict（来自 `profile.prompt_injection`），`render()` 出口统一追加一个划界的「## 求职者本人的补充指令（可信，优先遵循；区别于 HR 消息等外部输入）」块。**关键**：全局注入必须在 render 层追加、不能塞进 `system.md`——因为 `generate_reply` 不吃 system prompt，只有 render 出口能一处覆盖含 reply 在内的全部 3 条链。白名单 `_TASK_INJECTION_NAMES` 杜绝无关 profile 键泄进 prompt。两 runner（w1/w2）+ reanalyze 脚本传 `injection=profile.prompt_injection`；W3 不渲染 prompt 故不动。
  - **前端**：Settings「求职偏好」tab 把单个「评分备注」textarea 换成 4 段注入 textarea（global/score_job/analyze_intent/generate_reply），走同一 saveProfile；api `Profile` 类型 extra_notes → `prompt_injection`。CJK 用 scratchpad Python 脚本转字面量 `\uXXXX`（本环境 Edit 会解码 \uXXXX、raw CJK 又不自动转义），产物已 utf-8 校验 4 标签正确。
  - **测试**：617 passed（新增 `tests/test_prompt_injection.py` 5 例：无注入不变 / global 覆盖全部含 reply / task 层不外溢 / global+task 叠加 / 无关键不泄漏）。`npm run build` 绿（tsc 无悬空引用），`N` 自增到 2.12.0.1。
  - **端到端串联验证**：真实 `profile.yaml` → ProfileLoader → PromptManager → `render('score_job')` 尾部正确带注入块（PYTHONUTF8=1 验证）。**待真机 W1/W2 复核** LLM 是否遵循注入。

- HR 索要简历场景两面：意图抑制冗余回复（B）+ 手动发简历兜底·装填待发模型（A）（2026-07-29，v2.11.0.4，612 passed，build 绿，**前端 + W3 真机验证全部通过**，已 commit 182157e + push）
  - **待发送合并（v2.11.0.4，真机验证 OK）**：装填的待发简历并入「待发送」tab（`matchesTabFilter` 的 SEND_FILTER = `isQueuedForSend || resume_status==='queued'`），列表行加绿色「待发简历」徽章区分，顶部黄条计数/文案涵盖简历。实时进出 tab（装填/取消即时）。用户已真机验证：装填→待发送 tab 显示带徽章→取消即时消失。**后端重启坑坐实**：之前"点了没反应"根因＝运行中的旧 server 用 `python -m uvicorn ...`（**无 `--reload`**，7/28 启动）没加载新路由 → `/queue-resume` 404 静默回滚；已停旧进程、带 `--reload` 重启，`queue-resume` 探针返回我方 handler 的 404 证明路由生效。
  - **背景**：真机发现 HR 索要简历这一场景有两个相反缺口——① W2 检测漏判（`detect_resume_request` 认不出某些措辞）→ 简历没发出去；② 检测命中并发了简历后，`AnalyzeStep` 仍起草一条**多余**的待审批文字回复。B 补冗余、A 补漏发，按 B→A 顺序做。
  - **B — 意图抑制（确定性，code decides）**：`pipeline/w2/steps/analyze.py` 在拿到 LLM intent/needs_reply 后、生成回复前加抑制闸——`needs_reply and intent=="resume_request" and (needs_resume or already_sent) → needs_reply=False`。语义：**简历本身就是对「索要简历」的完整回应**，本轮将发/已发时再起草文字回复是待审批噪声，覆盖 LLM 的 `needs_reply=True`。**守门**：`(needs_resume OR already_sent)` 为假时（检测没找到简历可发）**不抑制**、仍起草兜底——正是检测漏判情形，与 A 衔接。抑制在 `generate_reply` 前短路；`reply_status=None` 保留用户动作。测试 +2。
  - **A — 手动发简历兜底（装填→待发→可取消→W3 发送）**：⚠️ 用户纠正了我最初的「点了立即发、不可撤销」设计——应与文字回复对称：**装填（改DB）→ 待发（可取消）→ W3 发送**，可回退（碰 HR 的动作集中在 W3 一步）。最终形态：
    - **DB**：`hr_conversations` 加 `resume_status`（null|queued）列 + 迁移；tracker 唯一写 `set_resume_status(conv_id, status)`（queue/cancel/发后清 三态都走它，NULL 是正确中性态）+ `get_queued_resumes`。「已发」仍由 stage=resume_sent + detect already_sent 表达，不重复。
    - **装填/取消端点**：`POST /conversations/{id}/queue-resume`（写 queued，**只碰DB不碰浏览器→可取消**）+ `/cancel-resume`（写 null）。取代之前的立即发端点。
    - **W3 发送**：`W3Pipeline` 除发已批准回复，再拉 `get_queued_resumes` 逐个 `SendResumePipeline`（新 `pipeline/w3/send_resume_pipeline.py`：locate 直开优先→`detect already_sent` 幂等跳过→复用 W2 `ResumeStep`（card→toolbar）→清 queued + 推进 stage=resume_sent）。**无新鲜度闸**（简历不会过时）。`w3_runner` 注册 resume/detect/upsert/clear/get_queued 工具。触发＝手动跑 W3（与批准回复一致）。
    - **删除**：之前的立即执行 `send_resume_runner.py` + 队列 `resume` 类型 + `_run_send_resume_workflow` 全部回退（改由 W3 承担）。
    - **前端**：Chat.tsx 会话头部——`resume_status==='queued'` 时显示「待发简历」标签 +「✕ 取消发简历」按钮，否则「📎 发简历」（装填）。**无 workflowRunning 闸、无不可逆确认**（DB 操作可取消，安全）。`API.queueResume/cancelResume`；序列化加 `resume_status`。interpret.ts +4 事件标签。
  - **职责边界**：W2 `ResumeStep` 不动（检测命中的自动发路径）；A 是人工兜底，装填后由 W3 发，两者复用同一组发送 tool。W3 文字回复流程未动。
  - **协作反馈固化**：用户指出我"确认需求前就动手"（A 确认了"触发源"却漏确认"立即 vs 待发"这一维度）→ 记项目记忆 [[confirm-before-acting]]，并（待用户确认措辞后）加进全局 `~/.claude/CLAUDE.md` 第 15 条。
  - **测试**：612 passed（B +2 / W3 resume pipeline +5 / tracker resume 队列 +3）；`npm run build` 绿。v2.11.0.3。
  - **CJK 处理坑复现**：Edit 直接写 `\uXXXX` 被解码回中文；本环境 raw CJK 保存后**未**自动转义（磁盘实测裸 CJK 字节）→ 用 scratchpad Python 脚本把 raw CJK/占位符替换为真 `\uXXXX` ASCII 再 build + 产物 utf-8 校验。旧记忆「自动转义生效」不可靠。

- W2 待审批列表实时移除（2026-07-28，v2.10.2.3，纯前端 Chat.tsx，build 绿）
  - **根因（纯前端，后端无缺陷）**：`Chat.tsx`「待审批」tab 的 reply_status 过滤只在 `loadConversations` 拉取那一刻做一次、存进 `conversations` state；批准/驳回/改写走乐观更新**就地改 `reply_status`、不从数组移除**；而 `displayed` 渲染派生只做 messages>0 + 搜索过滤、**不按 reply_status 重过滤**；Chat 又不轮询（只在挂载/切 tab 重拉）→ 操作后那条状态虽变但**仍显示在待审批列表**，直到切 tab 才消失。对比 `handleDismissAllPending`/`handleReject`/`handleDismissWechat` 都显式 filter 移除，单条批准/驳回/改写漏了。
  - **修（用户选方案 B：渲染时按当前 tab 实时过滤）**：抽模块级 `matchesTabFilter(conv, activeStage)` 作为 tab 归属的**唯一判定**（sentinel 按 reply_status/wechat_pending，真实 stage 按 conv.stage，全部→true）；`loadConversations` 的 fetch 过滤 + `displayed` 渲染派生**都调它**（消除「拉取时过滤 vs 就地改状态」双源，本质是同一契约两处实现的老坑）。渲染时实时过滤后，任何状态变化（批准/驳回/改写、以及待发送 tab 的取消）立即从不再匹配的 tab 掉出。`selected` 取自 `conversations`（非 `displayed`），故操作后该条虽移出列表但详情面板仍显示，可看确认。
  - **测试**：`npm run build` 绿（tsc 无错）；后端未动。**待真机点一次验证**批准/驳回后即时消失。

- W3 发送失败根因（聊天输入框选择器漂移）+ 会话头部显示在招岗位名 + 版本留痕规则（2026-07-28，v2.10.1.2，602 passed，build 绿）
  - **W3 发送失败诊断（用户报「有发送错误、确实没发出、但我们应该存了 job_id」）**：先用 DB 坐实——唯一那条 approved 回复的会话 `job_id`+`boss_conv_id` 都在、直开可用，且其消息末条是 **HR 的简历请求卡片**（新鲜度闸会通过），reply dict 也如实把两个 id 传给 send_pipeline。**所以「没存 job_id」被排除**，失败在运行期。**根因＝聊天输入框选择器漂移**：`navigate_to_conversation` 的「已打开」探针用新 id **`#boss-chat-editor-input`**，但 `send_chat_message` 与 `search_locate_conversation` 仍硬编码旧 id **`#chat-input`**。Boss 改 id 后 → 定位探针命中（located=True，看着「定位成功」），但 send 的 `querySelector('#chat-input')` 取到 null → `if(!el)return` **什么都没输入** → "text not set" → submit 失败 → **没发出去**，与现象吻合。
  - **修复（收敛，根治漂移）**：把输入框选择器收敛到 `tools/browser/helpers.py` 一处——`CHAT_INPUT_SELECTORS`（`_ele_any` 用）+ `CHAT_INPUT_QUERY_JS`（run_js 用，`||` 有序回退保证特定 id 优先于泛型 contenteditable，覆盖 `#chat-input`+`#boss-chat-editor-input`+`.chat-input`+`.chat-editor`）。三处消费者（send / search_locate 探针 / navigate 直开探针）全部改用共享常量，永不再分叉。新增 `test_chat_input_selector_convergence`（断言解析器含两 id + 三文件不得再内联 `querySelector('#chat-input')`）。**待真机 W3 复核**：确认 Boss 当前输入框真实 id + 发送真的落地（本修对两种 id 都安全，只扩不缩）。
  - **会话 navigator 显示在招岗位名**：查明岗位名**没存在 hr_conversations**（`hr_title` 是 HR 的职务如「招聘专员/HRBP」不是岗位），在招岗位名在 **`applications.title`**，按 job_id 硬关联（conv_id==job_id）。后端 `/api/conversations` 用同一次 `tracker.get(job_id)` 一并取出 url+title（零额外查询），`_serialize_conversation` 加 `job_title` 字段；前端 Chat.tsx 会话头部（公司·HR·职务下方）加一行「在招岗位：…」。W1 投过的岗位才有；HR 主动发起的会话可能为空。
  - **版本↔摘要↔提交留痕规则入 CLAUDE.md**：用户问「每次 commit 版本号时写改动摘要的规则加了吗」——原来没有显式规则（最接近开发规则#4）。补进「版本管理」段：升 X/Y/Z 的会话收尾必须写带版本号的 PROGRESS「已完成」摘要 + commit 标题带版本号，三者可互相追溯；N 构建号不单独要求摘要。
  - **测试**：602 passed（+2 convergence）；`npm run build` 绿，v2.10.1.2。

- W2 定位失败诊断 + 前端 job_id 显示与跳转按钮（2026-07-28，v2.10.0.1，600 passed，build 绿）
  - **诊断（用户问「应该 job_id 直开怎么还报定位错误」）**：先否定「沉底被 Boss 清理」——`filter_conversations` 只遍历本轮实时扫描（`current_convs`，来自 getGeekFriendList），被清理的会话根本不在扫描里、不会进循环、不可能报定位错误。**真因**：`navigate_to_conversation` 的直开（Treatment D）**不是无条件**的，须 `job_id AND boss_conv_id(≠'62001')` 同时具备，否则回退到按 hr_name+company 的慢滚动搜索（2×60 步后放弃 → "conversation not found"）。这俩 id **只来自 getGeekFriendList 的 XHR 抓包**：①整轮扫描退化到 DOM 模式（XHR 钩子没抓到）→ `encryptJobId=""`、`encryptBossId=d-c='62001'` → **每条**都跳过直开走慢搜索 → 大量失败；②单条会话本身缺 encryptJobId。库存 `812/1041 (78%)` 双 id 齐全。**且此前完全不可观测**（scan 没记 source、navigate 没记 method）。XHR 抓包稳定性（真正根子）按用户定本次不挖。
  - **① W2 定位失败加截图**：W2 注册 `CaptureScreenshot`（复用 W1 通用工具）；`ConversationPipeline` 在 `nav.status==FAILED` 时截图（label=`{run_id}_{conv_id}`）+ 发 visible `conv_navigate_failed`（带 screenshot/method/error），复用 `/api/apply-failure/{name}` 服务 + 前端「查看定位失败截图」按钮。对齐 W1 apply 失败截图做法。
  - **② 失败原因可观测**：`W2NavigateStep` 日志加 `method`（direct_url / js_click 回退）；`scan_step` 记 `source`（api/dom），DOM 退化时把 scan_list 标 degraded——一眼看出「直开被关掉、退回慢搜索」。
  - **③ 前端 W1/W2/W3 显示 job_id + 跳转岗位**：W2Navigate / W3 locate 的 scope 补 `job_id`（每实例至少一条事件带上，不改 conv_id 分组）；`WorkflowTrack.buildTree` 把 `scope.job_id` 收进 `InstanceNode.jobId`；`OpenJobButton` 从 W1-only 扩到 W1/W2/W3（构造 `https://www.zhipin.com/job_detail/{job_id}.html`，soft-key sha256 会话无 job_id 不显示），并在按钮旁显示 `job_id`。interpret 加 `conv_navigate_failed` 文案。
  - **测试**：新 `test_conversation_pipeline_nav_fail.py`（nav 失败→截图+visible 事件+中止，下游 Read 不得运行）。**600 passed**，`npm run build` 绿，v2.10.0.1。
  - **待办**：真机 W2 复核——①看 scan_list 的 source（若 dom→XHR 抓包才是要修的根子）②定位失败截图能定位真因（沉底 vs 抓包失败）③前端三流程 job_id 与跳转按钮显示正确。

- W3 成熟度 #3：verify 送达判据改「精确匹配 + 前后气泡数增量」，根治历史假阳性（2026-07-28，v2.9.6.2，599 passed，build 绿）
  - **背景/危害**：旧 verify 用 `probe=_norm(text)[:16]` + `any(所有 me 气泡含前缀)` —— 对整段历史做**存在性 substring 匹配**，不区分是不是刚发的那条。回复模板化/开头雷同时，历史里存在一条同开头我方消息，本次即便 `send_chat_message` 静默失败，重扫也撞旧气泡 → 判送达 → `mark_reply_sent`（置 'sent' 保护态 + **清空 reply_text**）→ **真人 HR 没收到、草稿被销毁、终态不再重试**。恰违背 W3「验证到送达才标已发」的立身之本（记忆里的 `duration_ms:1` 老坑）。
  - **修复（确定性纯函数，不取巧）**：新增模块级纯函数 `_reply_landed(pre_messages, post_messages, sent_text)`——数「与 sent **归一化后完全相等**的 me 气泡」在发送前/后各几条，`后 > 前`才算送达。复用发送前新鲜度闸那次 `read_messages`（`rd0`）作**零成本基线**（`pre_msgs`）。Verify 段把 substring `any` 换成它，重试/落库/mark 逻辑不变。
  - **同时盖住两个边界**：①**HR 在验证窗内插话**（末条变 HR）——我方新气泡仍使计数 +1 → 仍判送达（避免「末条==sent」的假阴性→重发）；②**发送静默失败 + 历史有同文旧气泡**——计数不增 → 判未送达、保草稿（避免假阳性丢回复）。位置判据无需引入，增量已编码「新增了一条完全相同的文本」。
  - **架构决策**：**不新建 Step、不新建 tool**。W3 的 `SendReplyPipeline` 是「每条回复一条流水线」+ inline 四 phase（Locate/Freshness/Send/Verify），不用独立 Step 类；Verify 早是 phase，原地改即可（起 VerifyStep = 造假 Step，违铁律）。三个副作用（`read_messages`/`write_hr_messages`/`mark_reply_sent`）已是现成 tool 复用；新判据是纯计算 → 模块级纯函数（同 `_norm`/`_last_nonsystem_sender` 约定）。
  - **测试**：`test_w3_send_pipeline` +2（边界 B 发送失败+同文旧气泡→未送达 / 边界 A HR 插话→仍送达）；现有 verify 两例前后序列读法兼容不变。**599 passed**，build 绿，v2.9.6.2。
  - **待办**：下次真机 W3 复核——真机重扫的消息顺序/文本归一化后与输入一致、增量判据不误伤正常送达。

- W3 成熟度 #2/#4：get_approved_replies 收敛+带 job_id + 定位直开优先 + summary 回传（2026-07-28，v2.9.5.2，597 passed，build 绿）
  - **#2-a 收敛 tool + 带出 id**：`tools/db/w2/get_approved_replies.py` 原**自持一份 SQL**（`SELECT conv_id,hr_name,company,reply_text,boss_conv_id`，**无 job_id**，违反「tools/db 薄壳、不自持 SQL」铁律）；`tracker.get_approved_replies()`（`SELECT *`，含全字段）反而只被测试用。改 tool 为薄壳调 tracker（SQL 只留一处），序列化**新增 `job_id`、`boss_conv_id`**。
  - **#2-b W3 定位链升级「直开优先，搜索兜底」**：`send_pipeline` Locate 步——拿到 job_id+boss_conv_id（且 boss≠'62001'）→ 先 `navigate_to_conversation`（Treatment D 直开 `chat?id=&jobId=`，O(1)，其自带 DOM 滚动回退）；`nav.ok` 即 located。未拿到 id 或 navigate 失败 → 回退 `search_locate_conversation`（搜索框，触达沉底会话）。`w3_runner` 注册 `NavigateToConversation`。下游新鲜度闸 + verify 重扫双护栏兜住「开错/没开」的弱情况，故接受 navigate 的 ok 契约安全。三振出局（record_locate_attempt）不动。前端 `WorkflowTrack` W3 locate 骨架加 navigate_to_conversation。
  - **#4 W3 summary 回传**：`workflow_orchestration._run_reply_workflow` 原返回 `("reply 工作流完成", {})` 丢弃 run_w3 的 summary（approved/located/replies_sent/failed/stopped）→ schedule_log reply 行 summary 恒空。改为 `summary = run_w3(...)` 并返回 `(msg, summary if dict else {})`，与 w1/w2 对称。
  - **测试**：新 `test_get_approved_replies_tool.py`（2 例：带 job_id/boss_conv_id + 只取 approved/revision）；`test_w3_send_pipeline` +2（有 id 走 navigate 不碰 search / navigate 失败回退 search）；`test_workflow_orchestration` +1（reply summary 传导）。**597 passed**，`npm run build` 绿，v2.9.5.2。
  - **待办**：下次真机 W3 复核——①直开在真机命中（id 来自 getGeekFriendList）②直开失败真能回退搜索框；余 #3 verify 探针假阳性未修。

- 审查整改一批：队列锁泄漏 + tool 失败当成功 + W1 抓卡误判 + 依赖 + CLI 退役 + W2 计数（2026-07-28，v2.9.4.1，592 passed，build 绿）
  - **起因**：一轮代码审查列出 Must/Should/Nice 分级问题，逐条核对源码后确认（无一是把有意设计误当缺陷）。本次做 5 条 Must + 1 条 Should；W3 简历 marker（Should）与 PDF 方案按用户定只记待办。
  - **#1 队列运行锁可能永久卡住**：`run_item` 先设 `emitter.current_workflow`（is_busy 信号），但 `w1_runner`/`w2_runner` 在 `start_workflow` 前加载 profile，失败时静默 `return {"error":...}`——不抛异常、不 finish_workflow → 队列锁永不释放，且被记为 success。**双修**：①runner 的 profile 加载改 **fail fast**（删 try/except，直接 raise），让 `run_item` 的 except 兜住（写 error 日志 + finish_workflow 清锁 + re-raise）；②`run_item` 加 `finally: emitter.current_workflow = None` 兜底——run_item 独占该 item 的锁生命周期，无论如何离开都保证释放，杜绝将来再出现「不抛不清」路径。
  - **#2 多处把 tool 失败当成功**（违反 tool 错误契约 + fail fast）：①`W3Pipeline` 取 `get_approved_replies` 失败时原折算空列表 → close("done")，把「读审批回复失败」伪装成「没有待发回复，完成」；改为 `not res.ok` 即记 failed + close("failed") + 返回 `error=load_approved_failed`。②`FinalizeStep` 四个 DB tool（backfill/sync/timeout/purge）失败原静默归 0 却仍报 successful；改为收集 `failures`，有失败则 `log_step(status="degraded")` + 记 `finalize_tool_failures`(visible)，`FinalizeStepOutput` 加 `failed_count` 传导给 W2 summary。
  - **#3 W1 抓卡失败被当成搜索无结果**：`W1Pipeline` 调 `extract_card_list` 后未查 `result.ok` 直接读 data → 选择器漂移/页面异常/浏览器故障都被解释成 `no_cards_found`。改为 `not result.ok` 时记 `extract_cards_failed`(visible) 并 break，与「真的搜索无结果」区分开，不再掩盖技术故障。
  - **#4 依赖缺 DrissionPage**：`requirements.txt` 无 `drissionpage`，而 `browser_context.py` 直接 import 它 → 新环境 `pip install -r requirements.txt` 后浏览器层一 import 即崩。补 `drissionpage>=4.1.0`。`playwright` 曾误删，因 PDF 方案未定重新保留（加注释标明用途，见待跟进）。
  - **#5 CLI onboarding 死路退役**：`main.py` 缺 session（`os.path.exists(session.json)` sentinel）时原进 `run_interactive_setup`，而其 `_step3_login_boss` 无条件 raise、`_session_is_valid` 恒 False = 死路。用户定 CLI 不再负责登录：改为明确提示去 Dashboard（BrowserSession + VerifySessionStep 是唯一登录路径），不再进死路。`OnboardingChecker` 保留（Dashboard 的 check_all 仍用）。
  - **Should Fix：W2 会话级异常无错误计数**：`W2Pipeline` 逐会话 `except` 后 `continue` 但无计数，summary 照样 done。加 `conv_errors` 计数 + 纳入 `finalize_out.failed_count` 为 `finalize_errors`，一批会话全失败不再读作 clean run。
  - **测试**：改 2 例（`test_workflow_orchestration` 断言 run_item 的 finally 保证释放锁，取代旧「靠 runner 清」契约；`test_w2_pipeline_stop_budget` 的 FinalizeStep mock 返回带 `failed_count` 的对象）。**592 passed**，`npm run build` 绿，版本 2.9.4.1。

- 修 W3 盲发过时草稿：发送前新鲜度闸 + 作废退回重分析（2026-07-28，v2.9.3.1，592 passed，build 绿）
  - **背景/根因**：W3 `send_pipeline` 原本 locate 成功后**直接发已批准文本，零核对**会话自批准以来是否变化。用户手动回了 HR、或简历刚发出、或上轮 send 未标记，W3 都照发批准时的旧草稿 → 给真实 HR 发重复/离题消息（唯一对真实 HR 不可逆的缺口）。W2 脏检查能发现用户手动回复并触发重分析，但 `approved` 草稿受 `PROTECTED_REPLY_STATUSES` 保护不被覆盖、而 `last_analyzed_ts` 照常前进 → 草稿变陈旧、水位却追平，W3 仍盲发。
  - **修复（确定性检测，code decides）**：`send_pipeline` 在 Locate 与 Send 之间加**发送前新鲜度闸**——重扫开着的会话（`read_messages`），取最后一条非系统消息（新增纯函数 `_last_nonsystem_sender`）：**是 HR = 仍在等我回 → 正常发**；**是我方 = 批准后已有人回过 → 判定陈旧，不发**。直接命中「用户手动回复」，也顺带堵住 verify 假阴性引发的重复发送。
  - **陈旧处置（用户定：作废 + 重走意图判断）**：新 tracker 唯一转换 `invalidate_reply_for_reanalysis`（`reply_status=NULL` + 清 `reply_text`/`intent` + `last_analyzed_ts=0`）→ 把会话打回「未分析」→ 下一轮 W2 `filter_conversations` 命中 `unanalyzed` 重跑意图判断，要回才重新起草进待审批队列。新薄壳工具 `invalidate_stale_reply`（W3 registry 注册），SQL 只在 tracker 一处。**取舍**：重跑意图分析归 W2（intent 的家），W3 不内联 LLM，故再起草在下一次 W2 而非 W3 当场——符合「最小外科手术」。
  - **两条护栏**：①**dry-run 在闸之前短路**（演练绝不读/作废草稿，locate 后即停）；②**读消息失败=无法核对 → 保守跳过本轮但保留 approved**（瞬时渲染抖动不毁草稿，下轮重试）。
  - **测试**：`test_w3_send_pipeline.py` 加 2 例（陈旧作废跳发 / 读失败保草稿）+ 改 2 例（发送前读与 verify 读需按序返回不同结果，FakeReg 支持 list 序列响应）；`test_hr_conversation_tracker.py` 加 2 例（作废重置 / 守卫只动 approved+revision）。**592 passed**，`npm run build` 绿（新增 `invalidate_stale_reply` 的 interpret 标签），版本 2.9.3.1。
  - **待办**：下次真机 W2/W3 复核——①新鲜度闸在真机正确识别「末条我方」不误伤正常发送；②作废后下轮 W2 确实重分析（`last_analyzed_ts=0` → `unanalyzed`）并按需重起草。

- 简化 W1：拆掉两层 DB 去重（相信 Boss 推送）+ 失败截图改最大化/全页/带 run_id 命名（2026-07-28，v2.9.2.1，588 passed，build 绿）
  - **背景/决策**：用户实测被跳过的岗在 Boss 上按钮全是「立即沟通」，证明 DB 的 APPLIED 记录不可靠、去重在误判丢机会。决定**不排查去重为何误判（不值得），直接删掉整个 DB 去重机制**——「能出现在搜索页的岗都不该跳」，投没投过唯一以 apply 那步真实按钮状态为准（`already_chatting`，绝不二次骚扰 HR）。
  - **W1 去重拆除**：`card_pipeline.py` 删层① `classify_job_for_w1`（job_id 精确去重，开面板前）+ 层② `check_content_duplicate`（内容指纹去重，抓 encryptJobId 轮换）两个 skip 分支；`content_hash` 仍计算并写入 application 行（改直接 `compute_content_hash`，留列备日后恢复，但不再据此跳）。注销 registry（`tools/db/w1/__init__.py`）+ 删两个 tool 文件。前端连带：`WorkflowTrack.tsx` SKELETON/LOOP_STEPS 去 classify 节点（否则监控显示永久「等待」）、`interpret.ts` 删 4 个死标签、`StateMachine.tsx` 架构流程页删「分类去重/指纹去重」两节点（Python 脚本按 ASCII 锚点删、零裸 CJK）。
  - **失败截图改进**：`capture_screenshot.py` 截图前 `set.window.max()` 最大化 + `get_screenshot(full_page=True)` 全页截（按钮在 footer 也在画面内）；`browser_context.open_browser` 加 `--window-size=1920,1080`（headless 默认 ~800px 视口是右侧详情面板被切、投递按钮不在旧截图里的根因）。`card_pipeline` 传 `label=f"{run_id}_{job_id}"`，截图名 `{run_id}_{job_id}_{ts}.png` 可回溯到某次 run 的某张卡。
  - **测试**：`test_content_dedup.py` 删掉 CheckContentDuplicate 两例（保留纯 hash/company_id helper 测试）；`test_card_pipeline_dry_run.py` 给 `_Logger` stub 加 `run_id`、删两个死 stub 分支；`test_capture_screenshot.py` FakePage 加 `set.window.max` + `full_page` kwarg 并断言最大化/全页生效。**588 passed**，build 绿（tsc 无悬空引用），版本 2.9.2.1。
  - **待办**：下次真机 W1 复核——①去重拆除后已投岗会重新走评分→apply，apply 用真实按钮状态兜住不重复骚扰；②失败截图在真机 headless 下能截到完整面板+按钮，据此定位 `button_not_found` 根因。

- 架构页补齐前端架构视图（2026-07-24，前端，v2.9.1.1，`npm run build` 过）
  - **背景**：架构页（`StateMachine.tsx`）的「架构」标签原本只有 ①系统全景 ②前后端沟通 ③后端四层——全是后端视角，前端自身被压成系统全景 SVG 里「浏览器·React 面板」一个方块，看不出内部结构。
  - **改动**：在③之后新增 **④前端架构** Section（与③后端四层对称），三块内容：SPA 分层表（壳/路由/状态/API 层/实时流/组件/构建 + 职责 + 代表文件）；前端内部数据流条（`SSE 一帧 → useWorkflowStream 回调 → pendingEventsRef 缓冲 → 每 200ms flush → state·留最后 200 → 重渲染`，附 10s 轮询兜底）；三个可展开技术讲解（为什么不用 react-router / SSE 洪流为什么要缓冲限流 / 一份 Context 管全局），复用现有 `Collapsible` 组件。
  - **内容与源码核对**：无 react-router（App.tsx 手动 page 状态切页）、单 AppContext、useWorkflowStream 的 ref 缓冲 + 5Hz flush 限流均取自实际代码，非臆造。
  - **实现方式**：CJK 全 `\uXXXX` 转义，用 scratchpad Python 脚本生成插入（Edit 工具会把 `\uXXXX` 解码回中文，本仓已知坑），文件保持纯 ASCII。纯前端静态内容新增，未触碰 Python，门是 `npm run build`（已过 tsc + esbuild）。

- 四路独立审视整改交付（2026-07-21~22，v2.8.0→2.9.0，478→590 passed，明细见 `docs/audit-remediation-log.md`）
  - **起因**：起 4 个独立 subagent 从架构分层 / W2 正确性 / 数据+隐私 / 测试+前端四个视角审视全项目，汇总带优先级总评（`docs/audit-remediation-plan.md`），逐阶段整改。
  - **阶段 0 冒烟测试可信化**：原冒烟「本轮没投没发也全绿」= 门形同虚设。加 `covered` 维度独立于 `ok`，report 出 `fully_covered`/`uncovered`，前端三态（红/黄未全覆盖/绿）；参数（score_threshold 等）透传避免阈值太高永远投不出去；**新建 `services/run_diagnostics.py`** 从 run JSONL 得确定性诊断（可诊断任意历史 run，全程 code decides 不调 LLM）；冒烟改走队列（`run_smoke(submit=...)` 依赖注入）消除 W1/W2 第二条执行路径；L2 数据不变量 +5 条（把历史 bug 变常驻探针）。诊断器扫 553 个历史 run 找出 8 个「真实外发后未收尾」。
  - **阶段 1 P0 隐私**：`logs/task_*/`（含真实 HR 姓名/公司/聊天/头像 URL）已在公开 repo。orphan 分支重建远程历史（126 commit→1，泄露清除，本地保留完整历史）；**新建 pre-commit PII 扫描器**（硬模式 + 从 jobs.db 实时比对，误报压到 0）；`.gitignore` 黑名单收敛为整目录 + 位置护栏（三道防线）。
  - **阶段 2 High（同一转换多份实现连抓四例）**：mark-sent 三份两义（一份写 NULL 而非 'sent' → 可能二次发送）/ update_hr_analysis 双实现（tracker 版缺 last_analyzed_ts）/ 新会话首轮分析丢写（analyze 在 upsert 前，纯 UPDATE 匹配 0 行）/ applied_at 语义相反（保留首次 vs 更新为最后 → 重投不计入今日、被提前清理）。收敛为「一个状态转换只能有一份 SQL」，SQL 只留 tracker。每项 live 冒烟验证。
  - **阶段 3 Medium**：停滞判定改用真实消息时间 `last_msg_ts`（旧用入库时间几乎一直失效，生产实测命中 0→35）；配置读写统一 config_manager（消除单例缓存与内联 yaml 分叉）；微信号解析下沉 `tools/biz_logic/wechat_id.py`（前端冗余拷贝删除）。审查后**维持原样**两项：too_old 优先于 unanalyzed（#51 有意取舍）、upsert_hr_conversation 双实现（有意职责分离）。
  - **阶段 4 Low**：score_job 加权聚合补 12 测试（唯一测试空白）；SelfCheck interval 泄漏修复；CLAUDE.md 铁律措辞与 tools/db 实际形态对齐。
  - **单拎 server.py 减重 -600 行（2638→2038）**：调度/队列执行/自检/限流/日志解析等编排逻辑从「接线层」下沉为三个 service——`scheduler_service.py`（SchedulerService，有状态用 service 类）、`workflow_orchestration.py`（OrchestrationService，get_state 访问器 + 跨簇依赖注入）、`run_log_reader.py`（纯函数 + 路径传参，无状态）。依赖注入方式按「有无状态」选。每批 live 冒烟验证。

- W2「读消息 / 分析 intent」解耦：加 `last_analyzed_ts` 独立水位线（2026-07-13，后端，478 passed，生产迁移已验证）
  - **背景**：上一步 `never_analyzed` 修复只盖住"intent 完全为空"的卡死，盖不住更隐蔽的一种——会话已有 intent（如 `general`），HR 再发新消息，重分析又失败 → intent 保持旧值（非空）→ `never_analyzed` 不触发，而 upsert 又把 `last_msg_ts` 推到新消息 → 下轮 `no_change` 跳过 → 新消息读了没分析成、又隐形。根因：**单一水位线（`last_msg_ts`）同时代表"读到哪"和"分析到哪"，且 analyze 失败仍前进**。
  - **修复（读/析解耦）**：`hr_conversations` 加列 `last_analyzed_ts`（最后**成功分析**到的消息时间），只在 `update_hr_analysis`（analyze 成功/结论时）前进；DEGRADED 失败路径不调 update → 水位不动。脏检查从 `conv_ts > 存的 last_msg_ts`（已见）换成 **`conv_ts > last_analyzed_ts`（已分析）**——analyze 失败下轮必 `conv_ts > last_analyzed_ts` 自动重试，无论 intent 空还是旧值。决策树简化：`newer_ts`→`unanalyzed`（吸收 never-analyzed for conv_ts>0）；`preview_changed`/`never_analyzed` 降为 conv_ts==0（无时间戳行）兜底。
  - **改动 6 处**：`schemas.py`（HRConversation 加 last_msg_ts/last_analyzed_ts）；`tracker._init_db`（迁移 + **回填**：已分析行 last_analyzed_ts=last_msg_ts，避免存量 627 全触发；生产回填 251 条、漏 0）+ `_row_to_hr_conv`；`update_hr_analysis` 工具（加 last_analyzed_ts 参数，MAX 防回退）；`AnalyzeStep`（成功+无HR两路传 last_msg_ts）；`get_conversation_states`（带出）；`filter_conversations`（主脏信号换 last_analyzed_ts）。
  - **测试**：新增 `test_filter_read_ok_analyze_failed_is_retried`（证明修复的关键用例：intent 非空 + 新消息 analyze 失败仍重试）+ 工具推进水位（MAX 防回退）+ 迁移回填 3 例；改 `newer_ts`→`unanalyzed`。**478 passed**。dashboard 已用新代码重启、生产迁移验证通过。
  - **待办**：下次真机 W2 复核 `unanalyzed` 分支行为（analyze 失败→下轮重试、成功→不再重扫）；存量部分无 ts 的已回填行会 `unanalyzed` 重扫一次后收敛（一次性、自限）。

- 真机会话对账实证：**漏库 = 0**（2026-07-13，`reconcile_conversations.py` --force 跑通）：DB 929 ≥ 扫到 627，在 Boss 不在 DB=0、在 DB 不在 Boss=302（历史/归档）。彻底证伪"有会话不在数据库"。
- 存量回填：`reanalyze_stuck_conversations.py` 真跑 108 条、0 失败、起草 75 条待审批（含 13 面试邀请 + 20 要简历）；空 intent+有 HR 消息从 106→1。

- 「有会话没出现在列表」调查 + 「在库但未分析」根因修复 + 对账/回填脚本（2026-07-13，后端，475 passed，未 push）
  - **调查结论**：①**没有系统性"漏库"**——DB 924 条 ≥ 上次真机扫描 909 条，DB 是超集；唯一不入库路径是 `too_old`（从没处理过 + 最后消息>14 天），那类本就停滞。②**真正的坑：69 条会话在库但从没被分析**——近 14 天有 HR 消息、`intent` 却为空、无草稿（其中 25 条最后一句是 HR 发的、明摆着等回），样例含大厂 OD 岗 / AI 产品经理 / 高薪财务岗等真机会。机制：某次 W2 `read_messages` 成功（消息落库）但 `AnalyzeStep` 整批失败（LLM 超时，"3.2天前"一大簇同时间戳为证），之后每轮被 `filter_conversations` 判 `no_change` 永久跳过，卡死空 intent → 控制台上隐形。全库共 106 条"空 intent + 有 HR 消息"。
  - **根因修复（3 处，防止再卡死 + 自愈存量）**：①`get_conversation_states` 返回值加 `intent`（让 filter 能看到）。②`filter_conversations` 加 `never_analyzed` 分支——库里有行但 intent 空 → 重新处理；放在 `too_old` 之后（老会话仍被拦、不捞几百条陈年会话）、`no_change`/`terminal` 之前。③`AnalyzeStep` 无 HR 消息分支改为**落 `intent='unknown'`**（原来直接返回不写库→永远空 intent→被新分支反复重抓）；落 unknown 后不再命中，**一次性自愈、不循环**，避免误伤 610 条"零 HR 空 intent"会话每轮被导航。
  - **两个脚本（`code/scripts/`，复用现有 Step、不搓分叉）**：①`reanalyze_stuck_conversations.py`——离线读 DB 已有消息、复用 `AnalyzeStep` 重跑分析回填 intent+草稿，不开浏览器；`--dry-run`/`--limit`/`--min-hr`，只选空 intent 天然幂等；已 dry-run 验证精准命中 106 条。②`reconcile_conversations.py`——复用 `ScanStep` 真机扫当前 Boss 列表对 conv_id 做差集、彻底证伪"漏库"；带 8765 端口守卫（`open_browser` 会 `_kill_stale_chrome` 杀 dashboard 浏览器，**必须先停 dashboard 再跑**）。
  - 测试：`test_filter_conversations.py` 加 `never_analyzed` + `too_old 优先` 2 例、补 3 处 fixture 的 intent；`test_analyze_step_no_hr.py` 更新契约（no-HR 现在落 unknown）；`test_hard_association.py` 补 1 处 intent。**475 passed**。
  - **待办**：①**用户先停 dashboard，跑 `reconcile_conversations.py` 对账**（拿真机差集实证"漏库≈0" + 当前列表卡死数）；②跑 `reanalyze_stuck_conversations.py`（建议先 `--limit 5` 验 LLM 质量，再全量）回填存量 106 条；③根因修复需下次真机 W2 复核 `never_analyzed` 分支生效、不误伤。

- 会话（navigator）加搜索框 + 列表改按「最后消息时间」排序（2026-07-13，版本 2.7.0，纯前端，build 绿 2.7.0.1，未 push）
  - **背景**：用户反馈「有些 Boss 会话没出现在控制台会话列表里」。查数据链路澄清根因：`get_hr_conversations` **无 limit**（库里会话全返回），但按 `created_at DESC`（会话首次入库时间）排序——有新消息的**老会话被埋在几百条下面**，看着像「没出现」。真正不在库的会话（W2 `too_old` 闸跳过 / 从未扫到）搜索也救不了，如实告知用户。
  - **改动（`Chat.tsx` 单文件）**：①左侧会话列表顶部（stage tabs 下方）加搜索框，客户端子串过滤 **公司名 / HR 名 / HR 头衔 / 最后消息预览 / 每条消息正文（全文）**（`convMatchesQuery`，不区分大小写；~900 会话客户端过滤无性能问题）；带清空按钮 + 「匹配 N / 总 M 条」计数。②`loadConversations` 拉取后按 `last_msg_at` 降序重排（纯前端，数据已有该字段），HR 刚回复的老会话自动浮顶，从根上缓解「埋在下面」。③空态区分「暂无会话数据」与「无匹配的会话」。
  - 搜索是叠加在当前 tab 过滤之上；`selected` 仍取自全量 `conversations`，搜索收窄不影响右侧已选会话。CJK 全程 `\uXXXX`（Python 脚本全文转义，规避 Windows GBK 工具链损坏）。未碰后端，pytest 不受影响（仍 473 passed）。
  - **待真机验证**：搜索/排序在真实数据（数百会话）下的交互与性能。

- 一键拒绝所有待审批回复（2026-07-11，版本 2.6.0，473 passed，build 绿，未 push）
  - 起因：待审批（`reply_status='pending'`）名单混入大量古老 conversation，逐条点「拒绝」太麻烦。
  - 后端：`tracker.dismiss_all_pending_replies()` 批量 UPDATE `pending → dismissed` 返回 count；**只动 pending，不碰 approved/revision/sent**（用户已决策的不受影响）。端点 `POST /api/conversations/dismiss-all-pending-replies`（静态路径，与 `/{conv_id}/dismiss-reply` 段数不同、不冲突）。
  - 前端：`Chat.tsx`「待审批」tab（`PENDING_FILTER`）列表顶部加「一键拒绝全部（N）」按钮 + **二次确认**（红色警示「不发送、仅清理名单，已批准的不受影响」）；切 tab 自动重置确认态；成功后 `loadConversations` 刷新。新增 `api.dismissAllPendingReplies()`。
  - 单测 `tests/test_dismiss_all_pending.py`（2 例：只 dismiss pending 不碰 approved/sent、无 pending 时 no-op）。CJK 走 Python 脚本转 `\uXXXX`（同 SmokeCard 套路）。

- 冒烟测试（回归层3）拆出「真跑档」：真投真发 + 落库断言 + 可配参数 + 强隔离（2026-07-11，版本 2.6.0，471 passed，build 绿 2.6.0.1，未 push，未真机验证）
  - **背景/决策**：用户指出冒烟只跑 dry-run 不够——「有真跑就一定要能控制参数」，且要验证「真发能不能发出去、数据库能不能落库」。方案讨论定 **A 方向**（不合并 IA、共享底层引擎），否掉 B（把自检并进回归测试）——理由：回归测试四层原本「由轻到重但全程无破坏性」，塞进真投真发会破坏「无脑随便跑」的安全心智，且自检(定时后台巡检)与回归测试(改后手动验)是两个正交语义，只是碰巧都用「跑 W1/W2」这个动作。关键认知纠偏：**自检的「真跑」其实是异步入队、不等结果、不断言落库**（`server.py` enqueue source=selfcheck），所以「验证真发+落库」是本次新做的能力，不是搬自检。
  - **后端 `services/regression.py` `run_smoke` 参数化**：`run_smoke(..., dry_run=True, w1_max=2, w2_max=5)` 一个函数吃两模式。dry-run 档判据不变（读路径没崩）。**真跑档（dry_run=False）判据升级为「断言外发动作已落库」**，两条对称硬断言：
    - W1：跑前 `tracker.count_today()` → `run_w1(dry_run=False)` → 跑后 `count_today()`；**applied>0 则今日投递数必须真增**（Δ≥1），否则「投了但没落库」= 落库失败判红（正是历史踩坑 [[w1-apply-db-fix]] 那类 bug）。applied==0（无卡/全跳过）如实报「未覆盖投递落库验证」，不伪装通过。
    - W2：跑前 `get_lifecycle_counts()["tables"]` 记 hr_messages 数 → `run_w2(dry_run=False)` → 跑后对比；**resumes_sent>0 则 hr_messages 必须真增**（发简历必落库一条我方消息），否则落库失败判红。无外发目标如实报「未覆盖发送落库验证（微信同意/落库仍真跑）」。W2 真写面确认为**两类**外发（dry-run 都 gate）：发简历(`ResumeStep`)+ **同意微信卡**(`WechatStep`，对真实 HR 不可逆)——回应用户「W2 不只是发简历」。W3(发已批准回复)按用户决定**不纳入**真跑。
    - 只读走 `count_today`/`get_lifecycle_counts` getter，不写 raw SQL（守层2铁律）。report 加 `mode`/`params`。
  - **端点 `server.py`**：`POST /api/regression/smoke` body 加 `{mode:"dry"|"live", w1_max, w2_max}`。live 沿用 409 浏览器互斥 **+ 复用 `_is_rate_limited_today()` 每日上限闸**（达 Boss 上限拒绝真投，同自检）。live 默认 1/1（真跑最小副作用），dry 默认 2/5。`_run_regression_smoke` 透传参数。
  - **前端（`Automation.tsx` SmokeCard + `api/index.ts`）**：`triggerRegressionSmoke(body)` 传 mode/参数；`SmokeReport` 加 mode/params。SmokeCard 保留无害 dry-run 一键跑；**真跑档强隔离**——独立红框区（w1_max/w2_max 数字输入框）+ 红色「真跑（真投真发）」按钮 → **二次确认弹窗**（红色警示「真实投递消耗配额、真发简历、同意微信给真实 HR，不可撤销」）才真发。结果区加 dry-run/真跑 mode 徽章。CJK 全程 `\uXXXX`（Python 脚本生成字面转义；踩坑：三元/prop 内的占位需裸字符串 `'\u..'` 而非 JSX 子节点式 `{'\u..'}`，否则 TS1005）。
  - 新单测 `tests/test_regression_smoke.py`（8 例：dry ok / W1 投了落库 ok / **W1 投了没落库判红** / W1 没投未覆盖 ok / W2 发简历落库 ok / **W2 发简历没落库判红** / W2 无外发 ok / W1 error 判红）。**471 passed**，build 绿。
  - **待真机验证**：①dry 档走端点+落盘+`smoke/last` 链路（上个会话的 ok=True 是脚本直调、没走端点，故 `regression_smoke_log.jsonl` 至今为空、Dashboard SmokeCard 显示「从未运行」）；②真跑档真投真发 + 落库断言真机生效（需登录态、会真投真发）。

- 会话定位收敛直开 + session 误判诊断化 + W2 扫描活跃时间闸（2026-07-10，版本 2.5.1.x→2.5.2.1，463 passed，未 push）
  - **前端定位按钮收敛为单一「在 Boss 打开」+ jobid 直开优先**：删除重复的独立「搜索定位」按钮（`Chat.tsx` + `api.locateInBrowser` + `POST /locate-in-browser` 端点）。`open-in-browser` 端点重构为清晰退化链：两 id 齐全 → jobid 直开（`NavigateToConversation`，O(1)，不再多余先开聊天列表）→ 直开不可用/失败 → 打开列表用搜索框（`SearchLocateConversation`，触达沉底会话）兜底。搜索框定位从独立按钮降级为内部兜底，不再有两个同功能按钮。
  - **session 误判可诊断化**：`verify_session.py` 判过期时把**实际跳转到的 URL** 记进 reason（原为死字符串，看不到跳哪、误判不可证伪）。登录态有效却被重定向到其它已登录路径（Boss 改版/活动页/慢加载中转）会显真实地址，供下次复现定位根因；error 语义（session_expired）不变。
  - **W2 扫描活跃时间闸（治「扫描很久以前的会话」）**：`filter_conversations` 新增时间闸——会话最后消息时间（`last_msg_ts`，getGeekFriendList 真实毫秒时间戳）早于活跃窗口的跳过（`reason=too_old`），不再导航进去 + 跑 LLM。判定顺序：`unread`（HR 刚发）/`approved`（已批回复）永远豁免（闸在其后）；闸在 `new`/`newer_ts`/`preview_changed` 之前（老会话不靠这些绕过）；`last_msg_ts==0`（DOM 兜底/迁移前无时间戳行）豁免。**窗口值复用 `no_response_days`（=14）不新增参数**：「14 天无新消息算停滞」与「只扫最近 14 天活跃」是同一窗口两面（超窗会话既跳扫描又被 FinalizeStep 软关闭），config/server/前端均不动。新增 6 例单测（too_old / unread 豁免 / approved 豁免 / 窗口内 new / 无时间戳豁免 / 窗口关闭向后兼容）。
- 回归测试模块（四层体检）+ LLM 兜底收敛 + W2 慢治本 + 回复生成 think 拆分（2026-07-09~10，版本 2.2.2.1→2.5.0.1，均已 push，457 passed，commits 609f230→36c4e29）
  - **回归测试四层体检**（导航「自动化」→「自动化和测试」+ 新「回归测试」Tab）：层0 环境(复用 selfcheck)/层1 逻辑(455 pytest UI 化，`services/regression.py` subprocess + JUnit XML 解析按文件分组)/层2 数据不变量(`run_invariants` 经 getter 只读查 5 项，**真机一跑抓到 9 条「已批准但 reply_text 空」历史遗留**)/层3 真机端到端冒烟(`run_smoke` 复用 run_w1/run_w2 dry-run 小规模，异步 background+浏览器互斥+前端轮询)。端点 `/api/regression/{pytest,invariants,smoke,smoke/last}`。前端 RegressionSection 4 层 + PytestCard/InvariantCard/SmokeCard。**层3 真机待用户验收**（需登录态/浏览器）。
  - **LLM 兜底收敛纯 ollama**：移除 codex_cli（`codex exec` 是编程 agent，判意图反问「你想让我干什么」把待分类消息当背景，三种 system×reasoning×ignore-config 全错、非 prompt 可修）+ claude_cli（`claude -p` 忽略 system + 抢主对话配额）。fast/balanced 纯 ollama qwen3:8b(think=false)，真实工具 5/5。正道走 chat completions(openai_compatible/anthropic_api)固化进 config 注释。
  - **W2 回复生成拆 think 步骤**：意图判断 think=false(快准) + 生成回复 think=true(斟酌措辞)拆成两次独立 LLM 调用；`think` 参数从 protocol→5 provider→FallbackChain→ModelRouter 全链透传(仅 ollama 用)；新 `generate_reply` tool/模板，`analyze_intent` 去 suggested_reply。真机 think=true 7.4s(有推理)vs false 0.4s。
  - **W2 慢治本**：`navigate_to_conversation` 直开会话 URL(`chat?id=encryptBossId&jobId=encryptJobId`，O(1) 真机 3.6s vs 旧 DOM 滚动搜索 ~103s，缺 id/boss=='62001' 回退搜索)+ 中止按钮真生效(W1/W2/W3 循环轮询 stop_requested)+ W2 25min 时间预算兜底。
- W1 统计排除 backfill 灌水 + LLM output_schema 结构化输出（2026-07-07）
  - **W1 count_today 排除 backfill**：`count_today` 加 `AND score IS NOT NULL`。backfill_application_from_conversation 补录历史投递时 score=NULL、applied_at=now()，把「今日投递」灌水（一次 W2 补 96 条 → 147 vs 真 51）。真 W1 投递 score 恒非 NULL（含 threshold≤0 的 score=0），据此排除。单测 `test_count_today_excludes_backfill.py`；`_rec` helper 补 score 默认值。
  - **LLM output_schema 穿透（codex 兜底调优 + ollama 主力增稳）**：给 `ModelRouter.complete`/`FallbackChain.complete`/5 个 provider `complete` 加 optional `output_schema`。ollama 用 `/api/generate` 的 `format`=JSON Schema 强制结构化输出（实测 qwen2.5:7b 带 schema 6.4s 出干净 JSON，比无 schema 25.7s 还快）；codex 用 `--output-schema <临时文件>`；其余接受即忽略，safe_parse_json 仍兜底。`analyze_intent` 传意图 schema（intent enum + confidence/needs_reply/suggested_reply）。
  - 444 passed。
- 修 hr_messages schema 漂移：4 列 UNIQUE → 3 列 + 去重（2026-07-07）
  - 生产 DB 的 hr_messages 是老 `UNIQUE(conv_id,sender,text,msg_time)`（4 列），代码是 3 列（`CREATE TABLE IF NOT EXISTS` 不改老表）。Boss 的 msg_time 是不稳定相对显示串（「刚刚 09:55」vs「06-10 09:55」同消息重扫拿不同 time），4 列约束当成新消息 → 累积 ~380 条重复（10%）。
  - `tracker._init_db` 加迁移：检测旧 4 列 UNIQUE（sql 含 `text,msg_time)`）→ rebuild 成 3 列表 + `INSERT OR IGNORE ... ORDER BY id` 去重（保留最早）。幂等（3 列库不触发）。真机已应用：3876→3496（删 380）、0 残留重复。单测 `test_hr_messages_migration.py`（2 例）。443 passed。
- 修 W2「一直报错」+ W3 定位失败即放弃（2026-07-07，版本 2.2.1.3）
  - **W2 upsert_hr_conversation UNIQUE 回滚死循环（主 bug）**：硬关联「遇到即吸收」逻辑的 else 分支（目标硬键行不存在时）用普通 `UPDATE hr_messages SET conv_id=...` 迁移消息，当 conv_id 下已有相同消息（本轮 write_hr_messages 先写 / 历史重复）就撞 `UNIQUE(conv_id,sender,text[,msg_time])` → 抛错 → 整个 upsert 事务回滚 → 遗留软键行没吸收成 → 每轮 W2 再扫再撞，多条会话一直报错。修复：else 分支改成和 target_exists 分支一样幂等（`UPDATE OR IGNORE` + `DELETE` 迁不动的遗留重复）。部署后遗留行下轮 W2 自愈。回归测试 `test_hard_association.py::test_upsert_absorb_idempotent_when_target_message_already_present`。
  - **W3 定位失败 N=3 即放弃**：会话被用户在 Boss 手动移除后，若还有已批准回复，W3 的 `search_locate_conversation` 会每轮定位失败、回复卡 approved、无限重试。新增 `hr_conversations.locate_fail_count` 列 + tool `record_locate_attempt`（定位成功清零 / 失败累加，达阈值 3 就把回复 reply_status→'dismissed' 退出 get_approved_replies）；send_pipeline 每次 locate 后调用它，放弃时记 `reply_locate_gave_up` 可见事件。单测 `test_record_locate_attempt.py`（4 例）。
  - 均为后端改动（无前端/构建）。441 passed。
  - **附带发现（未处理）**：① hr_messages schema 漂移——生产库 UNIQUE 是 4 列（含 msg_time），代码 CREATE TABLE 是 3 列（`CREATE TABLE IF NOT EXISTS` 不改老表）；② W2 LLM 降级是 ollama qwen3:8b + codex_cli 都 180s 超时（本机 LLM 慢，非代码 bug）。
- workflow 队列：统一调度 W1/W2/W3（2026-07-06，版本 2.2.x）
  - **动机**：原并发模型是单例互斥（`emitter.current_workflow`）——手动触发撞上在跑的工作流 → 409 拒绝；定时撞上 → 直接跳过（漏跑）。改为「一个队列 + 一个顺序 worker」：所有工作流启动（手动/定时/显式加入/编排链）统一 `enqueue`，FIFO 顺序执行。
  - **后端**：新 `services/workflow_queue.py`（内存 FIFO + 守护 worker，线程安全 Condition；enqueue/remove/move/reorder/clear/pause/resume + coalesce 防定时堆积 + is_busy 让位交互浏览器；runner 与 is_busy 注入 → 纯逻辑可单测）。`server.py`：`_queue_runner`（派发到 `_run_apply/check/reply_workflow` + 写调度日志 + 出错清 current_workflow 锁），`_initialize_state` 装配队列，三个 trigger 端点改 enqueue（不再 409），`_scheduled_run` 改 enqueue（coalesce，不再跳过漏跑），队列端点 get/add/batch/delete/clear/move/reorder/pause/resume。
  - **自检也入队**（统一调度）：`_run_selfcheck_cycle` 把真 W1/W2 改为 enqueue（source=selfcheck），不再「忙则跳过」；探针因需独占 Boss 浏览器加互斥守门（忙则本轮跳探针、W1/W2 仍入队）。
  - **前端**：队列面板 `pages/Queue.tsx` 放**控制台** CONTROL 下（不是自动化）；WorkflowPanel 按钮去「运行时禁用」→ 常亮即入队，`⚡W1+W2` 改 `enqueueWorkflowChain`（删掉盯 SSE 的 runAllPhase 脆弱链），入队弹提示；队列面板：当前运行/待执行（**拖拽改序** + 移除 + 清空 + **加入时间戳** `enqueued_at`）/最近完成/**暂停·继续**（暂停≠中止：当前跑完不接下一个）。
  - **修既有 bug**：`Logs.tsx` 里 `W1 · 求职决策` 的 `·`(·) 是**裸 JSX 文本节点**（前面有 `W1 ` 导致「>紧跟\u」的扫描漏掉），渲染成字面 `·`；折进 `{'...'}` 表达式修复。教训：裸文本 `\uXXXX` 检测要用「不在引号/注释内的 \u」而非「> 紧跟 \u」。
  - 测试：新增 `tests/test_workflow_queue.py`（10 例：FIFO/移序/reorder/coalesce/出错存活/is_busy/pause 等）+ 更新 `test_server.py` 6 例到新契约（enqueue 而非 409，fixture 清队列防跨用例污染）。**436 passed**，build 绿。
- 自动化页拆为「定时调度」「自检」两个 Tab（2026-07-06，版本 2.1.1.2）
  - **背景**：`pages/Automation.tsx` 默认导出原竖排三块（ScheduleCard 调度卡 + ScheduleLogCard 调度历史 + SelfCheckSection 自检），堆一起太挤。
  - **改动**：默认导出改为顶部 Tab 切换（样式复用架构页 StateMachine 的 pill Tab 栏）——定时调度 Tab（ScheduleCard + ScheduleLogCard）/ 自检 Tab（SelfCheckSection 原样复用，零内容改动）。`useState<AutoTab>` 本地切换，默认 schedule。仅一个文件改动。
  - CJK `\uXXXX`（Python 直写规避 Edit JSON 解码坑）；真机截图验证两 Tab 渲染正常无乱码；build 绿。
  - **背景**：完成 PROGRESS 里两条 [另开会话] 待办。架构 navigator 的「流程」Tab 原只画 W1/W2 两泳道，且 W1/W2 步骤在 job_id 硬关联升级（2.1.0.x）后已漂移。纯前端单文件改动（`dashboard/frontend/src/pages/StateMachine.tsx`），无后端/逻辑改动。
  - **新增 W3 泳道**（`W3_STEPS`）：取已批准（`get_approved_replies`）→ 定位（`search_locate_conversation`，搜索框定位沉底会话）→ 发送（`send_chat_message`）→ **验证**（`read_messages`+`write_hr_messages` 重扫确认「我方」气泡落地）→ 标记（`mark_reply_sent`）。验证节点带红色失败支路「未验证则保留 approved、不误标已发」。紫色 `#bf5af2`，`running==='w3'` 高亮。澄清：W3 本就是完整独立工作流（`w3_runner.py`+`w3/pipeline.py`+`w3/send_pipeline.py`+`tools/browser/w3/`），此前仅流程图漏画。
  - **W2 拆脏检查节点**：原「扫描」单节点拆为 扫描列表（`extract_conversation_list` 读 getGeekFriendList API 拿整页含 job_id/lastTS）+ **脏检查**（`filter_conversations` 按 lastTS 毫秒时间戳增量放行）；收尾节点补 `backfill` 补 application 说明；落库补 job_id/lastTS 落列。
  - **W1「落库」订正**：补 `upsert_hr_conversation`——投递成功建 `conv_id=job_id, stage='new'` 占位（W1→W2 硬关联）。
  - **数据模型 Tab 订正**：`hr_conversations` conv_id PK 从 `sha256(hr_name|company)[:12]` 改为「job_id 优先 / sha256 退化」+ 补 `last_msg_ts` 列；表关系注释改「job_id 优先，hr_name+company 退化关联」。
  - **全局措辞**：系统全景图 pipeline 框、页头、后端四层表 pipeline 行的「W1/W2」→「W1/W2/W3」。
  - **CJK 处理**：架构页硬约束全程 `\uXXXX`。踩坑复盘：Edit 工具会把 JSON 里的 `\uXXXX` 解码成汉字，无法写入字面转义；改用 Python 脚本直接读写文件（`e()` 生成字面 `\u` 序列 + str.replace 精确匹配），全文件零裸 CJK 校验通过。`npm run build` 绿（tsc 无悬空引用），构建自动 N+1 → 2.1.1.1。
  - **目标**：两表关联从软键（hr_name+company，历史 sync JOIN 35 次全 0 行）改为 job_id 硬键。job_id == Boss `encryptJobId` == 岗位详情 URL 片段（`job_detail/{片段}.html`，省 securityId 仍同页 → 片段即稳定主键；用户亲测确认）。
  - **采集（Phase 1）**：`browser_context.open_browser` 加载前 CDP 注入 XHR hook（`window.__xhrLog`，挨着 stealth）；`extract_conversation_list` 从读 DOM 改读 `getGeekFriendList` API 的 `zpData.result[]`（DOM 降为 hook 空时兜底）。scan 循环改**按 all_convs 增长量判定到底**（API 一次给整页 100 条、DOM 只渲染 ~15，旧 DOM 增量检测失效会死循环/误判）。真机：`source=api`、滚动分页 438 条全带 job_id、conv_id 全==job_id。
  - **身份+落库（Phase 2）**：新增 `derive_conv_id`（job_id 优先 / 无则 sha256(hr|company) 退化，`tools/biz_logic/conv_id.py`）；`upsert_hr_conversation` tool 加 `job_id`+`last_msg_ts` 参与列；tracker 加 `last_msg_ts` 列 + **conv_id re-key 迁移**（有 job_id 存量行 conv_id→job_id，级联 hr_messages）。
  - **关联+双向补表（Phase 3）**：`sync_application_status` JOIN 改 job_id 优先、hr_name+company 软兜底；新 tool `backfill_application_from_conversation`（W2→W1，finalize 里为有 job_id 无 application 的会话补 APPLIED——捞回 HR 主动发起/投递漏记/被 purge 的岗位）；W1 apply 成功建 `conv_id=job_id, stage='new'` 占位（W1→W2，W1 registry 也注册 UpsertHRConversation）。
  - **脏检查（Phase 4）**：`filter_conversations` 加 `newer_ts` 分支（用 `lastTS` 毫秒时间戳判增量，替代相对时间文本；preview 对比保留给无 ts 行兜底）。
  - **踩坑修复：historyless 重复行**。re-key 迁移只能修已有 job_id 的存量行（224/830）；606 条历史无 job_id 软键会话重扫会用 conv_id=job_id **新建行**孤立旧行+消息（真机 830→833 各丢历史）。修复：upsert 在 `conv_id==job_id` 时先按 hr_name+company 找遗留软键行**就地 re-key 吸收**（迁 conv_id+级联消息，目标已存在则删孤儿+合并消息）。真机复验 dup pairs=0、历史消息保留、stage 从 closed 复活。教训：**PK 迁移光靠一次性 migration 不够，写入路径要"遇到即吸收"**。
  - **决策**：两条 upsert 不物理合并（tool=live 权威写 identity/stage/job_id/ts；tracker 方法=onboarding 播种，多写 intent/reply，非重复，各司其职）。
  - 探针（`probe_hardlink.py`）先验证再开工：getGeekFriendList 首屏 100/100 全带 encryptJobId、87 命中 applications；会话级兜底源 = `getBossData` XHR。点"查看职位"按钮路永久放弃（`.position-content` 无 href/程序化点击不跳转）。
  - 测试：新增 `tests/test_hard_association.py`（16 例），全量 **426 passed**。
  - **真机端到端验证通过（2026-07-06）**：
    - 老数据迁移：`831→754`（re-key 迁移清掉 77 条历史重复行，消息全迁到硬键行，零唯一数据丢失）。
    - W1 真机（默认 3 卡真投）：`applied 3/3, errors 0`；3 个岗**各建 conv_id=job_id、stage='new' 会话占位**（W1→W2 打通）。
    - W2 真机（默认 200 会话、非 dry）：`convs_processed 200, resumes_sent 7, replies_sent 0, llm_degraded 0`。硬键会话 152→241（+89 软键被就地吸收）、软键残留 602→532、**待吸收重复对 0 / 残留重复 0**（吸收修复在 200 规模站住）；**W2→W1 backfill 补录 96 条 application**（有会话无应聘的岗位——含 150→63 漏记的真投——一并捞回 APPLIED）。source=api 由 +89 硬键间接证实（job_id 只能来自 API，DOM 抓不到）。

- W1 HR名抓取真机修正 + run_e2e 加 --search-url（2026-07-05，版本 2.0.6.2）
  - 真机跑发现 v2.0.4.1 的 HR 抓取**仍全空**：`read_panel_jd` 用 `_ele_any(page, ['.job-boss-info h2.name',...], timeout=2)` 当"等 HR 卡渲染"的门 → 门永远 None。根因：**DrissionPage `.ele()` 不认带空格的复合后代选择器**（单 class 可以），门没过就没跑那段验证过可靠的 run_js。改为 `page.run_js(_HR_NAME_JS)` 直接轮询 5×0.4s（querySelector 认复合选择器）。
  - **真机端到端验证通过**：`run_e2e w1 --search-url <ai搜索页>` 投递 1 卡 → `fetch_jd hr_name="某names"` → DB `applications.hr_name="某names"`（某companies，valid UTF-8，3字纯名，与 W2 会话表格式一致）；对比同 run 修复前落的空 hr_name。关联死链 W1 侧真机打通。
  - `scripts/run_e2e.py` w1 加 `--search-url` 参数（run_w1 本就支持；profile 关键词 `agent` 搜索返回 0 卡，需用已知有卡的 `ai` 搜索页测）。测试 `test_hr_name_capture.py` 同步（fake run_js 按 hr_present 返回 + patch sleep）。
  - 注：`agent` 关键词设置**已生效**（run 日志 loaded_url=query=agent），但该词 Boss 搜索 0 结果——建议换宽词。配额告警/暂停本轮**未撞上限**（rate_limited=False），真机验证待后续真达上限。

- 前端 IA 简化：自检并入自动化 navigator（2026-07-05，版本 2.0.6.1）
  - 「自检」navigator 取消，其三张卡（系统探针 / 定时常态自检 / 自检历史）并入「自动化」页的 SELF-CHECK 一节。IA 从 7 → 6 个 navigator。
  - `SelfCheck.tsx` default export → 命名 `SelfCheckSection`（去 max-w-3xl 适配全宽）；`Automation.tsx` import 并在 return 末尾加一节渲染。删 selfcheck 入口：`Sidebar` ITEMS + ShieldCheck import、`Topbar` title 映射、`app-context` Page 类型、`App.tsx` import + route。
  - build 通过（tsc 无悬空引用）。坑：Sidebar/Topbar Edit 的 old/new 用了 raw CJK（文件本是 \u 转义），但 Edit 自动归一化，验证 bare_CJK=0、\u 完整未污染。

- Boss 配额上限完整处理：120 接近告警 + 150 硬上限自动暂停定时/自检（2026-07-05，版本 2.0.5.1）
  - 延续 2.0.3 的 rate_limited（只停单轮 run）。本次补两级：
  - **120 接近告警**：`click_apply_button` 在配额提醒弹窗（"还剩N次"，N>0）时已返回 `quota_notice`；`apply.py` `ApplyStepOutput` 加 `quota_notice` 透传；`card_pipeline.py` applied 且带 notice → 发可见 `w1_quota_warning` 事件；`interpret.ts` 加标签「接近上限」+ 解读句「接近 Boss 每日沟通上限（原文）」。
  - **150 硬上限自动暂停**：`w1/pipeline.py` summary 加 `rate_limited`（仅硬上限 stop 时 True，区别于 max_cards stop）；`w1_runner.run_w1` 本就返回 summary；`server.py` `_run_apply_workflow` 接 summary，若 `rate_limited` → `_mark_rate_limited_today()`（记**中国日期**，因 Boss 按中国 00:00 重置配额）。闸门：`_scheduled_run` 对 `apply` + `_run_selfcheck_cycle` 整个 cycle，当日达上限则跳过并写 skipped_reason（W2 定时独立、不撞上限、不挡）。次日中国日期滚动自动解除；标志存内存（重启清除 = 至多多投一次即再触发重标）。
  - 验证：新增 `tests/test_apply_step_quota.py`（3 例）全绿；全量 pytest 绿；build 通过。坑：`server.py` 混用 raw CJK（如 line 552/594）与 `\u`，新增 skipped_reason 沿用 raw CJK；`interpret.ts` 是 `\u` 转义文件，用 Python 脚本插入避开 Edit 的 JSON 解码坑。

- W1 抓取 HR 名修复 → 打通两表关联死链（2026-07-05，版本 2.0.4.1）
  - 背景：排查"W1 投 150 只落库 63"时挖出更严重的独立 bug——`applications.hr_name` 399/400 空，而 `hr_conversations.hr_name` 全有值，`sync_application_status` 按 hr_name JOIN 永远 0 行（35 次调用 updated_count 全 0）。后果：W2→application 状态回填 / REJECTED→APPLIED 复活整条链**从上线就没生效过一次**。
  - 根因：W1 全程拿不到 HR 名。搜索卡结构上无 HR 名（注释确认）；详情面板**有**（`div.job-boss-info h2.name`），但 `read_panel_jd.py` 用 `timeout=0` 抓——JD 正文先渲染、HR 卡（job-boss-info）异步晚到，抓了个空（今日 1116 次全空）。且面板 h2.name 文本含子元素 `刚刚活跃`（span.boss-active-time），需剥离才能得纯名。
  - 真机排查：`open_browser` 无显式端口 = 默认 9222；用户登录浏览器无 CDP 端口连不上，遂自起有头登录浏览器导航搜索页→点开首卡 JD 面板→DrissionPage `run_js` dump DOM（坑：run_js 必须显式 `return`，IIFE 表达式返回 undefined）。定位真实 HR DOM = `div.job-boss-info h2.name`="王美雪\n刚刚活跃"、`div.job-boss-info .boss-info-attr`="友信美业 · 模特"。
  - 修复 3 处：`read_panel_jd.py`（HR 选择器改 `.job-boss-info h2.name` + `timeout=2` 等异步 + run_js 剥离 boss-active-time 取纯名）；`fetch_jd.py`（`FetchJDStepOutput` 加 `hr_name` 透传，原来只进日志 trace）；`card_pipeline.py`（upsert 用 `fetch.hr_name or card.hr_name`）。
  - 验证：新增 `tests/test_hr_name_capture.py`（5 例）全绿；全量 pytest 绿；build 通过。**真机端到端验证**：面板 `王美雪\n刚刚活跃`(8) → 提取 `王美雪`(3)，与 W2 会话表纯名格式（某names/某names…）一致。
  - 关键区分：这修的是**关联死链（问题B）**，不是今日计数漏记（问题A，W1 的 click_apply_button 识别问题，见下条）。两者独立。

- W1「今日投递」计数漏记根因修复 + Boss 配额上限识别停机（2026-07-04，版本 2.0.3.1）
  - 现象：用户报「今日投递只记 63，实际投了 150 触发 Boss 风控上限」。
  - 诊断（真实数据 + 失败截图，非猜测）：`count_today` SQL 无误，DB 今天确实只 63 条 APPLIED；今天 10 次 W1 run 聚合 `job_applied`=63 / `job_apply_failed`=456（全 dialog_blocked）。**铁证**：Boss 弹窗 08:17 自报「已与 120 位 BOSS 沟通」，我们全天仅 63 → Boss 计数器是 ground truth，证明大量 dialog_blocked 是真发出的招呼没识别成功。
  - 失败截图两种模式：①配额提醒弹窗「您今天已与120位BOSS沟通，还剩30次沟通机会哦 + 好」遮住成功弹窗；②过上限后静默无弹窗、按钮仍「立即沟通」。配额弹窗数字冻结跨 1 小时 = 从没被关掉（`handle_apply_dialog` 只关 `.greet-boss-dialog` 成功弹窗，不认温馨提示），滞留 DOM 挡住后续每张卡 → 刷出 456 假失败。
  - 根因：`click_apply_button` 只认单一成功信号（`.greet-boss-dialog`），凡不匹配一律 `dialog_blocked` → card_pipeline 当技术失败截图、不落库；配额提醒盖住成功弹窗时大量漏记。且 `rate_limited` 分支（apply.py/card_pipeline 都有）工具层从不返回 = 死代码。
  - 修复：`tools/browser/w1/click_apply_button.py` 重写投递后判定（多重成功信号）——①成功弹窗→applied；②配额提醒弹窗（含「沟通机会/您今天已与/达到上限/沟通次数」）→ 招呼已发出（Boss 已计数），立即点「好」关掉防污染，硬上限（达到上限/用完/明天再来/还剩0次）→ `rate_limited` 否则 `applied`(带 quota_notice)；③按钮翻转「立即沟通→继续沟通」→ applied(button_flip)；④都无→dialog_blocked。点击前若已有滞留配额弹窗 = 上张卡残留本卡没点 → 关掉 + 判 `stale_quota_dialog` 不计（防重现多记），硬上限则停机。
  - `pipeline/w1/steps/apply.py`：rate_limited 带 `message`。`pipeline/w1/card_pipeline.py`：rate_limited 发**可见** `w1_rate_limited` 事件（非红色失败）→ 本轮停机。`dashboard/frontend/src/components/workflow/interpret.ts`：新增 `w1_rate_limited` 标签「触发上限」+ 解读句「触发 Boss 每日沟通上限，已停止本轮投递」。
  - 验证：新增 `tests/test_click_apply_button.py`（12 例，FakePage 模拟点击前后 DOM 翻转）全绿；全量 pytest 绿；npm build 通过（tsc 无悬空引用）。坑：Edit 写 .ts 里 `\uXXXX` 被 JSON 解码，改用双反斜杠过比较 + Python `replace(r'\\u',r'\u')` 收敛。

- 架构页补「系统全景图」+「前后端怎么沟通」逐字节教程 + 清理死代码 + 版本规则改「动手前提醒」（2026-07-04，版本 2.0.2.3）
  - 起因：用户要「从架构页看懂前后端怎么运作」。核实发现「架构」Tab 名不副实——只有后端四层表，无前端、无全景、无连线。
  - `pages/StateMachine.tsx` 架构 Tab 顶部新增 `SystemOverview`（SVG 系统全景图：前端 ↔ FastAPI ↔ pipeline/services/tools ↔ 真实Chrome/Boss · SQLite · LLM，带 HTTP+SSE 连线 + 当前 agent 指示）+ `CommsDetail`（前后端通信小节）；原后端四层表降为第③块。
  - `CommsDetail` 按用户要的粒度做：JSON≠JSONL 澄清条（实时是一条条 JSON、落盘存档才是 JSONL）+ 折叠「逐字节实况」（点一次投递的真实 HTTP 请求/响应报文 + SSE 帧流，端点/字段全照 server.py 真码：`POST /api/workflow/apply`、`GET /api/workflow/stream`、8 字段事件）+ 完整来回四步 + 「不只 JSON」（multipart 上传 / PNG 截图）。
  - 清理：删死代码 `tracker.mark_no_response_rejected`（+2 测试；与「超时不判 REJECTED」的状态机重构冲突的僵尸）；删 design/ 下 17 个未跟踪调试脚本（inspect/debug/shot/verify）。保留 `docs/interview-prep-futu.md`（用户个人面试笔记）。
  - CLAUDE.md 版本管理：修正为四段 `X.Y.Z.N`（原文档误标三段、把自动递增的 N 说成 z）；规则改为「我在动手改代码前主动提醒你定 X/Y」，N 在 build 时自动跟上——把「发起版本判断」的责任从用户转移到我。
  - 坑：架构页 CJK 必须 `\uXXXX`，裸中文不进 tsx——全程用 Python 脚本把中文转 `\uXXXX` 后才写入（校验 0 处裸中文）；多行报文用「每行一 div + `whitespace-pre`」避开 `\n` 转义坑。
  - 验证：pytest tracker 子集 20/20 绿；build 三次（2.0.2.1→.3）无裸 CJK、tsc 无悬空引用。

- 「状态机」navigator 升级为「架构」navigator——从前端看懂整个项目（2026-07-04，版本 2.0.1.25）
  - `pages/StateMachine.tsx` 重构为 4 个页内 Tab：①**架构**（后端四层 tools/pipeline/services/dashboard：放什么·判据·代表文件 + ToolRegistry 粘合蓝框 + 端点铁律红框；顶部当前 agent 运行/空闲）②**流程**（W1/W2 双列编号时间轴，每步标 step·tool + 文件路径 + 一句说明；当前运行的 workflow 高亮脉冲）③**状态机**（保留原三状态机 + intent→stage→application 映射）④**数据模型**（SQLite 三表字段/关系 + LLM 路由链 ModelRouter→FallbackChain→5 Provider + 三条命名链 scoring/generation/analysis）
  - **部分接实况**：新增 `GET /api/architecture`（`server.py`）→ `tracker.get_lifecycle_counts()`（表行数 + by_status + by_stage，SQL 收在 tracker 层）+ `emitter.current_workflow`。前端各 Tab 叠加实时计数 pill（应聘状态/会话阶段/表行数）；实况为可选叠加，拉取失败页面照常渲染静态部分，每 15s 刷新
  - `api/index.ts` 加 `getArchitecture()` + `ArchitectureLive` 类型；Sidebar/Topbar navigator 更名 状态机→架构，图标 Workflow→Network（page id `lifecycle` 不变，避免动 localStorage 顺序）
  - 验证：pytest（tracker/stats/server 子集）全绿 + `get_lifecycle_counts()` 冒烟；build 通过；四个 Tab 独立浏览器截图确认渲染正确、实况计数生效（applications 298 / hr_conversations 784 / hr_messages 2128）
  - 坑复现：Write 大 CJK 文件不自动转义（1633 处），用 Python 脚本批量转 \uXXXX + `badge="X"` 双引号 JSX 属性改 `badge={'X'}`（属性双引号串不走 JS 转义）
  - 副产物：实况暴露 FOUND 落库之谜（见「待跟进」）

- Live 监控 4 项打磨：触发来源 + 运行参数入日志/标题 + 运行中指示器 + 评分颜色（2026-07-03，版本 2.0.1.22）
  - **触发来源**：run_start 之前没记谁触发的。新增 run_meta={trigger, params} 全链路——`services/run_logger.log_run_start(meta)` + `pipeline/run_logger`(meta) + `run_w1/run_w2` 加 `trigger` 参数并组 params + `emitter.start_workflow(meta)` 放进 start 事件 detail（live）+ `_parse_run_events` run_start→start detail（回放）。调用方标注：manual(默认)/scheduled(_scheduled_run)/selfcheck(_stage)/cli(main.py+run_e2e)，经 `overrides["_trigger"]` 传入 `_run_apply/check_workflow`
  - **前端 Live 标题栏**（WorkflowTrack RunView 顶部新 meta 条）：运行中指示器（animate-ping 绿点/已结束灰点）+「手动/定时/自检/命令行 触发」chip + 本次参数（w1: N卡·阈值M·演练? / w2: N会话·超时X天·清理Y天）。数据从 start 事件 detail 读
  - **评分颜色**（req）：`liveMsgCls` 让实时日志 job_scored 达标绿/未达标红（读 detail.above_threshold）、job_apply_failed 红；RecentCards 评分数字同款着色（scoreAbove helper）
  - 验证：pytest 全绿（run_logger/runner 签名改动无回归）；build 2.0.1.22，无裸 CJK
  - 坑：TRIGGER_LABELS/formatRunParams 等新增 CJK Write/Edit 未自动转义，仍用 chr(92) 脚本批量转 \uXXXX

- W1 投递技术失败：单独报错 + 失败截图诊断 + 计数修正（2026-07-03，版本 2.0.1.21）
  - 调查：投递成功的唯一后验 = 点击后 5s 内出现 `.greet-boss-dialog`/「已向Boss发送消息」成功弹窗（click_apply_button）。三种失败 button_not_found/dialog_blocked/error 原本①不写库(对)②**不报错(静默)**③**被误计入"投递成功"**（pipeline 把 SUCCESSFUL/DEGRADED 一律 applied+1）
  - 新 tool `tools/browser/w1/capture_screenshot.py`：DrissionPage `get_screenshot` 存 `data/apply_failures/<job_id>_<ts>.png`（诊断 Boss 验证码/风控拦截页/跳转到底显示什么）；guard 一切异常（截图不该拖垮流水线）
  - `card_pipeline`：投递失败分支（result∉{applied,already_chatting,rate_limited}）→ 截图 + 发可见 `job_apply_failed` 事件（带 result/screenshot/error）+ 返回 StepStatus.FAILED；rate_limited 仍作全局 stop 不算 per-job 失败
  - `pipeline.py`：计数修正——只有 SUCCESSFUL 才 applied+1；FAILED(投递失败)/DEGRADED(LLM评分错) 计入新增 `errors`，summary 加 errors
  - 后端 `GET /api/apply-failure/{name}`（FileResponse，防路径穿越）；前端 interpret.ts 加 job_apply_failed+APPLY_FAIL_LABELS、WorkflowTrack summary「失败」chip + 卡片红「投递失败」徽章 + 「查看投递失败截图」链接
  - 验证：新增 test_capture_screenshot（清洗/守门/捕获/异常）；pytest 全绿；build 2.0.1.21
  - 注：截图 headless 也可用；坑——interpret.ts Edit 插入把 export 挪错行(APPLY_FAIL_LABELS 抢了 SKIP_REASON_LABELS 的 export)，已修

- 状态机可视化 navigator + 会话「超时无回应」筛选 tab（2026-07-03，版本 2.0.1.20，纯前端）
  - 新 navigator「状态机」`pages/StateMachine.tsx`（侧边栏 Workflow 图标，自检与设置之间）：把三个状态机**全枚举值**列表化——①application status(5)②conversation stage(6)③LLM intent(6)，各含「含义/进入方式」+ 转移列表 + 三者映射表(intent→stage→application)。纯静态文档页，无后端数据；接线 app-context Page 加 lifecycle、App 路由、Sidebar ITEMS、Topbar PAGE_TITLES
  - 会话页新增筛选 tab「超时无回应」（sentinel `__stale__`，客户端筛 `stage=closed 且 intent≠rejection`——即 14 天停滞软标记而非 HR 明确拒绝），仿「待加微信」同款模式
  - 坑复现：Write 大 CJK 文件**不自动转义**（70 处裸中文）；用 `chr(92)` 避开源码反斜杠字面量的 Python 脚本批量转 \uXXXX（heredoc 里 `\\u` 仍被吞，必须 chr(92)）。Edit 小改动的 CJK 多被 harness 自动转义
  - 验证：build 2.0.1.20，无裸 CJK

- 清理死状态 CHATTING/SCORED + 重写 VALID_TRANSITIONS「装饰品表」与实际一致（2026-07-03，接上条）
  - 核实三个状态机：①application status ②conversation stage ③LLM intent，及三者映射（详见 memory [[w1-w2-status-revival]] / TECHNICAL）
  - CHATTING/SCORED 在 live 流程从不产生（sync 不映射 active→CHATTING；评分不达标不落库）→ 从 AppStatus 枚举删除；保留 FOUND（Job/ApplicationRecord 的投递前内存默认，从不落 applications 表）
  - 连带清理：`_TERMINAL_STATUSES`(classify)/`_DEDUP_STATUSES`(dedup) 去 CHATTING；`get_stats` 去 chatting 键；tracker init 加幂等迁移(历史 CHATTING→APPLIED、SCORED→FOUND，避免 get_stats KeyError)；前端 Dashboard/Jobs 状态标签、interpret.ts chatting 死标签删除
  - `VALID_TRANSITIONS`「装饰品表」真相：只在 upsert()/update_status() 打一条 warning、不阻止转移，真实转移全走 sync/purge 的 raw SQL 绕过它 → 重写成与实际 4 态一致（FOUND→APPLIED→INTERVIEWING→OFFER/REJECTED + REJECTED→APPLIED 复活 + OFFER→REJECTED），消除误导 warning；注释标明 advisory-only
  - 验证：更新 test_tracker（found_to_applied/applied_to_interviewing/offer_only_exits_to_rejected 等）、test_server fixture；pytest 全绿；build 2.0.1.18
  - 待续：会话「超时无回应」筛选 tab + 状态机可视化 navigator（下一步，编码这三张表）

- 超时/拒绝/复活状态机重构：超时不再判 REJECTED + 30天清理复活 + REJECTED收消息复活（2026-07-03，版本 2.0.1.17，后端为主）
  - 起因：用户澄清两个核心误解——①投递(W1)是纯动作、不需要HR回复，"投递后HR无回应"不该判 REJECTED；②REJECTED 目前混了三件事（真被拒 intent=rejection / 投递后无回应超时 / 会话陈旧关闭）
  - 目标状态机：APPLIED=已投(含在沟通)｜INTERVIEWING/OFFER=有进展｜REJECTED=**仅** HR明确拒绝(intent=rejection)｜超时=不改 application、只给会话打停滞软标记+提醒｜投递满30天无进展→**清理数据**重走流程｜REJECTED会话又收到消息→复活 APPLIED
  - 改动：
    - `mark_timeout_statuses.py`：**删除 application→REJECTED 整段**，只保留会话 no_response_days(14)天无消息→stage=closed 软标记（closed 不再连累 application）
    - `sync_application_status.py`：closed→REJECTED **仅** intent='rejection'；新增复活分支——application=REJECTED 且会话非 closed/offer（HR重新活跃）→APPLIED（raw SQL 覆写跨状态机）
    - 新 tool `purge_stale_applications.py`：applied_at 超 stale_conv_days(30)天且 status∉{INTERVIEWING,OFFER} → 级联删 application+hr_conversations+hr_messages（按 hr_name+company）；岗位再现→classify 查无→当新岗位重走 W1
    - `finalize_step.py`：去掉 no_response_rejected 处理；接入 purge（发 job_purged 事件）；保留 conv_timeout_closed
    - `config.yaml`：no_response_days=会话停滞软标记阈值(14)；stale_conv_days=30天清理阈值（复用现有参数，值刚好对齐；名字略偏，注释已说明）
    - 前端 `interpret.ts`：加 job_purged 标签「已清理」
  - 回退上轮方向错误的改动（超时→REJECTED "改得更准"）；VALID_TRANSITIONS[REJECTED]={APPLIED} 保留（复活+重投都用得上）
  - 验证：重写 test_finalize_w2_tools.py（sync 仅 rejection 判拒/复活、mark_timeout 不动 application、purge 删除/保护面试offer/REJECTED也清理）；pytest 全绿；build 2.0.1.17
  - 待续（本次未做）：①会话「超时无回应」筛选 tab（Chat页）②状态机可视化 navigator（前端新页）③W1 投递技术性超时→单独报错（用户要求留到最后排查）；遗留死代码 `tracker.mark_no_response_rejected` 未清

- 超时复活改按「最后一次会话消息时间」计时 + 纳入 CHATTING + REJECTED→APPLIED 转移合法化（2026-07-02，纯后端）
  - 起因：用户问「重复岗位怎么判定」「有没有 30 天自动复活」，要求先把 REJECTED 逻辑核清楚
  - 核实结论：①去重两层——classify 按 job_id 精确匹配 + check_content_duplicate 内容指纹 sha256(规范化标题|公司加密id|规范化JD)，两层终态集合刻意同步且都排除 REJECTED（可重投）；②没有「30天」，是 `no_response_days: 14`；③**关键发现：live 流程根本不产生 CHATTING 状态**——`sync_application_status_from_conversations` 只映射 interview/offer/closed→INTERVIEWING/OFFER/REJECTED，active 阶段不提升 APPLIED→CHATTING（CHATTING 仅存在于历史迁移数据）；会话↔应聘按 **hr_name+company** 关联（非 job_id）；④`upsert` 的 `_validate_transition` 返回值被忽略，ON CONFLICT 无条件覆写 status，故 REJECTED→APPLIED 一直能落库，只是每次误打 "invalid transition" warning
  - 改动（用户拍板：纳入 CHATTING，按最后消息时间计时）：
    - `tools/db/w2/mark_timeout_statuses.py`：applications UPDATE 从 `status='APPLIED' AND applied_at<=cutoff` 改为 `status IN ('APPLIED','CHATTING') AND COALESCE(MAX(hr_messages.created_at via hr_name+company join), applied_at) <= cutoff`。含义：距最后一条会话消息 N 天无活动才转 REJECTED；无消息（纯没回复的 APPLIED）回退按 applied_at；NULL 比较为假自动排除。这样 HR 刚回过的岗位不会被误判超时，聊过断联的也能复活重投
    - `services/tracker.py`：`VALID_TRANSITIONS[REJECTED] = {APPLIED}`（原为 set() 终态），使重投成为合法转移、消除误导 warning
    - `config.yaml`：no_response_days 注释更新为「距最后一次会话消息…」
  - 验证：新增 4 个测试（最近有消息不复活/聊过断联复活/CHATTING 复活/纯没回复仍按 applied_at 复活）；改 test_rejected_is_terminal→test_rejected_is_reappliable；pytest 全绿
  - 遗留：`tracker.mark_no_response_rejected`（days=3、跳过有会话者、走状态机）是死代码但逻辑与 live tool 分叉，未清理（未来陷阱）；no_response_days 仍 14（用户未定是否改 30）；「active→CHATTING 不提升」是独立缺口，未扩范围

- W1 跳过原因可见 + W1 总 summary（2026-07-02，版本 2.0.1.16）
  - 起因：用户报 W1 仍有不少跳过但前端看不到原因；且 W1 workflow 缺一个「看了多少/打分多少/投了多少」的总览
  - 诊断：跳过原因数据本就齐全（interpret.ts 的 SKIP_REASON_LABELS + prior_status，job_skipped 事件带 reason），但用户看的「逐职位卡片列表」只显示一个「跳过」徽章，不展开底部实时日志 firehose 就看不到原因；W1 summary 也从没接前端（`showRunSummary` 只给了 W2），且原 summary 无「打分数」
  - 后端：`CardPipeline.run` 返回值加 `scored`（第三个返回值，标记该卡是否真进了 LLM 评分阶段——拿到真实分数才算），`W1Pipeline` summary 增 `scored` 计数（cards_viewed/scored/applied/skipped/db_write_failures）
  - 前端 `WorkflowTrack.tsx`：①`SUMMARY_CHIPS` 按 workflow 分（w1: 查看/打分/投递/跳过 + 落库失败 chip>0 才显示），`showRunSummary` 对 w1 打开；②`skipReasonText(inst)` 从 job_skipped 业务事件（JSONL 回放）或 classify/apply 跳过 step 的 detail（实时无 debug SSE）取原因，逐职位卡片行显示「已投过 (CHATTING) / 评分未达标 / 重复岗位（换马甲）/ LLM 调用失败」+ tooltip
  - 注：跳过本身多为预期——最近一个月内投过的岗位仍是 APPLIED/CHATTING 终态，Boss 不过滤已投岗位会持续复现，只有 REJECTED（被拒/超时）才可重投；本次只做可见性，不改跳过逻辑
  - 坑复现：`interpret.ts` 导出 SKIP_REASON_LABELS 复用；WorkflowTrack 新增文案统一复用已转义的 STEP_LABELS（job_skipped/db_write_failed）+ ASCII 括号，避免再引入裸 CJK
  - 验证：pytest 全绿；build 通过 2.0.1.16，无裸 CJK

- W2 微信交换卡片自动同意 + HR 微信号强提醒 + hr_title 入库（2026-07-01，版本 2.0.1.13，端到端真机验证通过）
  - 起因：用户报「HR 请求交换微信」卡片没处理。查证 read_messages 其实已抓到（存为 hr 消息 `[卡片] 我想要和您交换微信…`）；真需求是①自动点「同意」②换微信后强提醒去加
  - 微信卡片 DOM（design/inspect_wechat_card.py 吸出）：`.message-dialog-both.message-card-wrap.green` 内 `.dialog-icon.weixin` + `.message-card-top-title` + `.card-btn`(拒绝/同意)。简历卡是 `.dialog-icon.resume`，两者都命中 read_messages 的 `.message-card-top-title` 分支
  - 后端（照简历卡片那套分层）：新 tool `tools/browser/w2/accept_wechat_card.py`（点 `.dialog-icon.weixin` 卡上未禁用的「同意」，DOM 层幂等——同意后 Boss 移除按钮、重跑 no-op，绝不重复同意）+ 新 step `pipeline/w2/steps/wechat.py` `WechatStep`（ConversationPipeline 在 read 之后、非 dry-run 时调用）。**关键：点同意成功后 `_rescan_and_persist` 带重试重扫 read_messages + write_hr_messages 落库**——因为 HR 点同意后立刻以卡片形式发来微信号 `[卡片] X的微信号\n<id>`，而 ReadStep 在点同意前就读完了，不重扫会漏
  - 决策（用户拍板）：换微信**不动 stage**（避免污染 offer 语义），提醒由前端从消息派生
  - 前端 `Chat.tsx`：`isWechatCard` 认「我想要和您交换微信」请求卡 + 「微信号」号码卡→都渲染独立绿卡；`wechatIdFrom(messages)` 从 `[卡片] X的微信号\n<id>` 抽出真实微信号；会话顶部强提醒横幅动态显示「HR 微信号：<id>，请尽快添加」（拿到号前回退通用提醒）
  - 顺带修 hr_title 从不入库的老 bug：`hr_conversations` 加 hr_title 列 + 迁移（仿 content_hash）、upsert 持久化（空值不覆盖）、`_row_to_hr_conv`、序列化、api 类型；会话标题从「公司 · HR名」→「公司 · HR名 · HR职位」（extract_conversation_list 早就抓了 hr_title，但 upsert 一直丢弃）。注：conv_id 实际是 sha256(hr_name|company)，不含 hr_title，故加列不影响会话身份
  - 验证：新增 test_accept_wechat_card / test_wechat_step，pytest 391 全绿；build 通过 2.0.1.13。端到端真机（用户 `!` 前缀自跑 design/verify_wechat_agree.py）：真卡 clicked:True → HR 发 `[卡片] 某names的微信号\nASDQWERPP` → 重扫落库 persisted_new:1（DB 确认）
  - 坑：Edit 工具写 `\uXXXX` 会被 JSON 解码成真字符；可靠做法=Edit 放 ASCII 占位符 → Python heredoc（保 UTF-8）replace 成 `\uXXXX`；PowerShell `Set-Content -Encoding utf8`(PS5.1) 会加 BOM 需去

- 简历功能：三期设计确认 + 功能一后端落地（2026-06-29，进行中）
  - 需求拆三个功能，细节逐项与用户确认，记入 `design/resume_feature.md`：①简历解析+段落化（积木库）②岗位特化生成（简历+招呼语，含预制模板）③发送（招呼语走 W3、简历发送先调研 Boss 附件上传）
  - 关键决策：固定类别（基本信息固定字段 + 教育/实习/项目/技能/获奖=块列表，一段经历=一块）；resume_blocks.yaml 单一可编辑源、上传仅预填；每块 LLM 生成「简单概括」；按需生成+存组合方案+按需渲染 PDF；预制模板关键词匹配→LLM 微调；招呼语 W1 投递后生成→审批→W3 发；**PDF 统一用 Chromium CDP `Page.printToPDF`（WeasyPrint 在本机缺 GTK libgobject 装不上，已验证 CDP 可行）**
  - 功能一后端（✅ pytest 绿）：`services/resume_blocks.py`（BLOCK_CATEGORIES + empty/load/save/is_available + `build_blocks`：LLM 把 resume_base+自我描述整理成结构化块库含 summary）；端点 GET/PUT `/api/resume/blocks`（读/整存，白名单清洗）、POST `/api/resume/blocks/build`（解析预填）
  - 功能一前端（✅ build 2.0.1.6 + 截图确认）：新建独立「简历」navigator `pages/Resume.tsx`（FlowCV 式：基本信息6固定字段 + 5类别块增删改/↑↓排序 + 每块要点多行/概括 + 自我描述输入 +「从简历解析预填」+「保存」）；api 加 ResumeBlocks 类型与 get/save/build 方法；接线 app-context Page 'resume'、App、Sidebar(FileText 图标)、Topbar
  - 功能二（✅ build 2.0.1.7 + 截图/DOM 确认）：岗位特化生成 + 预制模板
    - 后端 `services/resume_tailor.py`：预制模板存取(`resume_templates.yaml`)+关键词匹配(`match_template`，命中词最多胜)；`generate_resume_sections`(LLM 从积木库挑/排/微调出 sections，模板命中作起点提示)；`generate_greeting`(单独 LLM)；组合方案存 `resume_plans.yaml`(按 job_id，resume/greeting 分开挂)；`render_resume_html`+`render_html_to_pdf`(**Chromium CDP printToPDF**，独立端口 9920/临时 profile，不碰 Boss 浏览器)
    - 端点：GET/PUT `/api/resume/templates`；POST `/api/resume/tailor/resume`、`/api/resume/tailor/greeting`(各自按 job 生成并存方案)；GET `/api/resume/plan/{job_id}`、`/api/resume/plan/{job_id}/pdf`(渲染返回 PDF)
    - 前端（简历页新增两卡）：`TemplatesCard`(模板增删改：名称/关键词/建议块组合 csv/招呼语风格 + 保存)、`TailorCard`(选已投递岗位 → 生成定制简历/招呼语 → 展示 sections+招呼语 + 预览/下载 PDF)；api 加 ResumeTemplate/ResumePlan 类型与 get/save/tailor/plan 方法
  - 待续：功能三（招呼语 W1 投递后生成→审批→W3 发；简历发送先调研 Boss 附件上传）

- 自检独立成 navigator + 每日投递上限 dashboard 可编辑（2026-06-29）
  - 自检从设置页挪出，新建独立 navigator「自检」（侧边栏 ShieldCheck 图标，自动化与设置之间）：新 `pages/SelfCheck.tsx`（ProbeCard 系统探针 + ScheduledCard 定时常态自检 + HistoryCard 自检历史20条，更突出）；接线 `app-context` Page 加 selfcheck、`App.tsx` 路由、`Sidebar` ITEMS、`Topbar` PAGE_TITLES；从 `Settings.tsx` 删除原两组件+import（按行精确删 515-676）
  - 每日投递上限（Boss 硬上限）：dashboard「今日投递」卡原仅显示，现「日上限 N ✎ 改」可点击编辑→`updateSchedule({daily_limit})`→刷新（与自动化页同一存储；`/api/stats` 和 `/api/schedule` 的 daily_limit 都走 resolve_params("w1")）。`StatCard` 加 `descNode` prop、`load` 提为 useCallback 供编辑后刷新
  - 验证：build→2.0.1.5（Topbar PAGE_TITLES 缺 selfcheck 导致 TS7053，已补）；截图确认自检页三卡渲染+历史、dashboard 上限可编辑入口

- 系统自检模块 第二/三层：定时常态自检（真跑 W1+W2）（2026-06-29）
  - 需求：每 12h 自动真跑一次 W1(投10)+W2(全量max=300)，只管 W1/W2（W3 手动不纳入）；先探针全绿再串行真跑；既是常态化运行也是健康自检
  - 后端：`_run_selfcheck_cycle`（探针→W1→W2 串行，复用 run_probes/_run_apply_workflow/_run_check_workflow；开头 `current_workflow` 互斥守门；探针不过则跳过真跑；写 `data/selfcheck_log.jsonl`）；调度集成——`_SCHEDULE_DEFAULTS["selfcheck"]`(enabled/interval_minutes=720/w1_max=10/w2_max=300/with_probes) + `_load_schedule_config`/`_build_scheduler`(加 `selfcheck_interval` 间隔任务，调 `_scheduled_selfcheck`)/PUT `/api/schedule` 接受 selfcheck 节；端点 `POST /api/selfcheck/cycle`(手动触发,后台) + `GET /api/selfcheck/history`
  - 前端：`Settings.tsx` 新增 `ScheduledSelfCheckCard`（设置→环境&Session）：启用/间隔(小时)/W1投递数/W2上限/先跑探针 配置（存 `updateSchedule({selfcheck})`）+「立即跑一次完整自检」+ 自检历史列表（每条 5 阶段 ✓/✗）
  - 验证：pytest 全绿；build→2.0.1.3；实测手动 cycle(w1=1,w2=3) 5 阶段全绿(探针14s/DB/LLM→W1 20s→W2 79s)、写库、`/api/selfcheck/history` 可读；前端截图确认配置+历史渲染
  - 坑：JSX **裸文本节点**里的 `·` 被 escape_cjk 转成字面 `·`（不被解释）——须包成 JS 字符串 `{' · '}`（同 JSX 属性坑：转义只在 JS 字符串/JSX 文本由 esbuild 处理，裸文本节点的 `\u` 不解释）

- 系统自检模块 第一层：轻量探针（2026-06-29）
  - 目的：一键确认系统各环节正常、坏了定位在哪层（登录/浏览器/DB/LLM）
  - 后端 `services/selfcheck.py`（已存在的探针核心）：`_probe_browser_session`（复用 `open_browser`+`VerifySessionStep`）/`_probe_db`（tracker 只读）/`_probe_llm`（`ModelRouter.complete` 最小 prompt，注意返回 tuple(text,provider)）；各返回 `{name,label,ok,duration_ms,detail}`，只读无副作用
  - 端点 `POST /api/selfcheck`：运行中（`emitter.current_workflow`）拒绝（浏览器探针会撞车）；`logger.info` 留痕
  - 前端 `Settings.tsx` 新增 `SelfCheckCard`（设置→环境&Session 顶部）：一键运行 + 分项绿/红 + 详情 + 耗时
  - 验证：pytest test_server 全过；build→2.0.1.1；端点实测三项全绿（浏览器+登录14s/DB 4ms/LLM ollama 5s）；前端截图确认面板渲染 + 全绿
  - 待续：②流程 dry 冒烟（W1/W2/W3 dry，max=1）③实际验证（数量可配，复用现有 workflow runner）—— 用户要的「可配置每次实际验证多少」

- 会话卡片显示「距上次沟通 N 天」+ 排查会话未关闭（2026-06-27）
  - 需求2（已做）：后端 `_serialize_conversation` 加 `last_msg_at`（= 最后一条 `hr_messages.created_at`，无消息回退会话创建时间）；前端 `Chat.tsx` 加 `daysSinceContact`，会话卡片 HR 名右侧显示「N 天前/今天」，>7 天标琥珀色。注意：`last_msg_at` 是「最后记录消息的入库时间」（非真实 msg_time，那个格式不可靠；W2 重扫写新消息会刷新），对多数会话≈最后活动时间
  - 需求1（已做，用户定 14 天/按活动）：会话关闭从「按 `created_at` 行龄」改为「按最后活动天数」——`mark_timeout_statuses.py` 的 stale-close 用 `COALESCE(MAX(hr_messages.created_at), created_at) <= now - stale_conv_days`；`stale_conv_days` 默认 30→14（config.yaml + tool 默认）。根因：原按 created_at（注释：T030 表无 updated_at），且阈值 30、现有会话最老仅 16 天，故 398 个 idle>7 的一个都没关。修后模拟「下次 W2 关闭 110 个 idle>14」。`no_response_days(14)` 仍只标 application REJECTED（两者现都 14 天，语义一致：投递/沟通 14 天无果即放弃）。pytest 全绿

- v2.0.1.0 里程碑：自动化完工（2026-06-27）
  - 「自动化」整块功能闭环交付：① 工作流监控/回放——控制台 live + 「日志」页历史回放共用 `RunView`，JSONL 完整回放、人话解读（`interpret.ts`）、每卡片终态正确（投递/跳过/已处理/已关闭，0「等待」幽灵）；② 定时调度——interval/cron 触发、互斥跳过、重启恢复全部 e2e 实测通过；③ 参数体系——调度 + 手动面板统一到 canonical 键
  - 版本 `2.0.0 → 2.0.1`（功能版递增，用户确认）。下方为累积细节

- 控制台 WorkflowPanel 手动面板参数对齐 canonical（2026-06-27）
  - 全前端页面截图逐一确认渲染正常（控制台/职位/会话/日志/自动化/设置，无白屏/报错）
  - 发现控制台「投递参数」面板还显示废键标签 `apply_limit`/`days`（功能正常——加载/设默认早已走 canonical max_cards/no_response_days，触发靠端点 fallback）。对齐到 canonical 技术名（匹配面板既有技术标签风格）：标签 `apply_limit`→`max_cards`、`days`→`no_response_days`；触发载荷 `buildApplyPayload` 与 3 处 `triggerCheckWorkflow` 改发 canonical 键，不再依赖 fallback
  - build→2.0.0.23

- 定时调度端到端实测通过（2026-06-27，闭合长期「调度未实测」缺口）
  - interval（间隔）触发：设 1 分钟 + dry_run + max_cards=2，22:31:08 准点自动 `_scheduled_run` → W1 跑 19s → `schedule_log` 记 `trigger_type=scheduler/apply/success`
  - cron（定时）触发：设 22:34，准点触发 → W1 跑 20s → success 入库；`_next_runs.apply` 正确算出 22:34:00
  - 互斥跳过 live 实测：W2 手动 dry 跑着占 `current_workflow`，W1 间隔到点撞上 → `result=skipped / skipped_reason="w2 正在运行" / duration=0` ✅
  - 重启恢复 live 实测：启用 W1 间隔后真重启 uvicorn 进程 → 新进程从 schedule.yaml 恢复 `interval_enabled` + startup 自动重建调度器；且 `next_interval` 从「上次运行+间隔」续上（早于「重启时刻+间隔」），证明 `restore_interval_times` 连续性正确 ✅
  - 其余验证项：参数透传（canonical + dry_run 生效，全程 dry 无真投递）、next_runs/next_interval_runs 计算、关闭后 jobs 清空
  - 测试用安全姿势：dry_run=true + headless + max_cards 小，链路验证不产生真实副作用；测后已清理调度配置（全关、times 清空、参数复位）
  - 踩坑：`uvicorn --reload` 的 worker 是 multiprocessing 子进程（cmdline 不含 uvicorn），按 cmdline 杀只杀到 reloader、worker 会被重生；本会话多次重启累积了孤儿 reloader。清理需按「8765 端口占用者 + cmdline 含 uvicorn/multiprocessing/spawn_main」循环 Stop-Process

- W2 finalize 关闭移出循环列表 + 调度参数 schema 对齐 canonical（2026-06-26）
  - ①（前端）：「逐会话循环」列表只保留真正进入 ConversationPipeline 的实例（有 LOOP_STEPS 节点）；finalize 阶段批量关闭（`conv_timeout_closed`/`job_no_response_rejected`，有 conv_id/job_id scope 但没循环步骤）不再每个冒一张卡，改为列表计数旁的「超时关闭 N」汇总。`processed` 改为 `cards.length`，删死代码 `projectStatuses`。实测 w2_20260626_1416：循环列表从 250 张降到 7 张（6 跳过 + 1 进循环又被关的已关闭），右上「7 · 超时关闭 243」
  - ②（前后端）：调度参数 schema 对齐到 workflow canonical 键。后端 `_SCHEDULE_DEFAULTS` 改 W1=`score_threshold/max_cards/dry_run/headless`、W2=`max_conversations/no_response_days/stale_conv_days/dry_run/headless`；`_load_schedule_config` 只拷贝当前 schema 的键，丢弃老 schedule.yaml 的废键（`limit/apply_limit/days/generate_resume`），下次保存即收敛。前端 `Automation.tsx` 的 `APPLY_PARAMS`/`CHECK_PARAMS` spec + 默认 state 同步 canonical。`trigger_check` 已转发 `no_response_days/stale_conv_days/dry_run`（兼容旧 `days`）。背景：之前调度存废键，被 `resolve_params` 静默忽略，「参数配置」面板编辑不生效（误导）
  - 验证：全量 pytest 绿；build→2.0.0.22；GET /api/schedule 确认 params 已 canonical（废键消失，保留用户设的 headless/max_conversations）；截图确认 ① 循环列表清爽

- 默认参数实跑 W1/W2 验证 + 修 W2 回放幽灵「等待」卡片（2026-06-26）
  - 实跑（默认参数、真投递）：W1 `w1_20260625_1754` 15 职位→6 投递 + 9 跳过；W2 `w2_20260625_1757` →8 发简历 + 40 跳过 + 5 超时关闭。两条 run JSONL 经端点分析**终态全部正确、0 个「等待」**
  - 验证 W1 修复：新 run 的 classify/apply/upsert terminal 事件已落盘（跳过职位 classify=skipped、投递职位四步全 done），循环明细节点真实，不再 pending/等待
  - 发现并修 W2 两类「等待」幽灵（回放专属，实时 SSE 本无）：① `filter_decision`（per-会话过滤决策，`visible=False` 只写文件）被回放端点全量吐出 → 每个无变化会话冒一个「等待」卡（182 实例里 ~158 个）；② finalize 阶段 `conv_timeout_closed`/`job_no_response_rejected`（真实关闭动作）无循环步骤 → 落到「等待」
  - 修复：① 回放端点 `_parse_run_events` 跳过 `visible=False` 业务事件（镜像实时流）——`run_logger.log_business_event` 持久化 `visible` 字段（通用，未来 file-only 事件自动排除）+ 对老日志按名兜底跳 `filter_decision`；② 前端 `cardResult` 给 finalize 关闭事件徽章「已关闭」而非「等待」（真实结果，不隐藏）+ interpret.ts 加人话
  - 验证：全量 pytest 绿；build→2.0.0.21；W1 0等待、W2 0等待（全部 投递/跳过/发简历/已关闭 等有意义终态）
  - 注意：老 JSONL 无 `visible` 字段，靠按名兜底（仅 filter_decision）；新 run 通用生效

- 修 W1 监控「跳过职位显示等待 / 循环明细缺 terminal 状态」（2026-06-25）
  - 现象（用户在日志页发现）：① W1 有些卡片徽章是「等待」其实已终态 ② 点进循环明细只有「分类」、后面 step 全灰
  - 根因：W1 `CardPipeline` 的 classify/upsert 是裸 `reg.call`+`set_context`，**无 terminal `log_step`**；而 `set_context` emit 的 running 是 SSE-only 不落盘（`run_logger.emit_step_running`）。被分类跳过/评分未过的职位结果只写在 business event（`job_skipped`，status=info），`cardResult` 只看 step 的 done/skipped → 全落空 fallback「等待」；循环明细里 classify 因无 terminal step 停 pending(灰)
  - 修复（两路）：① 前端 `cardResult` 加 business-event 兜底（`inst.steps.has('job_applied')`→投递、`has('job_skipped')`→跳过）——business event 所有 run 都落盘，**老日志立刻正确、无需重跑** ② 后端 `card_pipeline.py` 给 classify（skip→skipped / 继续→successful）、未投递（llm_error/score_below → apply skipped）、upsert（successful/failed）补 terminal `log_step`——**新 run** 的循环明细节点状态真实，且顺带修了控制台 live 模式 classify 永远黄(running)的问题
  - 验证：全量 pytest 绿；build 通过（→2.0.0.20）；WorkflowTrack 转义后 non-ascii=0
  - 注意：老 JSONL 不含新 terminal 事件，循环明细里 classify/upsert 仍 pending（但徽章已由 business-event 兜底修正）；新 run 完整生效

- 「日志」页改用控制台同款 live 视图（2026-06-25，需求 2 真正落地）
  - 澄清需求：上一条「解读层」改在了控制台 LiveLog（跑偏）；用户真正要的是——在「日志」navigator 里把每次 run 的 JSONL 解析成类似 live 的可读视图，而非平铺 raw JSON。现「日志」详情现状是 Flow（英文 step/tool/status + JSON.stringify）/ Decisions（半英文摘要 + raw JSON），可读性差
  - 方案（与用户确认）：复用控制台可视化；原始 JSON 保留为下钻；文案重可读、不过度口语化
  - 抽共享组件：把 `WorkflowTrack` 的可视化主体抽成 `export function RunView({events, workflowId, summary})`（纯展示——「本次运行·非循环」+ 逐职位/会话循环 master-detail + summary chips + 人话 LiveLog；自带 selectedKey 选择态，调用方用 key= 重挂以重置）。`WorkflowCard` 瘦身为控制层（运行指示/中止/卡死检测/实时 vs JSONL 回放数据决策/summary 拉取）+ `<RunView/>`
  - Logs 页接入：详情默认新增「概览」tab = `<RunView events={getRunEvents 回放} workflowId={run.pipeline} summary={run.summary}/>`（与控制台一致的人话树视图）；保留 Flow/Decisions 两 tab 作为原始 JSON 下钻。选中 run 时并行拉 getRunEvents（概览）+ getRunDetail（原始）
  - 复用既有：`interpret.ts`（interpretEvent 人话）+ `/api/runs/{run_id}/events`（层 1 端点）+ `buildTree`/`InstanceDetail` 直接复用，上一轮没白做
  - CJK 铁律：RunView 主体 + Logs「概览」先写裸 CJK 再 python 字节级转 `\uXXXX`，两文件 non-ascii=0
  - 验证：build 通过（→2.0.0.19，tsc 无悬空引用）；服务存活、events 端点回放 554 条正常
  - 待跟进：用户在「日志」页确认概览视图可读性 + 文案是否需更精炼

- 工作流监控 log 解读函数 + W2「不发简历卡等待」修复（2026-06-25，被上一条复用）
  - 解读层（需求 2）：新增前端纯函数 `components/workflow/interpret.ts`——`interpretEvent(ev)` 把原始事件（step/tool/业务事件）翻译成人话（如 `Step analyze: successful`→「分析 完成」、`job_scored`→「评分 82（达标）· 技术栈匹配」、`job_skipped`→「跳过：分类判定不投」、`intent_analyzed`→「HR 意图：约面试」、`stage_advanced`→「阶段推进：沟通中 → 已发简历」）。人话的料读 `ev.detail`（业务事件带 score/intent/stage），实时 SSE 与 JSONL 回放共用同一套，显示一致。含 STEP/TOOL/INTENT/STAGE/SKIP_REASON 五张中文标签表。`LiveLog` 折叠头与展开行均改用 `interpretEvent`
  - 修问题 2（W2 不发简历卡「等待」）：根因——`ResumeStep` 仅在 `needs_resume` 时运行、不跑就不 emit，会话正常处理完（navigate/read/analyze done、resume 永远 pending、无 running）时 `cardResult` 成功分支全落空 → fallback「等待」误导。修复：`cardResult` 在 skipped 之后加一档「任意 step done 且无 running → 已处理」（teal），让「分析完成·无需动作」显示正常终态而非「等待」；W1/W3 不受影响（无 analyze 但同样受益于「已处理」兜底）
  - 配套：`buildTree` 的 StepNode/ToolNode 新增 `detail` 字段（归约时存 `ev.detail`），供 cardResult/extractScore 取业务数据；`extractScore` 改为优先读 `job_scored` 的 `detail.score`（权威，回放有），正则兜底——此前从 `score_job` tool message 抓分数实际抓不到（message 不含分数）
  - CJK 铁律：interpret.ts 全中文，先写裸 CJK 再用 `python` 字节级转 `\uXXXX`（scratchpad/escape_cjk.py，用 chr(92) 构造反斜杠）；WorkflowTrack 改动后同样幂等转义，两文件 non-ascii=0
  - 验证：build 通过（→2.0.0.18，tsc 无悬空引用）；端点取真实 W1/W2 run 抽查 business events 的 detail 含 score/reason/intent/result，解读函数字段对得上
  - 待跟进：用户在浏览器确认两层效果（层 1 回放 + 层 2 人话日志 + 「已处理」徽章）

- 工作流监控「上次运行完整回放」数据层（2026-06-25，需求拆分第 1 层）
  - 背景：`WorkflowTrack` 此前只吃实时 SSE，数据落地受 `App.tsx` 全局 `progressEvents.slice(-200)` 限制（跨 workflow 共享、服务重启即失），导致「workflow 结束后看不到上一次完整内容」。根因不是切 tab 清除，是 200 条共享上限被后续事件挤出
  - 方案（与用户确认）：分两层——① 数据回放（本次）② log 人话解读（前端纯函数，下一轮）。二者不合并但共享同一事件 schema。完整且持久的数据源是 run JSONL（`logs/runs/*.jsonl`），不是内存 buffer
  - 后端：新增 `GET /api/runs/{run_id}/events`，把 JSONL 拍平成前端 `ProgressEvent[]`（领域 status→ui status 复用 `pipeline.run_logger._ui_status` 单一真相源、ISO→epoch、补 workflow 字段、合成与 SSE 一致的 message；business events 以 status=info 带 detail 透出，供下一轮解读层用）
  - 前端：`api` 加 `getRunEvents`；`WorkflowCard` 运行中用实时 SSE、停跑时拉该 workflow 最近一次 run 的 JSONL 回放（`displayEvents = isRunning ? events : replayEvents`），喂同一个 `buildTree`。顺带消解了旧的 200 上限丢历史问题 + 服务重启历史仍在
  - 验证：pytest test_server 全过；build 通过（→2.0.0.17）；端点冒烟——最新 W2 run 回放 554 条完整事件（vs 内存上限 200），status/ts/workflow 结构正确
  - 待跟进：① 层 2 log 解读（前端 `interpret(event)` 纯函数，实时/回放共用）② 此前发现的 W2「不发简历卡等待」bug（`cardResult` 缺会话完成终态），可在层 2 一并修

- 清理死代码 + Sidebar navigator 支持拖动排序（2026-06-23）
  - 死代码清理：删除 W2 已不被调用的 `pipeline/w2/steps/reply.py`（`ReplyStep`——发回复边界已收口到 W3，grep 确认无任何 import，仅测试/注释里有文字提及）及其 `__pycache__`；删除 W3 残留的 `tools/browser/w3/__pycache__/verify_reply_delivered.*.pyc`（源 `.py` 早已删除、只剩 pyc 缓存）
  - Sidebar 拖动排序：`Sidebar.tsx` 6 个 navigator 改为原生 HTML5 drag-and-drop 可拖动重排（不引第三方拖拽库，符合 simplicity first），顺序持久化到 localStorage `ojf_nav_order`（与 `useDevLabels` 同套路）。`loadNavOrder` 对存储做白名单过滤 + 缺失补位，未来增删 navigator 自动兼容；拖动中项 `opacity-40`、目标项 `ring-signal-blue` 指示线、hover 显示 `GripVertical` 手柄可供性；纯 ASCII，title 保持 `\uXXXX`
  - 验证：pytest 全绿、`npm run build` tsc 无悬空引用（版本自增 2.0.0.15->2.0.0.16）、Python 字节级确认 Sidebar.tsx 无裸 CJK

- 新增「拒绝岗位」功能 + W1/W2 有头实操跑通（2026-06-22）
  - 实操：W1 有头（max_cards=15）投出 11 条；W2 有头（max_conversations=300）起草 26 条待审批回复；全程登录态稳。澄清此前「无头掉登录」的推断有误——实为登录态太久未用自然过期，与 headless 无关（已撤回错误记忆）
  - 「拒绝岗位」功能（区别于已有「驳回」=`dismiss-reply`，后者仅拒绝单条草稿、会话仍留活跃列表）：后端新增 `POST /api/conversations/{conv_id}/reject`（`reset_hr_conversation_stage`→`closed` + `update_reply_approval`→`dismissed`）；前端 `api/index.ts` 加 `rejectConversation`、`Chat.tsx` 会话头部加红色「✕ 拒绝岗位」按钮 + 二次确认 + 乐观从列表移除
  - 语义：关闭整个会话、不再起草回复；若该 HR 之后又发新消息，仍按现有统一机制（`filter_conversations` 核心逻辑未改）重新分析一次但不再生成草稿
  - 验证：pytest 71 passed（test_server.py）、build 通过版本→2.0.0.15、reject 端点冒烟返回自有 handler 格式；server 重启补上 `--reload`

- 工作流监控改造：单框 W1/W2/W3 标签切换 + per-instance 循环钻取（2026-06-21）
  - 背景：原 `WorkflowTrack` 把 W1/W2/W3 三张卡片纵向堆叠，每个界面太小；且单卡内把所有循环实例压成一个聚合骨架投影，看不到单个职位/会话在循环里的 step/tool 明细
  - 改动一（per-instance 钻取）：新增 `InstanceDetail` 组件（接受可空实例，空=全 pending 骨架），渲染单个循环实例自己的 step→tool 链路（状态点 + 真实消息，如评分/JD/投递结果，未跑到的按 SKELETON 模板灰显 pending）；`RecentCards` 列表项改为可点选按钮；单卡布局重构为 master-detail 左右分栏（左=本次 run 全部实例可滑动列表，右=选中实例的循环明细）；**默认跟随最新**正在处理的实例，手动点选则固定、可一键回到跟随。删除不再使用的聚合 `SkeletonProjection`
  - 改动二（单框 tab 切换）：W1/W2/W3 有互斥锁（同时只跑一个），故合并为单个全尺寸显示框 + 顶部 W1/W2/W3 标签栏（badge + 运行中绿点）；`useEffect` 监听 `workflowRunning`，某 workflow 一开始跑就自动切到它；`key={tab}` 让切换时重置 per-instance 选择。每个 workflow 现拥有约三倍纵向空间
  - 改动五（标签全局开关 + 写入守则）：新增 `hooks/useDevLabels.ts`（模块级 store + `useSyncExternalStore`，localStorage `ojf_dev_labels` 持久化，默认 ON，无需 Provider），`DevLabel` 关闭时 `return null`；Topbar 加「标签 ON/OFF」按钮一键切换全站显隐。约定写入 `docs/frontend.md` 新增「五、调试辅助：组件名标签（DevLabel）」（用法/开关/命名约定/复用组件透传 dev prop）。注：Topbar 新增 CJK 经 Edit 写入后仍是裸 CJK（Edit 视 \u↔CJK 等价、无法转义），改用 `python` 字节级把非 ASCII 全转 `\uXXXX`（验证 non-ascii=0）——重申既有坑：TSX 裸 CJK 须 python/PowerShell 字节级转，Edit 转不了
  - 改动四（全站组件名标签）：新增可复用 `components/dev/DevLabel.tsx`（半透明蓝色 pill，`inline` 跟随区块标题 / `float` 浮于 `relative` 父级右上角，`pointer-events-none` 不挡操作），给全站 6 个页面 + 工作流监控 + 布局 chrome 的主要区块挂上对应 React 组件名标签，方便非前端用户指认沟通。覆盖：WorkflowTrack（WorkflowTabs/RunSteps/RecentCards/InstanceDetail/LiveLog）、WorkflowPanel、Dashboard（ApproveBar/StatCard/StatusBar）、Jobs（StatusFilter/JobsTable/Pagination/JobDetailDialog）、Chat（QueuedBar/ConversationList/MessageThread/ReplyApproval）、Logs（RunList/RunDetail）、Automation（ScheduleCard/WorkflowScheduleSection/ScheduleLogCard）、Settings（Card 加 `dev` prop → PreferencesTab/ModelTab/SystemStatus/SessionCard/LLMProviders/ResumeUpload）、Sidebar、Topbar
  - 改动三（非循环步骤提到循环外 + 加大显示区）：按各 `pipeline/w{1,2,3}/*.py` 真实结构拆分 `RUN_STEPS`（run 级，scope={}：W1 navigate/scan、W2 scan/finalize、W3 scan）与 `LOOP_STEPS`（per-instance：W1 classify/fetch_jd/apply/upsert、W2 navigate/read/analyze/resume、W3 locate/send/verify）。run 级步骤取 `__run__` 实例单独渲染在「本次运行·非循环」区（循环外，只出现一次）；右侧循环明细只渲染 LOOP_STEPS（此前错把 scan/finalize 塞进每个实例）。`InstanceDetail` 重构为接受显式 `stepKeys`，run 级/循环级复用同一组件；删除不再引用的 `STEP_ORDER`。循环 master-detail 高度 240→360px、左列表 200→220px
  - 纯前端改动，后端零改（循环数据后端早已齐全：`buildTree` 已按 workflow→实例(job_id/conv_id)→step→tool 归约，W3 `send_pipeline.py` 也逐会话 `set_context(scope={conv_id,company})`）
  - 验证：`npm run build` 通过（tsc 无悬空引用）；字节级 grep 确认无裸 CJK / box-drawing（全 `\uXXXX`，符合 GBK 工具链铁律）

- v2.0.0 里程碑：全新代码重构 + 前端重设计 + W1/W2/W3 三流程拆分（2026-06-21）
  - **里程碑性质**：自早期 AI 工厂流程构建的初版以来，整个系统经过完整重构落定，升大版本 `1.x → 2.0.0`（`version.ts` 第4段为 build 自增号）。本条是对累积成果的归档式总结，逐项细节见下方历史条目
  - **代码架构重构**：退役旧 `orchestrator.py`/`scheduler.py`/单体 `browser_agent.py`（~2400 行）；确立后端四层分层铁律（tool 副作用 / step 工作流阶段 / service 共享基建 / 薄端点），浏览器层收敛为 `browser_context`（启动）+ `BrowserSession`（交互单例）+ `tools/browser`（流水线操作）+ `VerifySessionStep`（唯一登录校验）；tools/ 四层分包（browser/db/llm/biz_logic），经 `registry.call` 统一 trace/SSE；配置三层模型（系统/用户偏好/workflow 运行参数）
  - **前端重设计**：信息架构 7→6 navigator（控制台/职位/会话/日志/自动化/设置），设计系统「Apple-refined Telemetry」（Apple 令牌 + IBM Plex Mono 遥测层 + 信号色）；全量消重（配置/Session/LLM/审批各 2→1）；可视化从地铁图重构为 scope×step×tool 三层树
  - **W1/W2/W3 三流程拆分**：W1 投递（搜索→分类→抓 JD→评分→投递→落库）；W2 检查回应（扫描会话→读取→意图分析→按需发简历→落库→收尾，**不再发回复**）；W3 发送已批准回复（搜索定位→发送→重扫验证+回写 DB→标记 sent），边界清晰收口
  - **三流程实测状态**：W1 ✅ 可跑/落库/调度/实测；W2 ✅ 全绿；W3 ✅ 核心链路 locate→send→新verify→回写 端到端实测通过（某companies/李女士，run 日志 `logs/runs/w3_20260620_1055.jsonl` 为证）
  - **W3 剩余缺口**：未接入定时调度器（`_scheduled_run` 仅处理 w1/w2，W3 只能手动/API 触发）；死代码待清（W2 `pipeline/w2/steps/reply.py` 已不被调用、W3 残留 `verify_reply_delivered.pyc`）

- 修复会话「系统消息被误标 HR」显示+标记问题（2026-06-20）
  - 现象：Boss 平台提示「优秀竞争者会，建议你尽快沟通」在 DOM 上带 `item-friend`（HR 气泡）class，被 `read_messages` 读成 `sender='hr'`，DB 已重复落 322 条。一个根因造成两个问题：①显示——前端 `MessageBubble` 按 sender 渲染成左侧 HR 气泡而非居中淡显系统提示行；②标记——`analyze_hr_intent` 取 `messages[-5:]` 原样喂 LLM，`[hr] 优秀竞争者会…` 被当作 HR 最新消息，污染 intent 判定与 W3 回复草稿
  - 修复：`read_messages.py` 新增纯函数 `_reclassify_platform_tips`——读完 DOM 后对 `sender='hr'` 且文本匹配已知 Boss 平台提示前缀（`_PLATFORM_TIP_PREFIXES`，目前 `优秀竞争者会`，CJK 用 \uXXXX 转义）的消息重分类为 `system`。仅动 hr 气泡，真实 HR 文本与 `[卡片]` 换简历/微信卡片（detect_resume 依赖）保持 hr 不动
  - 历史数据：一次性回填 `hr_messages` 322 条 `优秀竞争者会%` 的 hr→system，修复已存会话显示
  - 前端：`Chat.tsx` 早已正确按 `sender === 'system'` 居中渲染，无需改前端/重建
  - 实测（截图复核）：DOM 断言该提示落在 `justify-center` 系统 pill（`bg-white/[0.04] text-text-3`）而非 HR 气泡（`bubble:false`），视觉确认居中淡显
  - 连带发现并修的更深根因：`analyze_hr_intent` 在会话「零 HR 消息」时仍起草——LLM 只拿到我方自我介绍（+平台提示），臆造出「HR 在认可我」并生成待发草稿。实测 67 条待审批里 45 条所在会话 HR 一字未回（intent 多为 general/「感谢您的认可…」，部分甚至以 HR 口吻乱写）。在 `AnalyzeStep` 加确定性守门：`has_hr_message=any(sender==hr)` 为假时跳过 LLM 调用、`needs_reply=False`、不起草（models judge / code decides）。新增单测 `test_analyze_step_no_hr.py`（无 HR→不调 LLM/不写库；有 HR→正常）
  - 历史数据二次清理：清空 45 条 bogus 草稿（reply_status/reply_text/intent 置 NULL），剩 22 条待审批全部是 HR 真实回过话的；侧栏会话徽章 67→22
  - 验证：pytest 368 passed

- 前端逐 navigator 重设计 第一轮完成：6 navigator + 全量消重（2026-06-14）
  - 续 2026-06-13 起点，完成余下 navigator 初步一轮 + 两个用户报告问题修复
  - **职位**：套新令牌（mono 数字/信号色 StatusPill）+ STATUS_TABS 对齐真实 AppStatus，删死的 ERROR 清除按钮
  - **会话**：双栏套令牌（TintBadge stage/intent + 信号气泡 + mono 时间戳），审批逻辑保留；INTENT_COLORS 对齐 Apple 信号色
  - **日志**：PipelineBadge/StatusBadge/EventNameBadge/筛选 tab 配色对齐信号色 + 两栏卡片质感
  - **自动化（新建 navigator）**：ScheduleCard/ScheduleLogCard 从控制台脚本化迁出（design/migrate_automation.py），接 App 路由 + Page 类型 + Sidebar；控制台调度区清空
  - **设置（三合一）**：配置/搜索配置/环境配置三页合并成单 navigator 3 Tab——求职偏好（搜索条件+评分备注 extra_notes 单一表单写 profile.yaml）/ 模型（能力路由+per-tool 唯一）/ 环境&Session（系统状态+Session 验证登录+简历上传 唯一）；删 Config.tsx/Profile.tsx/Setup.tsx；控制台 SessionChecker 移入
  - **后端统一端点**：server.py /api/profile get+save 增 extra_notes（读改写保留），成为 profile.yaml 全字段单一真相；api Profile 类型加 extra_notes
  - **修复**：①状态分布/已获回复词表错位（STATUS_META 对齐枚举 + responded→chatting）②首屏加载慢（移除 Google Fonts CDN，@fontsource 自托管）③监控面板空间恒定（骨架投影+滚动卡片）
  - **消重兑现**：配置 2→1、Session 2→1、LLM 2→1、审批 2→1、调度独立；信息架构落定 6 navigator（控制台/职位/会话/日志/自动化/设置）
  - 验证：pytest 全绿、build tsc 无报错（version→1.0.9.32）、每页 DrissionPage 真实截图复核、extra_notes 往返实测
  - 待跟进：逐页精修（自动化调度卡内部旧蓝待对齐、问题2 W2 实时进度实跑确认）；死代码 /api/config/profile 可删

- 前端逐 navigator 重设计 启动：设计系统「Apple-refined Telemetry」+ 控制台落地（2026-06-13）
  - 背景：重新设计前端，逐 navigator 讨论。先定信息架构再逐页推进，本轮完成 navigator #1「控制台」+ 全站共享设计系统底座
  - 信息架构（7→6 navigator）：控制台 / 职位 / 会话 / 日志 / 自动化 / 设置。消重决策——配置与搜索配置都写同一个 profile.yaml（`/api/profile` 裸读写 vs `/api/config/profile` 经 ConfigManager，字段大量交叉）应合并；Session/LLM/回复审批各有两处实现需收敛到单一权威入口。审批唯一入口归会话页，控制台只留计数跳转条；调度独立成「自动化」navigator
  - 视觉语言「Apple-refined Telemetry」：Apple 令牌（#000 底 + #1c1c1e 卡 + rounded-2xl + 柔阴影 + 系统字体栈 + 负字距）融合遥测层（IBM Plex Mono 只服务数据：数字/tool名/时间戳/score；Apple 暗色系统信号色 W1蓝#0a84ff/W2紫#bf5af2/绿#30d158/橙#ff9f0a/红#ff453a；极细网格+微噪点氛围层）
  - 基础设施（全 navigator 共享）：tailwind.config(.js/.ts 同步) 加 font-mono(IBM Plex Mono)/signal-* 信号色板/deco 装饰色/text-3 提亮 #6e6e73→#84848c；index.html 换字体(删死引用 Inter)；index.css 加 .atmosphere；App.tsx 注入氛围层
  - 控制台页（Dashboard.tsx 重排，指挥中心布局）：顶部全宽琥珀待审批行动条(脉冲+辉光，跳会话页)+ 侧栏会话计数角标；遥测条(mono 统计)+ 状态分布(信号色)；指挥中心 grid 左 WorkflowPanel(W1/W2 mono 分组+toggle+信号色按钮+渐变全流程) 右 WorkflowTrack(mono+RUN/OK/SKIP 徽章+时间戳，保留骨架/LiveLog/W2摘要/卡死检测全部功能)；删 ReplyApprovalCard 去重；Sidebar/Topbar 重命名「控制台」并套新令牌
  - 设计守则：docs/frontend.md 新增「文字色 vs 装饰色对比度契约」防复发条款（根因：曾把装饰灰 #48484a 用于时间戳/描述等信息文字致 ~1.9:1 不可读；铁律=文字色每档≥4.5:1，装饰灰禁用于 color: 文字）
  - 踩坑：esc.py 字节级转义器会把裸 JSX 文本节点的标点也转成 \uXXXX 致字面量渲染（SkeletonTree 的 ·· → 显示 ·），修正为 {'··'} 包裹——重申守则「JSX 文本节点必须 {'\uXXXX'}」
  - 验证：pytest 全绿、npm run build tsc 无报错(version→1.0.9.23)、启动后端 DrissionPage 真实页面截图复核两轮
  - 过渡留痕（不丢功能）：SessionChecker/ScheduleCard/ScheduleLogCard 暂留控制台底部标 TODO，归宿是后续「环境配置」「自动化」navigator
  - 待处理：余下 navigator（职位/会话/日志/自动化/设置）逐个套新设计系统；配置与搜索配置合并；Session/LLM 去重

- 可视化重构：地铁图 → scope×step×tool 全量层级树（2026-06-11）
  - 需求：把扁平水平地铁图换成可对应每个 SSE 事件的层级视图。讨论中校准两条正交轴——纵轴（step 内部调了哪些 tool）+ 横轴（W1/W2 循环里 N 个会话/卡片各自走到哪），用户拍板做全量三层树（scope×step×tool，每节点带成功/失败）、去掉地铁图、debug 默认开
  - 现状校准（基于代码）：tool 级数据源其实齐全且自动——`registry.call()` 内部对每个 tool 统一 `log_tool(step,tool,scope,successful/failed,耗时)`，每个 step 入口 `set_context` 提供归属（全覆盖）；只是 SSE 推送被 `_debug` 闸住、且 scope/tool 在传到前端途中丢了（前端 interface 只取 workflow/step/status/message/ts，tool 名还被拼进 step 字段）。另发现：实跑 step 比地铁图画的多（W1 含 scan/classify/upsert、W2 含 scan/finalize）；step 只在完成时发终态事件、没有 running 入口事件
  - 后端：①`ProgressEvent` 加 `tool`/`scope` 独立字段（progress_emitter.py）②run_logger emit 时正确传 scope，tool 事件不再拼 `step/tool` 而用独立 tool 字段；新增 `emit_step_running(step,scope)` 只走 SSE 不落文件 ③`registry.set_context` 调 emit_step_running，一处覆盖所有 step 入口 running 态 ④server.py SSE 序列化加 tool/scope，两处 debug 默认 False→True（保留开关）⑤测试 mock `_CapturingLogger` 补 emit_step_running
  - 前端（WorkflowTrack.tsx 推倒重写）：useWorkflowStream ProgressEvent 加 tool/scope；buildTree 把事件流归约成 workflow→scope实例(job_id/conv_id，run级归 __run__)→step→tool；可折叠层级树（实例行默认折叠、活跃实例自动展开、step 可展开看 tool 瀑布），每节点带 running/done/error/skipped 状态点；全部 step 纳入（含 scan/classify/upsert/finalize），STEP_ORDER 给规范顺序；保留 LiveLog（badge 加 tool）+ W2 summary chips + llm_degraded 告警。CJK 全 \uXXXX（PowerShell 字节级转，验证 non-ASCII 463→0）
  - 验证：pytest 全绿、npm run build 通过、tsc 无悬空、version 1.0.9.12→1.0.9.13。W1 navigate=run级搜索导航（CardPipeline 不调它，只 classify/fetch_jd/apply/upsert）故归 __run__ 正确
  - 待验证：UI 实际渲染未在浏览器确认（需重启 Dashboard server 让后端改动生效 + 跑 W1/W2 看层级树展开）

- 文档审计对齐 + W2 前端接线 llm_degraded/summary（2026-06-11）
  - 文档审计：TECHNICAL.md 大范围对齐 pipeline 架构现状——删退役死章节（orchestrator.py / critique_job / check_responses / 旧 browser_agent 单体方法），tools 改四层分包（llm/browser/db/biz_logic）总览，config.yaml 示例改三层 w1/w2，修 stage 流转与设计决策里的旧函数名，tests 章节对齐实际文件，删"W2 发简历从未运行"等已矛盾项；README.md 删 Critic / 简历 PDF 生成 / CLI Chat Agent 三个退役功能条 + 发简历改两路径「附件简历」marker 判据 + 调度改内置 Dashboard；design/ 6 个设计稿核查确认是新架构设计稿（命中旧符号都在"砍掉/不实现"语境）无需改；PROGRESS 变更日志型无需改
  - 前端接线（WorkflowTrack.tsx，后端零改动）：①修 bug W2_STEPS 顺序 reply,resume → resume,reply（地铁图对齐真实 pipeline）②W2 卡片地铁图下方加 run summary chips（处理会话/发简历/发回复/状态变更，取自 GET /api/runs?pipeline=w2 的 summary，run 结束 isRunning 边沿刷新）③summary.llm_degraded>0 时橙色告警条。CJK 全 \uXXXX（PowerShell 字节级转换，验证 non-ASCII=0）；npm run build 通过、tsc 无悬空、version 1.0.9.11→1.0.9.12
  - 解决上条 W2 遗留③（前端接线 llm_degraded/sent 可视化）
  - 待验证：UI 实际渲染未在浏览器确认（需启动 Dashboard 跑 W2 看 W2 卡片 summary/告警）

- W2 端到端验证：简历发送判据收拢 + hr_messages 落库 + LLM 层切 ollama（2026-06-11）
  - 背景：W2 首次有头实跑（5→30 会话），定位并修三块
  - 根因 1（hr_messages 恒零落库）：write_hr_messages 工具的 INSERT 漏 created_at(NOT NULL) → 被 `INSERT OR IGNORE` 静默吞 → inserted_count 恒 0（read 读到消息却零落库）。改为委托 tracker.insert_hr_messages（已含 created_at），消除一套对一套错的重复 INSERT。实跑落库 156 条
  - 根因 2（简历发送"成功"判据不可信）：toolbar 凭"按钮可点/跨境框消失"、accept 凭"点了同意 card_found"谎报成功——境外卡在跨境二次确认框时简历没发出却记 resume_sent。收拢到唯一真相"聊天框出现 `.message-item.item-system` 含「附件简历」系统消息"（境内"已发送给Boss"/境外"附件简历请求已发送"，两路径通用、实测 15/15）。helpers 新增 count_resume_delivered_markers + wait_resume_delivered(poll)，两个发送工具改为 tool 内 before/after marker 增量判 sent，ResumeStep 只读 sent
  - 境外跨境二次确认框（仅境外公司 + toolbar 主动发送时弹）：`div.panel-resume.sentence-popover`（标题"确定与对方交换简历吗？"）→ 确定 `.btn-sure-v2` / 取消 `.btn-outline-v2`
  - already_sent 同源收拢：detect_resume 改为 `any(sender=='system' and '附件简历' in text)`。必须限定 sender=='system'——HR 卡片索要文本本身也含"附件简历"，不限定会把索要误判成已发（该发不发，pytest 抓出）。精修 Tool 10（2026-06-02）的"system+简历"判定
  - LLM 层 Windows 真相：claude_cli 频繁 exit1（rate-limit，与主对话 claude 争配额，单次 analyze 拖到 100s）；codex_cli Windows subprocess 找不到 .cmd shim → is_available()=False 被 FallbackChain 跳过。balanced 链精简为仅 ollama（稳但慢 ~9.5min/30 会话）。FallbackChain 全失败 raise（不造假）→ intent 降级 unknown；新增 llm_degraded 每会话事件 + summary 计数
  - 验证：pytest 全绿（更新 2 个 detect_resume 测试匹配新语义）；实跑 30 会话 resumes_sent=2(新发)/already_sent 跳过上次 15 个/hr_messages 156/llm_degraded=0；commit add93fe + 92d322e
  - 遗留：①ollama analysis 慢，可评估 anthropic_api（需 key，不走 CLI rate-limit）②accept 境外跨境框选择器（旧 boss-dialog）未实测，靠 marker 兜底 ③前端接线 llm_degraded/sent 可视化

- W1 真实投递修复：投了不落库 + max_cards 失控（2026-06-10）
  - 背景：用户真实环境跑 W1（score_threshold=0 跳过 LLM、max_cards=15），发现①投递远超 15 张停不下来 ②真实投递成功（HR 收到招呼、点进 conversation 确认）但 DB 今天 0 条记录
  - **根因 1（投了不落库 = DB schema 从未迁移）**：code/data/jobs.db 的 applications 表停留在 **T030 重构前的旧 schema**（url NOT NULL + decision/critic_verdict/updated_at 等旧字段）；`CREATE TABLE IF NOT EXISTS` 永不重建已有表 → 541 条老数据的库从没迁移过。新 pipeline 的 upsert_application **不传 url** → 撞 url NOT NULL → INSERT 失败、upsert ok=False → 不落库。时间线吻合：5-29（T042 新 pipeline 接线）后所有投递都没入库，最后一条落库是 5-26（重构前旧路径传了 url，5 月落 423 条）。migrate_030.py 修不了它——它用 ALTER DROP COLUMN 删旧列但删不掉 url 的 NOT NULL 约束，且从没在这库跑过
  - **根因 2（投递不停止 = max_cards 只跳内层循环）**：pipeline/w1/pipeline.py 的 `if cards_viewed >= max_cards: break` 只跳出内层 for，外层 while 继续 scroll 翻页 → 每页投一张再 break，无限投。连带：dialog_blocked 被算作 SUCCESSFUL，consecutive_skips 不增长，"连续 5 次 skip 停"的保险也失效
  - 修复：①新增 scripts/migrate_app_rebuild.py 完整重建 applications 表对齐 tracker.py 新 schema（url 可空、去旧字段），541 条数据迁移 + status 值 remap，自带备份 jobs.db.bak_appmig（migrate_030 的 ALTER DROP 不可行，必须重建表）②pipeline/w1/pipeline.py max_cards 命中时 should_stop=True 终止外层 while ③tools/browser/w1/handle_apply_dialog.py 关闭按钮 a.cancel-btn → `.greet-boss-dialog a.boss-btn-cancel`（inspect 实测真实「留在此页」class，精确避开「继续沟通」boss-btn-primary）
  - 调查中证伪的猜测（都不是根因）：detection 选择器过时（.greet-boss-dialog 实测 HIT）、cwd 漂移连错库（PRAGMA 证实连的对库）、upsert 工具有 bug（迁移后同工具 ok=True）。投递成功标准 = 点「立即沟通」后弹 div.greet-boss-dialog（标题"已向BOSS发送消息" + 留在此页/继续沟通两 button），弹窗出现即成功
  - card_pipeline.py 加 score_threshold<=0 快速路径：跳过 score_job LLM 调用直接投（纯流程验证不耗 LLM；旧 orchestrator 有此快速路径，新 pipeline 重构后丢失）
  - 验证：pytest 359 passed；真实 W1（max_cards=1/阈值0/有头）cards_viewed=1 applied=1 **db_write_failures=0**，独立进程确认 DB 541→542 真实 APPLIED 入库（mtime 更新、跨重连存活）
  - ⚠️ 工具流损坏纠正：首次提交(7df8caf)时，migrate_app_rebuild.py 的 Write 与 max_cards 的 Edit 因工具流损坏报告了"假成功"实际未落盘（迁移从未运行、DB 仍旧 schema），其"541→543 入库"是幻象。2026-06-10 复核磁盘真相后**真正重做**：max_cards 落盘确认(line103 should_stop=True)、迁移以独立进程严格验证持久化、补 commit。教训：工具"成功"不可信，改动必须独立 grep/读回 + 数据落盘需全新进程跨重连验证
  - extract_card_list company 采集缺口修复（2026-06-10）：搜索卡公司名在 `span.boss-name`（在 a.boss-info 内），原选择器 `.company-name/.company-text` 全 MISS 致 company 空；且 hr_name 误用 `.boss-name` 把公司名当 HR 名。修：company 改 `.boss-name`||`a.boss-info`，hr_name 去掉 `.boss-name`（列表卡无 HR 名，HR 在详情面板/W2 聊天）。真实工具链投 1 张 NEW 卡端到端实证：company=乐漾、url=job_detail/{id}.html 均落库完整。W1 整体确认无问题（能停/正确跳已投/落库字段完整）
  - 遗留：①日志系统未验证（run log 仅 1KB，埋点可能没工作）②upsert_application 应传 url 补全数据 ③ApplicationTracker 用相对路径 data/jobs.db（cwd 漂移隐患，应改绝对路径）④本次产生 5 个临时诊断脚本（inspect_apply/verify_detect/verify_apply_e2e/diag_db/peek.py）待清理

- 配置系统三层重构 + 退役 factory 流程（2026-06-09）
  - CLAUDE.md 重写：退役 AI 工厂迭代流程（不再写 task / 调 codex / 出 report-review），改为"直接修改代码"的 7 条开发规则；同步修正过时内容（技术栈 Playwright→DrissionPage、目录结构、登录态在 browser_profile 而非 session.json）
  - 配置三层模型落地：config.yaml 重构为 Layer1 系统配置（llm/dashboard）+ Layer3 workflow 运行参数出厂默认（w1/w2 两节）；profile.yaml 清理为 Layer2 用户画像（删 name/scale）；新增 services/settings_resolver.py 实现三级 fallback（config 出厂默认 < data/user_settings.yaml 用户默认 < API/CLI override，None 值忽略），user_settings.yaml 懒创建，save_user_default 支持前端"设为默认"
  - 接线统一：main.py + dashboard/server.py 三条触发路径（手动 trigger / 定时 scheduled / CLI）都经 _run_*_workflow 走 resolve_params
  - 死字段清理：apply.aggressive_resume（零引用）、apply.generate_resume（工具已删）、job_search 整节（与 profile 重复 + limit_per_run 被 max_cards 取代）、schedule 整节（scheduler.py 已删）、browser.headless（下放 w1/w2）
  - 断链修复：max_conversations（原 run_w2 收下却未传 pipeline → 现 W2Config 加字段 + pipeline 截断，真正生效）；stale_conv_days（server 原不传 → 现传入）；daily_limit（归 w1 默认 150，改写 user_settings.yaml 而非 config.yaml）
  - 两个真 bug：profile_loader 删除 name 必填校验（投递打招呼 Boss 全自动发送、全流程不用 name，原必填是残留）；ProfileLoader 补全 degree/job_types/financing/districts/position_types/industries/boss_online（原只加载 6 字段，CLI 路径下这些搜索筛选全部丢失）
  - 新增 docs/configuration.md 配置 tutorial（三层模型 / 优先级链 / 字段参考 / 设为默认机制 / 死字段审计）
  - 测试：test_config_manager.py 适配 w1/w2 结构，test_server.py apply_limit→max_cards 契约更新；355 tests passed

- W2 收尾三工具：修复每会话落库 + 超时关闭崩溃（2026-06-04）
  - upsert_hr_conversation 的 INSERT 写 hr_title/job_title/updated_at 三个 T030 schema 不存在的列 → 真实 DB 实测每会话收尾落库必崩（no such column）→ stage/preview 从不入库；改为只写存在的列，title 入参保留不持久化
  - mark_timeout_statuses 的 WHERE updated_at 同样引用不存在列 → 陈旧会话超时关闭从未生效；改用 created_at
  - sync_application_status 实测正常（UPDATE...FROM，按 hr_name+company JOIN）
  - updated_at 系列 schema bug 至此共修 4 处（update_hr_analysis/upsert/mark_timeout/记录序列化），均为 T030 建新表后未同步、且因测试无法 collect 长期潜伏
  - 新增 tests/test_upsert_hr_conversation_tool.py（4）+ test_finalize_w2_tools.py（5）；354 tests passed
  - W2 全链逐 tool 审查全部完成

- Tool 12 ReplyStep：修复已批准回复重复发送（2026-06-04）
  - ReplyStep 原用 update_hr_analysis(reply_status='sent') 标记已发；Tool 10 把 approved 加入保护集后该转换被挡，reply_status 永停 approved → 每轮 get_approved_replies 重复捞出、重复发送（且修 updated_at 前该调用本就崩）；根因是用"重新分析"工具做权威状态转换
  - 新增 mark_reply_sent 工具（直接 UPDATE reply_status='sent', reply_text=''，与 dashboard mark-sent 一致），ReplyStep 改调它：分析路径继续保护 approved，发送后走专用权威转换，两者不再冲突
  - send_chat_message 审查扎实（contenteditable + execCommand insertText 解决 CJK IME + actions Enter）；未验证：Enter 后是否真发出
  - 新增 tests/test_mark_reply_sent_tool.py（3 测）；345 tests passed

- Tool 11 ResumeStep：真实浏览器实证（无代码 bug，推翻悲观警告）（2026-06-04）
  - accept_resume_card 选择器全部正确（.message-card-wrap/.dialog-icon.resume/.card-btn/"同意"）；对已接受的卡片正确返回 card_found=False
  - click_toolbar_send_resume 的 [d-c="62009"] 经实测确认存在且正确（发简历按钮），原"大概率错"的 WARNING 是误判；d-c 是 Boss 控件类型 ID（按功能固定：62001=会话卡、62009=发简历按钮），解释了其跨会话恒定；已修正 resume.py 误导性注释
  - 仍未验证（点击会真发简历，未测）：disabled 态 class、点击后是否弹简历选择框
  - 常态推送发送途径：ResumeStep 把 strategy 编进 SSE step message（resume sent via accept_card/toolbar），前端不开 debug 即可见走哪条途径
  - 仅注释 + 观测增强；342 tests passed

- Tool 10 AnalyzeStep：修复简历重复发送判定（2026-06-02）
  - detect_resume_request 的 already_sent 原只扫 "me" 消息，漏判系统通知；简历经卡片流程发送后由系统消息确认（"您的附件简历…已发送"/"对方已查看…简历"），导致 already_sent=false、needs_resume=true → 重复发简历；真实会话实测坐实，改为 system+简历 也判定 already_sent
  - 真 LLM（claude_cli）实测该会话 intent=general/needs_reply=false，判断准确；修正 analyze_intent.py 一处不准确的"未记日志"注释
  - 最终通读又修 update_hr_analysis 两处：① 写不存在的 updated_at 列 → 每次调用必抛 no such column、分析结果从未入库（T030 漏改，已删）；② 状态保护漏 approved、reply_text 无保护 → 重新分析会降级已批准回复/覆盖用户草稿（统一保护 {approved,sent,dismissed,revision}）
  - 新增 tests/test_detect_resume.py（5）+ test_update_hr_analysis_tool.py（4）；342 tests passed

- Tool 8/9 真实浏览器实证：修复会话打不开 + 消息漏读 + 空读容错（2026-06-02）
  - Tool 8 #5（最致命）：navigate 点击外层 .friend-content-warp 根本打不开会话（右面板停在空占位图）；实测点内层 .friend-content（带 d-c 的元素）才打开（message-item 0→8）；已改点 .friend-content。叠加此前 #1（非法 JS）+ #3（d-c 常量），navigate 此前完全打不开任何会话
  - Tool 9 空读改报错：read_messages 读到 0 条消息（导航/渲染失败）现返回 ok=False（原 ok=True 空），ReadStep FAILED、pipeline 短路该会话、循环继续下一条（fail-fast + per-iteration 故障隔离）
  - Tool 9 删除时间戳过滤：read_messages 原会丢弃无 .time 的 HR 文本气泡；实证某会话 3 条 HR 消息有 2 条因此被静默丢弃（Boss 只在时间组首条显时间）；改为只按"有无文本"保留
  - 新增 tests/test_read_messages.py（4 测）+ test_navigate_to_conversation 增断言；333 tests passed

- Tool 8 navigate_to_conversation：修复非法 JS 兜底 + HR 匹配（2026-06-01）
  - 修复 find-by-click 兜底策略的 JS 语法错误：原 f-string 只对 if 行生效，下面 `scrollIntoView({{...}})` 与 `}}` 是普通字符串里的字面双花括号 → run_js 必抛 SyntaxError，整个点击兜底永远失败；改用字符串拼接（单花括号）
  - 卡片匹配同时用 hr_name（.name-text）+ company（name-box span[1]）：原来只按 company 匹配，同公司多 HR 时会点错第一张卡（conv 身份是 hr_name|company）
  - 真实浏览器验证并修复 d-c 疑点：开 headed 浏览器 inspect 44 个会话卡，`.friend-content` 的 d-c 全部为常量 '62001'（用户自身/列表 ID，非会话 ID）→ 彻底删除 strategy 1（URL ?conversationId=d-c，对所有会话导航到同一错误位置），只保留 hr+company 匹配点击；结合 JS 修复，W2 会话导航此前一直是坏的，现在才可用
  - 新增 tests/test_navigate_to_conversation.py（4 测）；329 tests passed

- Tool 7 filter_conversations：终态排序修正 + 每会话决策可观测性（2026-06-01）
  - 终态判断改到决策树最后：approved/unread/new/preview_changed 均优先于 terminal——closed/offer 会话有新动静（含 preview 变化）仍会被处理，terminal 只跳"啥都没变"的会话；修复原来 terminal 压制 unread 导致的"被拒/拿 offer 后 HR 重新发起被漏掉"
  - 每会话决策可观测性：filter 返回 decisions（per-conv：conv_id/action/reason/stage/has_unread）+ summary（按 reason 计数）；scan_step 将 per-conv 写文件日志（logger.log filter_decision，visible=False → 只落文件不进 SSE），summary 走 SSE（scan_filter step + 人类可读 message）；run_logger.log_step 新增可选 message 覆盖（仅影响 SSE 展示，文件日志结构化数据不变）；registry _LARGE_FIELDS += decisions
  - Jobs.tsx:267 历史遗留的字面 em-dash（U+2014）改为 \\u2014 转义（落实 TSX 非 ASCII 必须转义的长期约定，全文件 0 非 ASCII）
  - 新增 tests/test_filter_conversations.py（7 测）；325 tests passed

- Tool 6 增量比对来源修复 + 完成 dashboard 的 T030 schema 迁移（2026-06-01）
  - W2 Tool 6 get_conversation_states 审查：本体（纯 SQL 批量读 last_msg_preview+stage）无问题；但 filter_conversations 的增量比对两端数据源错位——stored 端存 messages[-1][:100]（进会话内部解析、reply 前快照），current 端是聊天列表行预览，几乎恒不等 → 每轮重处理所有非终态会话（浪费 LLM、更像机器人；方向是过度处理不漏回复，定 Should Fix）。修法（同源）：ConvBasic 加 last_msg_preview → scan_step 透传 → conversation_pipeline 改存 conv.last_msg_preview；新增 tests/test_conversation_pipeline_preview.py 回归测试
  - 修复 T030 状态枚举改名漏改（DISCOVERED→FOUND）：services/browser_agent.py 3 处（构造新 Job 时用不存在的 AppStatus.DISCOVERED，运行时必崩的潜伏 bug）+ test_server.py 4 处（import 时 AttributeError 中断整轮 pytest 收集）
  - 完成 dashboard/server.py 的 T030 schema 迁移（此前未完成，核心读接口会崩；因 test_server.py 无法 collect 而长期未被发现）：
    - _serialize_record 引用 ApplicationRecord 已删字段（decision/critic_verdict/resume_path/error_msg/responded_at/apply_attempted/updated_at）→ /api/jobs 必崩；瘦身到真实字段
    - /api/conversations 引用 HRConversation 已删字段（messages/last_msg_text/suggested_reply/needs_reply/reply_draft/status）+ get_hr_conversations(status=) 传参错误 → 必崩；新增 _serialize_conversation 从新 schema 派生旧契约（messages 走 hr_messages 表、suggested_reply/reply_draft=reply_text、last_synced=created_at、status=stage、needs_reply 由 reply_status 推导），保持前端契约不变
    - pending-replies 字段引用修复；mark-sent SQL 改 reply_text（旧列 suggested_reply/reply_draft 已不存在）
  - 前端：Jobs.tsx 删除 5 个已删字段的死显示行；api/index.ts Job interface 瘦身；npm run build 通过（tsc 无悬空引用），v1.0.9.11
  - test_server.py 全面对齐当前 schema/API（_rec/_conv helper、SCANNED→SCORED、TestConversations reply_text 语义、TestLLMConfig capabilities/tool_providers、TestRunLogs run_start/run_end 格式 + pipeline 参数、TestWorkflow 改 patch _run_apply_workflow、session-check 改 emitter.current_workflow）
  - 318 tests passed（含此前无法 collect 的 test_server.py 约 70 个）
  - 设计决策：会话 API 采用"后端从新 schema 派生旧契约"以零改动保住前端；遗留 Jobs.tsx:267 一处预存 CJK 占位符损坏（与本次无关，未动）

- W2 逐 tool 人工审查：scan 健壮性 + 可观测性修复（2026-06-01）
  - 背景：人工逐 tool 审查 W2（检查 HR 回应）pipeline，已审至 Tool 3 ExtractConversationList，过程中发现并修复 5 处问题
  - tools/registry.py：`items` 加入 `_LARGE_FIELDS` 大字段黑名单——此前 ExtractConversationList 返回的整个会话列表（key=items，不在黑名单）被逐屏写入 run 日志，导致日志爆量 + HR 姓名/公司/消息预览隐私落盘
  - tools/browser/w2/navigate_to_chat_list.py：新增 `force` 参数（默认 False 保持"已在聊天页则短路"原行为；force=True 强制重载，供 scan 重试用）
  - pipeline/w2/scan_step.py：①scan 重试（导航+滚动最多 3 次，重试时强制重载 + 2s×attempt 退避，scan 是 W2 命脉，空列表多为瞬时失败）；②空到底=可见失败（重试耗尽仍空 → status=failed 事件 + 返回 StepStatus.FAILED，复用既有 scan_failed 通路）；③待审批回复会话漏抓告警（待审批回复必然之前抓到过，若本轮未抓到则 filter_conversations 会静默丢弃其回复 → 发 failed 告警）
  - pipeline/w2/steps/reply.py：回复发送失败状态 DEGRADED → FAILED（发送失败是真实失败该标红；流程仍跳过继续——控制流与状态标签解耦，下游只读 .sent 不受影响）
  - pipeline/run_logger.py：新增 _ui_status() 状态词表归一化，修复后端领域词（successful/failed/degraded）与前端 StepStatus 词表（done/error/skipped...）不匹配的真 bug——此前成功步骤节点不变绿、失败不变红（都落 default 灰色"等待"）；映射 successful→done/failed→error/degraded→skipped，仅在构造 SSE ProgressEvent 时翻译，文件日志仍写领域词保留分析精度
  - 设计原则沉淀：文件日志 vs SSE 推送词表分离；控制流（skip）与状态标签（failed）解耦；status 归一化收口到 run_logger 边界一处
  - 239 tests passed（排除预存损坏的 test_server.py）
  - 遗留运行时确认：boss_conv_id 取自 d-c 属性（疑非会话唯一 ID）、class 选择器易碎——待 Tool 8 NavigateToConversation 真实环境验证

- LLM ModelRouter + Config Manager + 前端配置页 + Session 验证抽象（2026-05-30）
  - T043 LLM ModelRouter：capability-based routing（fast/balanced/powerful），ModelRouter 类 + build_model_router()；ClaudeCLIProvider 修复 prompt injection（去掉 System: prefix，仅用 prompt）、Windows 编码修复（PYTHONUTF8=1）；CodexCLIProvider 修复（codex -q）；config.yaml llm.providers → llm.capabilities 结构
  - T044 Config Manager：services/config_manager.py 新建，ConfigManager 单例，save_profile 合并写入，save_system_config 禁写 llm section；GET/PUT /api/config/profile，GET /api/config/system 三个端点
  - T045 前端配置页：dashboard/frontend/src/pages/Config.tsx 新建，TagInput 组件，5 字段求职偏好编辑；Setup.tsx LLM UI 从 scoring/generation/analysis 改为 fast/balanced/powerful；Sidebar 新增"配置"入口
  - VerifySessionStep：pipeline/common/verify_session.py 新建，W1/W2 runner open_browser 后自动调用，/api/check/session 改用此 Step，删除旧 BrowserAgent 实现
  - WorkflowTrack/WorkflowPanel 对齐新 pipeline：workflow 过滤 apply/check → w1/w2；步骤名全部更新；handleAll() W1→W2 串联修复；debug 参数透传修复
  - 旧代码清理：scheduler.py 删除；/api/config/llm 迁移到 capabilities 结构并热重载 model_router
  - 239 tests passed，v1.0.9.9

- Pipeline 架构接线 + 旧代码清理 T042（2026-05-29）
  - pipeline/w1_runner.py + w2_runner.py 新建，run_w1()/run_w2() 成为生产入口
  - services/browser_context.py 新建（open_browser/close_browser/_kill_stale_chrome）
  - dashboard/server.py + main.py 接入 run_w1/run_w2，删除 Orchestrator 依赖
  - 14 个旧文件删除（orchestrator.py、event_log.py、9 个旧工具、3 个旧测试）
  - 215 tests passed

- Pipeline 架构重构实现阶段完成 T030~T041（2026-05-29）
  - T040 日志埋点：新建 services/run_logger.py + pipeline/run_logger.py，JSONL 格式升级（event 字段、run_id: w1_YYYYMMDD_HHmm），ToolRegistry.call() 统一 trace，8 个 Step 文件全部埋点，所有 business event scope/data 分离
  - T041 Dashboard Logs 页：server.py 重写 runs API（支持 w1/w2 pipeline 筛选，steps+tools 分组，精确 run_id 匹配），Logs.tsx 完全重写（Flow/Decisions 双 Tab，Step 展开查看 Tool，CJK 全 \uXXXX 规范）

- Pipeline 架构重构设计阶段完成（2026-05-28）
  - design/db_schema.md：三张表最终 schema（applications 删 7 个旧字段、hr_conversations 重写状态机、hr_messages 新建、actions 表删除）；conv_id 公式更新为 sha256(hr_name|company|hr_title)[:12]
  - design/tools_catalog.md：全量更新，删除 CritiqueJob/GenerateResume/UpdateApplicationStatus，新增 GetConversationStates/FilterConversations，ExtractConversationList 加 hr_title 字段，所有 Tool 契约对齐新架构
  - design/w1_pipeline.md / design/w2_pipeline.md：Step 级别完整设计确认，含 StepOutput 基类、on_error 策略、执行顺序、Stage 推导规则
  - design/logging.md：全量重写，Trace event + Business event 双轨设计；所有 Tool data 字段规格逐一定义；Business Events 清单（9 个事件含发出位置）
  - tasks/refactor_plan.md：总纲文档，含通用背景、核心概念、设计文档索引、现有代码索引、12 个 Task（030~041）各自的要做什么/预期产出/验收条件/参考文件及执行顺序依赖图

- W2 自动发送已批准 HR 回复（2026-05-23）
  - browser_agent.py _send_chat_message：修复 Enter 键提交方式，从 inp.key.enter()（ChromiumElement 无此属性）经 page.key.enter()（ChromiumPage 也无此属性）到最终正确写法 page.actions.key_down('Enter').key_up('Enter')（DrissionPage 4.1.x 唯一正确键盘 API）
  - tracker.py update_hr_analysis：CASE 保护范围从 ('approved','revision') 扩展到 ('approved','revision','sent','dismissed')，防止 check_chat_list 事后 LLM 再分析覆写已发送状态
  - 端对端验证通过：某companies·陈女士 msgs 1→2，DB reply_status='sent'，suggested_reply 已清空，workflow 结束 summary replies_sent:1

- 结构化事件日志系统（2026-05-22）
  - services/event_log.py（新模块）：RunLogger per-run JSONL 事件写入器，写入 logs/runs/{run_id}.jsonl；log_event() 支持 visible 标志区分用户可见/内部调试事件
  - orchestrator/browser_agent/check_responses 全部埋点（card_discovered/scored/skipped/applied/error/nav_recovered/cards_scraped/card_click/jd_loaded/apply_btn_clicked/hr_checked/intent_analyzed 等）
  - server.py 新增 GET /api/runs（运行列表）和 GET /api/runs/{run_id}（事件时间线）两个 API 端点
  - Logs.tsx 新页面：左栏 run 列表（workflow 筛选）+ 右栏事件时间线（visible 展开开关）；Sidebar 新增 Logs 导航项

- 投递稳定性提升（2026-05-22）
  - scrollIntoView fix：CDP 卡片点击前先 cards[i].scrollIntoView({block:'center',behavior:'instant'})，解决无头/小视口下 getBoundingClientRect() 坐标偏移导致点击无效
  - _kill_stale_chrome(profile_dp) 静态方法：启动前用 wmic/taskkill（Windows）或 pgrep/kill（Linux/Mac）清理占用 profile 目录的残留 Chrome 进程，解决端口 9222 冲突

- 自定义搜索 URL——W1 投递新功能（2026-05-22）
  - orchestrator.run_once() 新增 search_url: Optional[str] = None 参数；搜索迭代重构为扁平列表，custom URL 模式绕过 keywords×cities 笛卡尔积
  - server.py trigger_apply endpoint 透传 search_url → _run_apply_workflow → run_once()
  - WorkflowPanel.tsx：自定义搜索 URL checkbox + 输入框 + localStorage 历史记录 chips（max 10，dedup，newest-first）；customUrlMissing 校验阻止空 URL 触发运行

- 调度器健壮性提升（2026-05-22）
  - 并发竞态修复：trigger_check / trigger_apply HTTP handler 在 409 检查通过后立即设置 emitter.current_workflow，关闭两次快速点击绕过 409 的时间窗口
  - 重启续算：_get_last_run_time(workflow) 从 schedule_log.jsonl 读取最后运行时间，startup 时传 restore_interval_times=True 让 IntervalTrigger 以 last_run 为 start_date 续算
  - formatNextRun 前端升级：从"N分钟后"改为"N分N秒后（HH:MM:SS）"，同时显示相对时间和本地绝对时间

- HR 主动发起会话 stub 记录 + LLM 意图分析（2026-05-20）
  - task_20260519-2355_hr-initiated-stub：HR 主动发起对话时自动创建 stub ApplicationRecord，确保在 jobs 表中有对应记录可追踪
  - task_20260520-0114_llm-hr-analysis：LLM 分析 HR 意图，分类为 interview/offer/reject/general 等阶段并写入 intent 字段
  - task_20260520-0234_analysis-llm-chain：analysis LLM 链路独立配置（config.yaml analysis key），无此 key 时 fallback 到 scoring 链

- 自动调度功能完整实装（2026-05-19）
  - task_20260519-0241_schedule-backend（pass-with-notes）：APScheduler BackgroundScheduler 嵌入 server.py；CronTrigger（指定 HH:MM 时间点）+ IntervalTrigger（固定小时间隔）双触发模式；调度配置持久化到 data/schedule.yaml；运行记录追加写入 data/schedule_log.jsonl（JSONL 格式，线程安全）；新增 GET/PUT /api/schedule 和 GET /api/schedule/log 三个 API 端点；scheduler 与 FastAPI startup/shutdown 生命周期绑定；全量重建模式（_rebuild_scheduler）；Asia/Shanghai 时区；requirements.txt 新增 apscheduler>=3.10.0
  - task_20260519-0241_schedule-frontend（pass）：Dashboard 主页底部新增 ScheduleCard 组件；W1/W2 两栏并列（md 宽度以上）；每栏含启用开关、时间点标签（可删除）、时间点输入、间隔小时设置、下次触发时间预览（绿色）、近期运行记录（成功/跳过/错误三态图标）、"保存后立刻启动一次"复选框、"应用"按钮；卡片右上角显示调度器运行状态（绿/灰色指示点）；30s 自动刷新；所有 CJK 字符串以 \uXXXX 转义；npm run build 通过（203.91 kB JS）

- 修复 search_with_panel 投递弹窗假阳性 bug（2026-04-16）
  - 根本原因：_ele_any 只对第一个选择器应用 timeout，apply_success_dialog 第一个选择器"继续投递"在 React 异步卸载期间短暂残留，导致卡片2/3 的成功检测误命中残留元素，引发假阳性 success=True 和投递统计虚高
  - Pre-apply 阶段：每次 apply_btn.click() 前检查"留在此页"是否存在，若有则点击并等待"继续投递"从 DOM 消失（最多 2s），清除上一张卡片的残留对话框
  - Post-apply 阶段：投递成功后改为显式查找并点击"留在此页"（非 confirmed.click()），附 Escape 键兜底，并等待对话框完全关闭再处理下一张卡片
  - apply_success_dialog timeout 从 3s 延长至 5s；apply_btn 未找到时补充 emitter 事件（LiveLog 可见性）
  - 288/288 测试全部通过

- search_with_panel() JD 检测逻辑改进（2026-04-14）
  - 卡片点击后等待时间从 0.8-1.5s 增加到 1.5-2.5s，给 AJAX panel 更多加载时间
  - 扩展 CSS 选择器列表（新增 .job-sec-inner、.job-sec、[class*='job-sec'] 等 Boss直聘新界面候选项）
  - JS fallback 升级为三阶段：已知选择器 → viewport 右侧最大文本块（与类名无关）→ CSS 类名 dump 到日志（诊断用）
  - 修复 JS viewport 扫描 bug（best.len 改为 best.length）、消除 Python \s 转义警告
  - 288/288 测试全部通过

- W2 原子化重构：search_with_panel() 实现（2026-04-13）
  - browser_agent.py：新增 search_with_panel() 方法，全程留在搜索页做原子操作（点击卡片 → panel 读 JD → on_card 回调 → panel 投递 → on_apply_done 回调）
  - orchestrator.py：Pass 2 改为调用 search_with_panel()，on_card/on_apply_done 闭包承接评分/状态更新逻辑
  - WorkflowTrack.tsx：新增 LiveLog 实时日志组件（自动滚动、"回到最新"按钮、每行颜色编码）；getActiveStep 改为时间戳优先算法，解决"一直显示搜索"问题
  - App.tsx：progressEvents 容量从 200 增加到 500

- 测试套件完整化：FastAPI 集成测试 + E2E 手动测试指南（2026-04-12）
  - code/tests/test_server.py（新建）：62 个 FastAPI TestClient 集成测试，覆盖全部 API 端点；全部通过（5 个测试文件共 160 个测试）
  - 隔离策略：monkeypatch DATA_DIR/CONTROL_PATH/PROFILE_PATH/CONFIG_PATH 到 tmp_path，mock build_llm_client/_build_orchestrator/_check_session_via_browser
  - E2E_TESTING.md（新建于项目根目录）：11 个阶段手动测试指南，含 Onboarding/Session/Profile/W2 投递/W3 检查回应/Carryover/LLM 配置切换/异常场景，附快速验收清单
  - requirements.txt：新增 httpx>=0.24.0（TestClient 依赖）

- orchestrator per-job 流水线 + WorkflowTrack 全面重设计（2026-04-11）
  - orchestrator.py run_once() 重构：carryover pass（历史 DISCOVERED/SCANNED/SCORED 记录优先处理）+ search-then-process pass（搜索后立即逐 job 处理，不再批量），total_ref 可变引用实时追踪总数估计
  - _process_job() 新增 job_idx/total_jobs 参数；fetch/score/resume/apply 各阶段发射粒度 ProgressEvent（[N/M] 前缀 + 当前公司·职位）
  - WorkflowTrack 改为两张独立全宽卡片（W2/W3 各一行），节点改为水平地铁线路图（圆点 + 水平连接线），右侧为活跃步骤详情面板
  - W2 步骤新增 fetch（获取详情），共 5 步：搜索→获取详情→评分→简历→投递
  - 停止按钮全覆盖：WorkflowPanel 停止按钮改为始终可见（disabled 而非隐藏）；W2/W3 卡片标题栏各新增独立停止按钮，按 workflowId 区分 enabled/disabled
  - Dashboard 布局：WorkflowPanel 和 WorkflowTrack 各占独立全宽行，移除之前的 2:1 grid

- 搜索配置页重设计 + 线路图修复（2026-04-10）
  - Profile 页删除姓名字段；薪资范围改为单选 chip（对应 SALARY_CODES）；公司规模改为多选 chip（0-20人 / 20-99人 / 100-499人 / 500-999人 / 1000-9999人 / 10000人以上）
  - cities/experience/degree/job_types/financing 全部改为 chip 选择器，选项严格对应 boss_search_url.py 代码表
  - 新增"预览搜索 URL"按钮：调用 POST /api/preview/search，显示构造好的 URL，支持复制和在浏览器中打开
  - WorkflowTrack 修复：移除空状态隐藏逻辑，现在始终显示 W2/W3 所有步骤（无事件时为 pending 灰色）
  - 侧边栏"个人画像"重命名为"搜索配置"；API 层新增 previewSearch() 方法

- Apple 设计系统落地（2026-04-10）
  - tailwind.config.ts：全新 Apple 色彩令牌（页面背景 #000000、卡片 #1c1c1e/#2c2c2e、Apple Blue #0071e3）、SF Pro Display/Text 字体栈、自定义 card shadow（rgba(0,0,0,0.22) 3px 5px 30px）
  - index.css：-apple-system 字体栈、antialiased 渲染、Apple 风格细滚动条、focus ring #0071e3
  - Topbar：glassmorphism 导航栏（rgba(0,0,0,0.8) + backdrop-filter: saturate(180%) blur(20px)，高度 48px）
  - Sidebar：去除右边框，Apple Blue active 状态（bg-brand-dim + text-brand）
  - 所有卡片：去除边框，改用 shadow-card；StatCard 大数字负字间距 -0.28px，lineHeight 1.07
  - 所有按钮：主 CTA（全流程/保存/Resume）改为 pill 形（rounded-full）；次要按钮 8px 圆角（rounded-lg）；去除 glow shadow
  - 全局负字间距：body -0.374px，caption -0.224px，micro -0.12px（通过 style 属性内联）
  - 构建通过：177KB JS / 14.52KB CSS，0 TypeScript 错误

- React 前端迁移完成（task_025~029，2026-04-10）
  - task_025：React 18 + Vite + Tailwind CSS v3 初始化，布局骨架（App/Sidebar/Topbar），API 层，SSE hook，10s 轮询
  - task_026：Dashboard 页（4 张统计卡片）+ WorkflowPanel（所有参数 + 3 个触发按钮 + 全流程串联）+ WorkflowTrack（Metro 进度轨道，W2/W3 双栏）
  - task_027：Jobs 页（10 状态 tab + 20 条分页表格 + JobDetailDialog）；扩展 Job 接口（decision/critic_verdict/responded_at/resume_path 等）
  - task_028：Chat 页（双栏：会话列表+Stage tab / 消息气泡时间线），me=蓝色右侧，HR=深色左侧，自动滚动到底
  - task_029：Profile 页（8 个逗号分隔数组字段 + 只读 districts/position_types + 3 秒保存反馈）+ Setup 页（5 张状态卡片 + 简历上传）
  - 构建产物：~177KB JS gzip 55KB，~14.7KB CSS；旧 app.js/style.css 由 emptyOutDir:true 清除

- 前端零碎修复 + 计划立项（2026-04-09）
  - orchestrator.py：score_threshold=0 快速路径，跳过 score+critique 两个 LLM 调用，大幅提速
  - orchestrator.py：rate limiter 等待时间 10-30s → 5-20s
  - style.css：补全全局 `.hidden { display: none !important }` 规则（之前缺失导致 running-tip/按钮无法隐藏）
  - app.js：每 10s 轮询 `/api/workflow/status` 同步前端状态，修复服务器重启后 "任务正在运行" 显示残留
  - index.html + app.js + style.css：两个独立 workflow 面板合并为统一配置卡片，新增 days 参数、全流程按钮（Apply→Check 串联）
  - 前端重构技术栈决策：React 18 + Vite + Tailwind CSS v3 + shadcn/ui（替代原 Phase A/B 计划）
  - 新功能规划：无头模式 toggle、generate_resume toggle、W2/W3 详细进度事件（task_024~029）

- 协作基础设施建立（2026-03-29）
  - AGENTS.md：Claude Code 与 Codex 共同遵守的协作约定（编码规范、文件改动纪律、自检清单、冲突处理）
  - COLLAB.md：两个 agent 的异步沟通频道，固定模板（Time/Author/Scope/Change/Risk/Follow-up）
  - work-logger skill：新增 COLLAB.md 联动，写完 worklog 后自动追加一条 COLLAB 记录

- task_023：app.js 全部乱码中文字符串修复（2026-03-29）
  - WORKFLOW_STEPS 步骤标签（7 条）、PAGE_TITLES（5 条）、BOSS_CITY_CODES（21 城市）、BOSS_EXPERIENCE_CODES（8 条）、BOSS_DEGREE_CODES（7 条）、BOSS_SALARY_CODES（2 条）、BOSS_JOB_TYPE_CODES（3 条）、BOSS_FINANCING_CODES（8 条）、buildBossSearchUrl 默认城市 fallback
  - 全部改为 `\uXXXX` Unicode escape，防止 GBK 工具链再次损坏；node --check 通过

- task_022：停止按钮 UI 修复（2026-03-28/29）
  - index.html：Apply 卡停止按钮 id 改为 `btn-workflow-stop-apply`；Check 卡新增独立 `btn-workflow-stop-check`
  - app.js：新增 `getStopBtn(workflow)` 辅助函数；两个按钮独立显隐和状态控制；新增 `status="stopped"` warning toast；成功后保持"停止中..."直到 SSE done 事件到达
  - server.py：`/api/workflow/stop` 无 workflow 运行时返回 `{"ok": false}` 而非 `{"ok": true}`，防止前端永久等待

- task_021：停止按钮后端实现（2026-03-28）
  - orchestrator.py：apply workflow 的 keyword/city 双层搜索循环入口各加停止检查；run_once() 和 check_responses() 末尾按 stop_requested 分支选择 status="stopped" 或正常完成
  - check_responses.py：构造 _stop_check 闭包传给 sync_conversations
  - browser_agent.py：sync_conversations 新增 stop_check=None 参数，逐会话处理前调用

- task_020：简历发送状态机修复（2026-03-28）
  - browser_agent.py：引入 `resume_requested` 中间状态，两步提交（检测到请求先写 resume_requested，发送成功后才写 resume_sent）
  - browser_agent.py：scan_chat_list 修复——resume_requested 强制重新入队；空 preview 分支去掉 `last_msg_from=="hr"` 限制
  - browser_agent.py：_send_resume_in_current_chat Strategy 1 新增境外公司二次确认弹窗处理（Boss直聘 `span.boss-dialog__button:not(.button-outline)`）；弹窗检测失败返回 False 而非误判成功
  - browser_agent.py：发送失败时清空 `last_msg_preview`（双重保障，脏检查强制重扫）
  - tracker.py：新增 `reset_hr_conversation_stage` 方法

- HR 会话发简历逻辑完整重写（2026-03-26）
  - schemas.py：HRConversation 新增 `stage` 字段（general/resume_sent/interview/closed）
  - tracker.py：hr_conversations 表加 stage 列（自动迁移），get_hr_conversations 支持 stage 筛选
  - browser_agent.py：
    - 消息提取器修复：仅过滤 sender=="hr" 的无时间戳非卡片消息（之前误过滤"me"消息）
    - _detect_resume_request 完整重写：支持 A（系统通知）/ B（HR 卡片）/ C（HR 文本）三类请求，检查请求后无已发记录才返回 True
    - _has_sent_resume 修复：新增 system 消息识别（"附件简历已发送给对方"、"[卡片] *.pdf"）
    - _send_chat_message 新增：发打招呼解锁"发简历"按钮（双方回复后可用）
    - _send_resume_in_current_chat 重写为三策略：① 点卡片"同意"；② 点 toolbar"发简历"（div[d-c="62009"]）；③ 文件上传 fallback
    - scan_chat_list 新增 tracker 参数，脏检查逻辑从 sync_conversations 移入此处
    - sync_conversations 新增 aggressive 参数；修复 stage 继承 bug；无 me 消息时先打招呼再发简历
  - config.yaml：apply 下新增 aggressive_resume 字段
  - dashboard/server.py + app.js：会话过滤改为 stage-based（普通/已发简历/面试阶段）

- task_015：HR 会话同步（本地缓存 + 完整读取）+ HR 会话 DB 重构（2026-03-25）
  - scan_chat_list / sync_conversations / read_current_conversation 三个核心方法
  - HRConversation schema + hr_conversations SQLite 表（含自动迁移）
  - conv_id 改为 sha256(hr_name|company)[:12]（稳定主键，对齐 Boss直聘 业务语义）
  - company / hr_name selector 修复（之前取错了 span 节点）
  - 广告 Widget 过滤：time=="" 的 item-friend 消息跳过
  - 脏检查：比较 last_msg_preview，无变化跳过 sync
  - 真实环境验收：30/30 会话同步正确，公司名、发送方识别准确

- task_014：CLI Chat Agent（2026-03-25）
  - --chat 模式启动交互终端，LLM 识别意图分发到 check/apply/config/memory/chitchat
  - Ollama 不可用时降级规则匹配，不崩溃
  - daily_limit guard、长期记忆（long_term.yaml）
  - 验收：pass_with_warnings（W1-W5 不阻断）

- Workflow 2 + 3 端到端验证通过（2026-03-22）
  - Workflow 2（search→score→critic→apply）：7 次真实投递成功，apply 按钮选择器修复 `.btn-startchat` → `.op-btn-chat`
  - 打招呼语逻辑移除：Boss直聘自动发送，我们只需点击按钮
  - Critic 改为宽松模式：只拒绝硬性不符合条件的岗位（极大经验差距/城市不符/完全无关方向）
  - Workflow 3（--check 聊天检查）：check_chat_list() 完整重写，支持 scroll 滚动加载、天数/条数双重限制（config.yaml 配置）
  - 聊天列表选择器修复：`li[role="listitem"]`、`.name-text`、`.last-msg-text`
  - 反爬优化：homepage warmup、_human_pause 从 1-3s 增加到 2-5s、navigator.webdriver 注入 try/except
  - boss_online 过滤器：profile.yaml → Boss直聘 URL 参数 bossOnline=1
  - check_responses_days/max 加入 config.yaml（默认 7 天、200 条）
- 修复 json-repair 导入错误 + 评分阈值用户可配置（2026-03-22）
  - services/llm_parser.py：修复 `from json_repair import repair` → `repair_json`，安装 json-repair 包，评分 JSON 解析失败（errors 11→0）
  - services/onboarding.py：run_setup_profile() 新增第 9 步，用户交互输入评分阈值（0-100，默认 60）
  - orchestrator.py：run_once() 每次从 profile.yaml 读取 score_threshold 并覆盖 config 默认值，同步到 score_tool
  - config.yaml：score_threshold 默认值 72 → 60
  - dry-run 验证通过：searched 34, processed 38, errors 0；Critic 正常拦截不匹配职位
- task_013：增强聊天回复分类 + 附件简历处理流程
  - schemas.py：AppStatus 新增 RESUME_REQUESTED、AD_PUSH；StatusUpdate 新增 chat_url、is_ad_push 字段
  - browser_agent.py：新增 _classify_message()（关键词分类）、重写 check_chat_list()（跳过自发消息）、新增 send_resume_attachment()（文件上传发送）
  - check_responses.py：新增 _handle_resume_request()，自动检测并发送附件简历；AD_PUSH 仅记录日志；绝对路径修复
  - dashboard/server.py：PDF 上传同时保存为 data/resume_attachment.pdf
  - onboarding.py：新增 check_attachment_resume()，check_all() 返回 attachment_resume.ready
- task_010：第一轮 Bug 修复，清零所有 Must Fix
  - services/llm_client.py：ClaudeCLIProvider.complete() subprocess.run 上方加安全注释（list 形式、no shell=True）
  - services/resume_manager.py：render_pdf() 捕获 weasyprint ImportError，抛出含 pip install 指引的 RuntimeError
  - dashboard/server.py：upload_resume() 添加 10MB 文件大小限制，超限返回 HTTP 400
  - 核查确认 M2（打招呼用户名）和 M4（SCORED 状态 score_result）在初始构建中已正确实现
- 初始构建完成（task_001~009）：schemas、tracker、LLM 多 Provider、tool registry、browser agent、resume parser/manager、apply tool、orchestrator/scheduler、FastAPI dashboard

---

## factory 时代 ChatAgent 的 task_0xx 遗留 Warnings（2026-08-22 从 PROGRESS.md 搬入）

> ⚠️ 里面的 **W1~W5 是 chat agent 自己的 workflow 编号，不是现在的 W1 投递 / W2 检查回应 / W3 发送**——重名且毫无提示，这正是把它们搬出 PROGRESS 的原因。ChatAgent 已停用（`main.py --chat` 只打印「暂不可用」），`services/chat_agent.py` 全库唯一调用方是它自己的单测。**仅作史料，不是待办。**

- task_014 遗留 Warnings：
  - W1：_execute_pending 中 Guard 的 state 传入方式脆弱
  - W2：_run_config 意图提取依赖 LLM，Ollama 不可用时 config 修改无法走规则兜底
  - W3：is_confirm 把空字符串视为确认
  - W5：Ollama 失败后 _ollama_available 永久禁用本次 session
- task_013 遗留 Warnings：
  - W1：_classify_message() normalized 变量仅用于英文，中文匹配不一致
  - W2："发过来"关键词过于宽泛，可能误匹配非简历场景
- task_010 遗留 Warnings：
  - W2：MAX_UPLOAD_BYTES 建议提取为模块级常量
  - W3：parse_resume_file 失败时临时文件未清理
