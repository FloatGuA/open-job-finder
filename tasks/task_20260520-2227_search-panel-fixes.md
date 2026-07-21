# Task: search_with_panel 双重 emit + 滚屏等待修复

## 目标

修复 `browser_agent.search_with_panel` 的两个 bug：去除重复进度 emit（导致同一张卡片出现两条消息），并将滚屏后的等待时间从固定 2 秒改为轮询检测（最多等 6 秒），避免 Boss直聘 SPA 懒加载不足导致 `search_exhausted` 误判。

## 背景

`search_with_panel` 在调用 `on_card` 之前会自己 emit 一条 `[{cards_checked}/{max_cards_checked}]` 进度消息（分母是安全上限 300），而 orchestrator 的 `on_card` 闭包也会 emit `[{jobs_seen}/{limit_per_run}]`（分母是业务上限 15）。用户看到同一张卡片出现两条消息，且一条显示 `[8/300]` 完全误导。

第二个 bug：`next_card is None` 时滚屏后只 `_human_pause(2.0, 2.0)` 再检查，Boss直聘 SPA 懒加载有时需要 3-5 秒，2 秒不够导致新卡片未进 DOM 就判定 `search_exhausted`。

涉及文件：
- `code/services/browser_agent.py`

**不改动**：orchestrator.py、on_card 闭包、schemas、tracker、测试。

## 实现要求

### 1. 删除 browser_agent 里的重复 emit

在 `search_with_panel` 的 `do_search()` 内部，找到并删除以下代码块（大约 4 行）：

```python
# Emit to frontend so the user can see per-card progress.
if self.emitter:
    self.emitter.emit(_PE(
        workflow="apply", step="fetch", status="running",
        message=f"[{cards_checked}/{max_cards_checked}] {next_job.company} · {next_job.title}",
    ))
```

这条 emit 不应该在 browser 层，orchestrator 的 `on_card` 已经负责向用户展示 `[jobs_seen/limit_per_run]` 格式的消息。

### 2. 改进滚屏后等待逻辑

当前代码：
```python
if next_card is None:
    page.run_js("window.scrollTo(0, document.body.scrollHeight)")
    self._human_pause(2.0, 2.0)

    has_new_job_id = False
    for card in self._eles_any(_SELECTORS["job_card"]):
        candidate = self._parse_job_card(card, keywords, city)
        if candidate is not None and candidate.job_id not in seen_job_ids:
            has_new_job_id = True
            break

    if not has_new_job_id:
        exhausted_reason = "search_exhausted"
        break
    continue
```

改为轮询检测（最多等 6 秒，每 1.5 秒检查一次）：

```python
if next_card is None:
    page.run_js("window.scrollTo(0, document.body.scrollHeight)")

    has_new_job_id = False
    for _wait_attempt in range(4):  # 4 × 1.5s = 最多等 6s
        self._human_pause(1.5, 1.5)
        for card in self._eles_any(_SELECTORS["job_card"]):
            candidate = self._parse_job_card(card, keywords, city)
            if candidate is not None and candidate.job_id not in seen_job_ids:
                has_new_job_id = True
                break
        if has_new_job_id:
            break

    if not has_new_job_id:
        logger.info(
            "search_with_panel: no new job_id after scroll and %d wait attempts (%d checked so far)",
            4, cards_checked,
        )
        exhausted_reason = "search_exhausted"
        break
    continue
```

### 3. 补充 _parse_job_card 失败的 debug 日志

在 `_parse_job_card` 方法末尾（`if not href: return None` 之前）添加一行 debug 日志，方便诊断：

```python
if not href:
    logger.debug("_parse_job_card: no href found for card, skipping")
    return None
```

## 验收标准

- [ ] 前端 LiveLog 中，每张卡片只出现一条 `[N/15]` 格式的进度消息，不再出现 `[N/300]` 消息
- [ ] 对于 SKIP 卡片，只出现"已跳过"消息，不再有额外的重复行
- [ ] 滚屏后最多轮询 6 秒再判定 search_exhausted，而不是固定 2 秒
- [ ] `pytest tests/` 全部通过，无回归
