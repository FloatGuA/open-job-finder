# Database Schema Design

重构后三张表，去除冗余字段，职责清晰划分。

---

## `applications` — 投递状态

```sql
CREATE TABLE applications (
    job_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    hr_name     TEXT,
    url         TEXT,
    status      TEXT NOT NULL DEFAULT 'FOUND',
    city        TEXT,
    salary      TEXT,
    score       INTEGER,
    applied_at  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_applications_status ON applications(status);
```

**删除字段**：`updated_at`、`responded_at`、`critic_verdict`、`resume_path`、`apply_attempted`、`error_msg`、`decision`

**状态机（status）**：
```
FOUND → SCORED → APPLIED → CHATTING → INTERVIEWING → OFFER → REJECTED
```

---

## `hr_conversations` — 会话状态机

```sql
CREATE TABLE hr_conversations (
    conv_id          TEXT PRIMARY KEY,  -- sha256(hr_name|company|hr_title)[:12]
    hr_name          TEXT NOT NULL,
    company          TEXT NOT NULL,
    job_id           TEXT,              -- 关联 applications
    stage            TEXT NOT NULL DEFAULT 'new',
    boss_conv_id     TEXT DEFAULT '',
    intent           TEXT,
    reply_status     TEXT,              -- null|pending|approved
    reply_text       TEXT,              -- 当前工作回复，发送后清空
    last_msg_preview TEXT DEFAULT '',   -- DOM 截断预览，脏检查专用
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_hr_conversations_stage ON hr_conversations(stage);
CREATE INDEX idx_hr_conversations_boss_conv_id ON hr_conversations(boss_conv_id);
```

**删除字段**：`messages`（迁移到 hr_messages）、`status`（死代码）、`last_msg_text`、`last_msg_from`、`last_synced`、`needs_reply`（合并入 reply_status）、`reply_draft`（合并入 reply_text）、`suggested_reply`（合并入 reply_text）

**stage 状态机**：
```
new → active → resume_sent → interview → offer
  └─────────────────────────────────────────→ closed
```
- 只升不降
- `closed` 合并原 `rejected` 和 `closed`（结束原因记 event log）
- stage → applications.status 映射：interview→INTERVIEWING, offer→OFFER, closed→REJECTED

**intent 枚举**：
```
null | interview_invite | offer | rejection | resume_request | general | unknown
```

**reply_status 状态机**：
```
null ──→ pending ──→ approved ──→ (W2 发送后) null
  ↑                               (用户忽略后) null
```

---

## `hr_messages` — 消息历史

```sql
CREATE TABLE hr_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    TEXT    NOT NULL,
    sender     TEXT    NOT NULL,  -- hr | me | system
    text       TEXT    NOT NULL,
    msg_time   TEXT,              -- DOM 原始时间字符串
    created_at TEXT    NOT NULL,
    UNIQUE(conv_id, sender, text, msg_time)
);
CREATE INDEX idx_hr_messages_conv ON hr_messages(conv_id);
```

**用途**：
- 消息历史查询（AnalyzeHRIntent 输入）
- 推导 last_synced：`SELECT MAX(created_at) FROM hr_messages WHERE conv_id = ?`
- 推导 last_msg_from：`SELECT sender FROM hr_messages WHERE conv_id = ? ORDER BY id DESC LIMIT 1`
- DetectResumeRequest 输入

---

## 删除表

- `actions` 表：完全删除。唯一用途（判断是否投递过）由 `applications.status` 替代。

---

## conv_id 哈希变更

```python
# 旧
conv_id = sha256(f"{hr_name}|{company}")[:12]

# 新（加入 hr_title 防混淆）
# hr_title 是 HR 自身职位（如"HR经理"），从聊天列表左侧直接读取，无需点开会话
conv_id = sha256(f"{hr_name}|{company}|{hr_title}")[:12]
```

Breaking change，迁移脚本一次性处理，不维护向后兼容。
