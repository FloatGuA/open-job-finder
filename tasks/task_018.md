# Task 018 — 修复 task_013 Warnings（W1/W2/W4/W5）

## 背景

Task 013 的 review 遗留了 5 条 Warning，本 task 修复其中有实际风险的 4 条：

| # | 文件 | 问题 |
|---|------|------|
| W1 | `browser_agent.py` | `_classify_message()` 中 `normalized` 变量只用于英文，中文关键词匹配不一致 |
| W2 | `browser_agent.py` | 关键词 `"发过来"` 过于宽泛，会误匹配非简历场景 |
| W4 | `tools/check_responses.py` | `_handle_resume_request()` 未防重复发送，HR 多次请求时会多次触发 |
| W5 | `services/onboarding.py` | `check_attachment_resume()` 路径依赖 CWD，`dirname("")` 返回空字符串时为相对路径 |

不修复：
- W3（`utcnow()` → `timezone.utc`）：全项目统一迁移，单独 task 处理
- W6（`city`/`salary` 字段为空）：需扩展 tracker schema，单独 task 处理

---

## 修改清单

### 1. `services/browser_agent.py` — 修复 W1 + W2

**W1：统一使用 `normalized`（lowercase）做所有关键词匹配**

当前代码（伪代码）：
```python
def _classify_message(self, message: str) -> str:
    normalized = message.lower()
    resume_keywords = ["附件简历", "发一下简历", ...]
    for kw in resume_keywords:
        if kw in message:          # ← 用 message，不一致
            return "RESUME_REQUESTED"
    if "interview" in normalized:  # ← 只有这里用 normalized
        ...
```

修复：所有 `kw in message` 改为 `kw in normalized`（中文本身无大小写，实际效果等价，但代码一致）。同时将 `resume_keywords` 中的 Unicode 转义替换为直接中文字符，提升可读性。

**W2：移除宽泛关键词 `"发过来"`**

`resume_keywords` 列表中移除独立关键词 `"发过来"`，保留更精确的 `"简历发过来"` 和 `"把简历发过来"`。

---

### 2. `tools/check_responses.py` — 修复 W4（防重复发送）

`_handle_resume_request()` 在发送附件前，先查 tracker 当前状态：

```python
def _handle_resume_request(self, job_id: str, conv: ConversationRecord) -> None:
    # 防重复：若已是 RESUME_REQUESTED 且上次已成功发送，跳过
    record = self.tracker.get(job_id)
    if record and record.status == AppStatus.RESUME_REQUESTED:
        logger.info("job %s 已处于 RESUME_REQUESTED 状态，跳过重复发送", job_id)
        return
    # ... 原有发送逻辑 ...
```

注意：首次进入 `_handle_resume_request()` 时 status 可能还是 `APPLIED`，发送成功后才更新为 `RESUME_REQUESTED`。上面的检查拦截的是"已更新为 RESUME_REQUESTED 后 HR 又发了一条请求"的情形（第二次调用时状态已是 RESUME_REQUESTED）。

---

### 3. `services/onboarding.py` — 修复 W5（路径鲁棒性）

`check_attachment_resume()` 当前：
```python
path = os.path.join(os.path.dirname(self.resume_yaml_path), "resume_attachment.pdf")
```

若 `resume_yaml_path = "resume_base.yaml"`（无目录前缀），`dirname` 返回 `""`，`join` 结果为相对路径。

修复：改为基于 `__file__` 的绝对路径，与 `check_responses.py` 的 `ATTACHMENT_RESUME_PATH` 保持一致：

```python
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def check_attachment_resume(self) -> dict:
    path = _DATA_DIR / "resume_attachment.pdf"
    exists = path.exists()
    return {
        "ready": exists,
        "path": str(path),
        "note": None if exists else "请通过 Dashboard 上传附件简历 PDF，当 HR 请求时将自动发送。",
    }
```

---

## 验收标准

1. `_classify_message()` 中所有关键词均使用 `normalized`（lowercase message）匹配，无 `message` 直接匹配
2. `resume_keywords` 列表不包含独立的 `"发过来"` 词条
3. 当 job 状态已是 `RESUME_REQUESTED` 时，`_handle_resume_request()` 记录 info 日志并直接返回，不重复调用 `send_resume_attachment()`
4. `check_attachment_resume()` 返回的路径为绝对路径，在任意 CWD 下均正确
5. 现有语法检查（`python -m py_compile`）通过
