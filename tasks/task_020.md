# Task 020 — 简历发送状态机修复（resume_requested 中间状态）

## 背景

当前 `hr_conversations` 表的 `stage` 字段只有两个值：
- `general`：正常对话
- `resume_sent`：已发送附件简历

问题：`stage=resume_sent` 在检测到简历请求时就可能被设置，而不是在发送成功后才设置。
如果发送失败（超时、选择器找不到、浏览器崩溃），stage 已经写死为 `resume_sent`，导致后续
scan 永远跳过这条会话，简历永远无法补发。

此外，`scan_chat_list` 中空 preview 的第 4 分支有一个过于严格的条件
`cached.last_msg_from == "hr"`，而 Boss直聘 的附件简历请求卡片会被 DOM 分类为
`sender="system"`，导致 `last_msg_from` 实际值为 `"system"`，第 4 分支不触发。

---

## 目标

引入 `resume_requested` 中间状态，把"检测到请求"和"确认发送成功"分开：

```
general → resume_requested → resume_sent
              ↑
         (发送失败保持此状态，下次 scan 重试)
```

修复 `scan_chat_list` 的跳过逻辑，使 `resume_requested` 的会话永远重新入队。

---

## 改动范围

只修改以下两个文件：
- `services/browser_agent.py`
- `services/tracker.py`（如果 `upsert_hr_conversation` 需要调整签名）

---

## 详细要求

### 1. `sync_conversations`（`browser_agent.py`）

在处理每条会话时，把 stage 的设置拆成两步：

```python
# 步骤 A：检测到简历请求 → 先标记为 resume_requested
if needs_resume:
    tracker.upsert_hr_conversation(..., stage="resume_requested")

# 步骤 B：发送成功 → 再改为 resume_sent
success = self._send_resume_in_current_chat(...)
if success:
    tracker.upsert_hr_conversation(..., stage="resume_sent")
# 发送失败：保持 resume_requested，不修改
```

注意：`upsert_hr_conversation` 目前使用 `ON CONFLICT DO UPDATE SET stage=excluded.stage`，
即每次调用都会覆盖 stage。因此步骤 A 只在 `needs_resume=True` 时调用，步骤 B 只在
`success=True` 时调用，两次调用互不干扰。

当 `needs_resume=False` 时，照常调用 `upsert_hr_conversation` 写入其他字段，stage 传入
当前已有值（不降级）或保持 `"general"`。

### 2. `scan_chat_list`（`browser_agent.py`）

修改跳过条件：

```python
# 原逻辑（有问题）：
if cached and cached.last_msg_preview == last_msg_preview:
    if cached.stage == "resume_sent":
        continue  # 正确：已发送，跳过

# 新逻辑：
if cached and cached.last_msg_preview == last_msg_preview:
    if cached.stage == "resume_sent":
        continue  # 正确：已确认发送，跳过
    elif cached.stage == "resume_requested":
        # 发送失败的重试：重新入队，即使 preview 没变
        logger.debug("  re-queue %r (stage=resume_requested, retry)", company)
        needs_sync.append({...})
        continue
    else:
        # general：preview 未变，无 unread，跳过
        continue
```

修复空 preview 第 4 分支的条件（去掉 `last_msg_from == "hr"` 限制）：

```python
# 原条件（过于严格）：
elif not last_msg_preview and tracker is not None:
    cached = tracker.get_hr_conversation(cid)
    if cached and cached.stage != "resume_sent" and cached.last_msg_from == "hr":
        needs_sync.append(...)

# 新条件：
elif not last_msg_preview and tracker is not None:
    cached = tracker.get_hr_conversation(cid)
    if cached and cached.stage in ("resume_requested", "general") and cached.last_msg_from in ("hr", "system"):
        logger.debug("  re-queue %r (empty preview, stage=%r)", company, cached.stage)
        needs_sync.append(...)
```

实际上，条件可以更简单：只要 `cached.stage != "resume_sent"` 且 `cached` 存在即入队
（因为空 preview 说明有未渲染的卡片消息，值得去检查）。

### 3. 数据修复

在 `tracker.py` 中新增一个方法（或在现有方法中支持），允许将指定
`conv_id` 的 `stage` 重置：

```python
def reset_hr_conversation_stage(self, conv_id: str, stage: str = "general") -> None:
    """将指定会话的 stage 重置（用于修复错误标记）。"""
    with self._conn() as conn:
        conn.execute(
            "UPDATE hr_conversations SET stage = ? WHERE conv_id = ?",
            (stage, conv_id),
        )
```

这个方法主要供一次性修复脚本使用，不需要集成进主流程。

---

## 验收标准

1. `python -m py_compile services/browser_agent.py` 通过
2. `python -m py_compile services/tracker.py` 通过
3. `sync_conversations` 中：`stage=resume_requested` 在检测到简历请求后设置，
   `stage=resume_sent` 仅在发送成功后设置
4. `scan_chat_list` 中：`stage=resume_requested` 的会话不会被跳过，会重新入队
5. `scan_chat_list` 中：空 preview + `stage != resume_sent` 的会话会入队
6. `tracker.py` 新增 `reset_hr_conversation_stage` 方法

---

## 不需要做的事

- 不修改数据库 schema（`stage` 字段已是 TEXT，直接写新值即可）
- 不修改 `check_responses.py`、`orchestrator.py`、`dashboard/server.py`
- 不添加新的 API 端点
- 不修改前端代码
