# Task 016 — 修复登录态检测：补充 `/web/user/` 重定向识别

## 背景

`BrowserAgent._assert_logged_in(page)` 负责在每个主要操作前验证 Boss直聘 session 是否有效，失效时抛出 `SessionExpiredError`。当前检测逻辑：

1. URL 包含 `"login"` → 抛出
2. 页面正文不含 `"退出"` 或 `"个人中心"` → 抛出

**已知漏洞**：当 session 过期时，Boss直聘 将 `/web/geek/chat`、`/web/geek/job-recommend` 等页面重定向到 `/web/user/`（用户中心/选择登录方式页）。该 URL 不含 `"login"` 关键词，且该页面可能包含 `"个人中心"` 文字（作为 tab 标签），导致两项检测均无法捕获，系统静默失败。

调试实测：session 过期后导航到 `/web/geek/chat`，实际落地 URL 为 `https://www.zhipin.com/web/user/`，`_assert_logged_in` 未抛出异常，流程以空状态继续运行。

---

## 目标

修复 `_assert_logged_in`，使其能可靠检测 session 过期的所有常见情形。

### 具体改动

**`code/services/browser_agent.py` → `_assert_logged_in`**

在现有两项检测之前，增加一项"目标路径 vs 当前路径"检测：

- 在调用 `_assert_logged_in` 之前，通常已经导航到目标页（如 `/web/geek/chat`），若实际落地 URL 包含 `/web/user/`，则视为未登录重定向
- 另外，检测 `"/web/user/"` 在当前 URL 中的存在，作为第一项显式检查

修改后检测顺序：
1. URL 包含 `"/web/user/"` → 抛出（新增）
2. URL 包含 `"login"` → 抛出（保留）
3. 页面正文不含 `"退出"` 或 `"个人中心"` → 抛出（保留）

**`code/services/exceptions.py`（如需）**

确认 `SessionExpiredError` 错误消息包含"请运行 `python main.py --onboarding` 重新登录"的提示。若消息已含此提示则不改。

---

## 验收标准

1. `_assert_logged_in` 在 URL 为 `https://www.zhipin.com/web/user/` 时抛出 `SessionExpiredError`
2. 错误消息中包含重新登录的操作提示（`--onboarding`）
3. 原有检测逻辑（URL 含 `"login"`、页面不含正向指示词）保留不变
4. 不改变任何调用方的代码（调用方已正确处理 `SessionExpiredError`）

---

## 文件范围

- 修改：`code/services/browser_agent.py` → `_assert_logged_in` 方法
- 可选修改：`code/services/exceptions.py` → `SessionExpiredError` 消息（若消息不够明确）

---

## 注意事项

- 不要修改任何测试文件
- 不要修改调用方（`orchestrator.py`、`scheduler.py`、`tools/`）
- 改动范围极小（仅 `_assert_logged_in` 方法内部），不引入新依赖
