# OpenJobFinder

## 项目概述

一个在 Boss直聘上自动化求职的 AI Agent 系统：根据用户求职偏好自动搜索职位、用 LLM 评分决策、生成针对性简历、自动投递，并持续追踪应聘进度。

---

## 功能需求

### F1 — Browser Agent（浏览器自动化）
- 登录 Boss直聘（首次手动，后续复用 session.json）
- 根据关键词 + 城市搜索职位列表
- 抓取完整 JD 文本
- 执行投递操作（点击"立即沟通"+ 发送打招呼语）
- 定时检查聊天列表，获取回应状态

### F2 — Job Scorer（LLM 评分）
- 输入：JD 全文 + 用户 Profile
- 输出：匹配分（0-100）、决策（apply/skip）、原因、简历微调建议
- 低于阈值（默认 72）直接 skip，不进入后续流程

### F3 — Critic Agent（LLM 审核）
- 独立视角复核 Scorer 的决策
- 防止过拟合关键词、重复投递高度相似岗位
- 输出：approve / reject + 理由

### F4 — Resume Manager（简历管理）
- Dashboard 提醒用户上传简历（首次启动检测 resume 缺失时显示上传入口）
- 接受 Boss直聘 导出格式（PDF / Word）并自动解析为结构化数据存入 `data/resume_base.yaml`
- 根据 LLM 的 resume_patch 微调简历措辞，生成针对该 JD 的 PDF
- 使用 Boss直聘 标准简历模板风格渲染（Jinja2 + WeasyPrint）

### F5 — Application Tracker（状态追踪）
- SQLite 状态机，每个 Job 独立记录
- 状态流转：DISCOVERED → SCANNED → SCORED → APPLIED → RESPONDED → INTERVIEW → OFFER / REJECTED / ERROR
- 操作级幂等：apply 前先标记 apply_attempted，防止重复投递
- 记录每一步的时间戳和错误信息

### F6 — Orchestrator + Scheduler（主控循环）
- 结构化 Execution Loop：控制流由代码决定，LLM 只做评分决策
- 每个 Job 独立 try/except，单 job 失败不中断整轮
- APScheduler 定时：工作日 9am 执行投递，每小时检查回应
- Session 失效时暂停 Scheduler 并告警

### F10 — Onboarding & Interactive Setup（首次启动引导）
- 首次启动检测配置完整性：profile.yaml 缺失 → CLI 交互式问答填写
- 检测简历缺失 → Dashboard 显示上传提示卡片，阻止投递直到简历就绪
- 检测 session.json 缺失 → 引导用户执行手动登录并自动保存 session
- 检测 LLM Provider 不可用 → 提示用户检查配置或切换 fallback
- 所有 onboarding 状态在 Dashboard 首页以 checklist 形式展示

### F7 — Tool Registry（工具抽象层）
- 统一接口：search_jobs / score_job / critique_job / generate_resume / apply_job / update_status
- 所有 Service 通过 Tool 封装，不直接调用

### F8 — LLM Provider 抽象（多入口混用）
- 支持多后端：Claude CLI / Ollama（本地）/ Anthropic API / OpenAI-compatible API
- **多入口混用**：不同任务可独立配置不同 Provider（如 scoring 用 Claude CLI，generation 用 Ollama）
- 支持配置多个 Ollama 模型候选，按优先级 fallback
- Provider 不可用时自动 fallback 到下一个已配置入口，记录告警日志
- 通过 config.yaml 配置，运行时无需改代码

```yaml
# config.yaml 示例
llm:
  providers:
    scoring:
      - type: claude_cli
      - type: anthropic_api
        model: claude-sonnet-4-6
    generation:
      - type: ollama
        model: llama3.2
      - type: claude_cli   # fallback
```

### F9 — 基础设施
- **Logging**：按 job_id 分文件记录每步 decision + LLM 原始输出
- **Retry + Backoff**：所有 Playwright 和 LLM 调用，最多 3 次，指数退避
- **LLM 输出解析**：正则提取 JSON block → json-repair 修复 → 字段级类型强制
- **Rate Limiter**：每次 apply 前随机等待 10-30s，每小时上限 8 次
- **Dry Run 模式**：不真实投递，只打印决策，用于 debug 和 prompt 调优

---

## 技术栈

- 语言：Python 3.11+
- 浏览器自动化：Playwright（有头模式）
- LLM 调用：claude CLI（`claude -p`）为默认，可切换至 Ollama / Anthropic API / OpenAI API
- 数据库：SQLite（sqlite3 标准库）
- 调度：APScheduler
- 简历生成：Jinja2 + WeasyPrint
- 配置：YAML（PyYAML）
- JSON 修复：json-repair 库

---

## 约束条件

- **不使用 Anthropic SDK**（与工厂 CLI 认证不一致），LLM 调用统一走 `claude -p` 子进程或 HTTP
- 所有操作必须在工作时间段运行（09:00-18:00 工作日）
- 每日投递上限 25 个（防封号）
- 首次登录需人工操作，session.json 由用户手动触发保存
- 不依赖任何 Boss直聘 官方 API（仅浏览器操作）

---

## 输入 / 输出

**输入（用户配置文件）**
- `data/profile.yaml`：求职关键词、目标城市、期望薪资、技能描述（首次启动由 CLI 交互生成）
- `data/resume_base.yaml`：结构化简历（由 Dashboard 上传 Boss直聘导出文件后自动解析生成）
- `config.yaml`：运行模式、LLM provider 多入口配置、调度时间、阈值参数

**输出**
- `data/jobs.db`：所有职位的完整状态记录
- `logs/orchestrator.log`：loop 级别日志
- `logs/jobs/{job_id}.log`：单 job 完整执行路径
- `output/resumes/{job_id}.pdf`：针对该岗位生成的简历

---

## 目录结构

```
open-job-finder/
├── config.yaml
├── schemas.py
├── orchestrator.py
├── scheduler.py
├── tools/
│   ├── registry.py
│   ├── search_jobs.py
│   ├── score_job.py
│   ├── critique_job.py
│   ├── generate_resume.py
│   ├── apply_job.py
│   └── update_status.py
├── services/
│   ├── browser_agent.py
│   ├── llm_client.py           # 多 Provider + fallback 链
│   ├── llm_parser.py
│   ├── tracker.py
│   ├── resume_manager.py       # 上传解析 + PDF 渲染
│   ├── resume_parser.py        # Boss直聘 PDF/Word → resume_base.yaml
│   ├── onboarding.py           # 首次启动检测 + CLI 引导
│   ├── logger.py
│   ├── retry.py
│   └── rate_limiter.py
├── data/
│   ├── profile.yaml            # CLI 引导生成
│   ├── resume_base.yaml        # Dashboard 上传解析生成
│   ├── session.json
│   └── jobs.db
├── templates/
│   └── resume.html
├── output/
│   └── resumes/
└── logs/
    ├── orchestrator.log
    └── jobs/
```

---

## 验收标准

- [ ] 首次启动无 profile.yaml 时，CLI 引导用户完成填写并生成文件
- [ ] Dashboard 显示简历上传入口，上传 Boss直聘 PDF 后自动解析为 resume_base.yaml
- [ ] 能从 Boss直聘 搜索并抓取至少 20 条职位 JD
- [ ] LLM Scorer 输出稳定的 JSON，score 字段为 int，decision 在枚举值内
- [ ] Critic 能独立推翻 Scorer 决策（至少在测试用例中验证）
- [ ] apply_attempted 标记生效，重复运行 loop 不产生重复投递
- [ ] 单 job 异常不中断整轮 loop（注入 mock 异常验证）
- [ ] Dry Run 模式下全流程可跑通，不触发任何真实投递
- [ ] scoring provider 不可用时自动 fallback 到下一个已配置入口
- [ ] 切换 Ollama provider 后系统可正常运行（允许 JSON 降级处理）
- [ ] logs/jobs/{job_id}.log 包含该 job 从搜索到投递的完整链路
