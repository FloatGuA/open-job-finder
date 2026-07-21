# Task 037 — W1 Pipeline

## Goal
实现完整 W1Pipeline，驱动 NavigateStep + SearchLoop + CardPipeline，处理搜索到投递的完整流程。

## Background
现有 orchestrator.py 的 run_once() 是平铺的控制流，本 Task 将其重构为 Step + Pipeline 层次结构。

W1Pipeline 是整个 W1 工作流的顶层控制器，负责：
1. 初始化 RunLogger（run_id = `w1_{YYYYMMDD_HHmm}`）
2. 驱动 NavigateStep 打开搜索页
3. SearchLoop：提取卡片 + 滚动，将每张卡片交给 CardPipeline 处理
4. 收集结果，log_run_end

CardPipeline（per card）是内层循环，包含完整的单卡片处理逻辑。

依赖：T030（DB schema）+ T031（基础框架）+ T033（ProfileLoader）+ T034（W1 BrowserTools）+ T036（W1 非浏览器 Tools）。

## Implementation Requirements

### 目录结构

```
code/pipeline/
├── __init__.py
├── base.py                       # T031 产出，StepStatus / StepOutput
└── w1/
    ├── __init__.py
    ├── pipeline.py               # W1Pipeline
    ├── card_pipeline.py          # CardPipeline（per card 控制逻辑）
    └── steps/
        ├── __init__.py
        ├── navigate.py           # NavigateStep（打开搜索页）
        ├── fetch_jd.py           # FetchJDStep（点卡片 + 读 JD）
        └── apply.py              # ApplyStep（投递 + 弹窗处理）
```

### W1Pipeline（pipeline.py）

```python
@dataclass
class W1Config:
    url: str
    score_threshold: int
    dry_run: bool
    max_cards: Optional[int]      # None = 不限制
    stop_conditions: dict         # 见 design/w1_pipeline.md

class W1Pipeline:
    def __init__(self, registry: ToolRegistry, profile: Profile, logger: RunLogger)
    def run(self, config: W1Config) -> dict  # 返回 summary dict
```

run() 流程：
1. log_run_start
2. NavigateStep（on_error: ABORT_WORKFLOW — 搜索页打不开直接终止）
3. SearchLoop（外层循环提取卡片）：
   - ExtractCardList → 获取当前可见卡片
   - 每张新卡片：CardPipeline.run(card)
   - 停止条件（满足任意一条退出）：
     a. should_stop = True（rate_limited 触发）
     b. reached_end = True（无更多结果）
     c. 连续 5 张卡片全部 skip（疑似搜索结果质量下降）
     d. 已处理卡片数 >= max_cards（配置上限）
     e. 滚动后 new_card_count == 0（页面无新内容）
   - 不触发停止时：ScrollSearchResults 加载更多
4. log_run_end（汇总 cards_viewed / applied / skipped）

### CardPipeline（card_pipeline.py）

```python
@dataclass
class CardInput:
    job_id: str
    title: str
    company: str
    salary_raw: str
    city: str
    hr_name: str
    card_dom_index: int

class CardPipeline:
    def run(self, card: CardInput) -> tuple[StepOutput, bool]
    # 返回 (output, should_stop)
```

执行顺序（参照 design/w1_pipeline.md CardPipeline 章节）：

1. **ClassifyJobForW1**（DBTool）：
   - action="skip" → log_business_event("job_skipped", data={"reason": "classify_skip"}) → 返回 SKIPPED
   - action="apply_only" → 跳到 Step 4（ApplyStep）
   - action="full_pipeline" → 继续

2. **FetchJDStep**（ClickCardOpenPanel + ReadPanelJD + DecodeJobSalary）：
   - on_error: SKIP（面板打不开则跳过此卡片）
   - 输出：jd_text / salary_decoded

3. **ScoreJob**（LLMTool）：
   - 调用 ScoreJob Tool，传 jd_text + profile
   - **score >= threshold 判断由 CardPipeline 做**（not ScoreJob Tool）
   - score >= threshold → 继续
   - score < threshold → log_business_event("job_skipped", data={"reason": "score_below"})
     + UpsertApplication(status="SCORED") → 返回 SKIPPED
   - LLM 失败（ok=False）→ log_business_event("job_skipped", data={"reason": "llm_error"}) → 返回 DEGRADED
   - 成功后发出 log_business_event("job_scored", data={"score": ..., "reason": ..., "above_threshold": True, "provider_used": ...})

4. **ApplyStep**（ClickApplyButton + HandleApplyDialog）：
   - on_error: CONTINUE_DEGRADED
   - result="rate_limited" → should_stop = True
   - 成功 → UpsertApplication(status="APPLIED", applied_at=now) + log_business_event("job_applied", data={"result": result})

### NavigateStep（steps/navigate.py）

```python
@dataclass
class NavigateStepInput:
    url: str

@dataclass
class NavigateStepOutput(StepOutput):
    loaded_url: str
```

调用 NavigateSearchUrl Tool，on_error: ABORT_WORKFLOW。

### FetchJDStep（steps/fetch_jd.py）

```python
@dataclass
class FetchJDStepOutput(StepOutput):
    jd_text: str
    salary_decoded: str
```

调用 ClickCardOpenPanel → ReadPanelJD → DecodeJobSalary，on_error: SKIP。

### ApplyStep（steps/apply.py）

```python
@dataclass
class ApplyStepOutput(StepOutput):
    result: str          # applied / already_chatting / button_not_found / rate_limited
    should_stop: bool
```

调用 ClickApplyButton → HandleApplyDialog，on_error: CONTINUE_DEGRADED。

## Acceptance Criteria

- [ ] dry_run=True 时跑完 SearchLoop 不真实投递，日志出现 run_start / run_end
- [ ] CardPipeline 在 score < threshold 时：DB 写入 SCORED 状态，发出 job_skipped 业务事件，reason="score_below"
- [ ] CardPipeline 在 ClassifyJobForW1 返回 action="skip" 时直接跳过，不调用 LLM
- [ ] rate_limited 时 should_stop=True，W1Pipeline 退出 SearchLoop
- [ ] run_end summary 包含 cards_viewed / applied / skipped 三个计数

## Reference
- design/w1_pipeline.md（Step 设计、停止条件、UpsertApplication 触发时机）
- design/logging.md（Business Events：job_scored / job_applied / job_skipped）
- code/orchestrator.py（现有 run_once 逻辑参考，理解后重构）
- code/tools/apply_job.py（现有投递逻辑参考）
