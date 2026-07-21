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

### 3.3 配置读写统一 config_manager — 待做
### 3.4 微信号解析下沉 biz_logic — 待做
### 3.5 upsert_application 完整收敛（工具调 tracker，含 content_hash）— 待做
### 3.6 upsert_hr_conversation 完整收敛 — 待做

> **第五例双实现**：`tracker.upsert_hr_conversation` **不写** `last_msg_ts`/`hr_title`/`job_id`，只有工具版写（且含 legacy re-key 与 stage 状态机 CASE）。测试因此写不进该列，当前在测试里直写并注明。

---

## 阶段 4 · Low — 待做

- 4.1 补 `score_job` 加权聚合单测（唯一实质测试空白）
- 4.2 修 `SelfCheck.tsx` interval 泄漏（句柄未存 ref，卸载不清）
- 4.3 修正 CLAUDE.md/MEMORY「禁止 tool 层裸 SQL」措辞，与 `tools/db` 实际设计对齐

---

## 单拎（不在本轮）

- **server.py 减重**：2549 行，调度/队列/自检/限流编排下沉为 orchestration service
- **位置隔离方案 A**：统一 `private/` 目录，改 `DATA_DIR`/`RUNS_DIR` 等路径常量

---

## 贯穿全程的一条模式

**同一张表的写操作散在多处必然漂移。** 已连抓五例，判据是**同一列在不同实现里的 CASE 分支不一致**：

1. `mark_reply_sent` 三份两义（NULL vs 'sent'）
2. `update_hr_analysis` 双实现（缺水位线 / None 语义相反）
3. `upsert_application` 的 `applied_at`（保留首次 vs 更新为最后）
4. `upsert_hr_conversation` 缺三列（`last_msg_ts`/`hr_title`/`job_id`）
5. 冒烟自持执行路径（绕过队列的 schedule_log / trigger 映射 / 错误清理）

收敛手法统一为：**SQL 只留 tracker 一处，工具做薄壳 + ToolResult 契约**；或依赖注入（`submit` 回调）让被测逻辑只管断言。
