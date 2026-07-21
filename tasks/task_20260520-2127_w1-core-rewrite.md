# Task: W1 核心重写（orchestrator + browser_agent）

## 目标

重写 `orchestrator.py` 的 W1 流程和 `browser_agent.py` 的 `search_with_panel` 方法，实现干净的原子操作队列模型：删除 Carryover、Critic、简历生成，修正计数器语义，改用 job_id 游标做分页。

## 背景

依赖 Task A（`W1Action`、`CardSignal`、`classify_job_for_w1` 已存在）。

当前问题：
- `search_with_panel` 用 `cards_processed < limit` 做循环控制，`limit` 计的是 DOM 卡片检查次数（含已跳过），导致已知 job 消耗搜索上限
- `on_card` 返回 `bool`，无法区分"跳过继续"和"停止搜索"
- 分页依赖 DOM 卡片数量增长（Boss直聘 SPA 不可靠）
- Pass 1 Carryover、Critic、简历生成是历史遗留，本次删除

涉及文件：
- `code/orchestrator.py`
- `code/services/browser_agent.py`

**不改动**：`check_responses.py`（W2）、所有 W3 代码、Dashboard 前端、`score_job.py`、`critique_job.py`、`resume_tool.py` 本身。

## 实现要求

### 1. `code/services/browser_agent.py` — `search_with_panel` 重写

#### 1a. 签名修改

```python
def search_with_panel(
    self,
    keywords: str,
    city: str,
    on_card: Callable[["Job"], "CardSignal"],        # 从 bool 改为 CardSignal
    on_apply_done: Callable[["Job", bool], None] = None,
    search_url: str = None,
    dry_run: bool = False,
    max_cards_checked: int = 300,                   # 安全上限，防止死循环
) -> dict:                                          # 返回 {"cards_checked": int, "exhausted_reason": str}
```

**删除** `limit` 参数（业务上限由 `on_card` 闭包在 orchestrator 里控制，browser 不再关心）。其余参数（`experience`、`degree`、`salary`、`scale`、`job_type`、`boss_online`）不再使用，一并删除。

#### 1b. 主循环重写

```
初始化：
  seen_job_ids: set = set()   # 本次 run 已见的全部 job_id（跨页累计）
  cards_checked: int = 0      # 已检查的 DOM 卡片数（安全计数器）
  exhausted_reason: str = ""

主循环：while True（不再用 while cards_processed < limit）：
  if stop_requested: break
  if cards_checked >= max_cards_checked: exhausted_reason = "max_cards_checked"; break

  获取当前页所有卡片（_eles_any）
  找出第一张 job_id 不在 seen_job_ids 中的卡片（next_card）

  if next_card is None（当前页全是已见 job_id）:
    # 尝试滚动加载更多
    记录当前 seen_job_ids 快照
    page.run_js("window.scrollTo(0, document.body.scrollHeight)")
    等待 2s
    重新获取卡片，从中提取新 job_id
    if 没有任何新 job_id 出现:
      exhausted_reason = "search_exhausted"
      break
    continue  # 有新卡片，回到主循环顶部

  # 处理 next_card
  seen_job_ids.add(next_job.job_id)
  cards_checked += 1

  点击卡片、读取 JD、构建 full_job（逻辑与现有代码相同，不改）

  signal = on_card(full_job)   # 返回 CardSignal 而不是 bool

  if signal == CardSignal.STOP:
    exhausted_reason = "stop_signal"
    break
  elif signal == CardSignal.SKIPPED:
    continue  # 下一张
  elif signal == CardSignal.APPLIED:
    # 执行投递（逻辑与现有代码相同：pre-apply 清除旧弹窗、点投递按钮、等确认弹窗、关弹窗）
    success = ...
    if on_apply_done: on_apply_done(full_job, success)

return {"cards_checked": cards_checked, "exhausted_reason": exhausted_reason}
```

**分页停止条件（新）**：当前页所有卡片的 job_id 都在 `seen_job_ids` 中，且滚动后也没有出现新 job_id → `exhausted_reason = "search_exhausted"`，break。

**不改动**：卡片点击、JD 读取（含 JS fallback）、HR 名称读取、apply 按钮点击、成功弹窗检测、"留在此页"按钮处理 — 这些 DOM 操作逻辑与现有代码完全相同。

#### 1c. 调用方更新

`search_with_panel` 签名变了，同时更新 `orchestrator.py` 中的调用（见下方 Section 2c）。

---

### 2. `code/orchestrator.py` — W1 流程重写

#### 2a. 删除 Pass 1 Carryover

删除 `run_once()` 里以下全部代码块（约第 268–371 行）：
- `discovered_all = self.tracker.get_by_status(AppStatus.DISCOVERED)` 以及后续的 `scanned_all`、`scored_all`、`carryover_all`、`carryover_cap`、`carryover` 变量
- Carryover 超出上限的 warning emit
- `_process_one(record)` 函数定义（整个函数）
- `for record in carryover: _process_one(record)` 循环
- 与 `applied_today` / `jobs_done` 相关的 carryover 计数逻辑

删除后，`run_once()` 直接从 `profile = self._load_profile()` 之后进入关键词/城市嵌套循环。

#### 2b. 重写 `on_card` 闭包

用新的 `on_card(job) -> CardSignal` 替换现有的 `on_card(job) -> bool`：

```python
from schemas import W1Action, CardSignal, AppStatus
import datetime as _dt

jobs_seen = 0        # 进入原子操作队列的候选数（SKIP 不计）
applied_count = 0    # 本轮成功投递数

def on_card(job: "Job") -> "CardSignal":
    nonlocal jobs_seen, applied_count

    action = self.tracker.classify_job_for_w1(job.job_id)

    if action == W1Action.SKIP:
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="fetch", status="skipped",
            message=f"已跳过（{self.tracker.get(job.job_id).status if self.tracker.get(job.job_id) else '新建'}）：{job.company} · {job.title}",
        ))
        return CardSignal.SKIPPED

    # 检查停止条件（SKIP 的卡片不消耗配额）
    jobs_seen += 1
    if jobs_seen > limit_per_run:
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="fetch", status="skipped",
            message=f"已达搜索上限 {limit_per_run}，停止",
        ))
        return CardSignal.STOP
    if apply_limit is not None and applied_count >= apply_limit:
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="fetch", status="skipped",
            message=f"已达投递上限 {apply_limit}，停止",
        ))
        return CardSignal.STOP
    if self.emitter.stop_requested:
        return CardSignal.STOP

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    # 确保 DB 里有记录（新 job 先 upsert）
    if action == W1Action.FULL_PIPELINE:
        self.tracker.upsert(ApplicationRecord(
            job_id=job.job_id, title=job.title, company=job.company,
            url=job.url, status=AppStatus.DISCOVERED.value,
            city=job.city or "", salary=job.salary or "",
            created_at=now, updated_at=now,
        ))

    self.emitter.emit(ProgressEvent(
        workflow="apply", step="fetch", status="running",
        message=f"[{jobs_seen}/{limit_per_run}] {job.company} · {job.title}",
    ))

    # APPLY_ONLY：跳过评分，直接投递
    if action == W1Action.APPLY_ONLY:
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="score", status="skipped",
            message=f"评分已完成，跳过重新评分",
        ))
        return CardSignal.APPLIED

    # FULL_PIPELINE：评分
    if self.score_threshold == 0:
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="score", status="skipped",
            message="score_threshold=0，跳过评分",
        ))
        return CardSignal.APPLIED

    self.emitter.emit(ProgressEvent(
        workflow="apply", step="score", status="running",
        message=f"AI 评分中：{job.company} · {job.title}",
    ))
    score_result = self.score_tool.execute(job=job, profile=profile)["result"]
    self.update_tool.execute(
        job_id=job.job_id, new_status=AppStatus.SCORED.value,
        score=score_result.score, decision=score_result.decision,
    )

    if score_result.score < self.score_threshold or score_result.decision == "skip":
        # 评分不通过 → 标为 REJECTED
        self.update_tool.execute(job_id=job.job_id, new_status=AppStatus.REJECTED.value)
        self.emitter.emit(ProgressEvent(
            workflow="apply", step="score", status="skipped",
            message=f"评分 {score_result.score} 低于阈値 {self.score_threshold}，标记为 REJECTED",
        ))
        return CardSignal.SKIPPED

    self.emitter.emit(ProgressEvent(
        workflow="apply", step="score", status="running",
        message=f"评分 {score_result.score} 通过，准备投递",
    ))
    return CardSignal.APPLIED
```

**注意**：`profile`、`limit_per_run`、`apply_limit` 通过闭包引用外层变量（与现有 `on_card` 相同模式）。

#### 2c. 更新 `on_apply_done` 闭包

保留现有 `on_apply_done(job, success)` 逻辑，但去掉 `jobs_done` 计数（该变量随 carryover 一起删除）。只保留：
- `success=True` → `update_tool.execute(APPLIED)`、`applied_count += 1`、`_seed_hr_conversation`
- `success=False` → `update_tool.execute(ERROR)`
- `dry_run=True` → 跳过实际状态更新，emit skipped

#### 2d. 更新 `search_with_panel` 调用

```python
result = agent.search_with_panel(
    keywords=keyword,
    city=city,
    on_card=on_card,
    on_apply_done=on_apply_done,
    search_url=url,
    dry_run=effective_dry_run,
)
exhausted_reason = result.get("exhausted_reason", "")
```

删除 `limit=limit_per_run` 参数（新签名没有 `limit`）。

#### 2e. 更新 `run_once()` 返回值

```python
summary = {
    "jobs_seen": jobs_seen,
    "applied": applied_count,
    "skipped": 0,   # 可从 jobs_seen - applied_count 推导，保留字段兼容性
    "errors": 0,
    "exhausted_reason": exhausted_reason,
}
```

---

## 验收标准

- [ ] `search_with_panel` 签名中无 `limit` 参数
- [ ] `on_card` 返回 `CardSignal.STOP` 时，browser 立即退出循环（不再调用 `on_card`）
- [ ] 全页卡片 job_id 均已见，滚动后也无新 job_id → `exhausted_reason = "search_exhausted"`
- [ ] 30 张卡片全是 SKIP（`classify_job_for_w1` 返回 SKIP）→ `jobs_seen = 0`，搜索继续
- [ ] 评分不通过的 job → DB 状态变为 REJECTED
- [ ] `run_once()` 全流程无 `critique_tool` / `resume_tool` 调用
- [ ] Pass 1 carryover 相关代码全部删除（`carryover_all`、`_process_one` 等变量不再存在）
- [ ] `pytest tests/` 全部通过，现有测试不回归
