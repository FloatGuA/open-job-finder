# OpenJobFinder — Progress

## 状态快照

| 项目     | 值                              |
|----------|---------------------------------|
| 整体状态 | 进行中                          |
| 最后更新 | 2026-08-09（v2.19.1.14 修「待审批」实时计数 + 修日志陈旧 running + 全项目扫视补 jobs.db 备份/通知缺口） |
| 当前版本 | 2.19.1.14                       |

## 待跟进（另开会话）

### ✅ 待真机验证清单（2026-08-04 汇总，用户暂无精力验收）

代码都已写完、测试与 build 全绿、也已 push，但**下列行为只在合成/单测层面验证过，没在真实浏览器 + 真实 HR 场景跑过**。按"风险从低到高"排列，可分次做；每项标了怎么验、失败会怎样。

**A. 零风险（只看不发，随时可做）**

| # | 验什么 | 怎么做 | 失败的样子 |
|---|--------|--------|-----------|
| A1 | **简历拖拽手感** | 简历工作台里：条目上下拖、跨列从信息池拖进当前简历、拖整个分区 | 拖不动 / 蓝线不跟手 / 松手没落位 |
| A2 | **信息池回滚** | 「全部素材」→「历史版本」→ 挑一个灰灯版本点回滚 → 看内容是否变成那一版 | 回滚后内容没变，或绿灯没跟着移动 |
| A3 | **导出 PDF** | 工作台点「导出 PDF」→ 看下载的文件与右侧预览是否一致 | 排版与预览不一致 / 中文乱码 |
| A4 | **W2 选简历（只选不发）** | 跑一次 W2（可 dry-run）→ 撞到 HR 索要简历的会话 → 会话详情看有没有「建议发 X 版」 | 没有徽标 = 匹配没跑或没落库 |

**B. 会对真人产生动作（挑个能盯着的时间做）**

| # | 验什么 | 怎么做 | 失败的样子 |
|---|--------|--------|-----------|
| B1 | **自动发适配简历**（本轮新增，最需要验） | ①先在工作台**导出一次**目标简历的 PDF ②「自动化和测试 → 检查 → 参数配置」勾上「自动发适配简历」③跑 W2 并盯着 | 找不到上传控件 / 上传后没有「已发送简历」气泡 → **会自动回退 Boss 站内简历，不会漏发**；日志里能看到 `adapted_resume_fallback` 及原因 |
| B2 | W3 发送选择器 | 批准一条回复 → 跑 W3 → 确认消息真的出现在对话里 | 定位到了但没发出（`#chat-input` vs `#boss-chat-editor-input` 漂移，已收敛但真实 id 仍未确认） |
| B3 | W3 新鲜度闸 | 手动回一条 HR 后再跑 W3 → 应作废旧草稿而不是盲发 | 旧草稿仍被发出 |
| B4 | 意图抑制闸 | W2 撞 resume_request 且简历已发 → 不应再产生待审批草稿 | 仍生成多余草稿 |
| B5 | prompt 注入生效 | 设置里填注入 → 跑 W1/W2 → 看评分/意图 prompt 尾部是否带「求职者本人补充指令」块 | 注入没进 prompt（端到端串联已验，只差 LLM 是否遵循） |

**C. 需要特定条件才能撞上**

| # | 验什么 | 触发条件 |
|---|--------|---------|
| C1 | 配额上限处理 | 真实 W1 撞 Boss 每日上限时：看 `w1_quota_warning` 展示、当日调度是否被闸门跳过、次日是否自动解除 |
| C2 | 冒烟真跑档 | 跑一次 live 冒烟：确认投递/发简历真落库（`count_today` / `hr_messages` 增） |
| C3 | 会话列表性能 | 数百会话下搜索/排序的交互与性能 |

> **B1 是本轮唯一的新未知**：`upload_resume_file` 的选择器对真实 Boss 页面**从未跑过**（这段代码此前一直是死代码，本轮才补上送达验证并首次注册）。其余 B/C 项是更早遗留。


- **[2026-08-04 进行中] 简历系统接入 W2**：按岗位选简历已完成（v2.18.0）；自动发送适配简历的开关已实现（v2.18.1，**默认关**）。**剩下的唯一一步＝真机验证附件上传**——`upload_resume_file` 的选择器从未对真实 Boss 页面验证过，需开启开关后盯一次 W2 真跑；上传失败会自动回退 Boss 站内简历，不会漏发，风险可控。另注意：自动发送用的是**已导出的 PDF 存档**，所以要先在工作台导出过那份简历才有文件可发（没有则回退站内简历）。
- **[已完成 2026-08-03] ~~简历系统接入 W1/W2~~**（W1 查证不涉及简历，只接 W2；见「已完成」）
  - **现状**：简历制作侧已完整（信息池 → 多份简历 → A4 预览 → 导出 PDF + 快照回滚 + 前端守门测试）。但 **W1 投递、W2 发简历完全没接**——W2 现在发的仍是 Boss 站内简历，`data/resumes/` 里做好的几份一次都没被用过。
  - **产品边界（用户 2026-08-03 定，务必遵守）**：**Agent 只判断「投这个岗该发哪一份」，不替用户决定简历写什么**。AI 全自动组合内容的能力（`/api/resume/compose`）已实现但**收在默认关闭开关后**，未经用户明确同意不得启用。所以接入方向是**选择题**（从已存的几份里挑），不是生成题。
  - **待想清楚的设计问题（动手前先对齐，勿直接写）**：
    1. **怎么选**：按 `target` 字段关键词匹配岗位标题？还是 LLM 读 JD 判断？匹配不上时用哪份兜底（默认份 / 跳过）？
    2. **发什么**：W2 现在点的是 Boss 站内简历按钮。要发本地 PDF 附件，需确认 Boss 的附件上传交互（`upload_resume_file` 工具已存在但没接这条线），以及 PDF 从哪来——预先导出存档，还是投递前实时渲染？
    3. **可观测/可控**：选了哪份要落库可追溯（applications 加字段？）；是否需要人工确认闸（符合"对真人不可逆"的既有原则）。
    4. **W1 是否需要**：W1 阶段只是打招呼投递，可能根本不涉及简历；先确认 W1 到底要不要接。

- **[大部分完成 + 已 push 2026-07-30] Settings UI 重设计 + 相关**（真机截图逐版验证）：①**IA 重组**——4tab→3tab（求职偏好 / **模型 & Prompt** / 环境&Session）；注入移出求职偏好→独立 `InjectionSection`；模型路由+注入+可编辑模板合并进「模型 & Prompt」——**左列固定 320px（配置）、右列吃满（Prompt 模板）**，页面 `max-w-[1600px]`。②**Prompt 模板 = master-detail**：顶部选项卡短标签一行（系统角色/评分/意图分析/回复生成）+ 下方 560px 大编辑框看全全文 + 上方完整说明 + 已修改橙点。③`save_profile` **字段隔离**（分 tab 独立保存不互清）。④**页面持久化**：刷新保持当前 navigator（localStorage）。⑤**prompt 中文化**：system/score_job 译中文（保留占位符+JSON key）。⑥**仍待做（可选）——「环境 & Session」现代化**（只搬了 tab 未重做观感）；设置内子 tab 刷新不持久化（只主页面）；`max-w-[1600px]` 实测没完全铺满（内容止于 ~1140px，疑浏览器缩放）。均待用户后续决定。

### 🧭 LLM eval 路线图（2026-07-29 收口，攒数据后继续）

这一部分（给 agent 的三个 LLM 判断点建可评估体系）的全貌：

**✅ 已做（都已 commit，见「已完成」对应条目）**
- **eval 方法论 + 基座**：金标从真实生产来、精度≠可靠性两维、LLM-judge 须先对齐人标、回归当质量闸；`code/scripts/eval/`（export/run_intent_eval/diagnose_needs_reply/build_annotator）。三硬约束：金标 PII 只落 gitignore `data/eval/`、eval 忠实生产调用签名、ground truth 必须人标。（#82，commit 69b292e）
- **阶段1 意图 eval 跑通并收口**：用户标 58 条金标；核心认知 **intent 准确率(53%)≠needs_reply 准确率(90%)**（already_sent 派生兜底）；痛点「发完简历后误回」仅 4 条且是审批草稿非错发 → **接受**。prompt 调优验证「能调标签、调不动痛点」（小模型上限）。（#84）
- **意图 taxonomy 重构**（eval 副产品）：needs_reply 折叠进 intent、general 拆 inquiry/notice。（#83，commit 331440a，v2.12.1）
- **阶段2 地基**：`scored_jobs` 采集表，W1 每次真实打分（投+跳两侧）落库。（#85，commit c52f137）

**⏳ 还要做**
1. **阶段2 评分 eval**：写 score eval harness（决策级 precision/recall + 校准 `score_threshold`）+ 网页标注器（人标「这岗想不想要」）。
2. **阶段3 回复质量 eval**：`generate_reply` 的 LLM-as-judge（先拿审批 批准/驳回/改写 动作校准 judge）+ 采集审批通过率/改写编辑距离作生产指标；补 `safe_parse_json` 层级采集（格式可靠性）+ 一致性采样（同输入跑 N 次量方差）。
3. **DeepSeek 实验**（换强模型压意图那 4 条痛点）：接 `openai_compatible` provider，让 analyze_hr_intent 走 deepseek 重跑 diagnose，权衡成本。
4. **扩金标样本**：意图金标稀有类太少（interview_invite 3/resume_request 2）指标抖动，想继续调意图需补。

**⏰ 什么时候继续**
- **阶段2（首要）** → **触发条件：跑够真实 W1（`score_threshold>0` 的真实评分，非全投）让 `scored_jobs` 攒到 ~50–100 条含 JD 的评分记录（投+跳两侧都有）**。攒够即可开工。查进度：`get_scored_jobs()` 或 `SELECT count(*) FROM scored_jobs`。
- **阶段3** → 现有审批数据（244 dismissed + 32 sent）够起步，但 dismissed 脏（混 needs_reply 问题）；排在阶段2 之后。
- **DeepSeek** → 用户设 `DEEPSEEK_API_KEY` 后随时。

- **[已完成 + 真机验证通过 2026-07-29] ~~W3 手动发简历兜底~~**：见「已完成」。**装填→待发→可取消→W3 发送**模型（用户纠正了最初「立即发不可撤销」的设计）：点「发简历」只写 `resume_status=queued`（DB，可取消）→ 并入「待发送」tab → W3 运行时 `SendResumePipeline` 幂等发送→清 queued+stage=resume_sent。**前端交互（装填/取消/待发送合并/徽章）+ W3 真发简历落地均已真机验证通过（用户确认无问题）。** 本项收口。
- **[已完成 2026-07-28] ~~意图判断改进：HR 索要简历且简历已发 → 不应再起草回复~~**：见「已完成」。`AnalyzeStep` 加确定性抑制闸——`intent==resume_request 且（needs_resume 本轮将发 或 already_sent 已发）→ needs_reply=False`，覆盖 LLM 误判、生成回复前短路。检测漏判时（needs_resume/already_sent 都 False）**不抑制**、仍起草兜底，正好与手动发简历衔接。**待真机复核**：真机 W2 撞 resume_request 会话不再产生多余待审批草稿。
- **[已完成 2026-07-28] ~~W2 待审批列表没有实时更新~~**：根因如预判——纯前端。`Chat.tsx`「待审批」tab 的 reply_status 过滤**只在拉取那刻**做一次存进 `conversations`，而批准/驳回/改写是**就地改 `reply_status` 字段、不移除**，且 `displayed` 渲染派生**不再按 reply_status 过滤** + Chat 不轮询 → 操作后该条赖在列表里直到切 tab 重拉。修（见「已完成」）：抽一个 `matchesTabFilter(conv, activeStage)` 单判定，fetch 与 `displayed` 渲染派生**都用它**（消除「拉取时过滤 vs 就地改状态」双源），渲染时按当前 tab **实时**过滤——任何状态变化（批准/驳回/改写/取消）立即从不匹配的 tab 掉出。`selected` 取自 `conversations` 不受影响，详情面板仍显示刚操作的会话。后端无缺陷（#66/#67 已验）。
- **[2026-07-28 待做] W3 新鲜度闸漏「简历已发」system 事件**（审查 Should Fix，用户定本次只记不做）：`send_pipeline._last_nonsystem_sender` 只认 me/hr，简历发送成功是 **system 气泡**。场景：HR 要简历 → W2 `AnalyzeStep` 起草回复(pending) → `ResumeStep` 发附件(system)。此时最后一条非系统消息仍是 HR 的「要简历」→ 新鲜度闸通过 → W3 仍发批准的旧草稿。危害有限（回复与简历互补，非硬冲突），但确是水位盲区。**根治方向**：新鲜度判断纳入 resume-delivered 的 system marker，或记录**审批时的消息水位**（后者更彻底，覆盖所有「审批后发生过 system 事件」的情形）。
- **[下一个任务 · 2026-07-30 用户指定] PDF 简历生成方案**：PDF 简历功能未做完。**现状**：①`services/resume_manager.py`（`ResumeManager`）走 WeasyPrint（Jinja2→WeasyPrint，依赖系统库 libpango），`server.py:137` 初始化但**从不调用**；②`services/resume_blocks.py`（`build_blocks`，LLM 把简历解析+自述整理成结构化块库）+ `services/resume_tailor.py`（`generate_resume_sections`/`generate_greeting`/`render_resume_html`，LLM 按 JD 微调 + 拼 HTML）——这两条走**内联 Python 字符串 prompt、不走 PromptManager**；③前端 `pages/Resume.tsx` + `server.py` 的 resume 端点；④`requirements.txt` 的 `playwright` 只被两个根目录诊断脚本用，暂保留给未定 PDF 方案（若改用 headless Chromium print-to-pdf 替代 WeasyPrint 会用到）。**⚠️ 新会话动手前先（第15条）**：1) 梳理清楚上述 resume 全链路（解析→块库→JD 微调→HTML→PDF；哪步实现了、哪步断链、当前能跑到哪）；2) 定 PDF 渲染方案（WeasyPrint 继续 vs 换 headless Chromium print-to-pdf）+ 是否把 resume 生成 prompt 纳入 PromptManager/可编辑体系；3) 给方案对齐后再动手，据此收敛 weasyprint/playwright 依赖并接线 `ResumeManager`。别直接写。
- **[已完成 2026-07-28] ~~W3 盲发过时草稿~~**：核心担心——用户手动回了 HR 后 W3 仍盲发批准时的旧草稿。**已修（见「已完成」）**：W3 `send_pipeline` 加发送前新鲜度闸——重扫会话，最后一条非系统消息若不是 HR（=批准后有人回过）→ 作废草稿（`invalidate_reply_for_reanalysis`：清 reply_status/text/intent + last_analyzed_ts=0 打回未分析）→ 下一轮 W2 重跑意图判断，要回才重起草进待审批。dry-run 在闸前短路；读失败保守跳过保草稿。**取舍**：重起草归 W2（不在 W3 内联 LLM），故不是当场重发而是下次 W2。**待真机 W2/W3 复核**：①闸在真机能正确识别「末条我方」②作废后下轮 W2 确实重分析（last_analyzed_ts=0 → unanalyzed 命中）。
- **[2026-07-28 W3 审查遗留] W3 其余成熟度问题**（#2/#4 已修，见「已完成」；余 #3）：
  - **#2 【已完成 2026-07-28】** ~~`get_approved_replies` 两份实现 + W3 未拿到 O(1) 直开~~：tool 收敛为薄壳调 `tracker.get_approved_replies()`（消灭第二份 SQL）+ 带出 job_id/boss_conv_id；W3 定位链改「直开优先（`navigate_to_conversation` Treatment D）→ 搜索兜底」。见「已完成」。
  - **#3 【已完成 2026-07-28】** ~~verify 探针历史假阳性~~：改用「发送前/后精确匹配我方气泡数增量」（`_reply_landed`），彻底砍掉 16 字前缀 substring。见「已完成」。
  - **#4 【已完成 2026-07-28】** ~~W3 summary 被丢弃~~：`_run_reply_workflow` 现返回 run_w3 的完整 summary，schedule_log reply 行不再恒空。见「已完成」。
  - **#5 W3 从不自动调度 =【已确认有意设计，非待办，2026-07-28 用户确认】**：scheduler 只挂 W1/W2，批准回复只能靠手动触发/显式链才发出——发真人要人把关，不自动调度是刻意的。勿再当缺口重提。
- **[已完成 2026-07-29] ~~AI agent prompt 注入可配置化 + 注入分级~~**：见「已完成」。分级语义与用户对齐为**作用域分级 = 系统层(global) + 任务层(per-task)**（否掉强度分级/运行时粒度，simplicity first）。旧 `extra_notes`（只喂评分的单一注入口）判定为冗余、删除，由 `prompt_injection.global` 取代。**待真机复核**：真机 W1/W2 填了注入后，评分/意图/回复的 prompt 尾部确实带上「求职者本人补充指令」块。
- **[已完成 2026-07-28] ~~W1 又出现大量跳过（skip）~~**：**根因＝去重机制误判，非新 bug**。诊断最近真机 run（`w1_20260724_1018`）：37 个跳过 100% 是 `classify_skip`，`prior_status` 全是 APPLIED/INTERVIEWING——即 DB 认为「已投过」而跳。但用户实测：这些被跳岗的 Boss 按钮**全是「立即沟通」**（= Boss 根本不认为你招呼过），说明 DB 的 APPLIED 记录是脏的（历史「投 150 记 63」+ backfill 补 96 佐证）。**处理：直接拆掉 W1 两层 DB 去重**（见「已完成」），相信 Boss 推送，投没投过唯一以 apply 那步真实按钮状态（`already_chatting`）为准——从根上消灭「误判跳过」这一整类问题。排查「30 天复活/去重为何误判」判定不值得。
- **[部分完成 2026-07-28] 投递失败截图 + 排查投递失败根因**：①**截图已改好**（见「已完成」）——最大化窗口 + 全页截图（`full_page=True`）+ 命名带 run_id（`{run_id}_{job_id}_{ts}.png`，能定位到某次 run 的某张卡）+ `open_browser` 加 `--window-size=1920,1080`（headless 默认 ~800px 视口是右侧面板被切、按钮不在画面的根因）。②**根因排查待下次真机**：现在失败截图能看到完整详情面板 + 投递按钮区，下次真机 W1 撞 `button_not_found` 就能据图定位（选择器失配？按钮在 footer？未渲染完？）。此前 3 例 `button_not_found` 的旧截图因视口太窄看不到按钮，无法诊断。
- **[2026-07-22 已被整改收口] 冒烟测试相关待跟进**：下方 2026-07-10 的层2/层3 冒烟条目均已被 2026-07-21~22 的「阶段0 冒烟可信化」取代——冒烟加了 covered 三态、走队列、run_diagnostics 诊断器，并多次 live 冒烟真机验证（ok=True/fully_covered=True）。历史条目保留可追溯，不再是活跃待办。
- **[已验收 2026-07-10] 回归测试层3 真机端到端冒烟**：真机 `run_smoke` 跑通 **ok=True 148s**（登录态有效=浮瓜；W1 dry-run cards_viewed=2/scored=1/74s + W2 dry-run convs_processed=5/无 error/74s）。真机验证了层3 冒烟工作 + 直开 D 生效（5 会话 74s，旧版会慢死）。
- **[已澄清 2026-07-10] ~~层2 抓到的 9 条空正文~~ 是不变量误报、非脏数据**：9 条全 sent 状态，`reply_text` 是「working reply, cleared after send」——sent 后清空正文是**设计行为**。已修层2 不变量 `_REPLY_NEEDS_TEXT` 去掉 sent（只 approved/revision 待发送才须有正文），层2 现全绿。教训：不变量要用真机数据校准。
- **[已验证 2026-07-10] W2 回复生成 think 拆分 + 直开 D**：真机 W2 dry-run 跑通 analyze 链路无 error、直开 D 生效；generate_reply 单点已真机验证（think=true 7.4s 得体回复）。
- **[无关] `docs/interview-prep-futu.md`** 是会话外的未跟踪文件，与本项目无关，历次 commit 均排除。

- **[已完成 2026-07-06] ~~W2 会话列表抓取升级为读 getGeekFriendList API~~**：硬关联升级已落地并真机验证，见"已完成"。剩余小尾巴：①Phase 5 会话级 job_id 兜底（getBossData XHR）暂缓——探针证列表 API 100% 覆盖，没 job_id 的会话实际不存在，留待真出现漏网再补；②存量 606 条无 job_id 软键会话靠"重扫即吸收"逐步收敛，未一次性批量回填。
- **[已完成 2026-07-06] ~~架构-流程页升级为真实 workflow-step-tool 级~~**：见"已完成"。W1/W2/W3 三泳道对齐硬关联升级后的真实 step·tool + 源码位置。仍是手维护常量（`W1_STEPS`/`W2_STEPS`/`W3_STEPS`），未做自动派生——权威源仍是 run JSONL，后续代码若再迁步骤仍需手动同步此页。
- **[已完成 2026-07-06] ~~架构-流程页补脏检查环节~~**：W2 泳道已把「扫描」拆为 扫描列表（`extract_conversation_list`）+ 脏检查（`filter_conversations`，lastTS 增量）两独立节点。

- **需下次真实 W1 跑验证**本次投递漏记修复：配额提醒弹窗是否被正确识别为「已发送」、硬上限是否触发 rate_limited 停机、点「好」是否真能关掉弹窗解除后续阻塞。
- Boss 硬上限的**确切文案未截到实证**：`_HARD_LIMIT_MARKERS`（达到上限/用完/明天再来 + 还剩0次）为推断值，真机验证时留意实际文案，必要时补入。
- 今天 63→150 的历史计数**不回填**（无法逐条判定哪些 dialog_blocked 是真发出；计数明天自然归零）。**[部分解决 2026-07-06]** 这些真投没记上的岗位，凡是有 HR 会话的，已被 W2→W1 backfill 补录回 APPLIED（本次真机补 96 条）；纯无会话的仍无法回填。
- **[已修 2026-07-06] ~~W1 hr_name 偶发 `\n刚刚活跃` 后缀没剥干净~~**：原 `_HR_NAME_JS` 只按类名剥 `span.boss-active-time`，某 DOM 变体的活跃后缀 span 类名不同 → 漏剥，落成"X女士\n刚刚活跃"。改为**删所有子 span（名字是直接文本节点、不在 span 里）+ 取首行**（两机制各自都能盖住该变体，叠加更稳）；测试 mock 路由标记同步。待下次真机 W1 复核。
- **[待真机验证] 配额上限完整处理**（已实现，见"已完成"）：需真实 W1 撞上限时确认 ①接近上限的 `w1_quota_warning` 前端展示 ②硬上限后当日定时/自检真的被闸门跳过（看 schedule_log / selfcheck_log 的 skipped_reason）③次日中国日期滚动后自动解除。
- **[已收口 2026-07-06] ~~两表关联断裂~~**：本次 job_id 硬关联升级从根上解决（见"已完成"）。原 hr_name 路径的待办已大多变无关——①空 hr_name 不再影响关联（改按 job_id 硬 JOIN，405 条空 hr_name 应聘照样关联）；②sync 复活本次 W1+W2 真机跑通；③"一公司多 HR"边界对 job_id 硬键无影响；④真机已验证（W1 3/3 投递建占位 + W2 200 处理 sync 生效 + backfill 补 96）。仅遗留：532 条历史无 job_id 软键会话随后续 W2 逐步"即时吸收"收敛（无害，无需干预）。

## 已完成

- **修「日志陈旧 running」+ Chat.tsx 拒绝全部计数不实时更新**（2026-08-09，v2.19.1.14，commit `3832cd2`，696 passed，build 绿；纯代码修复，无需真机验证）
  - **日志陈旧 running 根因**：`w1_runner.py`/`w2_runner.py` 正常异常路径本就会 `run_logger.close("failed")` 再 raise——但**硬杀进程（Stop-Process/崩溃）跳过整个 except/finally**，run_end 永远不会写入；而 `run_log_reader.py` 的读取逻辑把"最后一行不是 run_end"一律显示成 `running`，且 server 启动时从无孤儿回收机制（grep 全库确认零命中）——两者叠加就是 Logs 页面卡死在 running 不会消失。
  - **修复**：新增 `services/run_logger.reconcile_orphaned_runs()`，server 启动时调用一次。判据干净：**进程刚启动，此刻不可能有任何 run 在真实运行**，所以任何"最后一行非 run_end"的 run 文件在此刻都是无歧义的孤儿——不是靠猜的启发式。给孤儿 run 追加一条合成 `run_end`（`status="failed"`, summary 注明"orphaned: 进程随服务器重启已消失"），复用既有 `failed` 状态词表（前端 Logs 页已有红色渲染，不用改前端）。只追加不改写，保持 JSONL 只增量写的既有纪律。`dashboard/server.py` 的 `startup()` 挂载调用 + 日志行。测试 +3（孤儿闭合/正常结束不动/无 runs 目录）。
  - **顺带清理**：Chat.tsx「一键拒绝全部」按钮三处用了未实时更新的 `conversations.length`（个别处理只改字段不移除数组项，长度不随之收缩），改用页面实际渲染用的 `tabScoped.length`；纯显示层修复，后端 `dismiss_all_pending_replies` 的 SQL 作用域本就按 DB 实时 `reply_status='pending'` 走，不受影响。
  - **PROGRESS.md 顺带精简**：清掉几条已过时/低价值的历史遗留待办（W2 已批准回复发不出去问题A/B、`update_status()`竞争与`datetime.utcnow()`迁移——后者其实已在别处完成、三条未验证选择器、"计算机视觉操作层"长期设想）——2026-08-05 从 TECHNICAL.md 迁入时未经复核就整体照搬，这次借机核实后清理。

- **简历排版与工作台改版**（2026-08-04，v2.19.0.1，677 passed + 前端 13 passed，build 绿，真机逐项验证）
  - **① 字体**：正文改 **微软雅黑**、标题类（姓名/分区标题/条目标题）改 **黑体**，移除原 Georgia 衬线（用户定）。
  - **② 字段级富文本**：每个条目的 **标题 / 时间 / 要点各自** 可切 粗/斜/下划线（B/I/U 三个开关 × 三个字段）。**空样式 = 用模板预设**，所以老数据与 AI 组合生成的简历行为完全不变，只是字体按 ① 换掉。开关只在「当前简历」列出现——信息池是素材库，不管排版。真机验证：点「标题-加粗」预览立刻出现 `font-weight:700`。
  - **③④⑤ 新建简历入口重构**：原「已保存简历」页的「+ 复制当前为新简历」与工作台的「当前简历」概念冲突，且工作台**没有把当前这版存进简历池的出口**。合并为工作台里一个控件「**存为新简历**」（目标岗位 + 可编辑简历名 + 按钮），默认名 = `日期_姓名_目标岗位`（如 `20260804_张三_游戏策划`，没填岗位退成「简历」）；用户改过名就不再自动覆盖。已保存简历页改为一行引导文案。措辞同步改清楚：「上传**本地**简历入池」「导出**当前简历** PDF」。
  - **⑥ 进阶折叠条**：从一行灰色小字改成带边框/箭头/副标题的可展开 bar（「进阶功能 · 预制模板 · 按已投岗位生成方案与招呼语」）。
  - 测试 +6（后端 3：样式归一化/往返/老数据补空；前端 3：字体断言/字段级样式只作用于指定字段/无 style 时不输出 inline 样式）。
  - **【v2.19.0.3 跟进】**
    - **B/I/U 内联到各输入框旁**：原来是详情区底部一条「排版」工具条（标题/时间/要点三组挤在一行），改成**改哪个框就点它旁边那组**——标题框右侧、时间框右侧、要点框右侧各一组，抽出 `MarkButtons` 组件复用。
    - **三列宽度重排**：当前简历列从 26rem 放宽到 `flex-1`（封顶 44rem，避免输入框被拉成一条长线），信息池收到 21rem，预览列固定 34rem（一页 A4 缩放后刚好）。
    - **预览改 Word 式分页**：`A4Preview` 不再是一条长页，而是按 A4 高度（1123px @96dpi）把**同一份 HTML 切成 N 页**渲染（每页一个 iframe + 负偏移 + 裁切），页间留白、右下角标「1 / 2」页码。**切片而非画分割线**——这样看到的断页位置就是打印时真实的断页位置，仍与导出 PDF 同源。
    - **【v2.19.0.5】英文字体 + 列宽兼容窄窗口**：正文与分区/条目标题的字体栈前面插 `Arial, Helvetica`——**字体栈自带分工**：Latin 字符命中 Arial（基础款），中文字符 Arial 无字形→自动回落雅黑/黑体，无需分元素设字体；姓名仍保留衅线（刻意保留的 fancy 元素）。当前简历列加 `xl:min-w-[40rem]`——宽屏下它本就比信息池宽（实测 832 vs 336），但**窗口变窄时两列会被压到接近**，最小宽度保证标题框 + 三个 B/I/U 任何窗口下都放得下。
    - **【v2.19.0.8】三列宽度拉平 + 删两处冗余字段**：
      - 列宽：上一版把信息池固定成 21rem，与当前简历差了 2.5 倍（336 vs 832）——用户要的是两列**差不多宽、简历只稍宽**。改成三列都参与拉伸：信息池 grow 1 封顶 44rem，当前简历 grow 1.15 封顶 52rem，**预览固定 basis 50rem 且 grow 0**（不参与分配，保住 A4 scale 1.0）。实测 631 / 725 / 794。
      - **删「自我描述」整张卡**（含「融入信息池」按钮）：该字段不进预览，唯一用途是当 `build_pool` 的输入；而 `build_pool` 是 **LLM 整体重写信息池**，与「简历内容由用户掌控、Agent 只判断投哪份」的产品边界相冲。前端入口拆除，后端 `/api/pool/build` 与 `info_pool.build_pool` **保留不动**（日后若要重新暴露很容易）。
      - **基本信息删 `degree`（学历）**：预览 header 只渲染 name / email / phone / city / target_title，`degree` 填了也不会出现。（注：`profile.yaml` 里的 `degree` 是**搜索学历筛选**，同名不同物，未动。）
    - **【v2.19.0.4】姓名字体 + 预览尺寸**：姓名从黑体改为讲究些的衬线（`STZhongsong / 华文中宋 / Songti SC / 宋体 / Georgia / serif` 逐级兜底）+ 字距 6px，与正文黑体拉开层次；分区/条目标题仍黑体。**预览此前被固定成 34rem 显得偏小、宽屏右侧一大片留白**——改为：信息池固定 21rem 不参与拉伸、当前简历封顶 52rem、预览参与拉伸（封顶 50rem），容器 `justify-center` 整组居中。实测 2480px 视口下 **A4 渲染到 794×1123 原尺寸（缩放 1.0）**，简历文字清晰可读，留白均分两侧而非全堆右边。

- **W2 按岗位选简历 + 自动发送适配简历开关**（2026-08-04，v2.18.0 / v2.18.1，674 passed + 前端 10 passed，build 绿）
  - **产品边界**：Agent 只做「投这个岗该发哪一份」的选择题，**不生成/改写简历内容**（用户 2026-08-03 定）。W1 经查证完全不涉及简历（`grep resume pipeline/w1/` 零命中），故只接 W2。
  - **选（默认行为）**：`services/resume_matcher.py` 确定性关键词匹配——每份简历的「目标岗位」切词后与岗位标题/JD 比对，**标题命中权重 3、JD 权重 1**（JD 里什么词都可能顺带出现），同分取 `updated_at` 更新的；全不中 → 当前激活份兜底 `matched=False`。**刻意不调 LLM**：路由决策要可解释、可预期，用户能一眼看懂为什么选了这份。落库 `hr_conversations.matched_resume` / `matched_resume_reason`（**存名字不存 slug**，简历删了事后仍可读），前端会话详情显示「建议发 X 版」+ 理由。
  - **发（开关，默认关）**：`w2.auto_send_adapted_resume`。开启后 W2 优先把匹配到的那份简历的**已导出 PDF** 作为附件发出。**PDF 来源选「已导出存档」而非后端重新渲染**（用户拍板方案 a）——A4 版式的唯一实现在前端 `src/lib/resumeHtml.ts`，后端再写一份就是「同一契约两份实现」，必然漂移；代价是用户需先导出过该简历。
  - **绝不漏发**：没导出过 / 找不到上传控件 / 上传后没出现送达气泡 —— 任一情况都**自动回退 Boss 站内简历**并记一笔 `adapted_resume_fallback`（不让「为什么发的是站内简历」变成哑谜）。6 个测试覆盖全部失败模式。
  - **补了上传工具的致命缺陷**：`upload_resume_file` 原本点完确定就返回 `ok=True`，**没有验证简历真的送达**——正是项目在工具栏那条路上吃过亏的「动作做没做 ≠ 结果发生没发生」。现改为复用 `wait_resume_delivered`（等新的「已发送简历」系统气泡）作为唯一权威成功信号。该工具此前**从未注册**，一并注册。
  - **接线守门**：参数是逐个枚举传递的（`workflow_orchestration` → `run_w2` → `W2Config`），漏一处开关就永远传不到 → 端到端验证过 config→resolver→runner→W2Config 全通；另有测试断言 `match_resume` 必须注册进 W2（否则 `registry.call` 静默失效）。
  - **⚠️ 未验证**：`upload_resume_file` 对真实 Boss 页面的选择器从未跑过（一直是死代码）。首次开启开关需真机盯一次。

- **信息池快照回滚 + 前端首次有自动化测试**（2026-08-03，v2.17.1，649 passed + 前端 10 passed，build 绿，端到端灾难恢复验证）
  - **补的是两个自评出来的最大风险**（非用户报障）：①信息池是唯一主库却**零备份**，而「融入信息池」让 LLM 整体重写 sections，一次误保存不可逆；②整块功能 90% 复杂度在 `Resume.tsx`（1028 行）却**零前端测试**——此前 4 个真机 bug 全是 pytest 绿 + build 绿的情况下靠用户实测才发现。
  - **① 快照**：`save_pool` 每次写盘前自动留档到 `data/pool_snapshots/{时间戳}.yaml`（同秒多次保存加序号）；**分层保留**——最近 10 个 + 最近 14 天里「每天最早的那个」（UI 绿标「每日」）。单纯「保留最近 N 次」的问题是：一天里连点十几次保存就会把几天前那个内容完好的版本挤掉，而那恰恰最需要回滚；测试专门守这条（一天内狂点 6 次，三天前的存档仍在且可回滚）。**列表首行是绿框「当前版本（正在使用）」**，历史项按内容指纹比对：与当前一致的亮绿灯显示「使用中」（不给回滚按钮），只有真正不同的版本才可点回滚——用户原话「不然可能点错了反而丢了重要的」。`list_snapshots`/`restore_snapshot`（回滚本身也先留档，防误回滚）+ 端点 + 「历史版本」UI（列出时间/分区数/条目数，一键回滚）。`build_pool` 回包带 `_stats`（整理前后条目数），**变少就在池上方橙色告警**提示核对或回滚，且未点保存不写盘。端到端验证：保存留档(11 条) → 模拟 LLM 清空(掉到 1 条) → 回滚 → 完整恢复 11 条、分区结构一致。
  - **② 前端测试**：引入 vitest + jsdom + @testing-library/react；`buildResumeHtml` 抽到 `src/lib/resumeHtml.ts` 便于单测（7 例：空分区渲染标题/空白条目过滤/分区顺序/HTML 转义/日期元素）；`SectionEditor.dnd.test.tsx`（3 例）守**拖拽放置契约**——断言 `dragenter` 与 `dragover` 都被 `preventDefault`（即"浏览器会不会给你 drop"），而非 drop 回调逻辑。**`npm run build` 改为先跑测试再构建**，测试挂则构建不出。
  - **变异测试证明有效**：把 `acceptEnter` 的 `preventDefault` 摘掉（忠实复现当初的真机 bug）→ 2 个测试立刻失败并直指"真机拖过去毫无反应"；还原后 10 passed。（注：只摘单层 `onDragEnter` 不会失败，因为事件冒泡到列级仍被接受——多层防御是有意的。）
- **三列简历工作台 + AI 定制降级为默认关开关**（2026-08-03，v2.17.0.1，645 passed，build 绿，合成 DragEvent 真机验证跨列拖拽）
  - **产品定位校正（用户 2026-08-03 定）**：简历内容**由用户自己掌控**——自己定几套版本，**Agent 只判断投这个岗该发哪一份**，不替用户决定简历写什么。v2.16 建好的 AI 全自动组合链路**保留但收进「AI 自动定制（实验）」默认关闭开关**（localStorage `resume.aiCompose`），打开才显示岗位/JD 输入。「AI 完全掌控简历内容」留待后期用户明确同意再推进。
  - **分页1 简历工作台 = 三列并排**：信息池（全部素材）│ 当前简历（这份实际包含什么）│ A4 实时预览。池与简历**同构数据、同一 SectionEditor 交互**，所以并排最自然。基本信息在池里编辑并同步进当前简历。
  - **池 → 简历跨列复制拖拽**：条目/整分区都可从池拖进简历列，**复制语义**（池保留）；落到**同名分区**（没有则按池的分区名自动新建）；支持精确插入位置（蓝线指示）；同标题+同时间去重跳过。另配 `→`（单条）/`⇒`（整分区）按钮作为拖拽的替代路径。简历列内仍可自由重排/跨分区移动/删除（只影响这份）。
  - **分页2 已保存简历**：多份简历管理（新建/切换/改名/改目标岗位/删除）+ 最近生成存档 + AI 定制开关 + 原进阶功能（预制模板/招呼语）折叠保留。
  - **修一个真 bug**：SectionEditor 在调 `onExternalDrop` 前就清空了模块级 `dragItem`，父组件读到 null → 跨列拖拽静默失效。改为把拖拽项作为参数传出。
  - **验证**：用合成 DragEvent 在真实页面派发（dragstart→dragover(指定半区)→drop），验证删除后从池拖回精确落位、池数量不变（复制而非移动）、去重生效。
  - **【v2.17.0.3 跟进三修】**
    1. **跨列拖拽真机失效的根因＝`dragenter` 未 `preventDefault`**：浏览器要求 dragenter **与** dragover 都被取消才把元素认作有效放置目标，否则 **drop 根本不触发**（拖过去毫无反应也无报错）。加统一 `acceptEnter`（四处落区：整列/分区/条目/空分区）并同步设 `dropEffect`。**上一轮"验证通过"是假绿——合成测试手动派发 drop，绕过了浏览器这道判定**；正确诊断法是只发 dragenter/dragover 后断言 `defaultPrevented`。
    2. **FlowCV 式视觉层级**：分区标题（一级）15px 加粗 + 左侧蓝色强调条；条目（二级）左缩进 + 引导线，从属关系一眼可见；拖拽锚点换 `⠿` 六点手柄、常驻 55-70% 不透明度、hover 满显 + 加大点击热区。
    3. **已保存简历加 A4 预览**：新端点 `GET /api/resumes/{slug}/blocks`（读某份内容**不改激活份**）+ `ResumeStore.get_blocks`；点卡片切换预览（白色描边标记当前预览），另设「编辑」按钮才切换激活份——**看和改分离**。
  - **【v2.17.0.4 保存修复】** 用户反馈「全部素材里改了保存不了、切走就没了」：根因是编辑状态在 Workbench 内部，**切分页即卸载丢失**，且唯一的顶部「保存」没表明它同时管信息池。修：①**信息池 / 当前简历各自独立保存按钮**（列头 + 「全部素材」卡右上各一个，未保存时蓝色可点、保存后变「✓ 已保存」）②**编辑状态提升到页面级**——切「已保存简历」再切回来，未保存的修改仍在 ③未保存时页签旁显示橙点「有未保存的修改」，关标签页/刷新触发浏览器拦截 ④切换/新建/AI 生成简历前 `flushEdits()` 自动落盘，避免被服务端内容覆盖；上传入池前若池有未保存改动会先征询。真机验证：改分区名→切页往返仍在→保存→服务器落盘→改回→再保存复原。
  - **【v2.17.0.6 可读性/可点性】** 用户反馈「保存不显眼、字体太小（比如新增）」，截图放大自查后整改：①**保存按钮做成真按钮**——13px 半粗、px-4 py-1.5，未保存＝蓝底白字 + 3px 蓝色光晕，已保存＝深底 + 边框（不再几乎隐形）；「全部素材」卡右上原本只有一个灰色 `✓`，改为始终显示「保存 / ✓ 已保存」文字 ②**操作按钮带文字 + 加大热区**：`+`→「+ 新增」、`⇒`→「⇒ 全部」，12px 中等字重 + hover 底色；`✕` 加 hover 红底 ③**小字下限抬高**：说明段落/计数徽章/时间/次级按钮 10px→11px，展开区 ↑↓/删除 11px→12px，概括输入框 11px→12px。**踩坑**：补丁脚本用 `repr(esc(...))` 生成 JS 常量导致**双反斜杠**，页面直接显示字面量 `保存`——写 `\uXXXX` 常量时不能再经 `repr()`。
  - **【v2.17.0.7 空分区预览】** 用户实测：只有一级标题、没有任何条目的分区，**预览完全无变化**（新建分区打了名字像没生效）。根因 `buildResumeHtml` 里 `if (!list.length) return ''` 把无条目分区整块跳过。改为**只要分区名非空就渲染标题**（名字与内容都空才跳过）——所见即所得，不想要的空分区删掉即可。真机验证：新建空分区→预览立刻出现「新分区」→改名→同步变更。
- **信息池 + AI 按 JD 组合简历**（2026-08-03，v2.16.0.1，645 passed，build 绿，真机验证组合行为）
  - **信息池（`data/info_pool.yaml`）= 关于求职者的全部信息主库**，高于任何一份简历：上传简历解析**入池**（`merge_parsed`：同名分区并组、同标题块替换、新块追加，池只增改不删）；简历 = 从池**复制**组合而来，改简历不回写池。首次访问自动把激活简历迁移为池初始内容。
  - **动态自定义分区（破坏性数据形状变更）**：文档形状从固定五键（education/internship/...+section_order）改为 `sections: [{name, blocks[]}]`，分区名自定义（如「游戏经历」「Agent 经历」）且**就是简历上的分区**，顺序即数组顺序。`load_blocks` 读到旧形状自动转换（保序、按中文名映射），存盘即固化——**存量文件零手工迁移**。
  - **AI 组合（`POST /api/resume/compose`）**：LLM 只输出「分区名 + 挑中的块 id（`s{分区}#{块}`）」（judge），块内容由 code 从池原样复制（不杜撰、非法 id 丢弃、空分区丢弃）；产出落成**一份新简历并激活**。新 prompt `resume_compose.md`（纳入可编辑体系）。真机验证（目标岗「游戏策划」）：正确**舍弃**无关的某研究所项目与某实习、把甲大学本科**排到**乙大学之前、项目分区重命名为「AI Agent 项目」——即用户要的「投开发岗剔除游戏经历、投策划岗把游戏经历前置」。
  - **前端**：简历页拆**子页切换**「简历制作 / 信息池」（localStorage 记忆）；`SectionEditor` 抽成共用组件（池与简历同一条状拖拽+展开详情交互）；分区名可就地改、可增删、预设快捷添加；左栏新增「AI 定制简历」（填岗位/JD → 生成并切换过去）。
  - 后端：`services/info_pool.py`（load/save/merge_parsed/build_pool）、`/api/pool` GET/PUT + `/api/pool/build`（自述融入池，取代旧 `/api/resume/blocks/build`）、tailor 端点改吃池。测试 +9（`test_info_pool.py` 迁移/合并语义/兜底、`test_resume_compose.py` id 校验与复制、legacy 形状转换）。
- 简历制作台：多份简历管理 + 最近生成存档 + 拖拽排序（2026-08-01，v2.15.0.1，639 passed，build 绿，真机验证多简历创建/切换/导出存档）
  - **多份简历（用户定：每份独立完整，FlowCV 式）**：`services/resume_store.py`——`data/resumes/index.yaml`（active + items 元数据）+ `{slug}.yaml`（每份完整块集）；**兼容位** `resume_blocks.yaml` 始终镜像激活份（JD 定制/onboarding/上传等既有消费方零改动），切换=拷入、保存=双写；首次自动把现有简历收编为「默认简历」。每份带「目标岗位」字段——给不同岗位各建一份默认版，投对应岗位用对应版本。
  - **左侧独立栏**：「我的简历」（激活份高亮+名称/目标岗位就地编辑（防抖落库）、点击切换（切换前自动保存当前份）、复制当前为新简历、删除守卫至少留一份）+「最近生成」（导出 PDF 按 `{时间戳}_{人名}_{简历名}.pdf` 存档 `data/resume_pdfs/exports/`，列表下载/删除，滚动上限 20 修剪，不再互相覆盖）。
  - **拖拽排序**：块卡片 ⠿ 手柄同分区内拖拽重排（保留 ↑↓）；分区（教育/实习/项目…）⠿ 手柄拖拽调整在简历里的先后——`section_order` 随简历存储，编辑列/预览/导出三处同序。
  - **概括说明写清**：placeholder/title 明确「不上简历；按 JD 定制时 AI 靠它挑块——写得准挑块才准」。
  - 后端：`/api/resumes` CRUD + activate、`/api/resume/exports` 列表/下载/删除、print-pdf 存档化；`resume_blocks.normalize_section_order`。测试 +6（store 迁移/双写/删除守卫/顺序归一化/存档修剪/路径穿越拒绝）。
  - **交互重做（v2.15.0.2，用户反馈"全尺寸卡拖动太僵硬"）**：改为 **FlowCV 式条状+展开**——收起=紧凑条（整条可拖、拖动中源条半透明、落点显示 2px 蓝色插入指示线，按鼠标在条上/下半判定前后）；点击条平滑展开详情表单（grid-rows 过渡；展开时不可拖；↑↓/删除收进展开区底部）；一次只展开一条；分区改轻量分组头（⠿+名称+计数+添加）同样插入线拖拽，全部分区收进一张「简历内容」卡。简历模板微调（tabular-nums 日期/1px 分隔线/字距）。真机验证条状渲染+点击展开。
  - **注**：拖拽是 HTML5 原生 DnD，自动化合成事件无法验证，需人工拖一下确认手感。
- FlowCV 式双栏简历编辑器 + A4 实时预览 + PDF 导出（2026-08-01，v2.14.0.7，commit `bc6611b`，633 passed，build 绿，真机截图逐版验证）
  - **交互模型**：Resume 页重写为左编辑（基本信息/自我描述/五类经历块，输入框加大）/ 右**固定 A4** 实时预览（794px 画布 `A4Preview` iframe 按面板宽等比 scale）；顶部工具条 上传/保存/导出 PDF；JD 定制（模板+岗位特化）折叠进底部进阶区（原样保留）。
  - **排版模板**：按用户 resume_inbox 的 FlowCV 简历还原固定单模板——居中大标题+联系行（· 分隔）、分区标题整行下划线、条目粗标题/右灰日期、Georgia 衬线+中文黑体。
  - **同源导出**：新增 `POST /api/resume/print-pdf`（前端预览 HTML → Chromium 打印），预览与 PDF 同一份 HTML，所见即所得；旧 `render_resume_html` 仍服务 JD 定制 plan PDF，暂不合并。
  - **待跟进**：print-pdf 端点需重启 dashboard 生效（改 server.py 时 --reload 未触发，运行中进程是旧的；fresh import 已验路由注册 OK）。
- 视觉模型解析简历：PDF 页面图片 → 视觉 LLM → 结构化块库（2026-08-01，v2.14.0.4，633 passed，build 绿，真实简历端到端验证）
  - **视觉 provider 最终选型（用户 2026-08-01 定）**：vision 链 = **codex_cli 主 → claude_cli 兜底**，**本地 VL 已从链移除并 `ollama rm qwen2.5vl:7b`**；两个 CLI 都失败 → **上传直接报错**（PDF 不再回落弱 pdfminer 文本路径，fail fast，宁可报错让用户知道；DOCX 无页面图仍走文本）。
  - **为什么弃本地**（真机对比同份 2 页 FlowCV 中文简历，测试文件不入库）：两个 CLI 都走**用户订阅额度、不需 API key、不额外付费**，精度**吊打**本地小 VL——codex_cli/claude_cli 均把 姓名/2 个学位/5 个项目 全抽对；本地 qwen2.5vl:7b 连名字都识别错、缺电话、区块串味；minicpm-v:8b 更差（臆造学历/丢光项目）；qwen2.5vl:32b(20GB+) 装不下 12GB 显存(RTX 5070)。
  - **两个 CLI 的视觉接法（各自坑）**：`claude_cli` 是 agent 壳不吃 base64 → 把图落临时 PNG、prompt 里让 claude 用 Read 工具读（~50s，直出干净 JSON）；`codex_cli` 原生 `-i <FILE>` 附图，但 `-i` 是**贪婪多值会吞掉位置参数 prompt** → prompt 必须走 **stdin**（否则报 no prompt）（~71s，23.6k token）。两者都存临时文件、用后清理、超时放宽 300s。
  - **ollama 视觉 num_ctx 坑**：一张简历页图就数千 image token，ollama 默认 `num_ctx=4096` 装不下多页 → DPI 220 直接 400 exceed_context、DPI 150 两页贴上限疑截断。视觉请求显式 `options.num_ctx=16384`。
- ~~视觉模型解析简历（v2.14.0.2 初版，qwen2.5vl:7b）~~ 见上（provider 选型收口到 CLI 主）。
  - **背景/痛点**：排版型简历（多栏/图形/表格）走 pdfminer 纯文本提取 + 正则会丢结构，解析质量差。改用视觉模型直接读页面版面。
  - **动手前核对推翻方案假设**：记忆里方案写 `qwen2.5vl + fitz 现成`，实测**两条都不成立**——ollama 无任何视觉模型、PyMuPDF 未装。先 `ollama pull qwen2.5vl:7b`（~6GB）+ `pip install PyMuPDF`。
  - **用户拍板两个决策**：①视觉模型来源＝**本地 VL 主 + 云端 Claude 兜底**（vision 链 `[ollama qwen2.5vl:7b, anthropic claude-opus-4-8]`）②视觉为主 + 文本兜底（回落 `parse_resume_to_blocks(pdfminer 文本)`）。
  - **架构（images 贯穿 FallbackChain）**：`complete()` 加 `images` 参数穿 `LLMProviderProtocol`/各 Provider/`FallbackChain`/`ModelRouter`；ollama 走 `payload["images"]`（timeout 有图放宽 240s）、anthropic 走 image content blocks、纯文本 provider（claude_cli/codex_cli/openai_compatible）收到图 raise → 链自动跳过（所以 vision 链只放视觉模型）；`ModelRouter.LEVELS` 加 `vision`。
  - **改动**：`protocols.py`/`llm_client.py`（images 贯穿 + vision level）/ `config.yaml`（vision 链）/ `resume_parser.py`（`render_pdf_to_images` fitz 渲染 base64 PNG）/ `resume_blocks.py`（`parse_resume_vision`）/ `prompts/resume_parse_vision.md`（新模板，纳入 `EDITABLE_PROMPTS` 前端可编辑）/ `server.py`（`upload_resume` 重写：PDF 视觉→blocks 失败回落文本；`build` 端点改读当前块库避免覆盖视觉结果；onboarding 简历就绪判断兼容块库）/ 前端 `Settings.tsx`（PROMPT_LABELS/DESC + 状态卡指向 resume_blocks.yaml）。测试 +4（images 透传/纯文本 provider 拒图/parse_resume_vision）。
  - **真机验证**：合成简历 PDF → 真实 qwen2.5vl:7b 正确抽出 basic_info + 实习/项目（带 bullets）+ 技能/奖项 + 中文 summary，JSON 解析归一化全通。小瑕疵：education 被塞进 basic_info.degree（prompt 可调，数据不丢）；真机应以用户真实中文简历为准。
  - **顺带清理**：Settings.tsx 删了上个会话遗留的坏死引用 `<InjectionBox promptName>`（组件从未定义、编译不过；注入已由 InjectionSection 承担）。**其余上个会话未提交 WIP（attachment_resume 状态卡删除 + ModelPromptTab 布局改堆叠）一并带入本次提交**。

> **更早的条目（v2.12.x 及以前，2026-07-30 及更早）已归档至 `docs/progress-archive.md`。**
> 归档判据是「还有人会回看吗」——通常一两个大版本以前的就不会了。
> 膨胀的代价不是磁盘，是没人再读它；一个没人读的状态板等于没有状态板。

## 进行中 / 待处理

### 已知限制与可改进方向（2026-08-05 从 TECHNICAL.md 迁入）

> **2026-07-22 整改收口**：四路独立审视的 High/Med/Low + server.py 减重已全部处理（明细见 `docs/audit-remediation-log.md`）。审查中确认两处「双实现」是**有意设计**非缺陷、维持原样：`upsert_hr_conversation`（工具版=运行时身份/stage、tracker 版=onboarding 播种，列集与调用方不重叠）、`filter_conversations` 的 `too_old` 优先于 `unanalyzed`（分析两月前死线程无收益，真机 909 会话靠此窗口收敛到约 12）。剩余可选项：server.py 减重批 C（session helpers，31 行，收益小）。

**必须改（数据完整性 / 可观测性，2026-08-09 全项目扫视发现）**

- **`data/jobs.db` 零备份、零恢复路径**：唯一权威库（applications + hr_conversations + hr_messages，几周真实投递与 HR 会话历史），`tracker.py` 初始化无任何快照逻辑，崩溃/坏盘/迁移写错即不可逆丢失。**本项目已经验证过这类风险会真的发生**——`info_pool.yaml` 在 v2.17.1 被判定"唯一主库却零备份"高风险后加了快照+回滚（见 `[[resume-vision-parse-plan]]` 一线记忆），但同样的教训没推广到更关键的 `jobs.db`；且 `jobs.db` 历史上已因 schema 漂移做过三次紧急重建（`migrate_030.py`/`migrate_app_rebuild.py`/`migrate_hrconv_rebuild.py`）。方向：仿 `info_pool` 的分层快照（写前存档 + 保留策略），或更轻量的定时 `VACUUM INTO` 落一份只读副本。
- **零主动通知通道**：全库 grep `webhook/email/notify` 零命中（唯一命中都是 `threading.Condition.notify()`）。调度器/自检全靠"写文件 + 用户自己打开 Dashboard 看"，没有推送。核心卖点是"不用盯着也能跑"，但 session 过期 / Boss 改版选择器失效 / 撞配额上限，任一失败都可能安静地跑好几天而无人察觉。方向：至少给"连续 N 次 run 失败"或"self-check 连续不通过"加一条本地可感知的信号（系统通知 / 邮件 / 简单的 webhook 出口，视用户实际会看哪个渠道而定——按需再定，不要过度设计）。

**待真实环境验证**

- `extract_conversation_list` 的 `boss_conv_id` 取自会话卡片 `.friend-content` 的 `d-c` 属性，但已知 Boss直聘 的 `d-c` 普遍是用户自身 ID 而非会话唯一 ID；其在 `navigate_to_conversation` 中的实际用途与有效性待确认。
- W2 会话卡片解析（`extract_conversation_list`）全部使用 CSS class 选择器（`.friend-content-warp`、`.name-text` 等），Boss直聘 改版易碎，已配 fallback 链缓解，待真实环境验证命中率。

**可选改进**

- `apply()` 选择器使用 CSS class（`.job-card-wrap`），Boss直聘 前端更新后可能失效；建议改为 data-* 属性或更稳定的选择器。
- `_classify_message()` 中英文关键词匹配逻辑不一致（Chat Agent W1）。
- Chat Agent：_execute_pending 中 Guard 的 state 传入方式脆弱（内部匿名类伪造），Ollama 失败后 `_ollama_available` 永久禁用本次 session。
- ~~`job_id` 关联目前靠 company 名模糊匹配~~（2026-07-06 已解决）：两表现按 `job_id`（encryptJobId）硬关联，同公司多岗位不再误配。仅历史无 job_id 的软键会话仍走 hr_name+company 兜底，随重扫「即时吸收」逐步收敛。
- **简历功能③（发送）未实现**：招呼语规划走「W1 投递成功 → 生成 → 进审批队列 → W3 发送」，简历附件的发送目前无流程——需先调研 Boss直聘 附件简历上传机制（`upload_resume_file` tool 已撤线）再接线。`/api/stats` 的 `attachment_resume.ready=false` 即此状态。
- **资源历史/方案文件无清理**：`data/selfcheck_history.jsonl` / `resume_plans.yaml` 持续追加/累积，暂无 GC，长期运行需加上限或归档。


### 前端逐 navigator 重设计（进行中，2026-06-13 起）

- [x] 信息架构 7→6 + 设计系统「Apple-refined Telemetry」+ navigator #1 控制台落地
- [x] 监控面板空间恒定改造：固定骨架（活跃投影）+ 固定高度滚动近期卡片，不再每卡堆叠（WorkflowTrack）
- [x] 首屏加载慢修复：移除渲染阻塞的 Google Fonts CDN 外链，IBM Plex Mono 改 @fontsource 自托管打包进 /static
- [x] 状态分布卡 + 「已获回复」词表错位 bug：前端 STATUS_META 对齐真实 AppStatus（FOUND/SCORED/APPLIED/CHATTING/INTERVIEWING/OFFER/REJECTED）+ server get_stats responded→chatting；Jobs.tsx 筛选 tab 同步对齐
- [x] 余下 navigator 全部初步一轮：职位 / 会话 / 日志 / 自动化（新建+迁移）/ 设置（三合一）
- [x] 控制台底部过渡块迁出：SessionChecker→设置「环境&Session」tab、ScheduleCard/ScheduleLogCard→「自动化」navigator
- [x] 配置 + 搜索配置合并（求职偏好单一表单写 profile.yaml，server /api/profile 统一收发含 extra_notes）；Session/LLM/审批 去重到单一入口
- [x] 自动化页调度卡对齐信号色（#0071e3→#0a84ff 等）+ 全局 checkbox/focus accent 改 #0a84ff
- [x] 死代码清理：删 /api/config/profile 端点(+_ALLOWED_PROFILE_FIELDS) + 前端 getConfigProfile/updateConfigProfile/ProfileConfig + 4 个过时 test_config_manager 测试
- [x] 端到端整体性验证（前端重设计后）：W1 真实投递 30（applied 22/db_write_failures 0/0 失败步骤）+ W2 全量 100（done/intent_analyzed 46/resume 5/llm_degraded 0/全程无断开），确认前端+后端改动未破坏 pipeline、日志正常
- [~] **逐页精修（当前阶段，逐个 navigator 抠视觉/交互）**：
  - [x] 控制台：LiveLog 默认折叠（砍 LIVE 列高度）+ Topbar 命名对齐侧栏（v1.0.9.34）
  - [x] 控制台其余（v1.0.9.35）：① 待审批条瘦身（双行+外发光→单行 计数·公司·按钮，去 3px 辉光左条/boxShadow，py-4→py-2.5）② 左右栏平衡（CONTROL minmax 400-460→360-420 + `xl:sticky xl:top-0`，LIVE 长列滚动时左栏钉住消除留白；grid 加 items-start）③ LIVE 密度（WorkflowCard p-5→p-4/mb-4→mb-3、骨架行 py-1.5→py-1、近期卡片 py-2→py-1.5 + maxHeight 200→180）④ 遥测/状态分布收紧（StatusBar p-5→p-4、StatCard 数字 40→38px + mt 收紧）。build tsc 无报错，DrissionPage 截图复核
  - [x] 职位（v1.0.9.36）：斑马纹 even:bg-white/[0.012] 提升可扫性 + 评分按高低着色（≥80 signal-green/≥60 text-1/<60 text-3）+ 整行 cursor-pointer 可点开详情 + 详情按钮转 ghost(bg-transparent) 减噪 + 公司列 font-medium。未做搜索/排序/聚合（超出精修范围、排序需后端支持）
  - [x] 会话（v1.0.9.36）：选中会话加左侧 2px 蓝色强调条（原仅淡背景选中态不明确）+ 列表项 py-3→py-2.5
  - [x] 日志（v1.0.9.36）：选中 run 加左侧 2px 蓝色强调条（与会话页一致）。结构本就完善（RUNS+DETAIL Flow/Decisions 双 Tab），空态正常
  - [x] 自动化（v1.0.9.36）：W1投递/W2检查 区块标题改成全站统一的 W1蓝/W2紫彩色徽章（原纯文本），接入信号色语言。组件签名 label→wf+title
  - [x] 设置（v1.0.9.36）：ChipSelect inactive chip 加 hover:brightness-150 反馈（原只有激活态变色无 hover）。该页本就最完善，无需结构改动
  - 节奏：从控制台开始逐个过，用户验收驱动 — 6 页第二轮精修完成

### 待跟进（杂项）

- [ ] 问题2：W2 实时进度——实跑时确认 SSE 事件是否进控制台 LIVE 骨架投影/近期卡片（本次有头跑未专门核验）
- [ ] 验证脚本 `design/drive.py`（前端驱动）+ `esc.py`/`shot_*.py`：DrissionPage 多实例必须用**独立调试端口**（drive.py 已用 9777），与服务端 Boss 浏览器默认 9222 冲突会致 Handshake 404/页面断开

### 后端运行时问题

- [x] **W2「conversation not found」高失败率 已修（= B）**：根因=navigate_to_conversation 用裸 `scrollTop+=600`×20，对 Boss 虚拟滚动+懒加载列表够不到第一批窗口（~46）之后的会话→深处会话全失败（w2_20260614_0654：54/100 失败，位置悬崖在 46）。对照 scan 用 `scrollTop=scrollHeight` 触发懒加载收齐 317 个。修复：navigate 改懒加载式下滚（scroll 卡住时跳 scrollHeight 触发加载）+ 利用 W2 顺序处理先从当前位置下滚（快）、找不到再回顶全扫兜底；结束检测用「scrollTop 未推进 AND 高度不增长」而非高度稳定（避免列表已全量加载时误判到底——第一版修复曾因此悬崖提前到 7）。实证：修复后 navigate **65/65 全成功，越过原悬崖 46 无失败**（pattern 全 0）。pytest 全绿、4 个 navigate 单测通过
- [~] W2「页面连接断开」（疑似已澄清）：上次 w2_20260613_1525 跑到一半 DrissionPage 连接断 + ~50 级联失败；本次同样 100 会话**未复现**，佐证用户判断——大概率是上次运行时反复 npm rebuild 冲断连接，非 W2 固有缺陷

### 下一步行动（优先级排序）

- [x] W1 真实环境端对端验证：真实账号跑 W1（max_cards=2/阈值0/有头），确认能停（cards_viewed=2）+ 能入库（db_write_failures=0，DB 541→543）（2026-06-10）
- [x] W2 真实环境端对端验证：真实账号有头跑 W2（5→30 会话），简历发送判据收拢到「附件简历」系统消息、hr_messages 落库 156 条、LLM 层切 ollama（2026-06-11）
- [ ] W2 后续：ollama analysis 慢（~9.5min/30 会话）可评估 anthropic_api（需 key，不走 CLI rate-limit）；accept 境外跨境框选择器（旧 boss-dialog）未实测靠 marker 兜底；前端接线 llm_degraded/sent 可视化
- [ ] 清理本次 5 个临时诊断脚本（inspect_apply/verify_detect/verify_apply_e2e/diag_db/peek.py），或留作诊断工具
- [ ] 调度器重建：用 APScheduler 直接调 run_w1/run_w2，恢复定时触发（scheduler.py 已删，需新建）
- [ ] onboarding 拆分：ConfigManager 迁移（_step2_configure_llm/run_setup_profile）+ 浏览器登录独立模块，逐步减少 browser_agent.py 依赖

### 保留的技术债

- [x] services/browser_agent.py **已删除**（2026-06-16，浏览器收敛 Phase 3）；交互浏览器统一走 BrowserSession，onboarding 的浏览器方法已桩化退役，整体待重写为 workflow
- --chat 模式禁用，ChatAgent 未迁移到新 pipeline
- test_server.py AppStatus.DISCOVERED 预存 bug（跳过运行）
- onboarding.py 仍写旧 profile 字段（score_threshold/scale/job_type 单数）且文件内中文已被 GBK 工具链损坏，待单独修复
- 前端需适配 /api/config/system 返回结构（apply/schedule/browser → w1/w2）；Config 页接入 w1/w2 运行参数 + "设为默认"按钮
- daily_limit 仅用于 stats 显示，pipeline 未实现真正限流
- agent_workflows.py（停用 Chat Agent 遗留）仍读旧 config 结构，随 chat 迁移再清理
- [x] 日志系统：**已验证正常工作**（2026-06-10）。完整 run 的 log（w1_20260610_0715.jsonl 5278B）含 run_start/tool×10/step×4/job_scored/job_applied/run_end 全套事件；之前"仅 1KB/只有 run_start"是被强杀的半截 run 产物，非埋点 bug
- [x] upsert_application 传 url：CardPipeline 构造 `https://www.zhipin.com/job_detail/{job_id}.html` 传入（2026-06-10）
- [x] ApplicationTracker 绝对路径：默认改为基于 __file__ 的绝对路径，根除 cwd 漂移连错库隐患（从项目根调用实测连对库，2026-06-10）
- [x] hr_conversations 旧 schema 迁移：调查确认 hr_conversations 停留 T030 前 schema（reply_draft/suggested_reply/last_synced 等旧字段），新增 migrate_hrconv_rebuild.py 重建表（259 行迁移，reply_draft→reply_text、last_synced→created_at）；hr_messages 已是新 schema 无需动（2026-06-10）

### 工程质量改进（进行中，按优先级排序）

- [x] pytest.ini + pytest-cov：配置测试路径、marker（unit/integration/slow）、coverage 报告
- [x] datetime.utcnow() 全局迁移：改为 datetime.now(timezone.utc)，消除废弃警告
- [x] update_status() 改为直接 SQL UPDATE：消除 read-modify-write 竞争风险
- [x] Boss直聘选择器集中管理：browser_agent.py 提取 _SELECTORS 字典 + _eles_any/_ele_any 辅助方法
- [x] Carryover 孤儿记录启动警告：超过 cap(5) 时打印 warning（含 DISCOVERED/SCANNED/SCORED 分项数量），并向 emitter 发 ProgressEvent；3 个单元测试通过
- [ ] _budget_ok() 逻辑提取 + 测试：从闭包提取为可独立测试的函数
- [ ] apply_limit + daily_limit 边界交互测试：两者同时接近上限时的优先顺序
- [ ] Boss搜索 URL 快照测试：关键参数组合 → 预期完整 URL 对比
- [x] 结构化 JSON 日志：event_log.py RunLogger，per-run JSONL 事件，/api/runs 端点，Logs 页面
- [ ] LLM fallback 命中层统计：FallbackChain 记录 attempt 序号到日志
- [ ] --health-check 环境自检：检查 Chromium/DrissionPage/Ollama/profile/session 就绪状态
- [ ] Dashboard 投递趋势：/api/stats 增加按天聚合历史数据

### 已知遗留问题（不阻断，待机会修复）

- _send_chat_message 输入框选择器（`.input-area div[contenteditable='true']`）未在真实环境验证，可能需根据实际 DOM 调整
- aggressive_resume 模式端到端未验证（需要有未回复的会话）
- 未读 badge selector 未验证（当前所有会话均已读）
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
- 待手动验证：Boss直聘账号登录 + session 保存
- 待安装：weasyprint 及系统级依赖（libpango 等），才能使用 PDF 简历生成
- 待安装：playwright install chromium
- apply() 选择器改为 data-* 属性（稳定性提升）

## 变更记录

> 早期条目里提到的 `AGENTS.md` / `COLLAB.md` / `E2E_TESTING.md` / `spec.md` 等是退役的 factory 流程产物，已于 2026-08-05 删除（当时确实存在，记录如实保留）。

- 2026-03-19：task_010 完成，修复 M1/M3/M5，核查确认 M2/M4 已实现，所有 Must Fix 清零
- 2026-03-20：task_013 完成，增强聊天回复分类（RESUME_REQUESTED/AD_PUSH）、附件简历自动发送流程、Dashboard 附件保存、onboarding 就绪检查
- 2026-03-22：修复 json-repair 导入错误，评分阈值改为用户可配置（profile.yaml + setup-profile 第 9 步），默认阈值 72→60，dry-run 全流程 0 错误
- 2026-03-22：Workflow 2 验证 7 次真实投递；Workflow 3 聊天检查实现（scroll+天数/条数过滤）；apply 按钮选择器修复；聊天选择器修复；反爬优化；boss_online/check_responses 参数配置化
- 2026-03-25：task_014 完成，CLI Chat Agent（--chat 模式），LLM 意图分发 + 规则降级
- 2026-03-25：task_015 完成，HR 会话完整读取与 SQLite 缓存；HR DB 重构（conv_id hash、company/hr_name 分离、广告过滤）
- 2026-03-26：HR 发简历逻辑完整重写：stage 字段、三类请求检测、三策略发送、积极/普通模式、无 me 消息先打招呼
- 2026-03-28：task_020 完成，简历发送状态机修复：resume_requested 中间状态、境外公司二次确认弹窗、脏检查双重保障
- 2026-03-28/29：task_021/022 完成，停止按钮全链路修复：后端停止检查点（orchestrator/check_responses/browser_agent）+ 前端双卡独立按钮 + server.py 无 workflow 时正确返回 ok:false
- 2026-03-29：task_023 完成，app.js 全部乱码中文字符串修复为 \uXXXX escape
- 2026-03-29：建立 Claude Code + Codex 协作基础设施（AGENTS.md、COLLAB.md、work-logger 联动）
- 2026-04-09：前端零碎修复（score 快速路径、rate limiter 提速、.hidden CSS 修复、workflow 状态轮询、统一参数面板）；确定前端重构技术栈（React+Vite+Tailwind+shadcn/ui）；立项 task_024~029
- 2026-04-10：task_025~029 完成，React 前端迁移全部落地（5 页面 + WorkflowPanel + WorkflowTrack，构建 177KB JS / 14.52KB CSS）
- 2026-04-10：Apple 设计系统落地（task_030）：#000000 背景、Apple Blue #0071e3 唯一强调色、SF Pro 字体栈、glassmorphism topbar、卡片无边框 + card shadow、pill 主 CTA、全局负字间距
- 2026-04-10：搜索配置页重设计：chip 选择器（城市/薪资/经验/学历/职位类型/公司规模/融资阶段）+ 预览 URL 按钮；WorkflowTrack 线路图始终显示；侧边栏标签更名
- 2026-04-11：orchestrator per-job 流水线重构（carryover+search-then-process）+ 粒度 ProgressEvent；WorkflowTrack 横向地铁卡片重设计（5 步 W2 + 活跃详情面板）；停止按钮全覆盖（WorkflowPanel 常驻 + W2/W3 卡片各自停止）；Dashboard 布局拆为独立全宽行
- 2026-04-12：62 个 FastAPI TestClient 集成测试（test_server.py）全部通过；E2E_TESTING.md 手动测试指南 11 阶段；requirements.txt 补 httpx
- 2026-04-12：工程质量 1-4 项完成：pytest.ini + pytest-cov、datetime.utcnow() 迁移、update_status() 直接 SQL UPDATE、browser_agent.py _SELECTORS 集中管理 + _eles_any/_ele_any 辅助方法；274 测试全通过
- 2026-04-13：W2 原子化重构——browser_agent.py 新增 search_with_panel()（全程停在搜索页，单卡点击+panel JD+回调投递）；orchestrator.py Pass 2 改为 search_with_panel 调用；WorkflowTrack.tsx 新增 LiveLog + 时间戳 getActiveStep 修复"一直显示搜索"；288 测试全通过
- 2026-04-14：search_with_panel() JD 检测逻辑改进：等待时间加长、选择器扩展、JS fallback 三阶段（选择器/viewport 右侧最大块/CSS 类名 dump）、修复 best.len bug；288 测试全通过
- 2026-04-16：修复 search_with_panel 投递弹窗假阳性 bug：pre-apply 清除残留对话框 + post-apply 改为点击"留在此页"并等待 DOM 关闭；apply_success_dialog timeout 3s→5s；LiveLog 补充 apply_btn 未找到事件
- 2026-05-19：自动调度功能完整实装（backend + frontend）：APScheduler 嵌入 server.py，CronTrigger+IntervalTrigger 双触发模式，schedule.yaml 配置持久化，schedule_log.jsonl 运行记录，GET/PUT /api/schedule + GET /api/schedule/log 三个 API，Dashboard ScheduleCard 组件（W1/W2 并列，启用开关+时间点+间隔+下次触发预览+近期记录+立刻启动）
- 2026-05-20：HR 主动发起会话 stub 记录（task_20260519-2355）；LLM HR 意图分析 intent 字段（task_20260520-0114）；analysis LLM 链路独立配置（task_20260520-0234）
- 2026-05-22：投递稳定性（scrollIntoView fix + _kill_stale_chrome）；自定义搜索 URL W1 新功能（orchestrator/server/WorkflowPanel + localStorage 历史）；结构化事件日志（event_log.py + /api/runs + Logs.tsx）；调度器竞态修复和重启续算（_get_last_run_time + restore_interval_times）
- 2026-05-23：W2 自动发送 HR 回复端对端落地：修复 DrissionPage 键盘 API（page.actions.key_down/key_up）；update_hr_analysis CASE 保护扩展到 sent/dismissed；验证 msgs 1→2，reply_status='sent'
- 2026-05-28：Pipeline 架构重构设计阶段完成：5 个设计文档（db_schema/tools_catalog/w1_pipeline/w2_pipeline/logging）全量确认；tasks/refactor_plan.md 总纲含 12 个 Task（030~041）执行顺序依赖图；开始进入实现阶段（T030 起）
- 2026-05-29：T030~T041 全部完成，Pipeline 架构重构实现阶段结束：T040 结构化 JSONL 日志全量埋点（step/tool/business event 三轨）；T041 Dashboard Logs 页完全重写（Flow/Decisions 双 Tab，API 层适配新格式）
- 2026-05-29：T042 Pipeline 接线 + 旧代码清理：run_w1/run_w2 新建，browser_context.py 提取，server.py/main.py 接入新架构，14 个旧文件删除，215 tests passed
- 2026-05-30：T043 LLM ModelRouter（capability routing + codex/claude CLI 修复）；T044 Config Manager（配置统一管理 + profile API）；T045 前端配置页；VerifySessionStep 抽象；WorkflowTrack/Panel 对齐新 pipeline；scheduler.py 删除；239 tests passed，v1.0.9.9
- 2026-06-01：W2 逐 tool 人工审查（审至 Tool 3）发现并修复 5 处：registry items 大字段过滤；navigate_to_chat_list force 参数；scan_step 重试 + 空=可见失败 + 待审批回复漏抓告警；reply 发送失败 DEGRADED→FAILED；run_logger _ui_status 状态词表归一化（修复节点不变绿/失败不变红的真 bug）。沉淀两条原则：文件日志 vs SSE 词表分离、控制流与状态标签解耦。239 tests passed
- 2026-06-09：配置系统三层重构 + 退役 factory 流程。CLAUDE.md 改为直接开发规则；config.yaml 三层化（Layer1 系统 llm/dashboard + Layer3 w1/w2 运行参数）；新增 settings_resolver.py（三级 fallback + user_settings.yaml 懒创建 + save_user_default）；main/server 三触发路径统一 resolve_params；清理死字段（aggressive_resume/generate_resume/job_search/schedule/browser）；修断链（max_conversations 生效 / stale_conv_days / daily_limit 归 w1）；修两 bug（profile_loader 删 name 必填 + 补全筛选字段）；新增 docs/configuration.md；355 tests passed
- 2026-06-10：W1 真实投递修复（投了不落库 + max_cards 失控）。根因①DB applications 表停留 T030 前旧 schema（url NOT NULL）从未迁移，新 pipeline upsert 不传 url 撞约束 → 5-29 后投递全不入库；根因②max_cards break 只跳内层 for，外层 while 续翻页无限投。修复：scripts/migrate_app_rebuild.py 重建表对齐 tracker schema（541 条迁移）、pipeline.py max_cards should_stop=True、handle_apply_dialog 关闭按钮改 a.boss-btn-cancel、card_pipeline 加 score_threshold<=0 跳 LLM 快速路径。证伪 detection过时/cwd漂移/upsert有bug 三猜测。pytest 359 passed；真实 W1（max_cards=2/阈值0）cards_viewed=2/applied=2/db_write_failures=0，DB 541→543。遗留：日志系统未验证、upsert 传 url、ApplicationTracker 绝对路径
- 2026-06-11：W2 端到端验证 + 简历发送判据收拢。三块：①hr_messages 恒零落库（write_hr_messages INSERT 漏 created_at 被 INSERT OR IGNORE 静默吞）→ 委托 tracker.insert_hr_messages，实跑 156 条；②简历发送"成功"判据不可信（境外卡跨境二次确认框却谎报成功）→ 收拢到唯一真相 item-system「附件简历」系统消息（两路径通用、实测 15/15），helpers.count_resume_delivered_markers + wait_resume_delivered(poll)，两发送工具 tool 内 marker 增量判 sent，detect_resume already_sent 同源（限定 sender==system 含「附件简历」，避免 HR 索要误判）；③LLM 层 claude_cli/codex_cli Windows 均不可用（rate-limit exit1 / subprocess 找不到 .cmd shim → is_available=False）→ balanced 链切 ollama，加 llm_degraded 每会话告警 + summary 计数。境外跨境框 div.panel-resume.sentence-popover → .btn-sure-v2。pytest 全绿；实跑 30 会话 resumes_sent=2/already_sent 跳过上次 15/hr_messages 156/llm_degraded=0。commit add93fe + 92d322e
- 2026-06-11：文档审计对齐 pipeline 架构现状（TECHNICAL 删退役死章节 orchestrator/critique/check_responses、tools 改四层分包总览、config.yaml 示例改三层 w1/w2、修 stage 流转与设计决策旧函数名、tests 章节对齐实际文件；README 删 Critic/简历 PDF/CLI Chat Agent 退役条 + 发简历改两路径「附件简历」marker 判据；design/ 6 稿核查确认是新架构设计稿无需改）+ W2 前端接线（WorkflowTrack：修 W2_STEPS 顺序 bug reply/resume、W2 卡片加 run summary chips + llm_degraded 橙色告警，取 /api/runs?pipeline=w2 的 summary，后端零改动，CJK 全 \uXXXX）。npm run build 通过、version 1.0.9.12。UI 渲染待浏览器验证
- 2026-06-13：前端逐 navigator 重设计启动。定信息架构 7→6（控制台/职位/会话/日志/自动化/设置）+ 消重决策（配置与搜索配置同写 profile.yaml 应合并、Session/LLM/审批收敛单一入口）；落地设计系统「Apple-refined Telemetry」（Apple 令牌融合 IBM Plex Mono 遥测层 + Apple 暗色信号色 + 网格噪点氛围层）；控制台页指挥中心布局重排（待审批行动条+遥测条+状态分布+CONTROL|LIVE grid，复用 WorkflowPanel/WorkflowTrack 重套令牌保功能，删 ReplyApprovalCard 去重）；docs/frontend.md 加对比度契约守则。pytest 全绿、build tsc 无报错 version 1.0.9.23、真实页面截图复核。Session/Schedule 暂留控制台底标 TODO 待迁
- 2026-06-14：前端重设计第一轮完成（6 navigator + 全量消重）。职位/会话/日志套令牌+词表对齐；新建自动化 navigator（迁 Schedule）；设置三合一（配置/搜索配置/环境配置→单 navigator 3 Tab，求职偏好单一表单，删 Config/Profile/Setup.tsx）；后端 /api/profile 统一收发 extra_notes；修状态分布词表错位 + 首屏慢（字体自托管）+ 监控空间恒定。两次 git 检查点（149bb39 + 本次）。pytest 绿、build version 1.0.9.32、每页截图复核
- 2026-06-14：修 W2「conversation not found」高失败率（B）。根因 navigate_to_conversation 裸 scrollTop+=600×20 够不到虚拟滚动列表深处（悬崖在 46）；改懒加载式下滚（卡住跳 scrollHeight 触发加载）+ 顺序处理从当前位置下滚 + scrollTop 到底检测。真实 W2 复跑实证 navigate 65/65 全成功越过悬崖 46。pytest 全绿
- 2026-06-14：LLM 链加 codex_cli 兜底（ollama 断线时）。修三处让 codex 真能用：Windows .CMD 解析（shutil.which 全路径，裸 ["codex"] 报 FileNotFoundError 老坑）、命令改 `codex exec`（0.131 非交互子命令，旧 -q 废）、`-s read-only` 防不可信 HR 文本注入 + utf-8。config fast/balanced 各加 codex_cli（ollama 优先、断则落 codex）。实测 is_available=True/complete→PONG，pytest 绿。代价：慢 ~20s/次 + 费 token（high reasoning，16k/次）——仅应急兜底
- 2026-06-14：codex 加 `-c model_reasoning_effort="low"`。但实测发现 token 大头砍不动——`codex exec` 有 ~15k token 固有底座（agent 系统 prompt + 工具 schema），与 reasoning effort/cwd 基本无关（项目 cwd 15.9k / 中性 cwd 15.0k / +low 15.0k；minimal 直接失败）。low 只省真实长 prompt 的"思考"那部分。结论：codex 就是 ~15k/次起步的应急兜底；常态用 anthropic_api/openai_compatible（真 chat completion，无此开销）更省
- 2026-06-18（续）：**W3「发送已批准回复」workflow 实现**（后端 735fcfb + 前端 v1.0.9.40）。边界：W2 起草+发简历不动，W3 只发已批准回复(approved/revision)并**验证投递**。每个 tool/step 有明确完成检查：SearchLocateConversation（搜索框 input.boss-search-input 定位，完成=会话编辑器 #chat-input 真出现）/ send_chat_message 改点 button.btn-send 提交（修多行 Enter 假成功根因）/ VerifyReplyDelivered（轮询 .message-item.item-myself 含回复前缀=真投递）/ SendReplyPipeline 仅 Verify 通过才 mark_reply_sent，否则保留 approved 不清正文。runner + /api/workflow/reply 端点 + 前端「发送已批准回复」按钮 + WorkflowTrack W3 卡（teal）。单测 test_w3_send_pipeline（4 例 pin 完成检查契约）+ test_progress_emitter。pytest 全绿、build v1.0.9.40。**边界收口**：W2 ConversationPipeline 移除 ReplyStep（不再发回复，旧路径是 res.ok 即标 sent 的假成功源）+ 删 import；W2 scan 移除"漏抓已批准回复"误导红色报错（W3 用搜索定位接管）。approved 管线在 W2 filter 仍保留（让 approved 会话被重读，reply_text 受 update_hr_analysis 保护不被冲掉）。pytest 全绿。**未做：真实发送端到端验证**（需先批准一条有正文的草稿，再跑 W3 真发——破坏性，待用户授权 + 选会话）。回放缓冲已改 per-workflow（3d291dc），刷新后 W1/W2/W3 各自最近一轮独立持久化。
- 2026-06-18：① **W3 设计文档** `design/w3_pipeline.md`（ab5d11e）——发送已批准回复独立 workflow：W2 起草+发简历不动，W3 只做 LoadApprovedStep→SendReplyPipeline(Locate→Send→Verify)；新增 2 tool（SearchLocateConversation 搜索框定位 / VerifyReplyDelivered 投递验证，根治假成功）；状态机零迁移；**未实现，待评审后填**。背景：W2 ReplyStep 把"执行了输入动作"当成功不验证真投递 → 假成功（多行回复 Enter 被当换行未提交、标 sent 还清空正文）；某companies 08d2aec5e71c 实例已撤回 pending。② **修前端刷新丢失 LIVE 进度**（ba72f1d）：ProgressEmitter 原纯 fan-out（subscribe 空队列只收连接后事件）→ 刷新 EventSource 重连丢全部进度。加回放缓冲（环形 max400，emit 入 buffer、subscribe 灌最近~200、start_workflow 清空），刷新/重连即重建 WorkflowTrack/LiveLog；前端零改动；补 test_progress_emitter（4 例）。**限制：survives 页面刷新、不 survives 服务重启**（内存缓冲；server-restart 持久化需前端 seed /api/runs，待评估）。
- 2026-06-16（续8）：浏览器收敛 Phase 3——**删除遗留单体 `services/browser_agent.py`（~2400 行）**。Phase 2 后 server.py 已不依赖它，仅剩 onboarding(CLI) 3 个方法（`_step3_login_boss` 登录 / `_step5_scan_history` 历史扫描 / `_session_is_valid` 校验）局部 import 它。三者均 CLI-only 且已被 Dashboard（BrowserSession）取代 → 桩化：去 browser_agent import、改成清晰退役报错（指向 Dashboard 设置页），`_session_is_valid` 返回 False。check_all()/文件检查（Dashboard /api/onboarding 在用）完整保留。全库零 `import browser_agent`（仅 helpers.py 一句注释提及），git rm 删除。pytest 全绿、`import services.onboarding/dashboard.server` 冒烟通过、check_all 正常。**浏览器收敛收官**：所有浏览器操作现在要么走工具化路径（W1/W2 pipeline tools），要么走 `BrowserSession`（交互端点）——一份启动、一份 session 检查、无遗留单体。onboarding 整体待重写为 workflow（W-onboarding）。注：MEMORY.md / modules/browser-agent.md 关于 browser_agent.py 的描述已过时待更新。
- 2026-06-16（续7）：浏览器收敛 Phase 2——登录/检查 session 端点迁出遗留 BrowserAgent。① `_check_session_via_browser` / check-session → `BrowserSession.verify()`（共享浏览器，不再每次开临时实例）② open-login / confirm-login / save-login → `BrowserSession.get_page()` + verify；确认登录后写 `data/session.json` 哨兵（onboarding `check_all` 第 58 行据此文件存在判定 session ready，必须保留）③ 修潜在 bug：confirm-login 原调 `_check_session_via_browser(page=agent._page)` 而该函数不接受 page 参数（会 TypeError）④ dev/page-inspect → BrowserSession ⑤ 移除 `app.state.login_agent`——**server.py 已彻底不依赖 BrowserAgent**（仅注释提及）。实证：check-session 返回 `{valid:true, name:浮瓜}`；pytest 全绿；服务重启正常。登录三端点逻辑已迁（构件 get_page/verify/哨兵均已验证），真实 logout 测试有破坏性故未做。`browser_agent.py` 仅剩 onboarding(CLI) 依赖——Phase 3（迁 onboarding → 删 browser_agent.py）待排期。无前端改动（端点契约保持）。
- 2026-06-16（续6）：修同步锁（Problem B）。根因：tracker 用**单个 sqlite3 连接**被 W2 工作线程与 API 事件循环线程**并发共用**（check_same_thread=False 但仍是同一连接），`with self.conn:` 事务交错 → "database is locked"/嵌套事务 → 运行期 UI 写库（approve/cancel/dismiss/save 等）失败。修：tracker `conn` 改为 **property 返回线程局部连接**（threading.local），每线程一条独立连接 + WAL + `busy_timeout=30000`；SQLite 靠文件锁串行化写入，运行期写库改为**等锁**而非立刻失败。所有 `self.conn`/`tracker.conn` 调用方零改动（property 透明）。补 test_concurrent_writes_no_lock（两线程各 30 写并发、零异常、60 条落库）。pytest 全绿、服务重启 + approve/cancel 写实测正常。前端"运行时禁用审批"作为 UX 保留（approve 即便点了本轮也不会被捞，故仍合理），但 DB 层现已普遍安全（所有并发写不再崩）。
- 2026-06-16（续5）：浏览器收敛 Phase 1 + 修跳转按钮误报 session 过期（ea4f31f，v1.0.9.39）。根因：交互端点（open-in-browser/browse-url）走遗留 `BrowserAgent`，自带浏览器启动 + 幼稚 `_assert_logged_in`，与流水线 `browser_context.open_browser` + 加固版 `VerifySessionStep` 分叉两份；加固只在流水线路径 → 交互路径瞬时故障被误报"session 过期"（堆栈实锤：navigate_to_conversation→_assert_logged_in→SessionExpiredError→500）。修：新增 `services/browser_session.py`（BrowserSession 单例，唯一交互浏览器主人，get_page 复用 open_browser、verify 委托 VerifySessionStep）；open-in-browser 改走 BrowserSession.verify + NavigateToChatList + W2 的 navigate_to_conversation tool，返回 {ok,code,error} 前端显示准确原因；browse-url 改走 BrowserSession。实证：之前报 500 的会话 73b8fae63255 现在 open-in-browser 返回 ok:true。pytest 绿。登录/检查端点暂留 BrowserAgent（Phase 2）。配套教程 `docs/browser-session-convergence.md`（用"验证 session"讲透两份分叉→一份共用 + 分层规则：tool/step/service/薄端点，铁律"端点不准内联副作用"）。**下一步：同步锁（Problem B，W2 运行时 UI 写库撞 SQLite 锁）。**
- 2026-06-16（续4）：会话页三项（用户验收驱动）。① **待审批筛选**（v1.0.9.38）：Chat 新增「待审批」tab（reply_status=pending），与「待发送」并列。② **会话跳转按钮**：会话头部加「↗ 在 Boss 打开」（openInBrowser→BrowserAgent.navigate_to_conversation，自动浏览器导航到该会话 Boss 页，靠 hr_name/company 定位、不需存 URL；沉底/运行中失败提示）+ 有 job_url 时「↗ 岗位」（browseUrl）。job_url 覆盖 33%(211/630)，故会话为主岗位为辅；跳转 tool 本就存在只是接到按钮。③ **修"待发送死数据"**（48aea41）：根因 get_approved_replies（**tool** tools/db/w2/get_approved_replies.py 自带 SQL，非 tracker 方法——W2 scan_step 调 tool）只取 reply_status='approved'，但前端把 revision 也标「待发送」→ 改过的回复永发不出、卡死。修：tool+tracker 方法 WHERE 改 IN('approved','revision')，补测试；运行时 dismiss 2 条两周前旧 revision（内容过时不补发）。pytest 全绿、build v1.0.9.38、截图实证待审批 tab+跳转按钮。
- 2026-06-16（续3）：会话页前端修复 + Problem B 规避（v1.0.9.37，纯前端）。① **待发送筛选**：Chat 新增「待发送」tab（SEND_FILTER 哨兵），客户端按 reply_status∈(approved,revision) 过滤——原来只能按 stage 筛、找不到待发送会话。② **系统消息渲染**：MessageBubble 新增 `sender==='system'` 分支，渲染成居中灰色提示条并剥离 `[卡片]/[hi]` 类标记——原来系统消息（"附件简历请求已发送"、`[卡片] xxx.pdf`）被当 HR 左泡显示。ConversationMessage.sender 类型补 'system'。③ **Problem B 规避**：workflowRunning 时审批操作区 pointer-events-none+opacity-50 + 提示"运行中暂不可用"，避免 UI 写库与 W2 撞锁（非根治后端并发，但消除踩雷）。build tsc 通过、DrissionPage 截图实证两项。**未修（数据质量，后端另算）**：read_messages 抓到重复消息 + 半截消息。**Problem A 定为新 workflow（W3）**：LLM 生成回复+批准+发送 抽成独立流程（原子操作多、与 W2 耦合浅），含"漏抓会话改用搜索/直接导航定位发送"——设计级改动，待排期。
- 2026-06-16（续2）：端到端验证"已批准 LLM 回复真实发出" **通过**。流程：UI 批准某companies/某names（fa59467fcef1，正文"感谢您的认可，我已发送简历。请问方便告知面试安排吗？"保留=修复生效）→ 跑 W2 → `replies_sent=1`、reply_sent 事件带真实正文、会话转 stage=sent + reply_text 清空。同轮验证"清空 last_msg_preview 强制重生"机制：某companies(a14c66089d97) filter 判 `preview_changed` 被重处理（preview 0→32），但 intent=general → **不起草**（W2 只对 resume_request/interview_invite 等可行动意图起草，general 不回）——故"无新草稿"是正确行为，非失败；也解释了它当初被批准即空（general 从无草稿）。结论：批准链路 + 发送 + 重处理机制全部正常。
- 2026-06-16（续）：修剩余 bug + 处理草稿重生。① **update_hr_analysis 状态保护扩围**：CASE 从 `('approved','sent')` 扩到 `('approved','revision','sent','dismissed')`（reply_text 与 reply_status 两处），再分析不再冲掉用户编辑/批准/已发/已驳回；仅 pending 不受保护可重生。pytest 全绿、后端重启生效。② **更正误报**：上条记的"前端 cancelReply/markSent/openLogin 反斜杠 URL bug"**不存在**——字节级核实 api/index.ts 全文 0 反斜杠、URL 全是正斜杠，是 Grep 输出把 `/` 渲染成 `\` 误导（Read 才是权威）。这几个按钮本就正常。③ **草稿重生用既有"清空 last_msg_preview 强制重扫"机制**：filter_conversations 只在 approved/unread/new/preview_changed 时 process，纯 pending 会被 no_change 跳过。给 2 条孤儿会话（某companies a14c66089d97 / 某companies c390fadbeaf0）清空 stored last_msg_preview → 下轮 W2 判 preview_changed → 重新分析 → pending 重生草稿（某companies若在 scan 内会重生；某companies沉底仍需"漏抓会话直接导航"方案解决）。④ W2 运行期间从 UI 点批准撞 SQLite 写锁致请求失败（前端乐观 UI 回退看着像没生效）——已确认现象，未改（建议：别在 W2 跑时点批准，或后续给写操作加重试）。
- 2026-06-16：修真凶 bug——**「批准回复」会清空回复正文**。根因：`approve_reply` 端点调 `tracker.update_reply_approval(conv_id,"approved")` 不传 reply_text，而该方法 `reply_text` 默认 `""` → `reply_text or None` → 把 reply_text 写成 NULL。所以每次点"批准"都把待发正文抹掉 → W2 发空回复（这才是 replies_sent=0 的根本原因，不只是会话沉底）。证据：库里所有 approved 正文皆空、revision（revise 会传 draft）皆有正文。修复：`update_reply_approval` 的 `reply_text` 默认改 `None` 哨兵，仅显式传入时才更新正文；approve/cancel/dismiss（不传）保留草稿，revise（传 draft）更新。pytest 全绿；后端直连实证 approve 后 text_len 52→52 保留（修复前→0）。已撤回 2 条被抹空的 approved（某companies a14c66089d97 / 某companies c390fadbeaf0）回 pending（正文已丢需 W2 重生）。**连带发现待修**：① 前端 api/index.ts 中 cancelReply/markSent/openLogin 的 URL 误写成反斜杠 `\api\...`（按钮失效）；② update_hr_analysis 状态保护只含 ('approved','sent')，漏 revision/dismissed；③ W2 运行期间从 UI 点批准会撞 SQLite 写锁致请求失败（前端乐观 UI 回退，看着像没生效）。另：conv_id 经全库审计 628 行 100% 复现 sha256(hr_name|company)、0 漂移 0 重复——schemas.py/migrate_030 注释写的三字段公式是过时文档（实际两字段，表无 hr_title 列）。
- 2026-06-16：6 页第二轮精修后全量系统测试（用户授权真实动作，前端触发→dashboard server 跑，有头，运行期不跑截图脚本避免 9222 冲突）。**W1 通过**：真实投递 apply_limit=10 → cards_viewed=10/applied=4(真投)/skipped=6/db_write_failures=0，日志 10 步全 successful + job_scored=4/job_applied=4/job_skipped=6 闭环完整。**W2 全量基本通过但暴露一个真实局限**：扫 320 会话/intent_analyzed=64/stage_changes=60/resumes_sent=10(真发)/llm_degraded=0/206 步成功；**但 replies_sent=0**。深查发现两个叠加问题，且测试前提本身有误：① 全库 approved 总数=1（唯一 c390fadbeaf0 某companies·张女士），DB 直查该条 **reply_text=NULL**——是"已批准但无正文"的异常孤儿态，即便发送也无内容可发；② 它又漏出 scan（scan_list 报 `approved_reply_conversation_missing_from_scan`，库内 628 会话/实时扫描 320，未在其中）。**未确认是真沉底还是 conv_id 漂移**（日志不落 scan 会话明细，无法区分；需 Boss 实地看该会话还在不在列表）。代码正确报警（非静默丢弃，设计如此）。结论：本次**没有合法的"有正文的已批准回复"用例**可验证发送功能，"2 条待发送"提示来自另一套计数（含 revision/旧值）。**待决策/待查**：(a) Boss 实地确认 c390fadbeaf0 是否仍在聊天列表 → 区分沉底 vs conv_id 漂移；(b) approved+NULL 正文如何产生（疑似历史 mark_reply_sent/再分析遗留）；(c) 是否需要给漏抓的已批准会话加直接导航兜底。导航/按钮：6 个侧栏 navigator 逐一 shot_nav 点击均正常渲染（导航通过）。
- 2026-06-15：控制台逐页精修第二轮（v1.0.9.35）。待审批条瘦身（单行化、去辉光、降高）；CONTROL 左栏 sticky 钉住 + 收窄配比解决与 LIVE 长列的高度失衡；LIVE 监控密度收紧（卡片/骨架行/近期卡片内距）；遥测卡+状态分布间距收紧。纯前端 4 处 .tsx（Dashboard.tsx/WorkflowTrack.tsx），build tsc 无报错，DrissionPage 截图复核
- 2026-06-15：修 VerifySessionStep 误导性报错。W1 无头跑时 session 校验抛了个无消息异常 → str(exc) 空 → 报 "Boss session invalid:"（空 reason），看着像登录态过期，实则浏览器故障（有头复检 valid=浮瓜，session 没掉）。修：① 空消息异常显示为 "类型名 (no message)"，reason 永不为空；② 区分 session_expired（redirect 真过期）vs verify_error（浏览器/页面故障）；③ 瞬时/模糊失败重试一次（真过期不重试）；w1/w2_runner 按 error code 给不同文案。补 tests/test_verify_session.py（4 例）。pytest 全绿
- 2026-06-22：工作流监控收尾 + 补全「workflow 参数默认值」前端缺口。① WorkflowTrack 收尾：卡片标题行去重（badge+标题与 tab 栏重复 → 删，只留运行中指示+中止按钮，连带清 title/badge props/badgeCls/active）、循环区 360→480px、撤掉淡蓝背景试验。② WorkflowPanel「⚡ 全流程」→「⚡ W1+W2」（名实相符：只串 W1→W2，不含 W3）。③ **补全默认值存储前端暴露**——根因：后端 `settings_resolver`（resolve_params + save_user_default + user_settings.yaml 懒创建）早已做好，触发端点也用 resolve_params 读默认，但写入侧 save_user_default 只被 daily_limit 用过、WorkflowPanel 参数全是硬编码本地 state（刷新重置、无回填、无「设为默认」）。修复：新增 `GET/POST /api/workflow/defaults`（复用 resolve_params/save_user_default，POST 按 config 节键名过滤垃圾键）；api 层加 getWorkflowDefaults/saveWorkflowDefault；WorkflowPanel 启动回填已存默认 + W1/W2 组各加「设为默认」按钮（写 user_settings.yaml）。pytest 74 passed（server/settings 子集）、GET/POST 冒烟通过、build 通过、无裸 CJK（WorkflowPanel 经 python 字节级转）。
- 2026-06-21：工作流监控前端改造（纯前端，后端零改，WorkflowTrack.tsx）。① per-instance 循环钻取——新增 InstanceDetail（可空实例，空=骨架全 pending）渲染单实例 step→tool 链路+真实消息；RecentCards 改可点选；单卡重构为 master-detail 左右分栏（左=本次 run 实例列表可滑动，右=选中实例循环明细），默认跟随最新、手动点选则固定。删聚合 SkeletonProjection。② 单框 tab 切换——W1/W2/W3 互斥，合并为单个全尺寸框 + 顶部标签栏（badge+运行中绿点），workflowRunning 变化自动切到运行中的 workflow，key={tab} 切换重置选择。每 workflow 纵向空间约 3 倍。③ 非循环步骤提到循环外——按 pipeline 真实结构拆 RUN_STEPS（scan/navigate/finalize）vs LOOP_STEPS，run 级单独渲染在「本次运行·非循环」区，循环明细只显示循环步骤；InstanceDetail 接受显式 stepKeys 复用；删 STEP_ORDER；循环区高度 240→360px。④ 全站组件名标签——新增 DevLabel（inline/float 两式），给 6 页 + 工作流监控 + Sidebar/Topbar 主要区块挂 React 组件名，便于非前端用户指认（Settings 的 Card 加 dev prop 复用）。⑤ 标签全局开关——useDevLabels（localStorage 持久化 + useSyncExternalStore）+ Topbar「标签 ON/OFF」按钮一键切换全站；约定写入 docs/frontend.md「五、调试辅助」。build 通过、无裸 CJK（Topbar CJK 用 python 字节级转 \uXXXX）
- 2026-07-01：W2 微信交换卡片自动同意（新 accept_wechat_card tool + WechatStep，点同意后重扫落库捕获 HR 发来的微信号卡片）+ 前端微信卡片独立绿卡渲染与动态微信号强提醒横幅（wechatIdFrom 抽真实号）+ 修 hr_title 从不入库老 bug（加列+迁移+持久化）会话标题加 HR 职位。pytest 391 全绿、build 2.0.1.13、端到端真机验证通过（点同意→HR 发微信号卡片→重扫落库）
- 2026-07-02：修 closed 会话遇新活动不复活的局限——upsert_hr_conversation CASE 加 `WHEN stage='closed' AND excluded.stage!='closed' THEN excluded.stage`。根因：陈旧关闭（14天无活动）后 HR 回头，filter 虽会重新处理但 stage 机单调只进、closed 绝对终态，从没实现复活半（「深圳守正不出奇」刚换微信仍显示已关闭即此）；hr_title 补不上也同源（closed→terminal-skip→不再处理）。复活后下次扫描会补 hr_title。公司名截断用户拍板不抓（库里无完整名）。单测 test_closed_revives_on_new_activity/test_closed_stays_closed_without_reopen_signal，pytest 393 绿
- 2026-07-02：加微信提醒增强（Dashboard 强提醒卡 + 会话列表「待加微信」筛选 tab + 点掉提醒）。后端 hr_conversations 加 wechat_dismissed 列+迁移、dismiss_wechat、_wechat_id_from（收紧为 [卡片] 前缀 + id 正则，排除含「微信号」的拒绝文本误报——实测 7→5 去掉 2 个某companies误报）、序列化加 wechat_id/wechat_pending/wechat_dismissed、新端点 GET /wechat-pending + POST /dismiss-wechat；前端 Dashboard WechatReminderCard（含卡内筛选）+ Chat「待加微信」tab + 横幅「已添加」按钮。测试 +6，build 2.0.1.15，重启 dashboard 后端点实测 5 位待加微信全为真实号
- 2026-07-04：「状态机」navigator 升级为「架构」navigator（4 Tab：架构/流程/状态机/数据模型，部分接实况）。前端 StateMachine.tsx 重构 + 新端点 GET /api/architecture + tracker.get_lifecycle_counts() + api getArchitecture/ArchitectureLive + Sidebar/Topbar 更名（Network 图标）。pytest 子集绿、build、四 Tab 截图验证实况计数生效。版本 2.0.1.25
- 2026-07-04：FOUND 落库之谜查清并修复（commit ec52390）。架构页接实况暴露 applications 表 46 条历史 FOUND 僵尸（重构前老流程经列 DEFAULT 'FOUND' 插表 + 旧 SCORED→FOUND 迁移），现行 W1 唯一落库点写死 status=APPLIED 永不产生 FOUND。修：tracker init 迁移改 DELETE WHERE status IN ('SCORED','FOUND')，令不变量在 DB 边界自愈。test_tracker 40 + 子集 146 passed
- 2026-07-04：架构页字号统一 +3px（47 处）+ 架构表首列 170→210px 防 dashboard/server.py 溢出（commit a9f1282，v2.0.1.27）
- 2026-07-04：「流程」Tab 升级为可点击 SVG 拓扑图（commit 18b62c7，v2.0.1.29）。水平泳道 W1/W2 + 真 SVG 箭头 + 投递失败红色虚线支路（截图诊断）+ 发简历「按需」虚线；点节点→详情面板展开 step·tool/源码/说明。修真 bug：Node 误解构 React 保留字 key（不作为 prop 传入）→ onClick 抛 TypeError 致选择失效，改 nodeKey+step 显式传递。截图验证主链+分支节点点击均生效
- 2026-07-06：W1↔W2 数据库 job_id 硬关联升级（v2.1.0.1）。软键（hr_name+company）→ job_id 硬键（==encryptJobId==URL片段）。采集改读 getGeekFriendList API（加载前 CDP 注入 XHR hook、DOM 兜底、滚动分页 438 条全带 job_id）；derive_conv_id（job_id 优先/sha256 退化）；upsert 加 job_id+last_msg_ts、conv_id re-key 迁移；sync JOIN 改 job_id 优先；新 tool backfill_application_from_conversation（W2→W1 补 APPLIED）+ W1 apply 建占位（W1→W2）；filter 用 lastTS 脏检查。修 historyless 重复行（upsert 遇到即吸收遗留软键行）。两条 upsert 不物理合并。test_hard_association 16 例、全量 426 passed。真机验证：老数据迁移 831→754（清 77 重复）；W1 3/3 投递 + 占位；W2 200 处理/7 简历/backfill 补录 96/重复 0。commit 82c80a0
- 2026-07-06：架构页「流程」Tab 升级——补 W3 泳道（取已批准→定位→发送→验证→标记，验证带失败保留支路）、W2 拆出脏检查节点（filter_conversations/lastTS 增量）、对齐 job_id 硬关联真实代码、订正数据模型 conv_id PK；纯前端单文件（StateMachine.tsx），npm run build 绿，版本 2.1.1.1
- 2026-07-06：自动化页拆为「定时调度」「自检」两个 Tab（pages/Automation.tsx，样式复用架构页；SelfCheckSection 原样复用），版本 2.1.1.2
- 2026-07-06：workflow 队列——统一调度 W1/W2/W3（services/workflow_queue.py 内存 FIFO+worker；三 trigger/定时/自检全改 enqueue；控制台队列面板：拖拽改序+暂停+移除+时间戳；W1+W2 按钮改批量入队删 SSE 脆弱链；修 Logs.tsx 裸文本中点的转义 bug），436 passed，版本 2.2.1.3
- 2026-07-07：修 W2 upsert_hr_conversation UNIQUE 回滚死循环（else 分支消息迁移改 UPDATE OR IGNORE + DELETE，多条会话一直报错自愈）+ W3 定位失败 N=3 即放弃（locate_fail_count 列 + record_locate_attempt tool，会话被手动移除后不再无限重试）。441 passed
- 2026-07-09：W2 慢根治 + 中止修复 + LLM 兜底收敛纯 ollama + codex 研究到底。①navigate_to_conversation 直开会话 URL（`chat?id=encryptBossId&jobId=encryptJobId`，O(1) 真机 3.6s vs 旧 DOM 滚动搜索 ~103s，缺 id/boss=='62001' 回退搜索）+ 搜索步 sleep 减半 + W2 25min 时间预算兜底。②修中止按钮（W1/W2/W3 循环轮询 stop_requested）。③LLM 链移除 codex_cli/claude_cli，fast/balanced 纯 ollama qwen3:8b(think=false)——对照实验（三种 system×reasoning×ignore-config 全错）+ `--json` 铁证确认 `codex exec` 是编程 agent 壳（反问「你想让我干什么」、把待分类消息当背景），判意图非 prompt 可修；claude_cli 抢主对话配额。正道走 chat completions（openai_compatible/anthropic_api），结论固化进 config 注释。452 passed。commits 609f230→ebe6763
- 2026-07-10：W2 回复生成拆成独立 think=True 步骤（升 Y → v2.3.0.x）。需求「意图 think=false 保持快准，只生成回复时开 think」；现状 analyze_intent 一次调用同时判意图+出 suggested_reply、think 全局硬编码 false。拆分：①`think` 参数从 protocol→5 providers→FallbackChain→ModelRouter 透传（仅 ollama 用，其余忽略）；②新 tool `generate_reply` + `prompts/generate_reply.md`（纯文本回复、无 job-agent system、think=True 斟酌措辞）；③`analyze_intent` 去掉 suggested_reply 只判 intent+needs_reply（保持 think=False）；④AnalyzeStep needs_reply=true 时才调 generate_reply。455 passed；真机验证 think=True 生效（7.4s 有推理 vs think=False 0.4s），回复「感谢邀请，明天下午三点方便，期待面试！」得体
- 2026-07-10：回归测试模块启动（层 0+1，升 Y v2.4.0.1）。导航「自动化」→「自动化和测试」+ 新增「回归测试」Tab（自检并入为层 0，删独立自检 Tab）。设计=**分层体检**：层0 环境探针(复用 selfcheck)/层1 逻辑回归 pytest/层2 数据不变量(待)/层3 真机端到端冒烟(待)。本次做 0+1：新 `services/regression.py`（subprocess 跑 `pytest --junitxml` + 解析 JUnit XML，按测试文件分组，ElementTree 空元素坑用 is not None）+ `POST /api/regression/pytest`（同步 def→threadpool，~10s，不碰浏览器故不与 workflow 互斥）+ 前端 RegressionSection（层0 复用 SelfCheckSection + 层1 PytestCard：运行按钮+总览+失败文件展开）。端到端验证 TestClient：HTTP200/455 passed/44 文件/9.7s。tsc 绿。2/3 后续迭代
- 2026-07-10：回归测试**层 2+3 + 前端可视化**（升 Y v2.5.0.1）。**层2 数据不变量**：`regression.run_invariants(tracker)` 经 getter 只读查 5 项（status 无死态/status 合法/stage 合法/reply_status 合法/已批准已发回复必有正文），真机对现有库跑**立刻抓到 9 条「已批准但 reply_text 空」历史遗留**（层2 价值证明）。**层3 真机端到端冒烟**：`regression.run_smoke` 复用 run_w1/run_w2 dry-run 小规模（W1 max_cards=2 / W2 max_conversations=5，均 dry_run 不投递不发送，W3 跳过），断言无异常+cards_viewed≥1；异步 background+浏览器互斥+写 regression_smoke_log.jsonl，前端轮询(5s×72)。端点 `POST /api/regression/invariants`(同步) + `POST /api/regression/smoke`(异步) + `GET /api/regression/smoke/last`。前端 RegressionSection 扩为 4 层(LAYER0 ENV/1 LOGIC/2 DATA/3 E2E)，新 InvariantCard(同步)+SmokeCard(异步轮询+警告横幅)。层2 单测 test_regression_invariants(2 例)，457 passed，tsc 绿。**层3 真机需登录态/浏览器无法在此验证**（端点接线已验 smoke/last），真机效果待用户验收
- 2026-07-07：schema 漂移修复（hr_messages 4列 UNIQUE→3列+去重迁移，真机 3876→3496）；LLM 降级调优（ollama 模型 qwen3:8b→qwen2.5:7b 非推理更快、超时 180→90s 快速 fail、codex 加 --ephemeral），解决 W2 意图分析 180s 超时降级 unknown；实测 qwen2.5:7b 26s 出合法意图 JSON。443 passed
- 2026-07-07：W1 count_today 加 `AND score IS NOT NULL` 排除 backfill 灌水（147 假象→真实计数）
- 2026-07-07：LLM output_schema 穿透——ollama format 强制结构化（qwen2.5 更快更稳）+ codex --output-schema；analyze_intent 传意图 schema。444 passed
- 2026-07-09：修「中止」按钮无效——W1/W2/W3 循环从不读 stop_requested，中止只设标志位。RunLogger 加 should_stop()，三条流水线在会话/卡片/回复之间轮询、优雅 break（仍走 FinalizeStep 收尾）+ summary 记 stopped。排查 W2 跑 5 小时根因：navigate_to_conversation 18 次失败×~103s=31min（占 62%），API 扫 661 会话但 DOM 滚动搜不到的死搜到底。446 passed
- 2026-07-09：W2 慢因治标 A+C——A: navigate_to_conversation 搜索步 sleep 0.8~1.2s→0.35~0.55s（失败耗时~减半）；C: W2 加时间预算 max_run_minutes（默认 25，超时优雅结束跑 FinalizeStep+记 stopped），防再跑 5 小时。BD（砍 Phase2 / API securityId 直开）待定。448 passed
- 2026-07-09：W2 治本 D——navigate_to_conversation 首选 `chat?id=<encryptBossId>&jobId=<encryptJobId>` 直开会话（两 id 均稳定、getGeekFriendList 已存），O(1) 无 DOM 滚动搜索。判定「打开成功」用聊天输入框存在（探针实测：无选中会话时输入框不存在=可靠信号）。真机实测 3.6s 打开+读取正确（旧 DOM 搜索 2~103s，18 次失败各 ~103s 消失）。缺 id/boss=='62001' 回退 DOM 搜索。610/873 会话可直开。452 passed
- 2026-07-09：LLM 链移除 codex_cli（实测判意图不准：编程 agent，清晰案例全判 general/unknown），fast/balanced 兜底改 claude_cli（判意图准，偶发 exit1=抢主对话配额、无人值守 W2 跑更稳，失败仅退化不错判）。codex --output-schema 的 OpenAI 严格 schema 需求（additionalProperties:false+全required）已知但因移除 codex 无需，analyze_intent schema 回退宽松版（ollama 6/6 验证过）。「选 analyze_intent provider」功能本已存在于 Settings→LLM

- 2026-07-22：四路独立审视整改交付（v2.8.0→2.9.0，478→590 passed，详见「已完成」顶部条目 + `docs/audit-remediation-log.md`）。阶段0 冒烟可信化（covered 三态 + run_diagnostics 诊断器 + 走队列）；阶段1 P0 隐私（orphan 重建历史 + PII 扫描器 + gitignore 整目录收敛 + 位置护栏，三道防线）；阶段2 High（mark-sent/update_hr_analysis/新会话丢写/applied_at 四例「同一转换多份实现」收敛，SQL 只留 tracker，均 live 冒烟验证）；阶段3 Medium（停滞口径改 last_msg_ts、配置统一 config_manager、微信解析下沉 biz_logic；too_old 顺序与 upsert 双实现审查后维持）；阶段4 Low（score_job 补测 / interval 泄漏 / 铁律措辞）；单拎 server.py 减重 -600 行（2638→2038，三 service：scheduler_service/workflow_orchestration/run_log_reader）
- 2026-07-24：架构页「架构」标签新增 ④前端架构 Section（v2.9.1.1，纯前端，`npm run build` 过）。补齐此前只有后端视角的空白——SPA 分层表 + 前端内部数据流条（SSE→缓冲→限流→渲染）+ 三个技术讲解（不用 react-router / SSE 缓冲限流 / 一份 Context 管全局），复用 Collapsible。CJK 全 `\uXXXX`，脚本生成插入
