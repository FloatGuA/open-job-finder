# Task: HR 主动发起会话时自动创建 stub application 记录

## 目标

当 HR 主动联系用户（`hr_conversations.job_id` 为 NULL 且 `applications` 表里没有该公司的记录）时，自动在 `applications` 表创建一条 stub 记录，使这类会话在 Jobs Dashboard 可见并参与状态流转。

## 背景

当前 `sync_statuses_from_hr_conversations()` 在 `tracker.py` 中，当找不到匹配的 application 时直接 `continue`。HR 主动联系的会话因此在 Jobs 页面完全不可见。

需要覆盖的查找链：
1. 先按 `conv.job_id` 查 applications（精确匹配）
2. 再按 `conv.company` 查 applications（`find_application_by_company`）
3. 两者都找不到 → 认定为 HR 主动，创建 stub

已有相关方法：`find_application_by_company(company)`、`upsert(record)`、`update_status()`

## 实现要求

### 1. `code/services/tracker.py`

新增方法 `create_stub_from_hr_conversation(conv: HRConversation) -> str`：

```python
def create_stub_from_hr_conversation(self, conv: HRConversation) -> str:
    """为 HR 主动发起的会话创建一条 stub application 记录。

    - job_id = "hr_{conv.conv_id}"（hr_ 前缀区分真实投递，不会与 Boss直聘 原生 ID 冲突）
    - title  = "[HR主动] {conv.company}"
    - status = RESPONDED（HR 已经联系，直接进入该状态）
    - applied_at = None（未投递）
    - responded_at = conv.last_synced

    创建后回写 hr_conversations.job_id，使下次 sync 可直接通过 job_id 找到。
    幂等：若已存在则直接返回，不覆盖。
    返回 job_id。
    """
```

具体实现步骤：
1. `job_id = f"hr_{conv.conv_id}"`
2. 若 `self.exists(job_id)` → 直接返回 `job_id`
3. 构造 `ApplicationRecord`（status=RESPONDED, applied_at=None, responded_at=conv.last_synced, apply_attempted=False）
4. `self.upsert(record)`
5. 在同一事务内执行 `UPDATE hr_conversations SET job_id = ? WHERE conv_id = ?`（回写 job_id）
6. 记录 logger.info
7. 返回 `job_id`

修改方法 `sync_statuses_from_hr_conversations(self) -> int`：

在"两次查找都找不到 record"时，增加以下逻辑（在 `if record is None: continue` 之前）：

```python
# HR-initiated: no matching application exists
if conv.last_msg_from == "hr":
    stub_id = self.create_stub_from_hr_conversation(conv)
    record = self.get(stub_id)
if record is None:
    continue
```

注意：stub 初始状态已是 RESPONDED，下方的 RESPONDED/RESUME_REQUESTED 升级逻辑仍正常运行（若 stage 已经是 resume_sent，同次 sync 就会升级到 RESUME_REQUESTED）。

### 2. 无需修改其他文件

`check_responses.py` 已在 Phase 2b 调用 `sync_statuses_from_hr_conversations()`，无需额外改动。`Jobs.tsx` 已能显示 RESPONDED 状态，stub 记录会自然出现在 Jobs 页面。

## 验收标准

- [ ] `create_stub_from_hr_conversation` 方法存在，签名正确，有 docstring
- [ ] 幂等：对同一 conv_id 调用两次只创建一条记录，第二次直接返回
- [ ] 创建后 `hr_conversations.job_id` 被更新为 `"hr_{conv_id}"`
- [ ] `sync_statuses_from_hr_conversations` 在 record 为 None 时，若 `last_msg_from == "hr"` 则创建 stub 并继续处理（不直接 continue）
- [ ] stub 的 status 为 RESPONDED，applied_at 为 None，responded_at 为 conv.last_synced
- [ ] 若 conv.last_msg_from != "hr"（系统消息等），不创建 stub
- [ ] 现有测试通过（`pytest code/tests/`），无回归
