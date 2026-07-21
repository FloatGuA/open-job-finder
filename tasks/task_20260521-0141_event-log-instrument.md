# Task: 结构化事件埋点（orchestrator + browser_agent + check_responses）

## 目标

在 `orchestrator.py`、`services/browser_agent.py`（仅 `search_with_panel` 流程）、`tools/check_responses.py` 中埋入 `RunLogger.log()` 调用，让每次 workflow run 生成有意义的事件流。

## 背景

`services/event_log.RunLogger` 已由 `task_20260521-0140_event-log-core` 实现。本 task 只负责在业务代码中创建 `RunLogger` 实例并在关键节点调用 `.log()`。

RunLogger 不阻断主流程——写入失败只打 warning，永不抛异常。

## 实现要求

### 1. `code/orchestrator.py`

**在 `run_once()` 开头** 创建 RunLogger，**在结尾**调用 `close()`：

```python
from services.event_log import RunLogger

def run_once(self, limit_per_run=30, score_threshold=None, apply_limit=0, dry_run=False, generate_resume=False):
    run_logger = RunLogger("apply")
    try:
        # ... 现有逻辑 ...
    finally:
        run_logger.close(status="done", summary=summary)
```

**需要埋入的事件**（所有事件 `visible=True` 除非特别标注）：

| 事件 | event_type | data 字段 | 触发时机 |
|------|-----------|-----------|---------|
| 找到职位卡片 | `card_discovered` | job_id, title, company, salary | on_card 被调用时（每个新 job_id） |
| LLM 评分完成 | `card_scored` | job_id, title, company, score, decision, reason | score_tool.execute() 成功后 |
| 职位跳过 | `card_skipped` | job_id, title, company, reason（"low_score"/"duplicate"/"limit_reached"/"critic_rejected"） | 各跳过分支 |
| 投递成功 | `card_applied` | job_id, title, company, score | apply_tool 成功后 |
| 投递失败 | `card_error` | job_id, title, company, error | apply_tool 异常时 |
| run 结束 | 由 close() 写 workflow_end | summary dict（jobs_seen, applied, skipped_low_score, search_exhausted_reason 等） | run_once finally |

**传递 RunLogger 到 BrowserAgent**：修改 `run_once` 中的 `BrowserAgent` 创建或 `search_with_panel` 调用，将 `run_logger` 传入（见第2节）。

---

### 2. `code/services/browser_agent.py` — `search_with_panel` 的 `do_search()`

`search_with_panel` 接受新的可选参数 `run_logger: RunLogger | None = None`（或通过 `self._run_logger` 设置，任一方式均可）。

**需要埋入的事件**（`visible=False`，action 级别）：

| 事件 | event_type | data 字段 | 触发时机 |
|------|-----------|-----------|---------|
| 卡片 JS 抓取 | `cards_scraped` | count | _scrape_cards_js() 返回后 |
| 点击卡片 | `card_click` | job_id, success | JS 点击后 |
| JD 加载 | `jd_loaded` | job_id, title, company | _wait_for_panel_ready 成功后 |
| 应用按钮点击 | `apply_btn_clicked` | job_id, btn_text | apply_btn.click() 或跳过 click 时 |
| 导航恢复 | `nav_recovered` | from_url, to_url | URL guard 触发时 |

---

### 3. `code/tools/check_responses.py`

**在 `execute()` 开头** 创建 `RunLogger("check")`，**结尾 `close()`**。

**需要埋入的事件**（全部 `visible=True`）：

| 事件 | event_type | data 字段 | 触发时机 |
|------|-----------|-----------|---------|
| 检查对话 | `hr_checked` | conv_id, hr_name, company, stage, message_count | 每条会话检查后 |
| 意图分析 | `intent_analyzed` | conv_id, hr_name, company, intent, confidence, suggested_action | LLM 分析完成后（如有） |
| 状态推进 | `status_advanced` | job_id, old_status, new_status | tracker 写入新状态后 |
| run 结束 | workflow_end | checked_count, updated_count, errors | close() |

---

## 验收标准

- [ ] 运行 `python main.py --dry-run`（或 Dashboard 触发 Apply workflow），在 `logs/runs/` 下生成 `.jsonl` 文件
- [ ] JSONL 文件中包含 `workflow_start`、多条 `card_discovered/card_scored/card_skipped/card_applied`、`workflow_end` 事件
- [ ] `GET /api/runs` 返回刚生成的 run 摘要
- [ ] `GET /api/runs/{run_id}?visible_only=true` 仅返回 `visible=true` 事件
- [ ] `pytest tests/` 全部通过（无回归）
