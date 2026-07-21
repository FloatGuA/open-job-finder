# Task 036 — W1 非浏览器 Tools

## Goal
实现 W1 专用的 4 个非浏览器 Tool：ScoreJob（LLMTool）、DecodeJobSalary（BusinessLogicTool）、ClassifyJobForW1（DBTool）、UpsertApplication（DBTool）。

## Background
现有 `code/tools/score_job.py` 是旧的评分 Tool，逻辑可参考但不直接复用——新版继承 BaseTool，使用 PromptManager 加载 prompt，返回 ToolResult。

ScoreJob 只返回 score / dimensions / reason / provider_used，不含 above_threshold（Pipeline 做比较，不是 Tool 做判断）。

依赖：T030（DB schema）+ T031（BaseTool）+ T032（PromptManager + prompts/score_job.md）。

## Implementation Requirements

### 目录结构

```
code/tools/
├── llm/
│   ├── __init__.py
│   └── score_job.py
├── biz_logic/
│   ├── __init__.py
│   └── decode_salary.py
└── db/
    └── w1/
        ├── __init__.py
        ├── classify_job_for_w1.py
        └── upsert_application.py
```

### ScoreJob（LLMTool）

```
Input:  job_id, title, company, jd_text, profile (Profile dataclass 或 dict)
Output: ToolResult, data = {
    "score": int,               # 0-100，Python 端加权求和（不让 LLM 计算整体分）
    "dimensions": {
        "skill_match": int,
        "experience_match": int,
        "city_match": int,
        "salary_match": int,
        "growth_potential": int
    },
    "reason": str,              # 一句话综合说明
    "provider_used": str
}
```

实现要点：
- 用 `prompt_manager.render('score_job', context)` 构建 prompt（context 含 title / company / jd_text / profile_summary）
- profile_summary 是从 Profile 对象格式化的简短文本（keywords / cities / salary）
- 调用 llm_client.complete(prompt) → 解析 JSON（用现有 safe_parse_json）
- 加权求和：默认权重可参照现有 score_job.py，在代码中作为常量
- LLM 返回解析失败时 ok=False，error 说明具体原因

### DecodeJobSalary（BusinessLogicTool）

```
Input:  raw_salary: str
Output: ToolResult, data = {}，ok 始终 True
        ToolResult 额外 data["decoded_salary"] 供 Pipeline 使用
```

从 browser_agent.py 中找到 PUA Unicode 解码逻辑，提取为纯函数。Boss直聘 薪资字段中 "–" 字符是 PUA 私用区字符，解码为正常数字。

### ClassifyJobForW1（DBTool）

```
Input:  job_id: str
Output: ToolResult, data = {"action": str, "reason": str}
```

查询 applications 表，判断该 job_id 走哪条路径：
- `"skip"`：status 已是 APPLIED / CHATTING / INTERVIEWING / OFFER / REJECTED
- `"apply_only"`：status 是 SCORED（已评分，跳过评分直接投递）
- `"full_pipeline"`：不在 DB，或 status 是 FOUND / SCORED（可重新评分）

注：SCORED 状态的 reason 为"已有评分，跳过重评"；具体边界判断参照现有 orchestrator.py 逻辑。

### UpsertApplication（DBTool）

```
Input:  job_id, title, company, hr_name, url, status,
        city=None, salary=None, score=None, applied_at=None
Output: ToolResult, data = {}
```

INSERT OR REPLACE into applications 表（新 schema，无废弃字段）。applied_at 仅在首次投递时写入。

### ToolRegistry 注册

提供 `register_w1_tools(registry, db, llm_client, prompt_manager)` 函数，批量注册 4 个 Tool。

## Acceptance Criteria

- [ ] `registry.call("score_job", job_id=..., title=..., company=..., jd_text=..., profile=...)` 返回含 score(int 0-100) 和 dimensions 的 ToolResult
- [ ] ScoreJob LLM 调用失败时 ok=False，不抛异常
- [ ] `registry.call("upsert_application", job_id="test_001", ...)` 写入后可从 DB `SELECT * FROM applications WHERE job_id='test_001'` 查到
- [ ] ClassifyJobForW1 对 status=APPLIED 的 job 返回 action="skip"
- [ ] DecodeJobSalary 对含 PUA 字符的薪资字符串返回正常字符串

## Reference
- design/tools_catalog.md（ScoreJob / ClassifyJobForW1 / UpsertApplication / DecodeJobSalary）
- design/logging.md（LLMTools / DBTools / BusinessLogicTools data 规格）
- code/tools/score_job.py（现有评分逻辑，提取权重和解析方式）
- code/services/tracker.py（现有 SQL，理解后迁移到新 schema）
- code/services/llm_parser.py（safe_parse_json，直接复用）
- prompts/score_job.md（T032 产出）
