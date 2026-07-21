# 浏览器会话收敛 · Tutorial

> 配套改动：commit `ea4f31f`（Phase 1）。本文用"验证 session"这个真实痛点，讲清**为什么会误报"session 过期"**、**收敛到底改了什么**、以及由此固化的**分层规则**。

---

## 1. 病：同一件事有两份实现，还不同步

这个项目里，"碰浏览器的活儿"长期有**两条平行路径**：

| | 工具化路径（W1/W2 流水线） | 遗留单体 `services/browser_agent.py` |
|---|---|---|
| 开浏览器 | `services/browser_context.py` 的 `open_browser()` | `BrowserAgent.start()` |
| 判断登没登录 | `pipeline/common/verify_session.py` 的 `VerifySessionStep` | `BrowserAgent._assert_logged_in()` |
| 打开某会话 | `tools/browser/w2/navigate_to_conversation.py`（tool） | `BrowserAgent.navigate_to_conversation()` |
| 谁在用 | `w1_runner` / `w2_runner` | `server.py` 的交互端点（open-in-browser / browse-url / 登录）直接手调 |

`open_browser()` 和 `BrowserAgent.start()` 一对比就发现：**stealth JS、`_kill_stale_chrome`、ChromiumOptions、User-Agent 一字不差，是复制出来的两份。** 验证 session、导航会话也各有两份。

**两份实现 = 改一处不同步另一处。** 这就是病根。

---

## 2. 症：session 明明没过期，却弹"session 过期"

`VerifySessionStep`（流水线那份）**之前被加固过**（commit 34971a0）：

```python
# 真过期（跳转到登录页）→ 立刻返回 session_expired，不重试
# 浏览器/页面瞬时故障 → 重试一次，再失败报 verify_error（reason 不为空）
```

但加固**只打在流水线这份**。交互端点用的是另一份 `_assert_logged_in`：

```python
def _assert_logged_in(self, page):
    # URL 跳到 /web/user/ 或含 login，或 body 缺登录指示词 → 直接抛 SessionExpiredError
    # 没有重试，不区分"真过期"和"浏览器抽风"
```

于是用户点"在 Boss 打开"时，真实堆栈是（来自服务端日志）：

```
open_conversation_in_browser
 → BrowserAgent.navigate_to_conversation
   → self._assert_logged_in(page)         # 幼稚那份
     → raise SessionExpiredError          # 一次抽风就抛
→ HTTP 500
```

叠加一个诱因：新开的浏览器若**连上了游离在 9222 端口的别的 Chromium**（两份 `_kill_stale_chrome` 都只杀自己 profile 的进程，清不掉别人的），那就是个未登录的浏览器 → 导航 chat 页跳登录 → `_assert_logged_in` 抛过期。**session 一直是好的，是这条路径自己有问题。**

---

## 3. 治：收敛成"一个浏览器主人 + 一份检查"

新增 `services/browser_session.py`：

```python
class BrowserSession:
    """唯一的交互浏览器主人。"""
    def get_page(self):
        if not self._is_alive():
            self._page = open_browser(self._data_dir, headless=self._headless)  # 复用那一份启动
        return self._page

    def verify(self) -> dict:
        out = VerifySessionStep(self.get_page()).run()                          # 复用那一份加固检查
        ok = out.status == StepStatus.SUCCESSFUL
        return {"ok": ok, "code": "" if ok else (out.error or "verify_error"),
                "reason": out.reason, "username": out.username}
```

端点改成**只接线**，不再内联遗留逻辑：

```python
# 之前（端点内联遗留单体 —— bug 出处）
agent = app.state.login_agent or BrowserAgent(session.json)
agent.start()
agent.navigate_to_conversation(...)         # 旧 navigate + 幼稚 _assert_logged_in

# 之后（委托给 service + 复用 W2 的 tool）
bs = app.state.browser_session
sess = bs.verify()                          # 一份加固检查
if not sess["ok"]:
    return {"ok": False, "code": sess["code"], "error": sess["reason"]}  # 准确文案
page = bs.get_page()
NavigateToChatList(browser=page).execute()                 # 先到聊天列表
NavigateToConversation(browser=page).execute(conv_id, ...) # 与 W2 同一份导航
```

收敛后白得四样东西：

1. **一份 session 检查**：误报从机制上消失——交互路径拿到的就是会重试、会区分"过期 vs 故障"的那份。
2. **修一处全好**：以后再加固 `VerifySessionStep`，W1/W2/按钮/登录同时受益，不再"修了一个漏一个"。
3. **准确文案**：返回 `code=session_expired`（请重登）/ `verify_error`（浏览器故障，重试），前端照实显示，不再一律弹"过期"。
4. **复用 W2 导航**：会话定位用的是刚修过懒加载滚动的那份 tool，不是另一份旧的。

---

## 4. 由此固化的分层规则（"代码该写哪"）

不是"全部塞进 tool"，而是**严格分层**，让新功能有确定的家：

| 层 | 放什么 | 判据 |
|---|---|---|
| `tools/` | 对外部系统的**单个副作用操作**（浏览器/DB/LLM） | "是不是一次碰浏览器/DB/LLM 的活儿" |
| `pipeline/`（step） | 把多个 tool 编排成**工作流的一个阶段** | "是不是某条工作流里的一段" |
| `services/` | 共享基建/单例（BrowserSession、tracker、llm_client、config） | "是不是被多处共用的基建" |
| `server.py` | **只做 HTTP 接线**：解析请求 → 调 tool/step/service → 序列化 | —— |

**一条铁律**：**端点不准内联副作用逻辑，必须委托。** 这次的 bug 正是因为端点内联了遗留 BrowserAgent，而不是调 tool/service。立了这条，"瞎写导致冗余"就被堵死。

> 注意：`step` 是"工作流阶段"，不是"任何复杂的东西"。像"在 Boss 打开会话"这种一次性交互动作，端点直接调 1~2 个 tool 即可，**不需要假 step**。

---

## 5. 验证

- 之前报 `500 SessionExpiredError` 的会话 `73b8fae63255`（跨越速运集团/曾紫霞），改后 `POST /open-in-browser` 返回 `{"ok": true}`。同一 session 状态、同一会话，唯一差别是代码路径。
- pytest 全绿；前端 build 无 tsc 报错（v1.0.9.39）。

---

## 6. 还没做（后续 Phase）

- **Phase 2**：登录/检查 session 端点（openLogin / confirmLogin / checkSession）仍用 `BrowserAgent`，迁到 BrowserSession。
- **Phase 3**：迁移 onboarding 残留依赖，**删掉 `services/browser_agent.py`**。
- **可观测性**：交互端点目前不走 registry，没有 trace/SSE。后续可让 BrowserSession 的操作也产出可观测事件（与流水线的 `log_tool` 同源）。
- **完全单实例**：交互浏览器与流水线浏览器目前仍是两个实例（靠 409 + kill-stale 协调），完全合一会牵出"W1/W2 默认无头 vs 交互要有头"的行为变更，单独排期。
