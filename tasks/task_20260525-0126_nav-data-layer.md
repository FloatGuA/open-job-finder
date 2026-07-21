# Task: 数据层 — 持久化 Boss直聘真实会话 ID (boss_conv_id)

## Goal
在 `hr_conversations` 表新增 `boss_conv_id` 列，在 W2 扫描时从 DOM `.friend-content[d-c]` 提取该值并持久化，使后续跳转功能可直接用 URL 导航而无需扫描列表。

## Background

Boss直聘 每个 HR 会话有直接 URL `/web/geek/chat?conversationId={d-c值}`，其中 `d-c` 是聊天列表每个 `.friend-content` 元素的 DOM 属性。当前 `hr_conversations.conv_id` 是 `sha256(hr_name|company)[:12]`，不是 Boss 的 ID。

`scan_chat_list`（`services/browser_agent.py` ~line 1280）已经在 per-item 循环里提取 hr_name/company，但没有提取 `d-c`。`sync_conversations` 调用 `tracker.upsert_hr_conversation(...)` 但不传 `boss_conv_id`。

相关文件：
- `services/tracker.py`：`hr_conversations` CREATE TABLE + `upsert_hr_conversation` + `_add_column_if_missing` helper
- `services/browser_agent.py`：`scan_chat_list` per-item 循环 + `sync_conversations` upsert 调用
- `tests/test_hr_conversation_tracker.py`：tracker 单元测试

## Implementation Requirements

### 1. `services/tracker.py`

**a. CREATE TABLE** — 在 `hr_conversations` 建表语句末尾（在 `reply_draft` 后）加：
```sql
boss_conv_id TEXT NOT NULL DEFAULT ''
```

**b. ALTER TABLE 迁移守卫** — 在 `_ensure_schema()` 或初始化函数中（参考现有 `_add_column_if_missing` 调用模式），加：
```python
self._add_column_if_missing("hr_conversations", "boss_conv_id", "TEXT NOT NULL DEFAULT ''")
```

**c. `upsert_hr_conversation`** — 方法签名加可选参数 `boss_conv_id: str = ""`。
ON CONFLICT DO UPDATE 的 SET 子句中加：
```sql
boss_conv_id = CASE WHEN excluded.boss_conv_id != '' THEN excluded.boss_conv_id ELSE hr_conversations.boss_conv_id END
```
（非空优先：传入非空值才覆盖，空值不覆盖已有的值）

**d. `HRConversation` dataclass/namedtuple**（若存在） — 加 `boss_conv_id: str = ""` 字段（末尾，带默认值，不影响现有调用方）。

**e. `get_hr_conversation`** 等读取方法 — 确保返回对象包含 `boss_conv_id` 字段（若使用 `row_factory` 或 namedtuple 映射，需要更新字段列表）。

### 2. `services/browser_agent.py` — `scan_chat_list` 提取 d-c

在 per-item 循环（`for idx, item in enumerate(items):`）里，在现有 `company` 提取之后、`last_msg_preview` 之前，加：
```python
try:
    conv_el = item.ele(".friend-content", timeout=0)
    boss_cid = (conv_el.attr("d-c") or "") if conv_el else ""
except Exception:
    boss_cid = ""
```

将 `"boss_conv_id": boss_cid` 加入所有 `needs_sync.append({...})` 的 dict 中。`needs_sync` 中有多处 append（force_all 分支、has_unread 分支、dirty-check 命中分支、pending_reply 强制加入分支等），每一处都需要加。

### 3. `services/browser_agent.py` — `sync_conversations` 持久化

找到 `tracker.upsert_hr_conversation(...)` 的调用（在 `sync_conversations` 方法内），加入：
```python
boss_conv_id=item.get("boss_conv_id", ""),
```

### 4. 测试

在 `tests/test_hr_conversation_tracker.py` 中新增测试：
- `test_upsert_stores_boss_conv_id`：传入非空 boss_conv_id，读回验证值正确
- `test_upsert_nonempty_wins`：已有非空 boss_conv_id，再用空值 upsert，验证原值不被覆盖
- `test_upsert_nonempty_overwrites_empty`：先插入空值，再用非空值 upsert，验证被正确更新

## Acceptance Criteria
- [ ] `pragma table_info(hr_conversations)` 显示 `boss_conv_id` 列存在
- [ ] 对已有数据库（无 `boss_conv_id` 列）运行后，ALTER TABLE 守卫自动补列，不报错
- [ ] `upsert_hr_conversation(boss_conv_id="abc123")` 后 `get_hr_conversation` 返回 `boss_conv_id="abc123"`
- [ ] `upsert_hr_conversation(boss_conv_id="")` 不覆盖已有的非空 `boss_conv_id`
- [ ] `scan_chat_list` 返回的 `needs_sync` 每个 item 包含 `boss_conv_id` 键（值可能为空字符串）
- [ ] 3 个新 tracker 测试通过
- [ ] `pytest tests/` 全部通过（不破坏现有测试）
