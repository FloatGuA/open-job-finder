# 端到端手动测试指南 / E2E Manual Testing Guide

本文档描述 OpenJobFinder 的手动 E2E 测试流程。每个测试阶段包含：

- **测试范围**：本阶段覆盖哪些组件和功能
- **功能边界**：哪些场景属于本阶段测试，哪些不属于
- **前提条件**：执行本阶段前需要满足的状态
- **测试步骤**：具体操作
- **预期结果**：每步操作后应观察到的状态

---

## 测试环境准备

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 安装前端依赖并构建
cd dashboard/frontend
npm install
npm run build
cd ../..

# 启动 Dashboard（保持运行，另开终端做后续操作）
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload
```

浏览器访问 `http://localhost:8765`，应看到 Dashboard 主页（React SPA）。

---

## 阶段 1：首次启动与 Onboarding

### 测试范围
- `main.py --onboarding` CLI 引导流程
- `OnboardingChecker` 状态检测
- `profile.yaml` 和 `session.json` 文件生成
- Dashboard 页首 Onboarding 状态提示

### 功能边界
- **在本阶段测试**：引导问答完成后文件是否正确生成
- **不在本阶段测试**：Boss直聘 账号登录成功与否（需要真实账号）

### 前提条件
- `code/data/` 目录不存在或为空（全新环境）

### 测试步骤

**步骤 1.1：运行 Onboarding 引导**

```bash
python main.py --onboarding
```

CLI 将依次询问：姓名、目标职位关键词、目标城市、学历、工作经验要求、期望薪资、工作类型。

**预期结果**：
- 每个问题有提示文字，输入后确认
- 全部回答完成后，提示 `profile.yaml 已生成`
- 打开 Chrome 浏览器并导航至 Boss直聘 登录页

**步骤 1.2：浏览器登录 Boss直聘**

在自动打开的 Chrome 窗口中完成 Boss直聘 扫码/手机号登录。

**预期结果**：
- 登录成功后，显示 Boss直聘 个人主页
- 登录窗口关闭后，`code/data/session.json` 文件生成（大小 > 0）
- `code/data/browser_profile/` 目录存在

**步骤 1.3：验证 Dashboard Onboarding 状态**

刷新 Dashboard，查看顶部统计区域。

**预期结果**：
- "配置文件" 状态显示绿色（已完成）
- "简历文件" 状态显示橙色（待完成，需要上传简历）
- "Session" 状态显示绿色（已完成）

---

## 阶段 2：Dashboard 基础功能

### 测试范围
- Dashboard 主页加载（React SPA）
- 统计数字渲染
- 应聘记录列表（空状态与有数据状态）
- 实时 SSE 事件流连接

### 功能边界
- **在本阶段测试**：页面渲染、静态数据展示
- **不在本阶段测试**：工作流触发、数据库写入

### 前提条件
- Dashboard 服务已启动（`uvicorn dashboard.server:app --port 8765`）

### 测试步骤

**步骤 2.1：主页正常加载**

访问 `http://localhost:8765`。

**预期结果**：
- 页面在 2 秒内加载完成，无 JS 报错（F12 控制台）
- 顶部显示统计卡片（总记录、今日投递、剩余额度）
- 左侧或主区域显示应聘记录列表（空状态：显示"暂无数据"或类似提示）
- SSE 连接建立（Network 标签中可见 `/api/workflow/stream` 连接，状态 200，类型 EventStream）

**步骤 2.2：统计数字正确**

新数据库状态下，各统计数字应为 0。

**预期结果**：
- 总记录：0
- 今日投递：0
- 剩余额度：25（默认每日上限）

**步骤 2.3：页面导航**

点击顶部或侧边导航，切换至各子页面（Profile、应聘记录、对话列表等）。

**预期结果**：
- 每个子页面在 1 秒内渲染
- 浏览器地址栏 URL 变化（SPA 路由）
- 刷新页面后仍能正确显示当前页面（若支持深链接）

---

## 阶段 3：Session 验证

### 测试范围
- "检查 Session" 按钮功能
- `GET /api/check/session` 接口
- `BrowserAgent.start()` + DOM 信息提取

### 功能边界
- **在本阶段测试**：Session 有效性判断、用户信息提取
- **不在本阶段测试**：Session 过期后的自动续期流程

### 前提条件
- `code/data/browser_profile/` 目录存在（Onboarding 完成）
- Boss直聘 账号处于已登录状态

### 测试步骤

**步骤 3.1：点击"检查 Session"**

在 Dashboard 主页找到 Session 检查区域，点击"检查 Session"按钮。

**预期结果（Session 有效）**：
- 按钮显示加载动画（约 5–10 秒，浏览器打开）
- 绿色提示框显示：`已登录 · {姓名} · {学历}`
- 成功后浏览器自动关闭

**预期结果（Session 失效）**：
- 红色提示框：`Session 已失效，请重新登录`
- 浏览器自动关闭

**步骤 3.2：工作流运行时点击检查**

先通过任意方式让工作流处于运行状态（参考阶段 4），再点击"检查 Session"。

**预期结果**：
- 不打开浏览器
- 返回提示：`工作流正在运行，浏览器占用中，请稍后再验证`
- 按钮恢复可点击

**步骤 3.3：重新登录流程**

点击"重新登录"（若 Session 失效），打开登录浏览器，完成登录后点击"确认登录"。

**预期结果**：
- `session.json` 更新时间戳变化
- Session 检查立即显示"已登录"

---

## 阶段 4：搜索配置（Profile）

### 测试范围
- Profile 页面表单（关键词、城市、薪资、经验等）
- `POST /api/profile` 保存
- `POST /api/preview/search` 预览搜索 URL
- `profile.yaml` 文件写入与读取

### 功能边界
- **在本阶段测试**：参数映射到 Boss直聘 URL 是否正确（城市/薪资/经验等 code map）
- **不在本阶段测试**：实际搜索结果（需要真实网络请求）

### 前提条件
- Dashboard 已启动
- 有效的 browser_profile 目录（Preview 会打开 Chrome）

### 测试步骤

**步骤 4.1：填写 Profile 表单**

导航至 Profile 页面，依次设置：

| 字段 | 填写值 |
|------|--------|
| 关键词 | `Python后端`（回车添加） |
| 城市 | 选择"北京" |
| 薪资 | 选择"15-25K" |
| 经验 | 选择"1-3年" |
| 学历 | 选择"本科" |

点击"保存"。

**预期结果**：
- 出现保存成功提示（绿色 Toast 或文字）
- 刷新页面后，以上字段值仍然保留
- `code/data/profile.yaml` 文件内容包含上述字段

**步骤 4.2：预览搜索 URL**

点击 Profile 页面的"预览搜索"按钮。

**预期结果**：
- Chrome 浏览器打开，直接加载 Boss直聘 搜索结果页
- URL 包含 `query=Python%E5%90%8E%E7%AB%AF`（或关键词的 URL 编码）
- URL 包含 `city=101010100`（北京的城市码）
- 搜索结果页显示相关职位（如果 Session 有效）

**步骤 4.3：边界验证——空关键词**

清空关键词，保存，再点击预览。

**预期结果**：
- URL 中不含 `query=` 参数
- 打开的是默认搜索结果页

**步骤 4.4：边界验证——未知城市**

在 YAML 文件中直接写入不存在的城市（如 `cities: [火星市]`），点击预览。

**预期结果**：
- URL 使用全国默认城市码 `100010000`
- 不报错

---

## 阶段 5：简历上传

### 测试范围
- `POST /api/resume/upload` 接口
- 文件类型验证（PDF/DOCX only）
- 文件大小限制（10 MB）
- 简历解析（`parse_resume_file`）
- `resume_attachment.pdf` 保存逻辑

### 功能边界
- **在本阶段测试**：上传流程、验证、文件保存
- **不在本阶段测试**：简历 PDF 与实际投递时使用的关联（阶段 6）

### 前提条件
- 有 PDF 或 DOCX 格式的简历文件

### 测试步骤

**步骤 5.1：上传有效 PDF 简历**

在 Dashboard 找到简历上传区域，选择一个 PDF 文件上传。

**预期结果**：
- 上传进度或加载动画
- 成功后显示：`简历已解析，发现字段：[name, skills, experience, ...]`
- `code/data/resume_base.yaml` 文件被创建/更新
- `code/data/resume_attachment.pdf` 文件存在（PDF 上传时同步保存）

**步骤 5.2：上传 DOCX 简历**

选择一个 DOCX 文件上传。

**预期结果**：
- 同步解析成功
- `resume_attachment.pdf` 不被更新（DOCX 上传不保存附件版本）

**步骤 5.3：上传不支持的文件类型**

选择一个 `.txt` 或 `.png` 文件上传。

**预期结果**：
- 立即拒绝（HTTP 400）
- 错误提示：`Only PDF and DOCX files are supported.`
- 不创建任何文件

**步骤 5.4：上传超大文件**

尝试上传一个 > 10 MB 的文件（如大型 PDF）。

**预期结果**：
- HTTP 400 响应
- 错误提示：`File too large. Maximum size is 10 MB.`

---

## 阶段 6：W2 投递工作流（Apply Workflow）

### 测试范围
- `POST /api/workflow/apply` 触发
- `Orchestrator.run_once()` 全流程
- 前端 WorkflowTrack W2 进度可视化
- 每个 job 独立流水线：搜索 → 获取详情 → LLM 评分 → （可选）简历生成 → 投递
- 每日投递上限 (`daily_limit`)
- 本次运行投递上限 (`apply_limit`)
- 停止按钮

### 功能边界
- **在本阶段测试**：全流程数据流、进度事件、状态机转换、上限控制
- **不在本阶段测试**：Boss直聘 DOM 选择器细节（任何 UI 变化都可能导致此处失败）

### 前提条件
- Session 有效（阶段 3 完成）
- `profile.yaml` 已配置（阶段 4 完成）
- `resume_base.yaml` 已存在（阶段 5 完成）
- LLM 可用（`claude -p` CLI 已安装或 Ollama 已运行）

### 测试步骤

**步骤 6.1：Dry-run 模式验证全流程**

在 WorkflowPanel 中，勾选"Dry Run"，设置 `limit=5`，点击"开始投递"。

**预期结果**：
- 按钮变为禁用，停止按钮变为可点击
- W2 工作流卡片出现，步骤节点依次激活：
  - `搜索` → 绿色（完成）
  - `获取详情` → 绿色（完成，每个 job 抓取 JD）
  - `评分` → 绿色（LLM 评分完成）
  - `简历` → 灰色（Dry Run 模式跳过）
  - `投递` → 灰色（Dry Run 模式不实际投递）
- 右侧详情面板显示当前处理的公司·职位名
- 每处理一个 job，状态提示更新
- 数据库中出现 DISCOVERED/SCANNED/SCORED 状态记录
- 应聘记录列表更新（score、decision 字段有值）
- 工作流完成后 W2 显示绿色"完成"状态
- 投递记录中 `status != applied`（Dry Run）

**步骤 6.2：验证评分过滤**

设置较高的 score_threshold（如 90），触发 Dry Run。

**预期结果**：
- 大多数 job 在评分阶段被过滤（decision = "skip"）
- 日志中显示 `score=xx < threshold=90，跳过`
- 被过滤的 job 状态为 SCORED，`decision=skip`
- 通过的 job 状态为 APPLIED（Dry Run 下标记为 applied，实际不投）

**步骤 6.3：真实投递（非 Dry Run）**

取消 Dry Run 勾选，设置 `limit=3`，`apply_limit=2`（最多投递 2 个），`score_threshold=60`，点击"开始投递"。

**预期结果**：
- 流程正常推进
- 投递第 2 个 job 后，工作流停止（apply_limit 达到）
- 数据库中有 2 条 APPLIED 记录，`applied_at` 时间戳有值
- 今日投递计数更新为 2

**步骤 6.4：并发触发保护**

工作流运行中（步骤 6.3 期间），再次点击"开始投递"按钮。

**预期结果**：
- 弹出错误提示：`已有 workflow 正在运行`
- 第二次触发被拒绝，工作流不中断
- HTTP 409 响应

**步骤 6.5：手动停止工作流**

触发投递后，点击"停止"按钮。

**预期结果**：
- 当前处理的 job 完成当前阶段后停止（不立即中断）
- W2 卡片显示"已停止"状态
- 停止后的 job 仍保留已处理的状态（不回滚）
- 停止按钮重新禁用

**步骤 6.6：每日上限保护**

提前在数据库中插入 25 条 `status=applied` 且 `applied_at=今日` 的记录（达到 daily_limit），然后触发投递。

操作方式（Python REPL）：

```python
from services.tracker import ApplicationTracker
from schemas import AppStatus, ApplicationRecord
from datetime import datetime

t = ApplicationTracker("code/data/jobs.db")
for i in range(25):
    now = datetime.utcnow().isoformat()
    rec = ApplicationRecord(
        job_id=f"fill_{i}", title="X", company="X",
        url="https://x.com", status=AppStatus.APPLIED.value,
        applied_at=now, created_at=now, updated_at=now,
    )
    t.upsert(rec)
t.close()
```

**预期结果**：
- `run_once()` 立即返回 `{"note": "daily_limit_reached"}`
- W2 工作流显示"今日投递已达上限（25/25）"或类似提示
- 不触发任何搜索或投递操作

**步骤 6.7：Paused 状态保护**

先调用 `POST /api/pause` 暂停，然后触发投递。

**预期结果**：
- `run_once()` 立即返回 `{"note": "paused"}`
- W2 显示"已暂停"提示
- 调用 `POST /api/resume` 恢复后，工作流可以正常触发

---

## 阶段 7：W3 检查回应工作流（Check Responses Workflow）

### 测试范围
- `POST /api/workflow/check` 触发
- `Orchestrator.check_responses()` 全流程
- 前端 WorkflowTrack W3 进度可视化
- 打招呼消息判断、HR 回复解析、对话状态分类
- `hr_conversations` 表更新

### 功能边界
- **在本阶段测试**：对话读取、状态分类、数据库更新
- **不在本阶段测试**：HR 具体回复内容的语义理解（依赖实际对话）

### 前提条件
- 数据库中存在至少 1 条 `status=applied` 记录（阶段 6 完成）
- Session 有效
- Boss直聘 HR 已有回应（实际环境需等待）

### 测试步骤

**步骤 7.1：触发检查回应**

在 WorkflowPanel 中，点击"检查回应"按钮（W3）。

**预期结果**：
- W3 工作流卡片激活，步骤节点依次激活：
  - `打开对话` → 绿色（打开聊天页）
  - `读取消息` → 绿色（抓取对话内容）
  - `分类状态` → 绿色（LLM 分类：interview/offer/rejected/pending）
  - `更新状态` → 绿色（写入数据库）
- 完成后 W3 显示"完成"

**步骤 7.2：验证对话列表更新**

切换到"对话记录"页面。

**预期结果**：
- 列表显示抓取到的 HR 对话
- 每条对话包含：HR 名、公司名、最后一条消息预览、分类状态（待回复/面试邀请/已拒绝）
- `hr_conversations` 表 `last_synced` 字段更新为当前时间

**步骤 7.3：无投递记录时触发检查**

数据库为空（或所有记录非 APPLIED）时触发检查。

**预期结果**：
- W3 工作流触发并正常完成（0 条对话处理）
- 显示"无待处理对话"或类似提示
- 不报错

---

## 阶段 8：Carryover 机制与断点续跑

### 测试范围
- Pass 1（Carryover）：处理数据库中残留的 DISCOVERED/SCANNED/SCORED 记录
- Pass 2（Search）：搜索新 job 并逐条处理
- 原子性：budget 耗尽时，未 upsert 到 DB 的 job 下次重搜

### 功能边界
- **在本阶段测试**：Carryover 逻辑、DB 不写入未处理 job
- **不在本阶段测试**：并发安全（不支持多进程）

### 测试步骤

**步骤 8.1：模拟中断后的 Carryover**

手动向数据库插入 1 条 DISCOVERED 记录（模拟上次运行中断）：

```python
from services.tracker import ApplicationTracker
from schemas import AppStatus, ApplicationRecord
from datetime import datetime

t = ApplicationTracker("code/data/jobs.db")
now = datetime.utcnow().isoformat()
t.upsert(ApplicationRecord(
    job_id="carryover_test", title="测试职位", company="测试公司",
    url="https://www.zhipin.com/job/carryover_test",
    status=AppStatus.DISCOVERED.value,
    created_at=now, updated_at=now,
))
t.close()
```

触发投递（limit=5, dry_run=True）。

**预期结果**：
- Pass 1 首先处理 `carryover_test`：进入 fetch JD → score 阶段
- Pass 1 完成后进入 Pass 2（搜索新 job）
- 日志显示 `Pass 1: 1 carryover job(s) found`

**步骤 8.2：Budget 原子性验证**

设置 `limit=3`，观察 DB 写入情况。

**预期结果**：
- 搜索返回 10 个 job（假设）
- DB 只写入 3 个 job 记录（upsert 在 budget check 之后）
- 其余 7 个 job 不在数据库中
- 下次运行会重新搜索，不受本次残留 job 影响

---

## 阶段 9：LLM 配置切换

### 测试范围
- Dashboard LLM 配置页
- `POST /api/config/llm` 写入 `config.yaml`
- 不同 provider 的 fallback 链（claude_cli → ollama → anthropic_api）

### 功能边界
- **在本阶段测试**：配置保存与读取的正确性
- **不在本阶段测试**：各 provider 的实际 LLM 调用性能

### 测试步骤

**步骤 9.1：切换为 Ollama**

在 Dashboard LLM 配置页，将 Scoring 和 Generation 都切换为 "ollama"，保存。

**预期结果**：
- `config.yaml` 中 `llm.providers.scoring[0].type = "ollama"`
- 刷新页面后配置仍为 "ollama"

**步骤 9.2：触发 Dry Run 验证 LLM 调用**

用 Ollama 配置触发 dry_run 投递。

**预期结果**：
- 评分阶段使用 Ollama（日志中可见 `ollama` 相关调用）
- 若 Ollama 未运行，显示 LLM 调用失败错误（不崩溃整个工作流）

---

## 阶段 10：异常与边界场景

### 测试范围
- 网络中断时的处理
- Boss直聘 页面结构变化时的处理
- LLM 返回无效 JSON 时的 fallback
- 简历生成失败时的降级

### 功能边界
- **在本阶段测试**：错误处理路径是否记录并继续（per-job 独立流水线）
- **不在本阶段测试**：自动恢复/重试超出单次重试范围的场景

### 测试步骤

**步骤 10.1：断网后触发工作流**

断开网络，触发 Apply 工作流。

**预期结果**：
- 浏览器无法加载 Boss直聘，抛出 Playwright timeout 异常
- 工作流标记为 error 状态（W2 卡片显示红色"执行失败"）
- Dashboard 不崩溃，可以再次触发工作流

**步骤 10.2：LLM 返回无效 JSON**

修改 `config.yaml` 使 LLM provider 指向无效 endpoint（如端口错误的 Ollama），触发评分。

**预期结果**：
- LLM 调用失败，`safe_parse_json` 抛出 `LLMParseError`
- 该 job 的评分阶段记录 error，状态更新为 SCANNED（不推进到 SCORED）
- 下一个 job 正常处理（per-job 流水线隔离）

**步骤 10.3：WeasyPrint 未安装时的简历生成**

卸载 weasyprint（`pip uninstall weasyprint`），触发需要生成简历的工作流（generate_resume=True）。

**预期结果**：
- 简历生成阶段抛出友好错误：`WeasyPrint 未安装，请运行 pip install weasyprint`
- 该 job 跳过简历阶段，继续进行投递（或直接跳过，取决于配置）

**步骤 10.4：Session 在工作流中途失效**

通过浏览器手动退出 Boss直聘 登录，然后触发工作流。

**预期结果**：
- 搜索或抓取 JD 时遭遇登录页跳转
- 抛出包含"login"或"跳转"的错误
- 工作流停止，W2 显示错误状态
- 数据库中已处理的记录保留状态（不回滚）

---

## 阶段 11：日志与数据库审查

### 测试范围
- `code/logs/` 日志文件内容
- SQLite 数据库完整性

### 测试步骤

**步骤 11.1：查看运行日志**

```bash
cat code/logs/orchestrator.log | tail -50
```

**预期结果**：
- 每个 job 处理阶段（fetch/score/resume/apply）有对应日志行
- 错误日志包含 traceback
- 没有 `AttributeError` 或 `KeyError` 等程序 bug（只允许外部依赖错误）

**步骤 11.2：数据库记录完整性**

```bash
sqlite3 code/data/jobs.db "SELECT job_id, status, score, decision, city, salary FROM applications LIMIT 10;"
```

**预期结果**：
- SCORED 状态的记录有 `score` 和 `decision` 值
- APPLIED 状态的记录有 `applied_at` 值
- 所有记录的 `city` 和 `salary` 字段不为 NULL（可以为空字符串）
- 无孤立状态（如 SCANNED 无后续处理的大量积压）

---

## 快速验收清单

以下检查项应在每次重大代码变更后快速过一遍：

```
[ ] Dashboard 主页正常加载（无 JS 错误）
[ ] /api/stats 返回有效 JSON
[ ] Session 检查可以打开并关闭浏览器
[ ] Profile 保存并刷新后值保留
[ ] Apply Dry-Run 模式完成全流程（5 个 job）
[ ] 应聘记录列表显示新增记录
[ ] W2 WorkflowTrack 步骤节点全部正确激活
[ ] 停止按钮在工作流运行时可用
[ ] 并发触发返回 409
[ ] 日志无 AttributeError / KeyError
```
