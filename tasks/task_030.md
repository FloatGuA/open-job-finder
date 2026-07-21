# Task 030 — DB 迁移

## Goal
按 design/db_schema.md 重写三张表的 DDL，删除 actions 表，更新 tracker.py 所有 SQL，并提供一次性迁移脚本处理现有 data/jobs.db。

## Background
现有 tracker.py 操作的 applications 表包含 7 个已废弃字段（decision / critic_verdict / resume_path / apply_attempted / error_msg / updated_at / responded_at），hr_conversations 表结构与新状态机不符，hr_messages 表尚不存在，actions 表将被彻底删除。

conv_id hash 公式从 `sha256(hr_name|company)[:12]` 更新为 `sha256(hr_name|company|hr_title)[:12]`。这是 breaking change，迁移脚本需处理现有数据。

本 Task 是整个重构的基础，所有后续 Tool 层任务（T034~T038）都依赖新 schema。

## Implementation Requirements

### 1. `code/services/tracker.py`

重写三张表的 CREATE TABLE DDL，严格对照 design/db_schema.md：

**applications 表**：
- 删除字段：updated_at / responded_at / critic_verdict / resume_path / apply_attempted / error_msg / decision
- 保留字段：job_id / title / company / hr_name / url / status / city / salary / score / applied_at / created_at
- status 枚举：FOUND → SCORED → APPLIED → CHATTING → INTERVIEWING → OFFER → REJECTED

**hr_conversations 表**（重写）：
- 字段：conv_id / hr_name / company / job_id / stage / boss_conv_id / intent / reply_status / reply_text / last_msg_preview / created_at
- stage 枚举：new / active / resume_sent / interview / offer / closed（只升不降，closed 合并原 rejected）
- reply_status 枚举：null / pending / approved
- 删除：messages / status / last_msg_text / last_msg_from / last_synced / needs_reply / reply_draft / suggested_reply

**hr_messages 表**（新建）：
```sql
CREATE TABLE hr_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    TEXT    NOT NULL,
    sender     TEXT    NOT NULL,  -- hr | me | system
    text       TEXT    NOT NULL,
    msg_time   TEXT,
    created_at TEXT    NOT NULL,
    UNIQUE(conv_id, sender, text, msg_time)
);
CREATE INDEX idx_hr_messages_conv ON hr_messages(conv_id);
```

**actions 表**：删除（DROP TABLE IF EXISTS actions）。

更新 tracker.py 中所有读写方法，使之与新 schema 对齐：
- 移除引用已删字段的代码
- 新增 insert_hr_messages(conv_id, messages) 方法（批量插入，跳过 UNIQUE 冲突）
- 新增 get_hr_messages(conv_id) → List[dict] 方法
- get_hr_conversations / upsert_hr_conversation 更新字段列表

### 2. `code/scripts/migrate_030.py`

一次性迁移脚本，处理现有 data/jobs.db：

1. 备份原始文件（data/jobs.db.bak）
2. 删除 actions 表
3. applications 表：ALTER TABLE DROP COLUMN 删除废弃字段（SQLite 3.35+ 支持），或重建表
4. hr_conversations 表：重建，保留 conv_id / hr_name / company / job_id / stage / boss_conv_id / intent 等可保留字段；新增 reply_text / last_msg_preview 初始化为空字符串；reply_status 初始化为 null；reply_draft / suggested_reply 内容迁移到 reply_text
5. hr_messages 表：CREATE TABLE IF NOT EXISTS
6. conv_id 无法自动迁移（需要 hr_title，现有数据无此字段）：打印 WARNING，保留现有 conv_id，不做修改

## Acceptance Criteria

- [ ] 迁移脚本在现有 data/jobs.db 上跑通不报错，打印迁移摘要
- [ ] 迁移后 PRAGMA table_info(applications) 无废弃字段
- [ ] 迁移后 PRAGMA table_info(hr_messages) 返回正确 6 列
- [ ] tracker.py 中无对已删字段（decision / critic_verdict / updated_at 等）的引用
- [ ] `pytest tests/` 中 tracker 相关测试通过（可能需更新现有测试以匹配新 schema）

## Reference
- design/db_schema.md（权威 schema 定义）
- code/services/tracker.py（现有实现，理解后修改）
- code/tests/test_tracker.py（现有测试，需同步更新）
