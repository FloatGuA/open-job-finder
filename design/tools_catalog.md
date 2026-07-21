# Tools Catalog

设计原则：Tool 是最小可复用的原子能力，无 pipeline 概念，做且只做一件事。
四类：BrowserTool（单次 IO）、LLMTool（单次推理）、DBTool（单次持久化读写）、BusinessLogicTool（纯函数，无 IO）。

**删减说明**：以下 Tool 在此次重构中不实现：
- **CritiqueJob**：Critic 二次审核砍掉
- **GenerateResume**：简历定制生成砍掉
- **UpdateApplicationStatus**：status 更新统一走 UpsertApplication，独立方法删除

---

## BrowserTools — W1 专用

### NavigateSearchUrl
**目的**：打开 Boss直聘 职位搜索页，加载第一屏结果。
```json
Input:  { "url": "string" }
Output: { "ok": "bool", "loaded_url": "string", "error": "string|null" }
```

### ExtractCardList
**目的**：从当前搜索页提取所有可见职位卡片的基本信息，不做任何点击。
```json
Input:  {}
Output: {
  "cards": [{
    "job_id": "string",
    "title": "string",
    "company": "string",
    "salary": "string  // 原始文本，含 PUA 字符",
    "city": "string",
    "hr_name": "string",
    "card_dom_index": "int"
  }],
  "has_more": "bool"
}
```

### ScrollSearchResults
**目的**：向下滚动搜索结果页触发懒加载，等待新卡片出现。
```json
Input:  { "current_card_count": "int" }
Output: { "ok": "bool", "new_card_count": "int", "reached_end": "bool" }
```

### ClickCardOpenPanel
**目的**：点击搜索结果中指定卡片，等待右侧 JD 面板加载完成。
```json
Input:  { "card_dom_index": "int", "job_id": "string" }
Output: { "ok": "bool", "panel_loaded": "bool", "error": "string|null" }
```

### ReadPanelJD
**目的**：从已打开的右侧面板中提取完整 JD 文本及原始薪资字符串（不做解码，解码由 DecodeJobSalary 完成）。
```json
Input:  {}
Output: { "ok": "bool", "jd_text": "string", "salary_raw": "string", "error": "string|null" }
```

### ClickApplyButton
**目的**：点击面板内的"立即沟通"按钮发起投递。
```json
Input:  { "dry_run": "bool" }
Output: {
  "ok": "bool",
  "result": "string  // applied | already_chatting | button_not_found | dialog_blocked | rate_limited",
  "error": "string|null"
}
```

### HandleApplyDialog
**目的**：投递后关闭"已向 BOSS 发送消息"弹窗，等待 DOM 元素完全消失，防止下一张卡片假阳性检测。
```json
Input:  { "action": "string  // close_and_wait | check_only" }
Output: { "ok": "bool", "dialog_was_present": "bool", "dialog_closed": "bool", "error": "string|null" }
```

---

## BrowserTools — W2 专用

### NavigateToChatList
**目的**：从任意页面导航到 Boss直聘 聊天列表页 `/web/geek/chat`，等待列表容器出现。
```json
Input:  {}
Output: { "ok": "bool", "error": "string|null" }
```

### ExtractConversationList
**目的**：从当前可见的聊天列表中提取所有会话项基本信息，不点击任何会话。
```json
Input:  {}
Output: {
  "items": [{
    "hr_name": "string",
    "hr_title": "string  // HR自身职位，如'HR经理'，从左侧列表直接读取（用于 conv_id hash）",
    "company": "string",
    "last_msg_preview": "string",
    "boss_conv_id": "string  // d-c 属性值，可能为空",
    "has_unread": "bool",
    "last_msg_time_raw": "string  // 如 '昨天'、'10:23'"
  }]
}
```

### ScrollChatList
**目的**：向下滚动虚拟滚动聊天列表，触发更多会话加载。
```json
Input:  { "seen_conv_ids": ["string"] }
Output: { "ok": "bool", "reached_end": "bool" }
```

### NavigateToConversation
**目的**：定位并打开指定会话。优先用 boss_conv_id 直接 URL 跳转；无时通过公司名在列表中做原子 JS 点击（scrollIntoView + click 在同一 JS 调用内，防止虚拟滚动 DOM 漂移）。
```json
Input: {
  "conv_id": "string",
  "company": "string",
  "hr_name": "string",
  "boss_conv_id": "string  // 非空时直接构造 URL 跳转，空时走滚动查找"
}
Output: {
  "ok": "bool",
  "boss_conv_id_confirmed": "string  // 跳转后从 URL 提取",
  "method": "string  // url_direct | scroll_click",
  "error": "string|null"
}
```

### ReadMessages
**目的**：读取当前已打开会话中的所有消息气泡，识别发送方和内容。
```json
Input:  {}
Output: {
  "ok": "bool",
  "messages": [{ "sender": "string  // hr|me|system", "text": "string", "time": "string" }],
  "error": "string|null"
}
```

### SendChatMessage
**目的**：在当前会话的输入框中输入文本并发送（用于打招呼或发送已批准回复）。
```json
Input:  { "text": "string" }
Output: { "ok": "bool", "error": "string|null" }
```

### AcceptResumeCard
**目的**：策略①——点击会话中 HR 发送的简历交换请求卡片上的"同意"按钮。若出现境外公司跨境数据同意弹窗，在此 Tool 内内联处理并确认。
```json
Input:  {}
Output: {
  "ok": "bool",
  "card_found": "bool",
  "cross_border_dialog": "bool  // 是否出现并处理了跨境弹窗",
  "error": "string|null"
}
```

### ClickToolbarSendResume
**目的**：策略②——点击聊天 toolbar 中的"发简历"按钮（需双方都有回复后才解锁）。
```json
Input:  {}
Output: { "ok": "bool", "button_found": "bool", "button_enabled": "bool", "error": "string|null" }
```

### UploadResumeFile
**目的**：策略③——通过文件上传控件发送本地 PDF 简历文件作为附件。
```json
Input:  { "resume_path": "string  // 本地 PDF 绝对路径" }
Output: { "ok": "bool", "error": "string|null" }
```

---

## LLMTools

### ScoreJob
**目的**：调用 LLM 按五个维度独立打分，Python 端加权求和得最终分，LLM 同时输出一句话总结供人工复查。
```json
Input: {
  "job_id": "string",
  "title": "string",
  "company": "string",
  "jd_text": "string",
  "profile": { "keywords": ["string"], "cities": ["string"], "experience": ["string"], "salary": "string" }
}
Output: {
  "ok": "bool",
  "score": "int  // 0-100，Python 加权计算",
  "dimensions": {
    "skill_match": "int  // 0-100",
    "experience_match": "int  // 0-100",
    "city_match": "int  // 0-100",
    "salary_match": "int  // 0-100",
    "growth_potential": "int  // 0-100"
  },
  "reason": "string  // 一句话综合说明，解释各维度评分的主要依据",
  "provider_used": "string",
  "error": "string|null"
}
```

### AnalyzeHRIntent
**目的**：分析 HR 最近发送的消息，判断意图类别，决定是否需要回复及建议回复内容。
```json
Input: {
  "conv_id": "string",
  "messages": [{ "sender": "string", "text": "string", "time": "string" }],
  "company": "string",
  "job_title": "string|null"
}
Output: {
  "ok": "bool",
  "intent": "string  // interview_invite | offer | rejection | resume_request | general | unknown",
  "confidence": "string  // high | medium | low",
  "needs_reply": "bool",
  "suggested_reply": "string|null",
  "error": "string|null"
}
```

---

## DBTools

### ClassifyJobForW1
**目的**：查询 DB，判断该职位在 W1 里应走什么路径：全流程 / 跳过评分直接投递 / 跳过。
```json
Input:  { "job_id": "string" }
Output: { "action": "string  // full_pipeline | apply_only | skip", "reason": "string" }
```

### UpsertApplication
**目的**：创建或更新 applications 表中的投递记录。
```json
Input: {
  "job_id": "string", "title": "string", "company": "string", "hr_name": "string",
  "url": "string", "status": "string", "city": "string|null", "salary": "string|null",
  "score": "int|null", "applied_at": "string|null"
}
Output: { "ok": "bool", "error": "string|null" }
```

### UpsertHRConversation
**目的**：创建或更新 hr_conversations 表，保留 stage 只升不降约束。写入会话结构字段，分析字段（intent/reply_text/reply_status）由 UpdateHRAnalysis 单独更新。
```json
Input: {
  "conv_id": "string", "hr_name": "string", "company": "string",
  "job_id": "string|null", "stage": "string", "boss_conv_id": "string|null",
  "last_msg_preview": "string"
}
Output: { "ok": "bool", "stage_changed": "bool", "error": "string|null" }
```

### WriteHRMessages
**目的**：将本次读取的消息列表写入 hr_messages 表，跳过已存在的重复记录。
```json
Input: {
  "conv_id": "string",
  "messages": [{ "sender": "string", "text": "string", "time": "string" }]
}
Output: { "ok": "bool", "inserted_count": "int", "error": "string|null" }
```

### UpdateHRAnalysis
**目的**：将 LLM 分析结果写入 hr_conversations（intent、reply_text、reply_status），CASE 保护已终态字段不被覆写（approved 状态不降为 pending）。
```json
Input: {
  "conv_id": "string",
  "intent": "string",
  "reply_text": "string|null",
  "reply_status": "string|null  // pending | null（approved 由用户通过 Dashboard 设置，此 Tool 不写）"
}
Output: { "ok": "bool", "error": "string|null" }
```

### GetApprovedReplies
**目的**：查询所有 reply_status = 'approved' 的会话，供 W2 ScanStep 标记必须发送回复的会话。
```json
Input:  {}
Output: {
  "conversations": [{
    "conv_id": "string", "hr_name": "string", "company": "string",
    "reply_text": "string", "boss_conv_id": "string|null"
  }]
}
```

### GetConversationStates
**目的**：批量查询 DB，返回指定 conv_id 列表的当前 last_msg_preview 和 stage，供 ScanStep 脏检查对比使用。
```json
Input:  { "conv_ids": ["string"] }
Output: {
  "states": {
    "{conv_id}": {
      "last_msg_preview": "string",
      "stage": "string"
    }
  }
}
```

### SyncApplicationStatusFromConversations
**目的**：根据 hr_conversations.stage 批量更新 applications.status（W2Pipeline 级别，所有会话处理完后执行一次）。
```json
Input:  {}
Output: { "ok": "bool", "updated_count": "int", "error": "string|null" }
```

### MarkTimeoutRejections
**目的**：扫描 DB，同时处理两类超时记录：
1. applications：`no_response_days` 天内无 HR 回应 → status 更新为 REJECTED
2. hr_conversations：`stale_conv_days` 天内无活动 → stage 更新为 closed

名称仅覆盖第一类含义，实现时需注意两类均须处理。
```json
Input:  { "no_response_days": "int", "stale_conv_days": "int" }
Output: {
  "ok": "bool",
  "no_response_rejected": ["string  // job_id"],
  "stale_closed": ["string  // conv_id"],
  "error": "string|null"
}
```

---

## BusinessLogicTools（纯函数，无 IO）

### DetectResumeRequest
**目的**：分析消息列表，判断 HR 是否明确请求发送附件简历，并检查之后是否已经发过（防重复发送）。
```json
Input: {
  "messages": [{ "sender": "string", "text": "string" }]
}
Output: {
  "needs_resume": "bool",
  "request_type": "string|null  // system_notification | hr_card | hr_text | null",
  "already_sent": "bool"
}
```

### DecodeJobSalary
**目的**：将 Boss直聘 薪资字段中的 PUA Unicode 私用区字符（–）解码还原为正常数字字符串。
```json
Input:  { "raw_salary": "string" }
Output: { "decoded_salary": "string" }
```

### FilterConversations
**目的**：根据当前扫描结果、DB 存储状态、已批准回复列表，过滤出本次需要进入 ConversationPipeline 的会话列表（纯函数，ScanStep 内部调用）。

过滤规则：
```
先排除（满足任意一条 → 跳过）：
  - stage IN ('closed', 'offer')    ← 终态，永不处理
再进入（排除后满足任意一条 → 进入处理）：
  - has_unread == True
  - conv_id 在 approved_reply_ids 中
  - stored last_msg_preview != current last_msg_preview
```

```json
Input: {
  "current_convs": [{
    "conv_id": "string",
    "has_unread": "bool",
    "last_msg_preview": "string"
  }],
  "stored_states": {
    "{conv_id}": { "last_msg_preview": "string", "stage": "string" }
  },
  "approved_reply_ids": ["string"]
}
Output: {
  "conversations_to_process": [{
    "conv_id": "string",
    "has_unread": "bool",
    "last_msg_preview": "string"
  }]
}
```
