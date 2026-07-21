# Task: W1 Per-job 分类函数 + 新增 Enum

## 目标

在 `schemas.py` 新增两个 enum，在 `tracker.py` 新增一个分类方法，为 W1 重写提供基础。同时在 `VALID_TRANSITIONS` 中补充 `SCORED → REJECTED` 转换。

## 背景

W1 重构的第一步。当前 `tracker.exists(job_id)` 一刀切跳过所有历史记录，导致 W1 找不到新候选。需要替换为语义明确的分类函数。

评分不通过的 job 直接标为 REJECTED（不保留在 SCORED 等待重评）。

涉及文件：
- `code/schemas.py`
- `code/services/tracker.py`

**不改动** W2/W3、orchestrator、browser_agent、任何 tool 文件。

## 实现要求

### 1. `code/schemas.py`

在文件末尾追加两个 enum：

```python
class W1Action(str, Enum):
    FULL_PIPELINE = "full_pipeline"   # 未处理，走全流程（fetch → score → apply）
    APPLY_ONLY    = "apply_only"      # SCORED+decision=apply，跳过评分直接打招呼
    SKIP          = "skip"            # 已完成或已拒绝，不处理


class CardSignal(str, Enum):
    APPLIED = "applied"   # 已投递，继续搜索
    SKIPPED = "skipped"   # 已跳过，继续搜索
    STOP    = "stop"      # 停止搜索，browser 立即退出循环
```

### 2. `code/services/tracker.py`

#### 2a. VALID_TRANSITIONS 补充一条转换

在现有 `VALID_TRANSITIONS` 字典中，`SCORED` 的出向集合加入 `REJECTED`：

```python
AppStatus.SCORED.value: {AppStatus.APPLIED.value, AppStatus.REJECTED.value, AppStatus.ERROR.value},
```

#### 2b. 新增 `classify_job_for_w1` 方法

在 `ApplicationTracker` 类中新增：

```python
def classify_job_for_w1(self, job_id: str) -> "W1Action":
    """Classify a job for W1 processing.

    Returns:
        FULL_PIPELINE  — not in DB, or fetch/score was interrupted (DISCOVERED/SCANNED)
        APPLY_ONLY     — scored and approved but apply was interrupted (SCORED+decision=apply)
        SKIP           — terminal: already applied, rejected, or in W2 conversation
    """
    from schemas import W1Action, AppStatus

    record = self.get(job_id)
    if record is None:
        return W1Action.FULL_PIPELINE

    TERMINAL = {
        AppStatus.APPLIED,
        AppStatus.RESPONDED,
        AppStatus.RESUME_REQUESTED,
        AppStatus.INTERVIEW,
        AppStatus.OFFER,
        AppStatus.REJECTED,
        AppStatus.AD_PUSH,
    }
    status = AppStatus(record.status)

    if status in TERMINAL:
        return W1Action.SKIP
    if status == AppStatus.ERROR:
        return W1Action.SKIP if record.apply_attempted else W1Action.FULL_PIPELINE
    if status in (AppStatus.DISCOVERED, AppStatus.SCANNED):
        return W1Action.FULL_PIPELINE
    if status == AppStatus.SCORED:
        if record.decision == "apply":
            return W1Action.APPLY_ONLY
        return W1Action.SKIP  # decision=skip → was already rejected, treat as SKIP
    return W1Action.SKIP  # fallback
```

注意：`classify_job_for_w1` 不接受 threshold 参数——评分不通过时直接标 REJECTED，不再做 threshold 重评。

## 验收标准

- [ ] `W1Action` 和 `CardSignal` enum 可正常 import
- [ ] 对所有 11 种 AppStatus 调用 `classify_job_for_w1` 无异常、无漏判
  - DISCOVERED → FULL_PIPELINE
  - SCANNED → FULL_PIPELINE
  - SCORED + decision="apply" → APPLY_ONLY
  - SCORED + decision="skip" → SKIP
  - APPLIED → SKIP
  - RESPONDED → SKIP
  - RESUME_REQUESTED → SKIP
  - INTERVIEW → SKIP
  - OFFER → SKIP
  - REJECTED → SKIP
  - AD_PUSH → SKIP
  - ERROR + apply_attempted=True → SKIP
  - ERROR + apply_attempted=False → FULL_PIPELINE
- [ ] `VALID_TRANSITIONS[SCORED]` 包含 REJECTED
- [ ] `pytest tests/` 全部通过，现有测试不回归
