# W1 Pipeline Design

搜索职位 + 评分 + 投递。

状态说明：✅ 已确认 | ⏳ 待确认

---

## 总体结构 ✅

```
W1Pipeline.run(url, profile, config)
│
├── NavigateStep                              [一次]
│
└── SearchLoop                                [W1Pipeline 管理]
    ├── Tool: ExtractCardList                 [每轮：提取当前页可见卡片]
    ├── CardPipeline × new_cards              [每张新卡]
    ├── 停止条件判断
    └── Tool: ScrollSearchResults             [每轮：向下滚动一次]
```

`seen_card_ids: set[str]` 由 W1Pipeline 跨轮维护，过滤已处理卡片。
循环控制逻辑（包括停止条件判断）归 W1Pipeline.run() 负责。

---

## 停止条件（SearchLoop）✅

```
满足投递预期    applied_count >= config.max_applies_per_run
满足查看预期    viewed_count  >= config.max_cards_per_run
不返回新结果    reached_end == True  或  consecutive_no_new_cards >= 3
达到当日上限    rate_limiter.is_exceeded()
ERROR          NavigateStep / ScrollSearchResults 不可恢复错误
```

---

## 删减范围 ✅

- **CritiqueJob**：不实现，ScoreJob 直接决策
- **GenerateResume**：不实现，ApplyStep 不涉及简历定制

---

## NavigateStep ⏳

**目的**：导航到搜索页，验证第一屏卡片加载成功。

```python
@dataclass
class NavigateStepInput:
    url: str

@dataclass
class NavigateStepOutput:
    ok: bool
    loaded_url: str
```

`on_error`: ABORT_WORKFLOW
Tool: `NavigateSearchUrl`

---

## CardPipeline（per card）⏳

**目的**：对单张卡片完成 分类预检 → 打开面板 → 读 JD → 评分 → 投递 → 持久化。

```python
@dataclass
class CardPipelineInput:
    card: CardBasic       # { job_id, title, company, salary_raw, city, hr_name, card_dom_index }
    profile: Profile
    dry_run: bool

@dataclass
class CardPipelineOutput:
    result: CardResult    # APPLIED | SKIPPED  ← 这张卡的处理结果
    should_stop: bool     # True = 通知 W1Pipeline 停止 SearchLoop
    job_id: str
    score: Optional[int]
    applied: bool
    error: Optional[str]
```

`on_error`: SKIP（单卡失败不影响其余卡片）

`should_stop` 由 CardPipeline 自身判断：读取 ApplyStep 的 result，
若 result=rate_limited 则设 should_stop=True。
Step 只汇报结果，不做控制流决策。
W1Pipeline 检查每张卡的 should_stop，任意一张为 True 则 break 循环。

### 执行顺序 ⏳

```
1. Tool: ClassifyJobForW1(job_id)
       SKIP         → 已在 DB 中，直接返回 result=SKIPPED（不重复写）
       APPLY_ONLY   → 跳过步骤 3~4，直接进步骤 5
       FULL_PIPELINE → 走完整流程

2. Tool: ClickCardOpenPanel(card_dom_index, job_id)
       → 打开右侧 JD 面板（APPLY_ONLY 和 FULL_PIPELINE 都需要）
       失败 → 返回 result=SKIPPED（不写 DB，属于瞬时错误，下次重试）

3. FetchJDStep                                [Step，仅 FULL_PIPELINE]

4. Tool: ScoreJob(...)                        [仅 FULL_PIPELINE]
       score < threshold → UpsertApplication(status=REJECTED, score, reason)
                           + 返回 result=SKIPPED
       ok=False          → 返回 result=SKIPPED（LLM 异常不写 DB，下次重试）

5. ApplyStep                                  [Step，APPLY_ONLY 和 FULL_PIPELINE 均执行]

6. Tool: UpsertApplication(...)               [见下方触发条件表]
```

### UpsertApplication 触发条件 ⏳

| 路径 | 触发时机 | 写入 status |
|------|----------|-------------|
| classify=SKIP | 不触发（已在 DB） | — |
| ClickCardOpenPanel 失败 | 不触发（瞬时错误，下次重试） | — |
| ScoreJob score < threshold | 步骤 4 后立即触发 | REJECTED |
| ScoreJob ok=False | 不触发（LLM 异常，下次重试） | — |
| ApplyStep result=applied | 步骤 6 触发 | APPLIED |
| ApplyStep result=already_chatting | 步骤 6 触发 | APPLIED |
| ApplyStep result=button_not_found | 步骤 6 触发 | ERROR |
| ApplyStep result=dialog_blocked | 步骤 6 触发 | ERROR |
| ApplyStep result=rate_limited | 步骤 6 触发 | ERROR |
| ApplyStep result=error | 步骤 6 触发 | ERROR |

---

## FetchJDStep ✅（Step 定性）⏳（数据契约）

**目的**：从已打开的 JD 面板中提取完整职位描述，解码薪资字段。

面板点击由上游 `ClickCardOpenPanel` 完成，此 Step 只负责**读取内容**，不涉及点击操作。

```python
@dataclass
class FetchJDStepInput:
    pass              # 依赖浏览器当前已打开的面板状态

@dataclass
class FetchJDStepOutput:
    ok: bool
    jd_text: str
    salary_decoded: str
```

`on_error`: SKIP
Tools: `ReadPanelJD` → `DecodeJobSalary`

---

## ScoreJob ✅（Tool，非 Step）⏳（数据契约）

**目的**：将 JD 文本喂给 LLM，按五个维度独立打分，Python 端加权求和，LLM 同时输出一句话总结。

```
Input:
  job_id        string
  title         string
  company       string
  jd_text       string
  profile       { keywords, cities, experience, salary }

Output:
  ok            bool
  score         int              // 0-100，Python 加权计算
  dimensions    {
    skill_match       int        // 0-100
    experience_match  int        // 0-100
    city_match        int        // 0-100
    salary_match      int        // 0-100
    growth_potential  int        // 0-100
  }
  reason        string           // 一句话：对五个维度评分的综合说明，供人工复查
  provider_used string
  error         string|null
```

注：`resume_patch` 已随 GenerateResume 一起删除。

---

## ApplyStep ✅（Step 定性）⏳（数据契约）

**目的**：在已打开的 JD 面板内完成投递全流程：确认面板状态 → 点击投递按钮 → 处理所有弹窗 → 确认结果。

多步浏览器交互 + 多种弹窗分支，需独立错误边界和独立日志。

```python
@dataclass
class ApplyStepInput:
    job_id: str
    title: str
    company: str
    hr_name: str
    dry_run: bool

@dataclass
class ApplyStepOutput:
    result: str    # applied | already_chatting | button_not_found | dialog_blocked | rate_limited | error
```

`result` 覆盖所有业务结果和系统异常，`ok` 字段冗余已删除。
控制流决策（是否 should_stop）由 CardPipeline 读取 result 后自行判断，Step 不参与 Pipeline 控制。

`on_error`: CONTINUE_DEGRADED（Step 内部异常映射为 result=error，不向上抛出）
Tools: `ClickApplyButton` → `HandleApplyDialog`

---

## StepOutput 基类（所有 Step 共用）✅

```python
class StepStatus(Enum):
    SUCCESSFUL = "successful"
    DEGRADED   = "degraded"
    SKIPPED    = "skipped"
    FAILED     = "failed"

@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None
```

所有 W1 Step 的具体 Output 继承此基类，子类字段存业务数据。
详见 `logging.md`。

---

## 待确认项

- [ ] NavigateStep 数据契约
- [ ] CardPipeline 数据契约 + 执行顺序细节
- [ ] FetchJDStep 数据契约
- [ ] ScoreJob 数据契约（含 reason 字段语义）
- [ ] ApplyStep 数据契约（含 should_stop 触发条件）
- [ ] UpsertApplication 在各路径下写入的 status 值
