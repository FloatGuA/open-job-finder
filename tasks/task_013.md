# Task 013 — 增强聊天回复分类 + 附件简历处理流程

## 背景与需求

当前 `check_chat_list()` 只分三类（INTERVIEW / REJECTED / RESPONDED），缺少：

1. **RESUME_REQUESTED**：HR 邀请查看附件简历（"发一下附件简历"、"把简历发过来" 等）
2. **AD_PUSH**：Boss直聘广告推送 / HR 主动发起（我们没有投递记录的对话）
3. **已读不回识别**：投递后 HR 未回复，当前 APPLIED 状态不更新（已是正确行为，不引入
   IGNORED 状态，保持 APPLIED 直到有真实回复）

此外，当 HR 请求附件简历时，需要：
- 检查用户是否已上传附件简历（`data/resume_attachment.pdf`）
- 若存在，在对应聊天窗口发送该文件
- 若不存在，记录警告并引导用户通过 Dashboard 上传

---

## 修改清单

### 1. `schemas.py` — 新增两个 AppStatus 值

```python
class AppStatus(str, Enum):
    # ... 已有值 ...
    RESUME_REQUESTED = "RESUME_REQUESTED"   # HR 请求查看附件简历
    AD_PUSH          = "AD_PUSH"            # Boss直聘广告推送/HR 主动发起（无投递记录）
```

### 2. `services/browser_agent.py` — 重写 `check_chat_list()` + 新增 `send_resume_attachment()`

#### 2a. 抽取消息分类逻辑为私有方法

```python
def _classify_message(self, message: str) -> str:
    """
    根据消息文本判断 HR 回复类型。
    返回值为 AppStatus 的 value 字符串。
    """
    # 附件简历请求关键词
    resume_keywords = [
        "附件简历", "发一下简历", "发简历", "简历发一下",
        "把简历发", "发你的简历", "看看你的简历", "能发一下",
        "发过来", "投递简历",
    ]
    if any(kw in message for kw in resume_keywords):
        return AppStatus.RESUME_REQUESTED.value

    # 面试邀请
    if any(kw in message for kw in ("面试", "约时间", "面谈", "邀请你")):
        return AppStatus.INTERVIEW.value

    # 拒绝
    if any(kw in message for kw in ("不合适", "感谢关注", "暂时", "遗憾", "婉拒", "岗位已满")):
        return AppStatus.REJECTED.value

    return AppStatus.RESPONDED.value
```

#### 2b. 重写 `check_chat_list()`

在已有逻辑基础上：
- 调用 `_classify_message()` 替代内联判断
- 新增 `is_ad_push` 字段到 `StatusUpdate`（当 job_id 为空且公司名不在我们的投递记录时置 True）
- 打开每个对话，检查最后一条消息是否来自 HR（而非我们自己）：
  - Boss直聘聊天页面中，我方消息通常在 `.chat-item-right` 或 `.chat-message.self`
  - HR 消息通常在 `.chat-item-left` 或 `.chat-message.other`
  - 若最后一条消息来自自己（我方），则该对话无 HR 回复，跳过（保持 APPLIED 不更新）
  - 若最后一条消息来自 HR，才生成 StatusUpdate

**实现策略**：为避免逐一打开对话导致性能差，先从聊天列表判断：
- 若 message 为空字符串 → 跳过（HR 未回复）
- 若 message 与我们的打招呼模板前缀匹配（"您好，我是"开头）→ 跳过（显示的是自己发的消息）
- 否则 → 进入分类流程

```python
GREETING_PREFIX = "您好，我是"

def check_chat_list(self) -> List[StatusUpdate]:
    ...
    for index in range(count):
        ...
        message = self._first_text(item, [...])

        # 跳过空消息或自己发送的消息（HR 尚未回复）
        if not message or message.startswith(GREETING_PREFIX):
            continue

        new_status = self._classify_message(message)
        ...
```

#### 2c. 新增 `send_resume_attachment(chat_url: str, resume_path: str) -> bool`

```python
def send_resume_attachment(self, chat_url: str, resume_path: str) -> bool:
    """
    打开指定聊天窗口，上传并发送附件简历 PDF。
    返回 True 表示发送成功，False 表示失败。
    """
    page = self._require_page()
    page.goto(chat_url, wait_until="domcontentloaded", timeout=30000)
    self._human_pause()
    self._assert_logged_in(page)

    # 点击附件上传按钮（Boss直聘聊天区域的文件图标）
    attach_btn = page.locator(
        ".chat-toolbar [data-type='file'], "
        ".toolbar-item[title='发送文件'], "
        "button:has-text('附件'), "
        ".icon-attach"
    ).first
    if not attach_btn.count() or not attach_btn.is_visible():
        logger.warning("Attachment button not found in chat %s", chat_url)
        return False

    # 使用 Playwright 的 set_input_files 触发文件上传
    with page.expect_file_chooser() as fc_info:
        attach_btn.click()
    file_chooser = fc_info.value
    file_chooser.set_files(resume_path)
    self._human_pause(1.0, 2.0)

    # 确认发送
    send_btn = page.locator(".send-btn, button:has-text('发送')").first
    if send_btn.count() and send_btn.is_visible():
        send_btn.click()
        self._human_pause(0.8, 1.5)
        return True

    return False
```

### 3. `schemas.py` — `StatusUpdate` 增加 `chat_url` 字段

```python
@dataclass
class StatusUpdate:
    job_id: str
    company: str
    new_status: str
    message: str
    updated_at: str
    chat_url: str = ""      # 新增：对应聊天窗口 URL，用于后续发送附件
    is_ad_push: bool = False  # 新增：是否为广告推送/HR 主动发起
```

在 `check_chat_list()` 中从聊天列表项提取 `href` 并填充 `chat_url`。

### 4. `tools/check_responses.py` — 处理新状态

在 `execute()` 中扩展 update 处理逻辑：

```python
for update in updates:
    # AD_PUSH 处理：无对应投递记录时，记录日志但不更新 tracker
    if update.is_ad_push or (record is None and update.new_status != AppStatus.AD_PUSH.value):
        logger.info(
            "AD_PUSH or untracked conversation from %s: %s",
            update.company, update.message
        )
        continue  # 暂不追踪广告推送

    if record and record.status in (AppStatus.APPLIED.value, AppStatus.RESPONDED.value):
        new_status = AppStatus(update.new_status)
        self.tracker.update_status(job_id, new_status, responded_at=update.updated_at)

        # RESUME_REQUESTED：触发附件简历发送流程
        if new_status == AppStatus.RESUME_REQUESTED:
            self._handle_resume_request(update, browser_agent)

        updated_count += 1
        ...
```

新增私有方法 `_handle_resume_request()`:

```python
ATTACHMENT_RESUME_PATH = "data/resume_attachment.pdf"

def _handle_resume_request(self, update: StatusUpdate, browser_agent) -> None:
    """
    处理 HR 请求附件简历：检查文件是否存在，存在则发送，不存在则警告。
    """
    import os
    if not os.path.exists(ATTACHMENT_RESUME_PATH):
        logger.warning(
            "HR from %s requested attachment resume, but no file found at %s. "
            "Please upload your resume PDF via the Dashboard (POST /api/resume/upload).",
            update.company,
            ATTACHMENT_RESUME_PATH,
        )
        return

    if browser_agent is None:
        logger.warning("Cannot send attachment resume: no browser_agent available.")
        return

    if not update.chat_url:
        logger.warning("Cannot send attachment resume to %s: no chat_url.", update.company)
        return

    success = browser_agent.send_resume_attachment(
        chat_url=update.chat_url,
        resume_path=os.path.abspath(ATTACHMENT_RESUME_PATH),
    )
    if success:
        logger.info("Sent attachment resume to %s (%s)", update.company, update.chat_url)
    else:
        logger.warning("Failed to send attachment resume to %s", update.company)
```

### 5. `dashboard/server.py` — 上传简历同时保存为附件简历

在 `POST /api/resume/upload` 中，上传成功后额外保存一份到 `data/resume_attachment.pdf`（仅对 PDF）：

```python
ATTACHMENT_RESUME_PATH = DATA_DIR / "resume_attachment.pdf"

@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)) -> JSONResponse:
    ...
    saved_path.write_bytes(content)

    # 同时保存为稳定路径的附件简历（仅 PDF）
    if suffix == ".pdf":
        ATTACHMENT_RESUME_PATH.write_bytes(content)

    parsed = parse_resume_file(str(saved_path))
    ...
    sections_found = [key for key, value in parsed.items() if value]
    return JSONResponse({
        "success": True,
        "message": "Resume parsed and saved.",
        "sections_found": sections_found,
        "attachment_saved": suffix == ".pdf",
    })
```

### 6. 在线简历检查（轻量提醒）

在 `services/onboarding.py` 的 `check_all()` 或 dashboard 的 `/api/onboarding/status` 中，
增加对 `data/resume_attachment.pdf` 的检查，告知用户是否已上传附件简历：

```python
# onboarding.py 中
def check_attachment_resume(self) -> dict:
    import os
    path = os.path.join(os.path.dirname(self.resume_yaml_path), "resume_attachment.pdf")
    return {
        "ready": os.path.exists(path),
        "path": path,
        "note": (
            None if os.path.exists(path)
            else "请通过 Dashboard 上传附件简历 PDF，当 HR 请求时将自动发送。"
        ),
    }
```

并在 `check_all()` 的返回值中加入 `attachment_resume` 键。

---

## 验收标准

1. `AppStatus` 包含 `RESUME_REQUESTED` 和 `AD_PUSH` 两个新值
2. `StatusUpdate` 包含 `chat_url` 和 `is_ad_push` 字段
3. `check_chat_list()` 能识别简历请求关键词，返回 `RESUME_REQUESTED` 状态
4. `check_chat_list()` 跳过以 `"您好，我是"` 开头的消息（自己发的打招呼）
5. `CheckResponsesTool.execute()` 对 `RESUME_REQUESTED` 状态调用 `_handle_resume_request()`
6. 当 `data/resume_attachment.pdf` 存在时，`send_resume_attachment()` 被调用
7. 当 `data/resume_attachment.pdf` 不存在时，记录清晰警告日志，不抛异常
8. Dashboard 上传 PDF 后，`data/resume_attachment.pdf` 被保存
9. `/api/onboarding/status` 返回 `attachment_resume.ready` 字段
10. 已有测试（dry-run 流程）不回归

---

## 不在本次范围

- 完整的"检查 HR 是否真正已读不回"（需进入每个对话检查消息方向，延迟到 task_014）
- 在线简历自动填写（需要 onboarding 扩展，延迟到 task_014）
- Boss直聘附件上传的精确选择器适配（需真实环境测试后迭代）
