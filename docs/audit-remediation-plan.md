# 独立体检整改计划

> 来源：2026-07-21 四路独立 subagent 审视（架构分层 / W2 正确性 / 数据+隐私 / 测试+前端）
> 版本目标：`2.7.0` → **`2.8.0`**（Y+1，整改交付）
> 决策已定：P0 走方案 B（filter-repo 抹历史 + force-push）；每批验证门含 **live 冒烟**；server.py 减重单拎不入本轮

---

## 阶段 0 · 完善冒烟测试（最优先）

**为什么排第一**：后续每批的验证门都是 live 冒烟。门本身不可信，后面三批就是用没校准的尺子量。

### 现状（`code/services/regression.py`）

三层：Layer1 `run_pytest`（跑 pytest 套件）/ Layer2 `run_invariants`（5 条数据不变量）/ Layer3 `run_smoke`（真机 W1+W2，dry|live）。

### 已确认的缺口

| # | 缺口 | 证据 | 后果 |
|---|------|------|------|
| G1 | **"未覆盖"被当成通过** | `_w1_live_ok`: `delta>=1 if applied>0 else True`；`_w2_live_ok` 同构 | 本轮无卡可投/无人要简历 → 全绿但零验证。**直接摧毁验证门的意义** |
| G2 | **W3（发回复）结构性不覆盖** | `run_smoke` docstring 明确排除 | 批次 1.1 改的 mark-sent 正在这条路径上，live 冒烟验不到 |
| G3 | **无法主动制造覆盖** | 冒烟守株待兔，等"恰好有动作" | 想验某条路径只能碰运气 |
| G4 | **Layer2 不变量太薄** | 仅 5 条（状态枚举 / reply 有正文） | #52/#53 那类 bug（106 条会话有 HR 消息但 intent 空）不变量完全测不出 |
| G5 | **冒烟与"本次改了什么"无关联** | 固定两步，不管改动内容 | 跑完无法回答"我改的东西被验到了吗" |
| G6 | **live 成本无护栏** | 每批 live = 真投真发 | 4 批 ≥ 4 次真实投递 + 可能的真简历外发，吃 Boss 日配额、影响真实 HR |

### 阶段 0 任务

**S1 · 消除假绿（最关键）**
给每个 check 增加第三态 `covered`，report 层区分 `ok`（无失败）与 `fully_covered`（关键路径真跑到）。
- `applied==0` / `resumes==0` → `ok=True, covered=False`，**不再计入"通过"**
- 前端 SmokeCard：绿=全覆盖通过 / 黄=通过但未全覆盖 / 红=失败
- 验证门口径改为：**必须 `fully_covered` 才算过门**

**S2 · 让 live 冒烟可强制覆盖**
- W1 加 `force_apply`：临时下调 score_threshold，确保本轮至少真投 1 个（否则报 not covered）
- W2 加 `target_conv_id`：指定会话强制走完 read→analyze→(resume)，不依赖"恰好有 HR 要简历"
- 目的：把"守株待兔"变成"主动制造覆盖"

**S3 · 补 Layer2 不变量（把历史 bug 变成常驻探针，零副作用）**
新增：
1. `有 HR 消息但 intent 为空的会话数 == 0` ← #52/#53 核心指标（当时 106 条）
2. `last_analyzed_ts <= last_msg_ts` ← 水位线不越界
3. `last_analyzed_ts > 0 的会话必有 intent` ← 水位线与结论一致
4. `hr_messages 无重复` ← 曾重复落 322 条
5. `reply_status='sent' 的 reply_text 为空` ← **正好守住批次 1.1 的语义统一**

这些是纯读库探针，可随便跑，且直接守住本轮要改的东西。

**S4 · 补上 W3/mark-sent 的验证（诚实方案）**
不真发给 HR。改为：单测覆盖三处收敛后的调用 + S3-5 不变量守语义 + 冒烟报告**明确标注"W3 发送路径不覆盖，靠单测+不变量守"**。
> 原则：诚实标注不覆盖，好过假装覆盖。

**S5 · 报告加覆盖清单**
跑完列出本次真实 covered 的路径，人工可对照"我改的东西验到了吗"。

**S6 · live 护栏**
- 确认冒烟受既有 `rate_limited` 日配额闸门管辖
- live 默认 `w1_max=1`
- 报告记录本次真实外发内容（投了哪个岗 / 发了几份简历），可审计

**阶段 0 验证门**：`pytest` 绿 + 新增不变量在生产库上跑出真实结果（预期能查出存量问题）+ **跑一次 live 冒烟确认新的 covered 判定生效**（这次是验证冒烟本身）

---

## 阶段 1 · P0 隐私（方案 B）

**1a 移除追踪（安全可回退）**
```
git rm -r --cached logs/
# .gitignore 补 /logs/ 覆盖全目录（现有 /logs/task_*/ 对已追踪文件无效）
git commit && push
```

**1b 历史改写（不可逆）**
```
pip install git-filter-repo
git filter-repo --path logs/ --invert-paths          # 抹 164 文件 / 41M
git filter-repo --path PROGRESS.md --replace-text ... # 清旧 blob 真实公司名/薪资
git push --force
```
- 涉及全部 121 commit（泄露自 initial commit 就存在）→ 所有 SHA 变化
- fork=0 / star=0 → 无人受影响
- filter-repo 会移除 remote，需重新 `git remote add`
- **残留**：GitHub 可能通过直接 SHA 缓存旧 commit 一段时间，彻底失效需给 GitHub Support 发工单

**验证门**：`git log --all -- logs/` 无输出 + `git log -p` 搜不到真实公司名 + 工作树 `logs/` 文件仍在 + `pytest` 绿（确认没误删代码）

---

## 阶段 2 · High

| # | 改动 | 文件 |
|---|------|------|
| 2.1 | **mark-sent 三份收敛**：端点改调 tracker，统一语义 `'sent'/''`（消除 `NULL` 那份 → 防重复发送） | `server.py:1807`、`tools/db/w2/mark_reply_sent.py`、`tracker.py:682` |
| 2.2 | 删 `tracker.update_hr_analysis` 死方法 + 其单测（无 `last_analyzed_ts`，误接即回退 #53） | `tracker.py:590` |
| 2.3 | **W2 新会话首轮丢写**：`update_hr_analysis` 改 upsert 语义（或 0 行更新返回非 ok），补集成测试覆盖"行不存在"顺序缺口 | `tools/db/w2/update_hr_analysis.py`、`conversation_pipeline.py` |

**验证门**：`pytest` + **live 冒烟（fully_covered）** + S3-5 不变量绿 + 真机 W2 观察 `unanalyzed` 分支

---

## 阶段 3 · Medium

| # | 改动 |
|---|------|
| 3.1 | `too_old` 与 `unanalyzed` 顺序：让"从未成功分析过"的行豁免 14d 窗口 |
| 3.2 | `mark_timeout` 改用 `last_msg_ts` 真实时间戳，与 `too_old` 口径对齐 |
| 3.3 | 配置读写统一 `config_manager` 单例，写后失效缓存 |
| 3.4 | 微信号解析下沉 `tools/biz_logic/`，前后端共用一份权威实现 |

**验证门**：`pytest` + live 冒烟 + `npm run build`（3.4 动前端）

---

## 阶段 4 · Low

| # | 改动 |
|---|------|
| 4.1 | 补 `score_job` 加权聚合单测（唯一实质测试空白） |
| 4.2 | 修 `SelfCheck.tsx:93` interval 泄漏，对齐 `Automation.tsx` pollRef 范式 |
| 4.3 | 修正 CLAUDE.md/MEMORY「禁止 tool 层裸 SQL」措辞，与 `tools/db` 实际设计对齐 |

**验证门**：`pytest` + `npm run build` + live 冒烟终验

---

## 单拎（不在本轮）

- **server.py 减重**：2549 行，调度/队列/自检/限流编排下沉为 orchestration service。跨多文件重构，按项目规则需单独给方案确认，建议本轮整改稳定后单独立项（届时再升一次 Y）。

---

## 执行纪律

1. 每阶段**改完即跑验证门**，绿了才进下一阶段；不绿就停下来报告，不带病前进
2. 阶段 0 完成前，不用 live 冒烟当门（现在的门会假绿）
3. `version.ts` 在阶段 0 动代码前改为 `2.8.0`
4. 每阶段结束更新 `PROGRESS.md`；重要决策/踩坑进 worklog + 项目记忆
5. **PROGRESS/worklog 举例严禁抄私有会话库的真实公司/HR/薪资**（已因此被 push classifier 拦过一次）
