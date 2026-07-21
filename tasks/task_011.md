# Task 011 — 重写 Onboarding 引导流程（环境配置三步）

## 背景

当前 `--onboarding` 流程存在以下缺陷：
- 无环境依赖检测，用户不知道需要装什么
- LLM 配置只打印一句"请检查 config.yaml"，没有任何引导
- 步骤顺序不合理（应先配 LLM，再登录）

本 task 重写 `services/onboarding.py` 的 `run_interactive_setup()` 方法，实现三步环境配置引导。

**范围说明**：
- 本 task 只做"权限/环境配置"三步（依赖、LLM、登录），这三步是纯 wizard 流程，不需要 schema
- 求职偏好配置（城市选择、关键词等）属于"业务参数"，需要从 Boss直聘 抓取真实数据，将在后续 task 中以 tool 形式实现
- 因此本 task 完成后，profile.yaml 由用户手动编辑或保留现有逻辑，不在此处引导

---

## 新的引导流程（顺序固定）

### Step 1：Python 环境检查

检测以下依赖是否可导入：
- `playwright`（核心，缺失则阻断）
- `fastapi`、`uvicorn`（Dashboard，缺失则警告）
- `weasyprint`（PDF 生成，缺失则警告，不阻断）
- `yaml`、`requests`、`jinja2`（基础依赖）

**逻辑**：
- 用 `importlib.util.find_spec()` 检测，不实际 import
- 核心依赖缺失：打印 `pip install -r requirements.txt` 提示后 `sys.exit(1)`
- 可选依赖缺失：打印警告，继续执行
- playwright 浏览器单独检测：运行 `playwright install --dry-run chromium`，失败则提示 `playwright install chromium`

### Step 2：配置 LLM Provider

按以下顺序依次检测，找到第一个可用的即完成配置：

**2a. claude CLI**
- 运行 `claude --version`，成功则标记可用
- 询问用户确认使用（y/n）

**2b. codex CLI**
- 运行 `codex --version`，成功则标记可用
- 询问用户确认使用（y/n）

**2c. Anthropic API Key**
- 询问用户输入 API Key（输入时不回显，用 `getpass`）
- 用 `requests` 发一个最小请求验证 key 是否有效
- 有效则写入环境变量提示（不写入文件）并记录到 config

**2d. OpenAI 兼容 API**
- 询问 base_url 和 api_key
- 同样发请求验证

**2e. Ollama**
- 检测 `http://localhost:11434/api/tags` 是否可达
- 可达则列出可用模型，让用户选择

**最终**：
- 至少一个 provider 可用才继续
- 将选定的 provider 配置写入 `config.yaml` 的 `llm.providers.scoring` 和 `llm.providers.generation`

### Step 3：登录 Boss直聘

- 检测 `data/session.json` 是否已存在且有效
  - 已有 session：询问用户是否重新登录（y/n），默认跳过
- 打开 Playwright 浏览器，导航到 Boss直聘登录页
- 提示用户手动扫码或账号密码登录
- 用户按 Enter 确认完成后，调用 `_assert_logged_in()` 验证
- 验证通过则保存 session（`save_session()`）

---

## 实现要求

### 修改文件：`services/onboarding.py`

- 将 `run_interactive_setup()` 拆分为三个私有方法：
  - `_step1_check_dependencies() -> bool`
  - `_step2_configure_llm() -> bool`
  - `_step3_login_boss() -> bool`
- `run_interactive_setup()` 顺序调用三步，任一步返回 False 则中止并给出说明
- 每步开始前打印清晰的步骤标题，如：`\n=== Step 2/3: Configure LLM Provider ===`
- 三步全部完成后打印汇总，提示下一步："运行 python main.py --dry-run 验证完整流程"

### 修改文件：`main.py`

- `--onboarding` 分支直接调用 `checker.run_interactive_setup()`（现有逻辑，无需大改）
- 首次启动（无 profile.yaml）时自动触发 onboarding，同样已有，保持不变

### 不修改

- `config.yaml` 结构保持不变，只更新其中的 `llm.providers` 部分
- `BrowserAgent` 类不修改，onboarding 直接使用现有 API
- 其他 services 文件不动

---

## 验收标准

1. `python main.py --onboarding` 顺序执行三步，每步有清晰标题
2. Step 1：playwright 未安装时打印 `playwright install chromium` 并退出；weasyprint 未安装时警告但继续
3. Step 2：按 claude CLI → codex → Anthropic API Key → OpenAI 兼容 API → Ollama 顺序检测，跳过不可用的，至少一个成功才继续，并将配置写入 config.yaml
4. Step 3：浏览器打开后等待用户手动登录，按 Enter 后验证登录状态，成功则保存 session
5. 三步完成后打印汇总，提示运行 `python main.py --dry-run`
6. 不破坏现有的 `check_all()` 方法（Dashboard 依赖它）

---

## 不在本次范围内

- 求职偏好配置（城市/关键词/薪资）——后续 task 以 tool 形式实现
- Dashboard 的 onboarding 状态页面改版
- LLM API Key 的持久化加密存储
- 多账号 Boss直聘 session 管理
