# Task 015 — 验证并修复 `_send_chat_message` 聊天输入框选择器

## 背景

`BrowserAgent._send_chat_message(text)` 方法用于在当前打开的 Boss直聘 会话中发送一条文本消息，目的是在无"我方"历史消息时先打招呼，解锁"发简历"工具栏按钮（该按钮要求双方都回复过才可用）。

该方法目前使用以下候选选择器（按优先级）：
1. `css:.input-area div[contenteditable='true']`
2. `css:.chat-input div[contenteditable='true']`
3. `css:div[contenteditable='true']`（全局 fallback）

以及发送按钮：`css:button[d-c='62013']`（发送按钮由调试确认的稳定 `d-c` 属性）

**这些选择器未经真实 DOM 验证。** 需要通过调试脚本 dump 真实 HTML 后确认或修正。

---

## 目标

1. 新建调试脚本 `code/debug_chat_input.py`：
   - 复用 `BrowserAgent` 的浏览器 session，导航到 `/web/geek/chat`
   - 点击第一个会话（`document.querySelectorAll('.friend-content-warp')[0].click()`）
   - 等待 2s 后，用 JS 提取聊天输入区域的 HTML：
     - 先尝试 `.input-area`、`.chat-input`、`.chat-op` 的父节点
     - 若都不存在，dump 所有 `contenteditable` 元素的 outerHTML
   - 将结果写入 `code/debug_chat_input.txt`

2. 运行脚本（假设浏览器已打开，session 有效），读取 `debug_chat_input.txt`

3. 根据 dump 结果，**更新 `_send_chat_message` 中的选择器**，确保至少一个候选选择器能命中真实输入框。若全局 `div[contenteditable='true']` 能命中且唯一，则保留为 fallback 即可。

4. 在调试脚本中增加一段"真实发送测试"（可用 `DRY_RUN = True` flag 控制）：
   - `DRY_RUN = True`（默认）：只 dump DOM，不实际发送
   - `DRY_RUN = False`：调用 `browser_agent._send_chat_message("您好，测试消息，请忽略。")` 并检查返回值

---

## 验收标准

1. `debug_chat_input.py` 可执行，将聊天输入区 HTML 写入 `debug_chat_input.txt`
2. `_send_chat_message` 中至少有一个选择器经 DOM 验证可用（注释说明哪个是验证过的）
3. 脚本中有 `DRY_RUN` flag，`DRY_RUN=False` 时实际调用 `_send_chat_message`

---

## 文件范围

- 新建：`code/debug_chat_input.py`
- 修改（如需）：`code/services/browser_agent.py` → `_send_chat_message` 方法的选择器部分

---

## 注意事项

- 调试脚本复用 `BrowserAgent` 初始化流程（`data/session.json`），不重新登录
- 若浏览器未打开，脚本应给出清晰错误提示（`BrowserAgent._require_page()` 会自动处理）
- 选择器修改后不改变方法的整体逻辑和接口
- 不要修改任何测试文件
