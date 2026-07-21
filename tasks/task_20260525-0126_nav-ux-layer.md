# Task: 使用层 + 前端 — 跳转按钮 URL 导航 + UI 反馈

## Goal
让"↗ 跳转"按钮真正可用：`navigate_to_conversation` 优先用已存的 `boss_conv_id` 直接 URL 导航（~2-3 秒），修复 `open-in-browser` 端点无浏览器时的自动开启行为，并给前端按钮添加 loading/disabled 状态和错误展示。

## Background

**依赖**：本 task 依赖 `task_20260525-0126_nav-data-layer` 已完成——`hr_conversations` 表已有 `boss_conv_id` 列，`HRConversation` 对象已有 `boss_conv_id` 属性。

当前问题：
1. `navigate_to_conversation`（`services/browser_agent.py`）只能扫描列表 + 按位置点击（最坏 40-50 秒）。应该优先用 `boss_conv_id` 直接 `page.get(url)` 导航。
2. `open-in-browser` 端点（`dashboard/server.py`）在 `login_agent` 为 None 时自动新建 BrowserAgent + 启动 Chrome，耗时 10-30 秒，无用户提示。应改为直接返回 400 错误。
3. `Dashboard.tsx` `handleOpenInBrowser` 的 `catch {}` 是空的，所有错误静默丢弃，按钮无 loading 状态。
4. `Chat.tsx` `handleOpenInBrowser` 无 loading 状态（有错误展示但按钮不 disabled）。

相关文件：
- `services/browser_agent.py`：`navigate_to_conversation` 方法（~line 1523）
- `dashboard/server.py`：`open_conversation_in_browser` 函数
- `dashboard/frontend/src/pages/Dashboard.tsx`：`ReplyApprovalCard` 组件
- `dashboard/frontend/src/pages/Chat.tsx`：`handleOpenInBrowser` + 跳转按钮

## Implementation Requirements

### 1. `services/browser_agent.py` — `navigate_to_conversation` URL 优先

将方法签名改为：
```python
def navigate_to_conversation(self, conv_id: str, hr_name: str, company: str, boss_conv_id: str = "") -> bool:
```

在 `ensure_browser_alive()` 之后、现有导航逻辑之前，插入快速路径：
```python
if boss_conv_id:
    self.ensure_browser_alive()
    page = self._require_page()
    self._assert_logged_in(page)
    page.get(f"{self.BASE_URL}/web/geek/chat?conversationId={boss_conv_id}", timeout=30)
    self._human_pause(1.5, 2.5)
    logger.info("navigate_to_conversation: direct URL for conv_id=%s boss_conv_id=%s", conv_id, boss_conv_id)
    return True
```
若 `boss_conv_id` 为空，继续执行现有的扫描+点击 fallback 逻辑（不改动）。

### 2. `dashboard/server.py` — `open_conversation_in_browser` 端点

当前实现在 `login_agent` 为 None 时自动创建新 BrowserAgent。改为：

```python
existing: Any = getattr(app.state, "login_agent", None)
if existing is None:
    return JSONResponse(
        {"ok": False, "error": "请先在“环境配置”页面打开自动浏览器"},
        status_code=400,
    )
```

lambda 里传入 `boss_conv_id`：
```python
boss_cid = getattr(conv, "boss_conv_id", "") or ""
found = await loop.run_in_executor(
    None,
    lambda: existing.navigate_to_conversation(
        conv.conv_id, conv.hr_name, conv.company, boss_cid
    ),
)
```

删除原有的"新建 BrowserAgent + agent.start() + app.state.login_agent = agent"分支。

### 3. `dashboard/frontend/src/pages/Dashboard.tsx` — loading + error state

在 `ReplyApprovalCard` 组件的现有 state 声明附近（`useState` 调用区）新增：
```tsx
const [openingId, setOpeningId] = useState<string | null>(null)
const [openError, setOpenError] = useState<string | null>(null)
```

将 `handleOpenInBrowser` 改为：
```tsx
const handleOpenInBrowser = async (convId: string) => {
  setOpeningId(convId)
  setOpenError(null)
  try {
    await API.openInBrowser(convId)
  } catch (e) {
    setOpenError((e as Error).message)
  } finally {
    setOpeningId(null)
  }
}
```

跳转按钮改为（注意：CJK 必须用 `\uXXXX` escape，不能用裸中文）：
```tsx
<button
  type="button"
  onClick={() => void handleOpenInBrowser(item.conv_id)}
  disabled={openingId === item.conv_id}
  className="rounded-lg px-2.5 py-1 text-xs text-text-2 transition hover:text-text-1 disabled:opacity-50 disabled:cursor-not-allowed"
  style={{ background: 'rgba(255,255,255,0.07)' }}
>
  {openingId === item.conv_id ? '跳转中…' : '↗ 跳转'}
</button>
```

在卡片列表下方、`</section>` 前，显示错误（CJK 用 escape）：
```tsx
{openError && (
  <p className="mt-2 text-xs" style={{ color: '#f87171' }}>{openError}</p>
)}
```

### 4. `dashboard/frontend/src/pages/Chat.tsx` — loading state

在现有 state 声明区（`editingReply`、`draftText` 附近）新增：
```tsx
const [openingBrowser, setOpeningBrowser] = useState(false)
```

将 `handleOpenInBrowser` 改为：
```tsx
const handleOpenInBrowser = async () => {
  if (!selected) return
  setOpeningBrowser(true)
  try {
    await API.openInBrowser(selected.conv_id)
  } catch (e) {
    setError((e as Error).message)
  } finally {
    setOpeningBrowser(false)
  }
}
```

跳转按钮改为（CJK 用 `\uXXXX` escape）：
```tsx
<button
  type="button"
  onClick={() => void handleOpenInBrowser()}
  disabled={openingBrowser}
  className="rounded-lg px-2.5 py-1 text-xs text-text-2 transition hover:text-text-1 disabled:opacity-50 disabled:cursor-not-allowed"
  style={{ background: 'rgba(255,255,255,0.07)' }}
  title={'在自动浏览器中打开该会话'}
>
  {openingBrowser ? '跳转中…' : '↗ 跳转'}
</button>
```

## Acceptance Criteria
- [ ] `navigate_to_conversation` 在 `boss_conv_id` 非空时直接 URL 导航，不进入扫描循环
- [ ] `navigate_to_conversation` 在 `boss_conv_id` 为空时仍走原有扫描+点击 fallback（不破坏）
- [ ] `open-in-browser` 端点在 `login_agent=None` 时立即返回 400，不尝试开启新浏览器
- [ ] Dashboard 跳转按钮：点击后变灰并显示"跳转中…"，请求完成后恢复；失败时在面板下方显示红色错误文字
- [ ] Chat 跳转按钮：点击后变灰并显示"跳转中…"，请求完成后恢复；失败时在页面错误区显示
- [ ] 前端所有 CJK 文字均使用 `\uXXXX` escape，不含裸中文字符
- [ ] `pytest tests/` 全部通过
- [ ] `npm run build` 成功，版本号自动递增
