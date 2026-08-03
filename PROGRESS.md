# OpenJobFinder — Progress

## 状态快照

| 项目     | 值                              |
|----------|---------------------------------|
| 整体状态 | 进行中                          |
| 最后更新 | 2026-08-03（v2.17.1 信息池快照回滚（分层保留）+ 前端首次有测试：vitest 10 例守门拖拽放置契约与预览渲染） |
| 当前版本 | 2.17.1.1                        |

## 待跟进（另开会话）

- **[2026-08-03 用户指定·下一块] 简历系统接入 W1/W2（目前整块功能仍是孤岛，实际投递价值 = 0）**
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

- **信息池快照回滚 + 前端首次有自动化测试**（2026-08-03，v2.17.1，649 passed + 前端 10 passed，build 绿，端到端灾难恢复验证）
  - **补的是两个自评出来的最大风险**（非用户报障）：①信息池是唯一主库却**零备份**，而「融入信息池」让 LLM 整体重写 sections，一次误保存不可逆；②整块功能 90% 复杂度在 `Resume.tsx`（1028 行）却**零前端测试**——此前 4 个真机 bug 全是 pytest 绿 + build 绿的情况下靠用户实测才发现。
  - **① 快照**：`save_pool` 每次写盘前自动留档到 `data/pool_snapshots/{时间戳}.yaml`（同秒多次保存加序号）；**分层保留**——最近 10 个 + 最近 14 天里「每天最早的那个」（UI 绿标「每日」）。单纯「保留最近 N 次」的问题是：一天里连点十几次保存就会把几天前那个内容完好的版本挤掉，而那恰恰最需要回滚；测试专门守这条（一天内狂点 6 次，三天前的存档仍在且可回滚）。`list_snapshots`/`restore_snapshot`（回滚本身也先留档，防误回滚）+ 端点 + 「历史版本」UI（列出时间/分区数/条目数，一键回滚）。`build_pool` 回包带 `_stats`（整理前后条目数），**变少就在池上方橙色告警**提示核对或回滚，且未点保存不写盘。端到端验证：保存留档(11 条) → 模拟 LLM 清空(掉到 1 条) → 回滚 → 完整恢复 11 条、分区结构一致。
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
  - **真机端到端验证通过**：`run_e2e w1 --search-url <ai搜索页>` 投递 1 卡 → `fetch_jd hr_name="黄国强"` → DB `applications.hr_name="黄国强"`（华为云计算，valid UTF-8，3字纯名，与 W2 会话表格式一致）；对比同 run 修复前落的空 hr_name。关联死链 W1 侧真机打通。
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
  - 验证：新增 `tests/test_hr_name_capture.py`（5 例）全绿；全量 pytest 绿；build 通过。**真机端到端验证**：面板 `王美雪\n刚刚活跃`(8) → 提取 `王美雪`(3)，与 W2 会话表纯名格式（姚勤福/曹先生…）一致。
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
  - 验证：新增 test_accept_wechat_card / test_wechat_step，pytest 391 全绿；build 通过 2.0.1.13。端到端真机（用户 `!` 前缀自跑 design/verify_wechat_agree.py）：真卡 clicked:True → HR 发 `[卡片] 余英奇的微信号\nASDQWERPP` → 重扫落库 persisted_new:1（DB 确认）
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
  - **三流程实测状态**：W1 ✅ 可跑/落库/调度/实测；W2 ✅ 全绿；W3 ✅ 核心链路 locate→send→新verify→回写 端到端实测通过（五世科技/李女士，run 日志 `logs/runs/w3_20260620_1055.jsonl` 为证）
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
  - 端对端验证通过：卓越教育·陈女士 msgs 1→2，DB reply_status='sent'，suggested_reply 已清空，workflow 结束 summary replies_sent:1

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

## 进行中 / 待处理

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

- [ ] **W2 已批准回复发不出去 · 问题A（沉底会话漏抓）**：reply 发送依赖会话仍在 scan 到的滚动列表里；沉底会话扫不到 → `approved_reply_conversation_missing_from_scan` → replies_sent=0。修向：发送时用 Boss 聊天列表**搜索框按公司/HR 定位并直接导航**，不依赖滚动窗口。详见记忆 [[w2-reply-send-gaps]]
- [ ] **W2 已批准回复发不出去 · 问题B（运行期写锁）**：W2 跑时从 UI 点批准撞 SQLite 写锁→请求失败→乐观 UI 回退（看着像没生效）。修向：写端点加 busy_timeout/重试，或 running 时禁用批准按钮。临时规避：别在 W2 跑时点批准
- [ ] 问题2：W2 实时进度——实跑时确认 SSE 事件是否进控制台 LIVE 骨架投影/近期卡片（本次有头跑未专门核验）
- [ ] 日志陈旧 running：被强杀的 run（如 w2_1412/1426）永久显示 running，未 finalize。可在 server 启动时把孤儿 running 标 aborted/failed
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

### 长期规划

- [ ] **计算机视觉操作层**：Boss直聘 前端 DOM 变更频率极高（class 无语义、定期重混淆），CSS 选择器方案长期维护成本高。规划将频繁断裂的操作（简历发送按钮、打招呼按钮、简历请求卡片识别）改为截图 → Claude Vision 识别坐标 → `page.actions.move_to(x,y).click()`，与 DOM 结构完全解耦。DrissionPage 自带截图 API，结合现有 FallbackChain 无需引入新依赖。短期先做混合模式（稳定操作保留 DOM，高频断点改用 Vision），长期可全视觉化。

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
- 2026-06-18：① **W3 设计文档** `design/w3_pipeline.md`（ab5d11e）——发送已批准回复独立 workflow：W2 起草+发简历不动，W3 只做 LoadApprovedStep→SendReplyPipeline(Locate→Send→Verify)；新增 2 tool（SearchLocateConversation 搜索框定位 / VerifyReplyDelivered 投递验证，根治假成功）；状态机零迁移；**未实现，待评审后填**。背景：W2 ReplyStep 把"执行了输入动作"当成功不验证真投递 → 假成功（多行回复 Enter 被当换行未提交、标 sent 还清空正文）；五世科技 08d2aec5e71c 实例已撤回 pending。② **修前端刷新丢失 LIVE 进度**（ba72f1d）：ProgressEmitter 原纯 fan-out（subscribe 空队列只收连接后事件）→ 刷新 EventSource 重连丢全部进度。加回放缓冲（环形 max400，emit 入 buffer、subscribe 灌最近~200、start_workflow 清空），刷新/重连即重建 WorkflowTrack/LiveLog；前端零改动；补 test_progress_emitter（4 例）。**限制：survives 页面刷新、不 survives 服务重启**（内存缓冲；server-restart 持久化需前端 seed /api/runs，待评估）。
- 2026-06-16（续8）：浏览器收敛 Phase 3——**删除遗留单体 `services/browser_agent.py`（~2400 行）**。Phase 2 后 server.py 已不依赖它，仅剩 onboarding(CLI) 3 个方法（`_step3_login_boss` 登录 / `_step5_scan_history` 历史扫描 / `_session_is_valid` 校验）局部 import 它。三者均 CLI-only 且已被 Dashboard（BrowserSession）取代 → 桩化：去 browser_agent import、改成清晰退役报错（指向 Dashboard 设置页），`_session_is_valid` 返回 False。check_all()/文件检查（Dashboard /api/onboarding 在用）完整保留。全库零 `import browser_agent`（仅 helpers.py 一句注释提及），git rm 删除。pytest 全绿、`import services.onboarding/dashboard.server` 冒烟通过、check_all 正常。**浏览器收敛收官**：所有浏览器操作现在要么走工具化路径（W1/W2 pipeline tools），要么走 `BrowserSession`（交互端点）——一份启动、一份 session 检查、无遗留单体。onboarding 整体待重写为 workflow（W-onboarding）。注：MEMORY.md / modules/browser-agent.md 关于 browser_agent.py 的描述已过时待更新。
- 2026-06-16（续7）：浏览器收敛 Phase 2——登录/检查 session 端点迁出遗留 BrowserAgent。① `_check_session_via_browser` / check-session → `BrowserSession.verify()`（共享浏览器，不再每次开临时实例）② open-login / confirm-login / save-login → `BrowserSession.get_page()` + verify；确认登录后写 `data/session.json` 哨兵（onboarding `check_all` 第 58 行据此文件存在判定 session ready，必须保留）③ 修潜在 bug：confirm-login 原调 `_check_session_via_browser(page=agent._page)` 而该函数不接受 page 参数（会 TypeError）④ dev/page-inspect → BrowserSession ⑤ 移除 `app.state.login_agent`——**server.py 已彻底不依赖 BrowserAgent**（仅注释提及）。实证：check-session 返回 `{valid:true, name:浮瓜}`；pytest 全绿；服务重启正常。登录三端点逻辑已迁（构件 get_page/verify/哨兵均已验证），真实 logout 测试有破坏性故未做。`browser_agent.py` 仅剩 onboarding(CLI) 依赖——Phase 3（迁 onboarding → 删 browser_agent.py）待排期。无前端改动（端点契约保持）。
- 2026-06-16（续6）：修同步锁（Problem B）。根因：tracker 用**单个 sqlite3 连接**被 W2 工作线程与 API 事件循环线程**并发共用**（check_same_thread=False 但仍是同一连接），`with self.conn:` 事务交错 → "database is locked"/嵌套事务 → 运行期 UI 写库（approve/cancel/dismiss/save 等）失败。修：tracker `conn` 改为 **property 返回线程局部连接**（threading.local），每线程一条独立连接 + WAL + `busy_timeout=30000`；SQLite 靠文件锁串行化写入，运行期写库改为**等锁**而非立刻失败。所有 `self.conn`/`tracker.conn` 调用方零改动（property 透明）。补 test_concurrent_writes_no_lock（两线程各 30 写并发、零异常、60 条落库）。pytest 全绿、服务重启 + approve/cancel 写实测正常。前端"运行时禁用审批"作为 UX 保留（approve 即便点了本轮也不会被捞，故仍合理），但 DB 层现已普遍安全（所有并发写不再崩）。
- 2026-06-16（续5）：浏览器收敛 Phase 1 + 修跳转按钮误报 session 过期（ea4f31f，v1.0.9.39）。根因：交互端点（open-in-browser/browse-url）走遗留 `BrowserAgent`，自带浏览器启动 + 幼稚 `_assert_logged_in`，与流水线 `browser_context.open_browser` + 加固版 `VerifySessionStep` 分叉两份；加固只在流水线路径 → 交互路径瞬时故障被误报"session 过期"（堆栈实锤：navigate_to_conversation→_assert_logged_in→SessionExpiredError→500）。修：新增 `services/browser_session.py`（BrowserSession 单例，唯一交互浏览器主人，get_page 复用 open_browser、verify 委托 VerifySessionStep）；open-in-browser 改走 BrowserSession.verify + NavigateToChatList + W2 的 navigate_to_conversation tool，返回 {ok,code,error} 前端显示准确原因；browse-url 改走 BrowserSession。实证：之前报 500 的会话 73b8fae63255 现在 open-in-browser 返回 ok:true。pytest 绿。登录/检查端点暂留 BrowserAgent（Phase 2）。配套教程 `docs/browser-session-convergence.md`（用"验证 session"讲透两份分叉→一份共用 + 分层规则：tool/step/service/薄端点，铁律"端点不准内联副作用"）。**下一步：同步锁（Problem B，W2 运行时 UI 写库撞 SQLite 锁）。**
- 2026-06-16（续4）：会话页三项（用户验收驱动）。① **待审批筛选**（v1.0.9.38）：Chat 新增「待审批」tab（reply_status=pending），与「待发送」并列。② **会话跳转按钮**：会话头部加「↗ 在 Boss 打开」（openInBrowser→BrowserAgent.navigate_to_conversation，自动浏览器导航到该会话 Boss 页，靠 hr_name/company 定位、不需存 URL；沉底/运行中失败提示）+ 有 job_url 时「↗ 岗位」（browseUrl）。job_url 覆盖 33%(211/630)，故会话为主岗位为辅；跳转 tool 本就存在只是接到按钮。③ **修"待发送死数据"**（48aea41）：根因 get_approved_replies（**tool** tools/db/w2/get_approved_replies.py 自带 SQL，非 tracker 方法——W2 scan_step 调 tool）只取 reply_status='approved'，但前端把 revision 也标「待发送」→ 改过的回复永发不出、卡死。修：tool+tracker 方法 WHERE 改 IN('approved','revision')，补测试；运行时 dismiss 2 条两周前旧 revision（内容过时不补发）。pytest 全绿、build v1.0.9.38、截图实证待审批 tab+跳转按钮。
- 2026-06-16（续3）：会话页前端修复 + Problem B 规避（v1.0.9.37，纯前端）。① **待发送筛选**：Chat 新增「待发送」tab（SEND_FILTER 哨兵），客户端按 reply_status∈(approved,revision) 过滤——原来只能按 stage 筛、找不到待发送会话。② **系统消息渲染**：MessageBubble 新增 `sender==='system'` 分支，渲染成居中灰色提示条并剥离 `[卡片]/[hi]` 类标记——原来系统消息（"附件简历请求已发送"、`[卡片] xxx.pdf`）被当 HR 左泡显示。ConversationMessage.sender 类型补 'system'。③ **Problem B 规避**：workflowRunning 时审批操作区 pointer-events-none+opacity-50 + 提示"运行中暂不可用"，避免 UI 写库与 W2 撞锁（非根治后端并发，但消除踩雷）。build tsc 通过、DrissionPage 截图实证两项。**未修（数据质量，后端另算）**：read_messages 抓到重复消息 + 半截消息。**Problem A 定为新 workflow（W3）**：LLM 生成回复+批准+发送 抽成独立流程（原子操作多、与 W2 耦合浅），含"漏抓会话改用搜索/直接导航定位发送"——设计级改动，待排期。
- 2026-06-16（续2）：端到端验证"已批准 LLM 回复真实发出" **通过**。流程：UI 批准百世教育/庄先生（fa59467fcef1，正文"感谢您的认可，我已发送简历。请问方便告知面试安排吗？"保留=修复生效）→ 跑 W2 → `replies_sent=1`、reply_sent 事件带真实正文、会话转 stage=sent + reply_text 清空。同轮验证"清空 last_msg_preview 强制重生"机制：吉屋教育(a14c66089d97) filter 判 `preview_changed` 被重处理（preview 0→32），但 intent=general → **不起草**（W2 只对 resume_request/interview_invite 等可行动意图起草，general 不回）——故"无新草稿"是正确行为，非失败；也解释了它当初被批准即空（general 从无草稿）。结论：批准链路 + 发送 + 重处理机制全部正常。
- 2026-06-16（续）：修剩余 bug + 处理草稿重生。① **update_hr_analysis 状态保护扩围**：CASE 从 `('approved','sent')` 扩到 `('approved','revision','sent','dismissed')`（reply_text 与 reply_status 两处），再分析不再冲掉用户编辑/批准/已发/已驳回；仅 pending 不受保护可重生。pytest 全绿、后端重启生效。② **更正误报**：上条记的"前端 cancelReply/markSent/openLogin 反斜杠 URL bug"**不存在**——字节级核实 api/index.ts 全文 0 反斜杠、URL 全是正斜杠，是 Grep 输出把 `/` 渲染成 `\` 误导（Read 才是权威）。这几个按钮本就正常。③ **草稿重生用既有"清空 last_msg_preview 强制重扫"机制**：filter_conversations 只在 approved/unread/new/preview_changed 时 process，纯 pending 会被 no_change 跳过。给 2 条孤儿会话（吉屋教育 a14c66089d97 / 潮流电子 c390fadbeaf0）清空 stored last_msg_preview → 下轮 W2 判 preview_changed → 重新分析 → pending 重生草稿（吉屋教育若在 scan 内会重生；潮流电子沉底仍需"漏抓会话直接导航"方案解决）。④ W2 运行期间从 UI 点批准撞 SQLite 写锁致请求失败（前端乐观 UI 回退看着像没生效）——已确认现象，未改（建议：别在 W2 跑时点批准，或后续给写操作加重试）。
- 2026-06-16：修真凶 bug——**「批准回复」会清空回复正文**。根因：`approve_reply` 端点调 `tracker.update_reply_approval(conv_id,"approved")` 不传 reply_text，而该方法 `reply_text` 默认 `""` → `reply_text or None` → 把 reply_text 写成 NULL。所以每次点"批准"都把待发正文抹掉 → W2 发空回复（这才是 replies_sent=0 的根本原因，不只是会话沉底）。证据：库里所有 approved 正文皆空、revision（revise 会传 draft）皆有正文。修复：`update_reply_approval` 的 `reply_text` 默认改 `None` 哨兵，仅显式传入时才更新正文；approve/cancel/dismiss（不传）保留草稿，revise（传 draft）更新。pytest 全绿；后端直连实证 approve 后 text_len 52→52 保留（修复前→0）。已撤回 2 条被抹空的 approved（吉屋教育 a14c66089d97 / 潮流电子 c390fadbeaf0）回 pending（正文已丢需 W2 重生）。**连带发现待修**：① 前端 api/index.ts 中 cancelReply/markSent/openLogin 的 URL 误写成反斜杠 `\api\...`（按钮失效）；② update_hr_analysis 状态保护只含 ('approved','sent')，漏 revision/dismissed；③ W2 运行期间从 UI 点批准会撞 SQLite 写锁致请求失败（前端乐观 UI 回退，看着像没生效）。另：conv_id 经全库审计 628 行 100% 复现 sha256(hr_name|company)、0 漂移 0 重复——schemas.py/migrate_030 注释写的三字段公式是过时文档（实际两字段，表无 hr_title 列）。
- 2026-06-16：6 页第二轮精修后全量系统测试（用户授权真实动作，前端触发→dashboard server 跑，有头，运行期不跑截图脚本避免 9222 冲突）。**W1 通过**：真实投递 apply_limit=10 → cards_viewed=10/applied=4(真投)/skipped=6/db_write_failures=0，日志 10 步全 successful + job_scored=4/job_applied=4/job_skipped=6 闭环完整。**W2 全量基本通过但暴露一个真实局限**：扫 320 会话/intent_analyzed=64/stage_changes=60/resumes_sent=10(真发)/llm_degraded=0/206 步成功；**但 replies_sent=0**。深查发现两个叠加问题，且测试前提本身有误：① 全库 approved 总数=1（唯一 c390fadbeaf0 潮流电子·张女士），DB 直查该条 **reply_text=NULL**——是"已批准但无正文"的异常孤儿态，即便发送也无内容可发；② 它又漏出 scan（scan_list 报 `approved_reply_conversation_missing_from_scan`，库内 628 会话/实时扫描 320，未在其中）。**未确认是真沉底还是 conv_id 漂移**（日志不落 scan 会话明细，无法区分；需 Boss 实地看该会话还在不在列表）。代码正确报警（非静默丢弃，设计如此）。结论：本次**没有合法的"有正文的已批准回复"用例**可验证发送功能，"2 条待发送"提示来自另一套计数（含 revision/旧值）。**待决策/待查**：(a) Boss 实地确认 c390fadbeaf0 是否仍在聊天列表 → 区分沉底 vs conv_id 漂移；(b) approved+NULL 正文如何产生（疑似历史 mark_reply_sent/再分析遗留）；(c) 是否需要给漏抓的已批准会话加直接导航兜底。导航/按钮：6 个侧栏 navigator 逐一 shot_nav 点击均正常渲染（导航通过）。
- 2026-06-15：控制台逐页精修第二轮（v1.0.9.35）。待审批条瘦身（单行化、去辉光、降高）；CONTROL 左栏 sticky 钉住 + 收窄配比解决与 LIVE 长列的高度失衡；LIVE 监控密度收紧（卡片/骨架行/近期卡片内距）；遥测卡+状态分布间距收紧。纯前端 4 处 .tsx（Dashboard.tsx/WorkflowTrack.tsx），build tsc 无报错，DrissionPage 截图复核
- 2026-06-15：修 VerifySessionStep 误导性报错。W1 无头跑时 session 校验抛了个无消息异常 → str(exc) 空 → 报 "Boss session invalid:"（空 reason），看着像登录态过期，实则浏览器故障（有头复检 valid=浮瓜，session 没掉）。修：① 空消息异常显示为 "类型名 (no message)"，reason 永不为空；② 区分 session_expired（redirect 真过期）vs verify_error（浏览器/页面故障）；③ 瞬时/模糊失败重试一次（真过期不重试）；w1/w2_runner 按 error code 给不同文案。补 tests/test_verify_session.py（4 例）。pytest 全绿
- 2026-06-22：工作流监控收尾 + 补全「workflow 参数默认值」前端缺口。① WorkflowTrack 收尾：卡片标题行去重（badge+标题与 tab 栏重复 → 删，只留运行中指示+中止按钮，连带清 title/badge props/badgeCls/active）、循环区 360→480px、撤掉淡蓝背景试验。② WorkflowPanel「⚡ 全流程」→「⚡ W1+W2」（名实相符：只串 W1→W2，不含 W3）。③ **补全默认值存储前端暴露**——根因：后端 `settings_resolver`（resolve_params + save_user_default + user_settings.yaml 懒创建）早已做好，触发端点也用 resolve_params 读默认，但写入侧 save_user_default 只被 daily_limit 用过、WorkflowPanel 参数全是硬编码本地 state（刷新重置、无回填、无「设为默认」）。修复：新增 `GET/POST /api/workflow/defaults`（复用 resolve_params/save_user_default，POST 按 config 节键名过滤垃圾键）；api 层加 getWorkflowDefaults/saveWorkflowDefault；WorkflowPanel 启动回填已存默认 + W1/W2 组各加「设为默认」按钮（写 user_settings.yaml）。pytest 74 passed（server/settings 子集）、GET/POST 冒烟通过、build 通过、无裸 CJK（WorkflowPanel 经 python 字节级转）。
- 2026-06-21：工作流监控前端改造（纯前端，后端零改，WorkflowTrack.tsx）。① per-instance 循环钻取——新增 InstanceDetail（可空实例，空=骨架全 pending）渲染单实例 step→tool 链路+真实消息；RecentCards 改可点选；单卡重构为 master-detail 左右分栏（左=本次 run 实例列表可滑动，右=选中实例循环明细），默认跟随最新、手动点选则固定。删聚合 SkeletonProjection。② 单框 tab 切换——W1/W2/W3 互斥，合并为单个全尺寸框 + 顶部标签栏（badge+运行中绿点），workflowRunning 变化自动切到运行中的 workflow，key={tab} 切换重置选择。每 workflow 纵向空间约 3 倍。③ 非循环步骤提到循环外——按 pipeline 真实结构拆 RUN_STEPS（scan/navigate/finalize）vs LOOP_STEPS，run 级单独渲染在「本次运行·非循环」区，循环明细只显示循环步骤；InstanceDetail 接受显式 stepKeys 复用；删 STEP_ORDER；循环区高度 240→360px。④ 全站组件名标签——新增 DevLabel（inline/float 两式），给 6 页 + 工作流监控 + Sidebar/Topbar 主要区块挂 React 组件名，便于非前端用户指认（Settings 的 Card 加 dev prop 复用）。⑤ 标签全局开关——useDevLabels（localStorage 持久化 + useSyncExternalStore）+ Topbar「标签 ON/OFF」按钮一键切换全站；约定写入 docs/frontend.md「五、调试辅助」。build 通过、无裸 CJK（Topbar CJK 用 python 字节级转 \uXXXX）
- 2026-07-01：W2 微信交换卡片自动同意（新 accept_wechat_card tool + WechatStep，点同意后重扫落库捕获 HR 发来的微信号卡片）+ 前端微信卡片独立绿卡渲染与动态微信号强提醒横幅（wechatIdFrom 抽真实号）+ 修 hr_title 从不入库老 bug（加列+迁移+持久化）会话标题加 HR 职位。pytest 391 全绿、build 2.0.1.13、端到端真机验证通过（点同意→HR 发微信号卡片→重扫落库）
- 2026-07-02：修 closed 会话遇新活动不复活的局限——upsert_hr_conversation CASE 加 `WHEN stage='closed' AND excluded.stage!='closed' THEN excluded.stage`。根因：陈旧关闭（14天无活动）后 HR 回头，filter 虽会重新处理但 stage 机单调只进、closed 绝对终态，从没实现复活半（「深圳守正不出奇」刚换微信仍显示已关闭即此）；hr_title 补不上也同源（closed→terminal-skip→不再处理）。复活后下次扫描会补 hr_title。公司名截断用户拍板不抓（库里无完整名）。单测 test_closed_revives_on_new_activity/test_closed_stays_closed_without_reopen_signal，pytest 393 绿
- 2026-07-02：加微信提醒增强（Dashboard 强提醒卡 + 会话列表「待加微信」筛选 tab + 点掉提醒）。后端 hr_conversations 加 wechat_dismissed 列+迁移、dismiss_wechat、_wechat_id_from（收紧为 [卡片] 前缀 + id 正则，排除含「微信号」的拒绝文本误报——实测 7→5 去掉 2 个艺兔科技误报）、序列化加 wechat_id/wechat_pending/wechat_dismissed、新端点 GET /wechat-pending + POST /dismiss-wechat；前端 Dashboard WechatReminderCard（含卡内筛选）+ Chat「待加微信」tab + 横幅「已添加」按钮。测试 +6，build 2.0.1.15，重启 dashboard 后端点实测 5 位待加微信全为真实号
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
