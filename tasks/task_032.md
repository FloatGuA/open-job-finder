# Task 032 — Prompt System

## Goal
建立独立的提示词管理层：提示词从 Python 字符串移到文件，通过 PromptManager 统一加载和渲染，支持占位符替换。

## Background
现有提示词硬编码在 `code/tools/score_job.py` 和 `code/tools/check_responses.py` 中（Python 多行字符串），修改需要改代码。本 Task 将其移到 `prompts/` 目录，版本化管理，实现提示词与代码解耦。

T036（W1 非浏览器 Tools）和 T038（W2 非浏览器 Tools）的 LLM Tool 实现依赖本 Task 产出的模板文件和 PromptManager。

## Implementation Requirements

### 1. 提示词模板文件

位置：项目根目录 `prompts/`（不在 `code/` 下，提示词是配置而非代码）。

**`prompts/system.md`**：
Agent 身份、目标、行为准则。内容包括：
- 这是一个自动化求职 Agent，代用户在 Boss直聘 投递职位
- 评分和意图分析应准确、保守
- 不伪造信息，不做用户未授权的操作

**`prompts/score_job.md`**：
ScoreJob 评分模板。内容要求：
- 从现有 `code/tools/score_job.py` 中提取 prompt 字符串，迁移到此文件，不要凭空写
- 保留 5 维度独立打分结构（skill_match / experience_match / city_match / salary_match / growth_potential，各 0-100）
- 输出 JSON 格式约束，含 dimensions / reason 字段
- 占位符：`{{title}}` `{{company}}` `{{jd_text}}` `{{profile_summary}}`

**`prompts/analyze_intent.md`**：
HR 意图分析模板。内容要求：
- 从现有 `code/tools/check_responses.py` 中提取 prompt 字符串，迁移到此文件，不要凭空写
- 意图枚举：interview_invite / offer / rejection / resume_request / general / unknown
- 输出 JSON 格式约束，含 intent / confidence / needs_reply / suggested_reply 字段
- 占位符：`{{company}}` `{{job_title}}` `{{messages}}`

### 2. `code/services/prompt_manager.py`

```python
class PromptManager:
    def __init__(self, prompts_dir: Optional[Path] = None)
    # 默认路径：项目根目录 prompts/（相对 __file__ 向上找到 prompts/）

    def load(self, name: str) -> str
    # 读取 prompts/{name}.md，文件不存在抛 FileNotFoundError

    def render(self, name: str, context: dict) -> str
    # load(name) 后替换所有 {{key}} 占位符
    # context 中的 key 对应模板里的 {{key}}
    # 有未替换的占位符时抛 ValueError（列出未替换的 key 名）
```

## Acceptance Criteria

- [ ] `PromptManager().render('score_job', {'title': 'Python工程师', 'company': '字节跳动', 'jd_text': '...', 'profile_summary': '...'})` 返回完整 prompt 字符串，无 `{{` 残留
- [ ] `PromptManager().render('analyze_intent', {'company': '...', 'job_title': '...', 'messages': '...'})` 正常返回
- [ ] 传入不存在的 name 抛 FileNotFoundError
- [ ] context 缺少模板所需 key 时抛 ValueError（不静默忽略）
- [ ] prompts/score_job.md 内容来自现有代码提取，不是重新写的

## Reference
- code/tools/score_job.py（提取现有 prompt，行 ~20~80 左右，查找字符串字面量）
- code/tools/check_responses.py（提取现有 prompt）
- code/services/llm_client.py（了解 LLM 调用方式，prompt 如何传入）
