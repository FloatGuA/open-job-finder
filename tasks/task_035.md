# Task 035 — W2 Browser Tools

## Goal
从 browser_agent.py 中拆分出 9 个 W2 专用 BrowserTool，每个继承 BaseTool，在 ToolRegistry 中注册。

## Background
W2（聊天管理）的浏览器操作与 W1 完全独立。本 Task 将 W2 相关操作（导航聊天列表、读取消息、发送消息、发简历）抽取为独立 Tool 类。

ExtractConversationList 需要提取 hr_title（HR 自身职位，如"HR经理"），这是新 schema 中 conv_id hash 的必需字段。现有代码可能没有提取这个字段，需要补充对应的 DOM 读取逻辑。

依赖：T031（BaseTool / ToolResult / ToolRegistry）。

## Implementation Requirements

### 目录结构

```
code/tools/browser/
└── w2/
    ├── __init__.py
    ├── navigate_to_chat_list.py
    ├── extract_conversation_list.py
    ├── scroll_chat_list.py
    ├── navigate_to_conversation.py
    ├── read_messages.py
    ├── send_chat_message.py
    ├── accept_resume_card.py
    ├── click_toolbar_send_resume.py
    └── upload_resume_file.py
```

### 各 Tool 规格

参照 design/tools_catalog.md「BrowserTools — W2 专用」章节。

**NavigateToChatList**
- Input: 无
- 导航到 `/web/geek/chat`，等待列表容器出现
- ToolResult.data: `{}`（成功与否在 ok 字段）

**ExtractConversationList**
- Input: 无
- 提取当前可见会话列表
- Output items 含：hr_name / hr_title / company / last_msg_preview / boss_conv_id / has_unread / last_msg_time_raw
- `hr_title`：HR 自身职位，从聊天列表左侧直接读取（不点开会话）。若 DOM 中无此字段则为空字符串
- ToolResult.data: `{"item_count": int}`

**ScrollChatList**
- Input: seen_conv_ids: List[str]
- 向下滚动虚拟滚动列表
- ToolResult.data: `{"reached_end": bool}`

**NavigateToConversation**
- Input: conv_id: str, company: str, hr_name: str, boss_conv_id: str
- 优先用 boss_conv_id 直接 URL 跳转，空时走原子 JS 点击（scrollIntoView + click 同一 JS 调用，防 DOM 漂移）
- ToolResult.data: `{"method": str, "boss_conv_id_confirmed": str}`

**ReadMessages**
- Input: 无
- 读取当前会话所有消息气泡
- ToolResult.data: `{"message_count": int}`（消息内容不写日志）
- ToolResult 额外返回 messages 列表供 Pipeline 使用

**SendChatMessage**
- Input: text: str
- 输入文本并发送（正确键盘 API：page.actions.key_down('Enter').key_up('Enter')）
- ToolResult.data: `{}`

**AcceptResumeCard**
- Input: 无
- 点击 HR 发的简历交换卡片"同意"按钮，内联处理跨境弹窗
- ToolResult.data: `{"card_found": bool, "cross_border_dialog": bool}`

**ClickToolbarSendResume**
- Input: 无
- 点击 toolbar"发简历"按钮
- ToolResult.data: `{"button_found": bool, "button_enabled": bool}`

**UploadResumeFile**
- Input: resume_path: str
- 通过文件上传控件发送 PDF
- ToolResult.data: `{}`

### ToolRegistry 注册

提供 `register_w2_browser_tools(registry, browser)` 函数。

### 已知踩坑（必读）

- **键盘 API**：DrissionPage 4.1.x 中 ChromiumElement 和 ChromiumPage 均无 `.key` 属性。唯一正确入口：`page.actions.key_down('Enter').key_up('Enter')`
- **虚拟滚动 DOM 漂移**：ScrollChatList 和 NavigateToConversation 的 JS 点击必须在同一次 JS 调用内完成 scrollIntoView + click，不能分两步
- **boss_conv_id 确认**：NavigateToConversation 成功后从当前 URL 提取 boss_conv_id 作为 confirmed 值

## Acceptance Criteria

- [ ] 每个 Tool 可通过 `registry.call(name, ...)` 调用，返回 ToolResult
- [ ] ExtractConversationList 输出的 items 包含 hr_title 字段（可为空字符串）
- [ ] NavigateToConversation 在 boss_conv_id 非空时使用 URL 直跳，method="url_direct"
- [ ] SendChatMessage 使用 page.actions 发送，不使用 .key 属性
- [ ] 所有 Tool 在 browser=None 时返回 ok=False + error，不抛异常

## Reference
- design/tools_catalog.md（BrowserTools W2 专用 — 输入输出契约）
- design/logging.md（Trace Tool data 规格 W2 BrowserTools 表格）
- code/services/browser_agent.py（现有实现，特别是 scan_chat_list / sync_conversations / _send_chat_message / _send_resume_in_current_chat）
- TECHNICAL.md Known Pitfalls（DrissionPage 键盘 API 和虚拟滚动踩坑记录）
