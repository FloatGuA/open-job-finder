# 整改执行明细

> 计划见 `docs/audit-remediation-plan.md`；本文件记录**实际改了什么、为什么、验证结果**。
> 版本：2.8.0.x ｜ 起于 2026-07-21 四路独立审视

---

## 阶段 0 · 冒烟测试可信化（已完成）

| 项 | 改动 | 提交 |
|---|------|------|
| covered 三态 | `run_smoke` 加 `covered` 维度，独立于 `ok`；report 出 `fully_covered`/`uncovered`；前端红/黄/绿 | `5e12293` |
| 参数透传 | 冒烟可传 `score_threshold`/`no_response_days`/`stale_conv_days` | `5e12293` |
| run 诊断器 | 新建 `services/run_diagnostics.py`，从 JSONL 得确定性结论，可诊断任意历史 run | `5e12293` |
| L2 不变量 +5 | 水位线不越界 / 已分析必有结论 / 已发送不留草稿 / 有HR消息必已分析 / 消息无孤儿 | `5e12293` |
| 冒烟走队列 | `run_smoke(submit=...)` 依赖注入，消除 W1/W2 第二条执行路径 | `b93a929` |
| W2 覆盖判据 | `resumes_sent>=1` → `convs_processed>=1`（发简历无法主动触发，门结构性关不上） | `577c76c` |

**关键发现**：dry-run 被当技术失败（重复记 apply failed + 监控红字 + 每次白截截图）；553 个历史 run 里 10 个中断、8 个中断前已真实外发。

---

## 阶段 1 · P0 隐私（已完成）

- `logs/` 停止追踪（164 文件），`.gitignore` 收敛为 `/logs/` — `6ce596f`
- pre-commit PII 扫描器（硬模式 + 从 jobs.db 实时比对），误报 32→0 — `3e4389d`
- orphan 分支重建远程历史：126 commit → 1，泄露清除 — `02ffd29`

**泄露实测**：`logs/task_015/codex.log` 含 28 个去重头像 URL（≈28 位可识别个人）、面试 52 次、简历 39 次、21 个公司名、11 处薪资。

---

## 阶段 2 · High（已完成，live 冒烟验证全绿）

### 2.1 mark-sent 三份实现、两种语义 — `1538c7e`

| 位置 | 原 SQL |
|------|--------|
| `server.py` 端点 | `reply_status='sent', reply_text=''` + **内联裸 SQL** |
| `mark_reply_sent` 工具 | 同上 |
| `tracker.mark_reply_sent` | **`reply_status=NULL, reply_text=NULL`** |

`'sent'` 在 `update_hr_analysis` 的保护集内，`NULL` 不在 → 走 NULL 那条路的会话在下次再分析时看起来"从未处理"，**可能给同一位 HR 二次起草并发送**。

**改**：三处统一走 `tracker.mark_reply_sent`，SQL 只剩一处；返回 rowcount 让端点能正确回 404。

### 2.2 update_hr_analysis 双实现 — `1538c7e`

生产走工具版；tracker 版是只被测试调用的活死代码，且两版已漂移：

| | 工具版（正确） | tracker 版 |
|---|---|---|
| `last_analyzed_ts` | 有 | **无** — 误接回生产就静默回退 #53 |
| 传 `None` 时 | 保持原值 | **写 NULL 清空草稿** |

**改**：以工具版为准合并进 tracker；保护集提升为常量 `PROTECTED_REPLY_STATUSES`。
**分层**：`ALLOWED_REPLY_STATUSES` 白名单留在**工具层**（它约束"再分析路径不得自设终态"），tracker 存储层不设——审批流程与测试夹具需要直接设 approved。曾把它下沉到 tracker，立刻挂 7 个测试。

### 2.3 新会话首轮分析被静默丢弃 — `1538c7e`

W2 **先 analyze 后 upsert**（stage 依赖待计算的 intent）。对 W1 从未投过的会话（HR 主动先联系），analyze 时行还不存在 → 纯 UPDATE 匹配 0 行**且返回 ok** → intent/草稿/水位线全丢；随后 upsert 只写 stage 与 preview，留下"stage 已推进但 intent 为空"的行。**生产实测 4 条**。

**改**：`update_hr_analysis` 写入前 `INSERT OR IGNORE` 保证行存在，身份列留空由紧随的 upsert 填；`OR IGNORE` 保证既有行 stage/身份不被回退。

### 2.4 applied_at 语义相反（live 冒烟抓出）— `3821fb1`

冒烟报「真投 1 但今日投递数未增(Δ=0)」。排查是第四例双实现：

```sql
工具版(生产)  applied_at = CASE WHEN 原值 IS NULL THEN 新值 ELSE 原值 END  -- 保留首次
tracker 版    applied_at = excluded.applied_at                          -- 更新为最后
```

三个消费方全按「最后一次投递」解读（`count_today` / `purge_stale_applications` / `ORDER BY`）。后果不止统计：REJECTED 重投（有意流程）后时间戳停在旧值，**会被按早已被取代的投递时间提前清理**。

**改**：工具版改为 `excluded.applied_at` 优先，传 NULL 才保留原值。

**验证**：live 冒烟三轮 → `ok=True / fully_covered=True / uncovered=[] / diagnostics 无异常`，`count_today` 12→14。

---

## 阶段 3 · Medium（进行中）

### 3.1 too_old 与 unanalyzed 顺序 — **审查后维持原样** `fdd14f6`

审计建议让"从未成功分析过"的行豁免活跃窗口。改完后两个测试断言相反行为（`test_empty_intent_but_too_old_stays_skipped`），查证确认是 **#51 的有意取舍**：

- 分析最后消息在两个月前的线程没有收益（`FinalizeStep` 反正软关），却要为每具尸体付一次 LLM
- 真机 909 会话靠这道窗口收敛到约 12 个
- HR 若重新联系会带未读标记或更新时间戳，**两者都排在该判定之前**

**结论**：不改行为，把取舍与"不要在没回答『分析死线程是为了什么』之前动这个顺序"写进注释。

### 3.2 停滞判定时间口径 — `fdd14f6`

原用 `MAX(hr_messages.created_at)`——**入库时间，不是 HR 说话时间**。首次扫描几个月前的老会话时，每条消息都拿到今天的 created_at，线程看起来刚刚活跃。

```
生产实测：旧口径命中 0 条 ／ 新口径命中 35 条
```

同时修掉**两个时钟不一致**：`too_old` 按 `last_msg_ts` 判"不处理"、`mark_timeout` 按入库时间判"软关" → 会话被当陈旧跳过却从未被标记，两边都不可见。

**改**：改用 `last_msg_ts`；`last_msg_ts=0` 的行保留原入库时间逻辑。

### 3.3 配置读写统一 config_manager — `71eb3b3`

一半端点走单例、一半直接 yaml 读写同一批文件。单例有内存缓存，被绕过写盘后 `get_system_config()`/`get_profile()` 继续返回旧值——`/api/config/system` 正是读单例的，显示与刚保存的不一致。

`/api/profile` GET/POST、`/api/config/llm` POST、`/api/preview/search` 全部改走单例。

**llm 段需要专门方法**：`save_system_config` 是顶层 `dict.update`，而 llm 是嵌套结构（`capabilities[level]` 是 provider 字典的**列表**），平铺 update 会破坏它——config_manager 里「禁止写 llm」的守卫是对的，端点绕过它才是问题。新增 `save_llm_settings()` 只改首个 provider 的 type。

`schedule.yaml` / `resume_base.yaml` 不动：不属 config_manager 管辖。**收敛范围按「谁的文件」划，不是见 yaml 就收。**

**测试隔离**：ConfigManager 是全局单例，绑定首次路径后忽略后续（有意设计）。端点改走单例后测试间会读到第一个测试的 tmp_path → client fixture 重置 `_instance`，并按真实部署前提在沙箱建最小 config.yaml，**而不是放宽「缺配置即 fail-fast」的守卫**。

### 3.4 微信号解析下沉 biz_logic — `71eb3b3`

server.py 内联正则解析，注释自承 "mirrors Chat.tsx"，前端持第二份拷贝 → Boss 改文案要改两处。

后端下沉 `tools/biz_logic/wechat_id.py`；**前端那份直接删除**——它是冗余 fallback：`wechat_id` 由 API 从**同一批 messages** 算好返回，前端再算不可能得到不同结果。`isWechatCard` 保留（渲染判断，非身份提取）。补 8 个测试（内联时零测试）。

### 3.5 upsert_application 完整收敛 — **评估后不做**（`applied_at` 真 bug 已修）

`tracker.upsert` 没有任何生产调用方（只被测试调用），工具版才是 `card_pipeline` 走的路径。两者差异：tracker 版有 `_validate_transition` + created_at 保留，工具版有 `content_hash`。

看似该收敛，但 `VALID_TRANSITIONS` 在 tracker 里已标注 **ADVISORY ONLY**——它只驱动一条警告日志，真实转换（`sync_application_status` / purge）本来就走裸 SQL 绕过它。所以生产路径缺这个校验影响有限，而完整收敛要把 `content_hash` 并进 tracker 并重排 created_at 逻辑，收益不匹配风险。

**真正的缺陷（`applied_at` 语义相反）已在 2.4 修掉**，那才是会造成实际后果的部分。

### 3.6 upsert_hr_conversation 完整收敛 — **不该做，是我判断错了**

一度记为"第五例双实现"。查证后确认：**两个实现职责不同，有意分离**，且工具文件顶部注释早已写明。

| | 调用方 | 写什么 |
|---|---|---|
| 工具版 | `card_pipeline`(W1 stub) + `conversation_pipeline`(W2 扫描) | 身份/stage/`last_msg_ts`/`hr_title`/`job_id`；**故意不碰** intent 三件套 |
| tracker 版 | 仅 `services/onboarding.py`（播种） | 身份/stage + intent/reply_status/reply_text |

列集不同、调用方不重叠 → 不是分叉。tracker 版**本就不该写** `last_msg_ts`（那是扫描时数据，属工具版职责），所以测试里直写该列是合理做法。

**教训**：判断分叉前先看**调用方是否重叠、列集是否相同**，并先读文件顶部注释——这里的取舍早就写好了，我没读就下了结论。这与 3.1 是同一个错误的两次重犯。

---

## 阶段 4 · Low（已完成）

### 4.1 score_job 加权聚合单测 — 12 例

「models judge, code decides」的 **code 那一半**：LLM 给五个维度分，Python 做加权，产出决定每次投递的那个数字。此前零测试——错的权重、拼错的维度 key（静默落回 50）、坏掉的钳制都会无声上线。

覆盖：权重和为 1、满分/零分、单维度加权值（同时钉住权重数值与"是加权和而非平均"）、混合手算、缺维度落回 50、越界钳制、非 dict 维度项、浮点、解析失败、LLM 异常不被吞、`provider_used` 可追踪。**一次通过**——实现本就正确，缺的只是守门。

### 4.2 SelfCheck.tsx interval 泄漏 — 已修

`runNow` 里 `setInterval`/`setTimeout` 句柄是局部常量，无 cleanup。10 分钟窗口内离开页面 → interval 继续把 `onRan` 打到已卸载组件，最长空转 10 分钟。改为存 ref + `useEffect` 卸载清理，并在重复点击时先清旧 poll。

### 4.3 铁律措辞修正 — 已修

旧措辞「禁止在端点 / tool 层直接执行 SQL」与 `tools/db/*` 的实际形态冲突（13 个工具都复用 `tracker.conn`，是 sanctioned 的），读起来像被集体违反，会误导后续评审。

改述为**「一个状态转换只能有一份 SQL」**：tracker 独占连接/schema/迁移与每个写操作的唯一实现，`tools/db/*` 做薄壳调 tracker，端点一律无 SQL。CLAUDE.md 里附上五例漂移表与识别判据（**同一列在不同实现里的 CASE 分支不一致**）。

---

## 单拎 · server.py 减重（进行中，v2.9.0）

方案见发布的 artifact（三新模块 + 依赖注入 (c) service 类）。**消费方分析后不照搬方案的"批 A 一次搬 535 行"**——scheduler 是 orchestration 的消费者、schedule 配置被 7 处端点共用，真实边界更细，先抽耦合最浅的。

### A-1 SchedulerService — `596d430`（-99 行，2638→2539）

APScheduler 的所有权（build/rebuild、两个 scheduled 入口、`_scheduler` 全局+锁）下沉为 `services/scheduler_service.py` 的 SchedulerService 类。跨簇依赖（入队/限流/自检/调度日志/配置读/last_run_time）作为 callable 注入 → 不依赖 app.state，可 fake 测试。

- schedule 配置 load/save **留在 server.py**（7 处端点用它，共享基建），作为 `load_config` 注入
- `/api/schedule` 不再遍历 `_scheduler.get_jobs()`，改调 service 的 `next_run_times()`
- 新增 `test_scheduler_service.py`（7 例，内联时只能经 HTTP 触达）
- **真机验证**：启动装配 `_scheduler_running=True` / `/api/schedule` 正常 / live 冒烟 `ok=True fully_covered=True` 无异常 / count_today Δ+1

### A-2 OrchestrationService — `0717cdb`（-280 行，2539→2259，审计 High 本体）

server.py 长出的工作流执行下沉：队列 runner、三个 W1/W2/W3 runner、Boss 日限流态、自检周期、冒烟驱动 → `services/workflow_orchestration.py`。这是 live 冒烟真正走的路径，耦合最深、风险最高。

- **`get_state` 访问器而非 import app**：耦合 app.state 不可避免，但调用时读（此时 `_initialize_state` 已填充），service 不依赖 FastAPI、可 fake 测
- 接线：`_get_orch()` 懒构造 / `WorkflowQueue(runner=orch.run_item)` / scheduler 注入改指 orch / 冒烟端点改调 orch；`_is_rate_limited_today`/`_run_selfcheck_cycle` 留薄 alias
- 新增 `test_workflow_orchestration.py`（10 例）；`test_server` 两个 patch 目标改指 service 方法
- **真机验证**：启动装配成功 / live 冒烟 `ok=True fully_covered=True` 无异常 / `trigger=smoke_live` 正确 / W1 投递 Δ+1 + W2 真发简历1 均落库

**批 A 累计 -379 行（2638→2259）**。

### B run_log_reader 归并 / C session helpers — 待做

## 单拎 · 位置隔离方案 A — 待做

统一 `private/` 目录，改 `DATA_DIR`/`RUNS_DIR` 等路径常量。

---

## 贯穿全程的一条模式

**同一张表的写操作散在多处必然漂移。** 已确认四例，判据是**同一列在不同实现里的 CASE 分支不一致**：

1. `mark_reply_sent` 三份两义（NULL vs 'sent'）
2. `update_hr_analysis` 双实现（缺水位线 / None 语义相反）
3. `upsert_application` 的 `applied_at`（保留首次 vs 更新为最后）
4. 冒烟自持执行路径（绕过队列的 schedule_log / trigger 映射 / 错误清理）

收敛手法统一为：**SQL 只留 tracker 一处，工具做薄壳 + ToolResult 契约**；或依赖注入（`submit` 回调）让被测逻辑只管断言。

## 但同样重要：两次差点把有意设计当缺陷

这轮里我有**两次**准备"修"掉其实是刻意为之的东西：

| 项 | 我以为 | 实际 |
|---|--------|------|
| 3.1 `too_old` 优先于 `unanalyzed` | 架空了"失败下轮必重试"的承诺 | #51 的有意取舍——分析两月前的死线程没收益，真机 909→12 靠它收敛 |
| 3.6 `upsert_hr_conversation` 双实现 | 第五例分叉 | 有意职责分离——工具版管运行时身份/stage，tracker 版只管 onboarding 播种，列集与调用方均不重叠 |

**两次的识别信号都在现场**：3.1 有测试专门断言相反行为且 docstring 写明理由；3.6 的工具文件顶部注释直接写着 "intentionally kept apart rather than merged"。

**动手前先读注释与测试名。** 审计报告（包括 AI 生成的）给出的是可疑点，不是判决；与既有取舍冲突时，正确处理往往是**把取舍写进代码**，而不是改行为。
