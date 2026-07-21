# Task 034 — W1 Browser Tools

## Goal
从 browser_agent.py 中拆分出 7 个 W1 专用 BrowserTool，每个继承 BaseTool，在 ToolRegistry 中注册。

## Background
现有 `code/services/browser_agent.py` 是一个巨型类，包含 W1（搜索投递）和 W2（聊天管理）的所有操作。本 Task 将 W1 相关操作抽取为独立 Tool 类，注入共享的 DrissionPage browser 实例，每个 Tool 只做一件原子操作。

依赖：T031（BaseTool / ToolResult / ToolRegistry 已定义）。

## Implementation Requirements

### 目录结构

```
code/tools/browser/
├── __init__.py
└── w1/
    ├── __init__.py
    ├── navigate_search_url.py
    ├── extract_card_list.py
    ├── scroll_search_results.py
    ├── click_card_open_panel.py
    ├── read_panel_jd.py
    ├── click_apply_button.py
    └── handle_apply_dialog.py
```

### 各 Tool 规格

参照 design/tools_catalog.md「BrowserTools — W1 专用」章节。每个 Tool：
- 继承 BaseTool
- `name` = snake_case 名称（如 `navigate_search_url`）
- `description` = 一句话说明
- `execute(**kwargs)` 接受 Input 字段，返回 ToolResult，`data` 字段严格对照 design/logging.md「W1 BrowserTools」表格

**NavigateSearchUrl**
- Input: url: str
- execute 调用 DrissionPage 打开 URL，等待页面稳定
- ToolResult.data: `{"loaded_url": str}`

**ExtractCardList**
- Input: 无
- 从当前搜索页提取所有可见卡片（job_id / title / company / salary / city / hr_name / card_dom_index）
- ToolResult.data: `{"card_count": int}`
- ToolResult.ok 的 data 另含 `cards` 列表（Pipeline 使用，不写入日志）

**ScrollSearchResults**
- Input: current_card_count: int
- 向下滚动，等待新卡片出现
- ToolResult.data: `{"new_card_count": int, "reached_end": bool}`

**ClickCardOpenPanel**
- Input: card_dom_index: int, job_id: str
- 点击卡片，等待右侧 JD 面板加载
- ToolResult.data: `{"panel_loaded": bool}`

**ReadPanelJD**
- Input: 无
- 从已打开面板读取 jd_text 和 salary_raw（不做解码）
- ToolResult.data: `{"salary_raw": str}`（jd_text 过大不写日志）
- ToolResult 的 data 额外返回 jd_text 供 Pipeline 使用（只是不写日志）

**ClickApplyButton**
- Input: dry_run: bool
- 点击"立即沟通"按钮
- ToolResult.data: `{"result": str}` 枚举值：applied / already_chatting / button_not_found / dialog_blocked / rate_limited

**HandleApplyDialog**
- Input: action: str（"close_and_wait" | "check_only"）
- 处理投递后弹窗
- ToolResult.data: `{"dialog_was_present": bool, "dialog_closed": bool}`

### ToolRegistry 注册

在 `code/tools/registry.py` 或新建的 `code/tools/browser/w1/__init__.py` 中提供 `register_w1_browser_tools(registry, browser)` 函数，批量注册 7 个 Tool。

### 现有逻辑迁移

读懂 browser_agent.py 中对应方法（search_with_panel / extract_cards / click_card 等），理解现有 DrissionPage 选择器和等待逻辑后，在新 Tool 中重写。不要 import 旧 BrowserAgent 类，直接使用注入的 browser 实例（DrissionPage ChromiumPage 对象）。

## Acceptance Criteria

- [ ] 每个 Tool 可通过 `registry.call("navigate_search_url", url="...")` 调用，返回 ToolResult
- [ ] ToolResult.ok = True 时 data 字段包含 design/logging.md 规定的字段
- [ ] ToolResult.ok = False 时 data 为 `{}`，error 字段为错误描述字符串
- [ ] ClickApplyButton 在 dry_run=True 时不做真实点击，返回 result="dry_run"
- [ ] 所有 Tool 在 browser 为 None（未初始化）时返回 ok=False + 有意义的 error，不抛异常

## Reference
- design/tools_catalog.md（BrowserTools W1 专用 — 输入输出契约）
- design/logging.md（Trace Tool data 规格 W1 BrowserTools 表格）
- code/services/browser_agent.py（现有实现，理解后重写）
- code/tools/base.py（T031 产出，BaseTool 定义）
