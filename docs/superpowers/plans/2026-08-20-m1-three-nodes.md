# 计划 B：m1 拆成三个节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 m1 里那个「一个巨大的 ReAct 节点」拆成 `survey_structure`（探结构）/ `plan_buckets`（定桶计划）/ `scan_buckets`（逐桶扫），并让抓取与分类由代码承担，agent 只做导航与桶策略。

**Architecture:** 外层仍是 LangGraph 线性图。三个新节点里只有两个是 ReAct（`survey_structure` / `scan_buckets`），`plan_buckets` 是一次普通 LLM 调用（不碰浏览器 → 可单测、可 eval）。抓取走计划 A 已建好的执行器（`split_rows` / `job_url_online` / `read_total_count` / `validate_manual`），由一个新工具 `harvest_current_page` 串起来交给 `scan_buckets` 的 agent 调用。

**Tech Stack:** Python 3.11+ / LangGraph `StateGraph` + `create_react_agent` / chrome-devtools-mcp（经 `multisite/chrome_mcp_client.py`）/ sqlite3（经 `services/tracker.py`）/ pytest。

**Spec:** `docs/superpowers/specs/2026-08-19-m1-survey-plan-scan-design.md`

## Global Constraints

- **计划 A 的产出是地基，只用不改**：`multisite/site_manual.py`、`multisite/executors.py` 里已有的函数签名一律不动（**Task 1 是唯一例外**，它明确要改 `job_url_online`）。
- **`layer1_agent.py` 已 1500+ 行**。新增的独立逻辑（harvest、桶计划）放新模块，节点函数才留在 `_make_nodes` 里。
- **状态写操作归 `tracker` 独占**：新增列的 schema、迁移、读写只能有一份 SQL，落在 `services/tracker.py`；端点与工具层一律不出现 SQL。
- **fail fast**：内部路径不写防御性兜底、不静默吞错。「这一页没有岗位」和「解析失败」必须是两个可区分的结果。
- **CJK**：`.py` / `.md` 直接写中文。（`\uXXXX` 规则只约束 JS/HTML/TSX，本计划不碰前端。）
- **测试**：改行为的先写会红的测试。每个 task 结束跑全量 `cd code && python -m pytest -q`，**只看退出码是不是 0**——这个环境跑全量不打印结尾汇总行，不要数条数、不要在报告里写全量条数；单文件运行会打印汇总行，那个数字可信。
- 计划里写的 `Expected: N passed` 是手数的，**以实际用例数为准，绝不为凑数增删测试**。

---

### Task 1: `job_url_online` 顺手把 JD 读回来

**Files:**
- Modify: `code/multisite/executors.py`
- Test: `code/tests/test_executors_url_online.py`

**Interfaces:**
- Consumes: 无（改的是计划 A 的产出）
- Produces: `async job_url_online(row, tools, manual) -> tuple[str, str] | None`
  ——返回 `(url, detail_snapshot)`；取不到仍返回 `None`。

**为什么这是第一个 task**（spec §5.1 + DECISION 已定）：spec 用「取 URL 和取 JD 是**同一次访问**」论证了"总是取 JD"这个决定便宜。而现在的实现拿到 URL 立刻 `close_page`，JD 一个字没读。**拖到 harvest 写了一半再改，要改两处；而若改成"每个岗位再导航一次"，run 时长按 spec 自己的估算直接翻倍**（`候选数 × 8 秒` → ×16）。

- [ ] **Step 1: 写失败的测试**

在 `code/tests/test_executors_url_online.py` 追加：

```python
class TestJobUrlOnlineAlsoReadsTheDetailPage:
    """取 URL 和取 JD 必须是同一次访问。

    spec §5.1 的成本论证就建立在这上面：`new_tab_on_click` 的站本来就必须点开详情页
    才能拿到 URL，既然已经在那一页上了，顺手读走快照近乎免费。分成两次访问会让
    run 时长翻倍（每个岗位 ≈8 秒 → ≈16 秒）。
    """

    def test_returns_url_and_detail_snapshot(self):
        tools, _ = _tools()
        got = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert got is not None
        url, detail = got
        assert url == "https://join.qq.com/post_detail.html?postid=999"
        assert "DETAIL-SNAPSHOT" in detail

    def test_reads_the_detail_page_not_the_list_page(self):
        """必须在**切到新标签页之后**读快照。读成列表页的话，每个岗位拿到的 JD
        都一样，而那看起来完全正常——分类会按同一段文本给所有岗位打分。"""
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        names = [c[0] for c in calls]
        assert "select_page" in names, "没有切到详情页就读快照"
        assert names.index("select_page") < names.index("take_snapshot")

    def test_closes_the_tab_even_after_reading(self):
        """加了读快照这一步之后，「拿完必须关」这条不能被破坏。"""
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert ("close_page", 1) in calls
        assert ("close_page", 0) not in calls

    def test_still_returns_none_when_nothing_opens(self):
        tools, calls = _tools(pages_after_click=PAGES_ONE)
        assert _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual())) is None
        assert not any(c[0] == "close_page" for c in calls)
```

**同时改造 `_tools()` 这个假工具**：它现在只有 `click` / `list_pages` / `close_page`，要加 `select_page`（记录切到哪一页）和 `take_snapshot`（返回含 `DETAIL-SNAPSHOT` 的文本）。**已有的四条测试要跟着改成解包 `(url, detail)`**——这是签名变更，不是弱化断言。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_executors_url_online.py -q`
Expected: FAIL（现在返回的是裸 url 字符串，解包会炸或断言不符）

- [ ] **Step 3: 改实现**

`job_url_online` 在 `close_page` 之前插入「切过去 + 读快照」：

```python
    idx, url = fresh[0]
    # **在同一次访问里把详情页快照也读走**（spec §5.1）：这个站本来就必须点开才能
    # 拿到 URL，既然已经在这一页上，读快照近乎免费。分成两次访问会让 run 时长翻倍。
    await get_tool(tools, "select_page").ainvoke({"pageIdx": idx})
    detail = _flat(await get_tool(tools, "take_snapshot").ainvoke({}))
    await get_tool(tools, "close_page").ainvoke({"pageIdx": idx})
    return url, detail
```

docstring 里把「返回 `(url, detail_snapshot)`」和「detail 读的是详情页不是列表页」写清楚，并**删掉**计划 A 留下的那句「本函数不读 JD，计划 B 接 harvest 时一并改签名」——它已经过时了。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_executors_url_online.py tests/test_manual_validation.py -q`
Expected: 全绿。**`validate_manual` 的判据③也调 `job_url_online`，要跟着改解包**（它只需要 url）。

- [ ] **Step 5: 变异验证**

把 `select_page` 那一行注释掉（于是读的是列表页快照），重跑：
`test_reads_the_detail_page_not_the_list_page` 必须变红。恢复。
**这一步不能跳**——「读成列表页」是这个改动唯一会静默产生错数据的方式：每个岗位拿到
一样的 JD，而分类照跑不误。

- [ ] **Step 6: 全量 + 提交**

```bash
cd code && python -m pytest -q   # 只看退出码
git add code/multisite/executors.py code/tests/test_executors_url_online.py
git commit -m "feat(multisite): job_url_online 顺手读详情页快照，取 URL 与取 JD 同一次访问"
```

---

### Task 2: `pending_jobs` 存 JD

**Files:**
- Modify: `code/services/tracker.py`
- Modify: `code/schemas.py`
- Test: `code/tests/test_pending_jobs.py`

**Interfaces:**
- Consumes: 无
- Produces: `PendingJob.jd: str = ""`；`tracker.add_pending_job(..., jd: str = "")`。

**三个确定的消费方**（spec §5.2）：④ 的评分器吃 JD；Checkpoint 1 审批页要显示；eval 要攒真实样本。

- [ ] **Step 1: 写失败的测试**

```python
class TestPendingJobCarriesJD:
    """JD 要跟岗位一起落库。

    **不是"以后可能有用"**：①W1 的评分器吃的就是 JD，抓一次两处用；②Checkpoint 1
    审批时人要看得到（现在只有标题，是盲批的另一半）；③eval 要攒真实样本。
    """

    def test_jd_round_trips(self, tracker):
        jid = tracker.add_pending_job(site_name="s", url="https://x/1", title="t",
                                      jd="职责：做 Agent 工具开发")
        assert tracker.get_pending_job(jid).jd == "职责：做 Agent 工具开发"

    def test_jd_defaults_to_empty_not_none(self, tracker):
        """空串而不是 NULL——消费方是字符串处理（评分器切词、前端渲染），
        None 会让每个消费方各写一次 `or ''`。"""
        jid = tracker.add_pending_job(site_name="s", url="https://x/2", title="t")
        assert tracker.get_pending_job(jid).jd == ""

    def test_existing_rows_migrate_with_empty_jd(self, tracker):
        """加列前就存在的行读出来 jd 必须是空串，不能炸也不能是 None。"""
        tracker.conn.execute("INSERT INTO pending_jobs (site_name, url, title, status) "
                             "VALUES ('s', 'https://x/old', 'old', 'pending')")
        tracker.conn.commit()
        row = next(j for j in tracker.get_pending_jobs() if j.url == "https://x/old")
        assert row.jd == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_pending_jobs.py -q`
Expected: FAIL，`TypeError: add_pending_job() got an unexpected keyword argument 'jd'`

- [ ] **Step 3: 写实现**

1. `code/schemas.py` 的 `PendingJob` 加一个字段（放在 `why` 之后，带注释说明它的三个消费方）：

```python
    # 岗位详情页的原文（`job_url_online` 取 URL 时同一次访问顺手读回来的）。
    # 三个消费方：W1 评分器、Checkpoint 1 审批页、eval 样本。空串 = 没抓到。
    jd: str = ""
```

2. `code/services/tracker.py`：
   - 迁移照抄本文件既有的 `ALTER TABLE` 那一族（`grep "ALTER TABLE pending_jobs"` 或 `grep "ADD COLUMN"` 找现成写法），加 `jd TEXT DEFAULT ''`
   - `add_pending_job` 加 `jd: str = ""` 参数并写进 INSERT
   - `_row_to_pending_job` 读出来，`row["jd"] or ""`

**照抄本文件的既有风格**：写操作一律 `with self.conn:`（本文件 27 处这么写、0 处用显式 `commit()`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_pending_jobs.py -q`
然后 `cd code && python -m pytest -q` 确认退出码 0（**上千个既有测试是"没改坏 tracker"的唯一证据**）。

- [ ] **Step 5: 提交**

```bash
git add code/schemas.py code/services/tracker.py code/tests/test_pending_jobs.py
git commit -m "feat(multisite): pending_jobs 存 JD —— 评分/审批/eval 三个消费方"
```

---

### Task 3: `harvest_current_page` —— 抓一页岗位

**Files:**
- Create: `code/multisite/harvest.py`
- Test: `code/tests/test_harvest.py`

**Interfaces:**
- Consumes: `executors.split_rows` / `job_url_online` / `job_url_offline`（Task 1 改过签名）、`SiteManual`
- Produces: `async harvest_page(snapshot_text, tools, manual, *, bucket, classify, sink, known_urls, limit) -> dict`
  返回 `{"rows": int, "collected": int, "skipped_known": int, "url_failed": int, "truncated": bool}`。
  `classify(items: list[dict]) -> list[dict]` 是注入的分类函数（Task 4 提供真的，测试注入假的）。
  `sink` 是收集结果的 list。

**分工（spec §5）**：agent 决定去哪个桶、勾哪个框、还要不要继续；**代码承担"把这一页 N 条抓下来"**；分类是 LLM，但批量、不占 ReAct 轮次。

- [ ] **Step 1: 写失败的测试**

```python
"""抓一页岗位：切行 → 逐行取 URL 和 JD → 批量分类 → 落袋。

**为什么必须是代码而不是 agent 自己做**：一页 10 个岗位，每个都要「点开→读 URL→
读 JD→关掉」。交给 agent 就是 40 次工具调用、40 个 ReAct 轮次；60 步预算只够一页半。
代码做完这些只占 agent 的**一次**工具调用。
"""
import asyncio
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

from multisite.harvest import harvest_page
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
         "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
         "row_anchor": "工作地点：", "dimensions": [], "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


def _tools(fail_uids=()):
    """假浏览器：每次 click 开一个 URL 带自增序号的新页，快照里带该序号。"""
    state = {"n": 0, "pages": "## Pages\n0: list (https://x/list) [selected]\n"}
    calls = []

    async def click(uid: str):
        calls.append(("click", uid))
        if uid in fail_uids:
            return "Successfully clicked on the element"   # 点了但不开新页
        state["n"] += 1
        state["pages"] = ("## Pages\n0: list (https://x/list) [selected]\n"
                          f"1: detail (https://x/job/{state['n']})\n")
        return "Successfully clicked on the element"

    async def list_pages():
        return state["pages"]

    async def select_page(pageIdx: int):
        calls.append(("select_page", pageIdx))
        return "ok"

    async def take_snapshot():
        return f"## Latest page snapshot\nJD-{state['n']}"

    async def close_page(pageIdx: int):
        calls.append(("close_page", pageIdx))
        state["pages"] = "## Pages\n0: list (https://x/list) [selected]\n"
        return "closed"

    fns = ((click, "click"), (list_pages, "list_pages"), (select_page, "select_page"),
           (take_snapshot, "take_snapshot"), (close_page, "close_page"))
    return [StructuredTool.from_function(coroutine=f, name=n, description=n) for f, n in fns], calls


def _classify_all(items):
    """假分类器：每条都归「开发」。"""
    return [{**it, "category": "开发", "why": "测试"} for it in items]


def _run(c):
    return asyncio.run(c)


class TestHarvestPage:
    def test_collects_every_row_on_the_page(self):
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink,
                                known_urls=set(), limit=100))
        assert out["rows"] == 10
        assert out["collected"] == 10
        assert len(sink) == 10

    def test_each_job_gets_its_own_url_and_jd(self):
        """**每个岗位的 JD 必须来自它自己的详情页。** 全都一样的话，分类会按同一段
        文本给所有岗位打分，而那看起来完全正常。"""
        tools, _ = _tools()
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert len({j["url"] for j in sink}) == 10
        assert len({j["jd"] for j in sink}) == 10

    def test_bucket_is_recorded_on_every_job(self):
        """投递上限常常按招聘项目算，没有 bucket 就只能拿全站数去比。"""
        tools, _ = _tools()
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert all(j["bucket"] == "技术" for j in sink)

    def test_known_urls_are_skipped_and_counted(self):
        """跨 run 没有记忆，重跑同一个站必然重新找到上次那批岗位。
        跳过它们**而且要计数**——不计数的话"这一页都是旧的"和"这一页是空的"分不开。"""
        tools, _ = _tools()
        sink = []
        first = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=first, known_urls=set(), limit=100))
        known = {j["url"] for j in first}

        tools2, _ = _tools()
        out = _run(harvest_page(SNAPSHOT, tools2, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=known, limit=100))
        assert out["skipped_known"] == 10
        assert out["collected"] == 0

    def test_a_row_whose_url_cannot_be_read_is_counted_not_fatal(self):
        """一行取不到 URL 不能中断整页——但要计数，否则"少了两个"无声无息。"""
        tools, _ = _tools(fail_uids={"1_78", "1_87"})
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert out["url_failed"] == 2
        assert out["collected"] == 8

    def test_limit_stops_early_and_says_so(self):
        """`limit` 是成本闸（每个岗位一次详情页往返 ≈8 秒）。停下来要**说出来**，
        否则"这一页只有 3 个岗位"和"抓到 3 个就到上限了"分不开。"""
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=3))
        assert out["collected"] == 3
        assert out["truncated"] is True

    def test_not_truncated_when_the_whole_page_fits(self):
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert out["truncated"] is False

    def test_classify_failure_drops_the_whole_page_without_writing(self):
        """分类挂了整页回退、**不落袋**。半页结果落袋会让下次去重误判成"已收录"。"""
        def boom(items):
            raise RuntimeError("LLM down")

        tools, _ = _tools()
        sink = []
        with pytest.raises(RuntimeError, match="LLM down"):
            _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                              classify=boom, sink=sink, known_urls=set(), limit=100))
        assert sink == []

    def test_no_rows_is_a_distinct_result_from_failure(self):
        """锚点切不出行 → rows=0、collected=0，**不抛**。这是合法结果
        （筛到了一个空桶），跟解析失败要能分开。"""
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(row_anchor="这个文本不存在"),
                                bucket="技术", classify=_classify_all, sink=sink,
                                known_urls=set(), limit=100))
        assert out["rows"] == 0 and out["collected"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_harvest.py -q`
Expected: `ModuleNotFoundError: No module named 'multisite.harvest'`

- [ ] **Step 3: 写实现**

新建 `code/multisite/harvest.py`。要点：

- 先 `split_rows`，再**按 limit 截断**（截断了置 `truncated=True`）
- 逐行取 URL：`new_tab_on_click` 走 `job_url_online`（拿 `(url, detail)`），其余走 `job_url_offline`（`detail` 为空串）
- 取不到 URL → `url_failed += 1`，`continue`（不抛）
- `url in known_urls` → `skipped_known += 1`，`continue`（**在取 URL 之后判断**：URL 是取回来才知道的）
- **分类在循环之后一次性批量调用**（不是每行一次）——这是"不占 ReAct 轮次"的关键
- 分类抛异常就让它抛（fail fast），但**必须在写 sink 之前**——先攒 `pending` 列表，分类成功后才 `sink.extend(...)`

**不要在这个模块里碰 tracker**（落库是节点的事，不是 harvest 的事）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_harvest.py -q`
Expected: 9 passed

- [ ] **Step 5: 变异验证**

把「分类成功后才写 sink」改成「边循环边写 sink」，重跑：
`test_classify_failure_drops_the_whole_page_without_writing` 必须变红。恢复。

- [ ] **Step 6: 全量 + 提交**

```bash
cd code && python -m pytest -q
git add code/multisite/harvest.py code/tests/test_harvest.py
git commit -m "feat(multisite): harvest_page —— 一次调用抓完一页，分类批量不占 agent 轮次"
```

---

### Task 4: 批量分类

**Files:**
- Create: `code/multisite/classify.py`
- Create: `prompts/layer1_classify_jobs.md`
- Test: `code/tests/test_classify_jobs.py`

**Interfaces:**
- Consumes: `services/llm 相关`（用 `multisite.agent_runtime.build_model`）
- Produces: `classify_jobs(items, quotas, *, model=None, prompt_text=None) -> list[dict]`
  ——入参每项至少 `{title, jd, site_category}`，出参每项加 `{category, why}`。

**为什么单独一个模块**：它是**纯判断**，不碰浏览器、不走 ReAct 循环。抽出来就能单测、能做 eval（spec §8）。

- [ ] **Step 1: 写失败的测试**

```python
"""岗位分类：批量、纯判断、可测。

**不走 ReAct 循环**是刻意的（spec §2.1 同理）：它不需要"看一眼再决定下一步"，
输入是文本、输出是标签。做成普通 LLM 调用换来的是**可单测 + 可 eval**。
"""
import json

import pytest

from multisite.classify import classify_jobs

ITEMS = [
    {"title": "AI算法工程师", "jd": "职责：LLM 应用、Agent 工具开发", "site_category": "技术"},
    {"title": "服务运营 - 数据分析", "jd": "职责：售后数据看板", "site_category": "市场"},
]
QUOTAS = {"AI NATIVE": 3, "开发": 5, "运营": 3}


class _FakeModel:
    """按脚本回话的假模型。真实调用会走 langchain 的 `.ainvoke`。"""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)

        class _R:
            content = self.payload if isinstance(self.payload, str) else json.dumps(
                self.payload, ensure_ascii=False)
        return _R()


class TestClassifyJobs:
    def test_assigns_a_category_to_each_item(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "LLM/Agent"},
                            {"index": 1, "category": "运营", "why": "数据看板"}])
        out = classify_jobs(ITEMS, QUOTAS, model=model)
        assert [o["category"] for o in out] == ["AI NATIVE", "运营"]
        assert out[0]["why"]

    def test_keeps_the_original_fields(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        out = classify_jobs(ITEMS, QUOTAS, model=model)
        assert out[0]["title"] == "AI算法工程师"
        assert out[0]["jd"].startswith("职责")

    def test_a_category_outside_the_quota_table_is_rejected(self):
        """类别必须来自配额表。放任 LLM 自造类别名，配额就形同虚设
        （它报一个新名字就绕过了上限）。"""
        model = _FakeModel([{"index": 0, "category": "机器学习", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        out = classify_jobs(ITEMS, QUOTAS, model=model)
        assert out[0]["category"] == ""
        assert "机器学习" in out[0]["why"]

    def test_a_missing_index_leaves_that_item_unclassified(self):
        """LLM 少回一条时，**不能让后面的答案错位顶上**——那会给岗位安错标签，
        而结果看起来完全正常。按 index 对齐，缺的就是空。"""
        model = _FakeModel([{"index": 1, "category": "运营", "why": "y"}])
        out = classify_jobs(ITEMS, QUOTAS, model=model)
        assert out[0]["category"] == ""
        assert out[1]["category"] == "运营"

    def test_unparseable_response_raises(self):
        """整段回不成 JSON 是**失败**，不是"都没分上类"。
        静默返回全空会让上层把它当成"这一页没有符合的岗位"。"""
        model = _FakeModel("对不起我不会")
        with pytest.raises(ValueError):
            classify_jobs(ITEMS, QUOTAS, model=model)

    def test_empty_input_does_not_call_the_model(self):
        model = _FakeModel([])
        assert classify_jobs([], QUOTAS, model=model) == []
        assert model.prompts == []

    def test_prompt_carries_title_jd_and_site_category(self):
        """三样都要进 prompt：只给标题的话，「职责里出现 LLM/Agent 就归 AI NATIVE」
        那条核心规则一个字都执行不了。"""
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        classify_jobs(ITEMS, QUOTAS, model=model)
        blob = str(model.prompts)
        assert "AI算法工程师" in blob and "Agent 工具开发" in blob and "技术" in blob
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_classify_jobs.py -q`
Expected: `ModuleNotFoundError: No module named 'multisite.classify'`

- [ ] **Step 3: 写实现**

1. `prompts/layer1_classify_jobs.md`：占位符 `{{quota_table}}` / `{{golden_examples}}` / `{{jobs}}`。
   内容从 `prompts/layer1_find_jobs.md` 的「判断岗位时注意」那一节搬过来（**那几条归类规则是这个项目积累的资产**，尤其「AI NATIVE 优先于开发/产品」和「AI 方向的产品经理归 AI NATIVE」）。要求输出 JSON 数组 `[{"index": 0, "category": "...", "why": "..."}]`。

2. `code/multisite/classify.py`：
   - `model` 缺省用 `agent_runtime.build_model()`
   - 用 `services/llm_client.py` 现成的 `safe_parse_json`（**grep 确认真实函数名再用，不要猜**）解析；解析不出来抛 `ValueError`
   - 按 `index` 对齐回原列表，缺的留空
   - 类别不在 `quotas` 里 → `category=""`，把 LLM 报的名字写进 `why`（**留痕，不是丢弃**：类别报错是调 prompt 的最好线索）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_classify_jobs.py -q`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
cd code && python -m pytest -q
git add code/multisite/classify.py prompts/layer1_classify_jobs.md code/tests/test_classify_jobs.py
git commit -m "feat(multisite): 批量分类 —— 纯判断、不走 ReAct、可单测可 eval"
```

---

### Task 5: `plan_buckets` —— 定这一轮打哪几个桶

**Files:**
- Create: `code/multisite/bucket_plan.py`
- Create: `prompts/layer1_plan_buckets.md`
- Test: `code/tests/test_bucket_plan.py`

**Interfaces:**
- Consumes: `SiteManual`
- Produces: `plan_buckets(manual, quotas, constraints, *, model=None) -> list[dict]`
  ——每项 `{"dimension": str, "option": str, "why": str, "targets": list[str]}`。

**术语（实现时别混）**：**桶**＝站点自己的顶层分类（技术/产品/设计…），运行时发现；**类别**＝我们的目标类别（AI NATIVE/开发/…），来自 profile。桶计划做的就是这两者的映射。

**不做成 ReAct**（spec §2.1）：它不碰浏览器，输入是手册和求职条件，输出是一份清单，没有「观察→行动」的循环可言。做成普通 LLM 调用换来**可单测、可 eval**（给定手册 A + 条件 B → 该选哪些桶，有 ground truth）。

- [ ] **Step 1: 写失败的测试**

```python
import json

import pytest

from multisite.bucket_plan import plan_buckets
from multisite.site_manual import SiteManual

MANUAL = SiteManual.from_dict({
    "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
    "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
    "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
    "row_anchor": "工作地点：", "important_notes": "",
    "dimensions": [
        {"name": "岗位类别", "options": ["青云课题", "技术", "产品", "设计", "市场", "职能"],
         "multi_select": True},
        {"name": "工作城市", "options": ["深圳", "北京", "上海"], "multi_select": True},
    ],
})
QUOTAS = {"AI NATIVE": 3, "开发": 5, "产品": 3}


class _FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)

        class _R:
            content = self.payload if isinstance(self.payload, str) else json.dumps(
                self.payload, ensure_ascii=False)
        return _R()


class TestPlanBuckets:
    def test_returns_the_planned_buckets(self):
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "青云课题", "why": "AI 方向", "targets": ["AI NATIVE"]},
            {"dimension": "岗位类别", "option": "技术", "why": "开发岗在这里", "targets": ["开发"]},
        ])
        out = plan_buckets(MANUAL, QUOTAS, "只看深圳", model=model)
        assert [b["option"] for b in out] == ["青云课题", "技术"]
        assert out[0]["targets"] == ["AI NATIVE"]

    def test_an_option_not_in_the_manual_is_dropped(self):
        """LLM 编一个手册里没有的选项，代码照着去点必然点空——而"点空"表现为
        "这个桶没有岗位"，跟真的没岗位分不开。在这里就丢掉。"""
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "量子计算", "why": "编的", "targets": ["开发"]},
            {"dimension": "岗位类别", "option": "技术", "why": "真的", "targets": ["开发"]},
        ])
        out = plan_buckets(MANUAL, QUOTAS, "", model=model)
        assert [b["option"] for b in out] == ["技术"]

    def test_a_dimension_not_in_the_manual_is_dropped(self):
        model = _FakeModel([
            {"dimension": "学历要求", "option": "本科", "why": "编的", "targets": ["开发"]},
        ])
        assert plan_buckets(MANUAL, QUOTAS, "", model=model) == []

    def test_targets_outside_the_quota_table_are_dropped(self):
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "技术", "why": "x", "targets": ["开发", "机器学习"]},
        ])
        out = plan_buckets(MANUAL, QUOTAS, "", model=model)
        assert out[0]["targets"] == ["开发"]

    def test_a_bucket_with_no_valid_target_is_dropped(self):
        """一个桶如果对不上任何目标类别，扫它就是纯浪费预算。"""
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "职能", "why": "x", "targets": ["行政"]},
        ])
        assert plan_buckets(MANUAL, QUOTAS, "", model=model) == []

    def test_unparseable_response_raises(self):
        model = _FakeModel("我不知道")
        with pytest.raises(ValueError):
            plan_buckets(MANUAL, QUOTAS, "", model=model)

    def test_empty_plan_is_a_valid_result(self):
        """站上确实没有相关的桶，是合法结论。返回空列表，**不抛**。"""
        model = _FakeModel([])
        assert plan_buckets(MANUAL, QUOTAS, "", model=model) == []

    def test_prompt_carries_the_manual_dimensions_and_the_quotas(self):
        model = _FakeModel([])
        plan_buckets(MANUAL, QUOTAS, "只看深圳", model=model)
        blob = str(model.prompts)
        assert "青云课题" in blob and "AI NATIVE" in blob and "只看深圳" in blob
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_bucket_plan.py -q`
Expected: `ModuleNotFoundError: No module named 'multisite.bucket_plan'`

- [ ] **Step 3: 写实现**

`prompts/layer1_plan_buckets.md` 占位符 `{{dimensions}}` / `{{quota_table}}` / `{{constraints}}`，
要求输出 JSON 数组。**prompt 里要说清楚**：只能从给出的选项里挑，不许自造。

`code/multisite/bucket_plan.py` 的校验层（**这才是这个模块的价值**）：
逐条核对 `dimension` / `option` 真的在手册里、`targets` 真的在配额表里；对不上就丢。
**校验不是防御性编程**——LLM 编一个不存在的选项，下游代码去点必然点空，而"点空"
表现为"这个桶没有岗位"，跟真的没有分不开。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_bucket_plan.py -q`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
cd code && python -m pytest -q
git add code/multisite/bucket_plan.py prompts/layer1_plan_buckets.md code/tests/test_bucket_plan.py
git commit -m "feat(multisite): plan_buckets —— 纯判断不走 ReAct，编出来的桶在这里就丢掉"
```

---

### Task 6: 三个新节点接进 m1 的图

**Files:**
- Modify: `code/multisite/layer1_agent.py`
- Create: `prompts/layer1_survey_structure.md`
- Create: `prompts/layer1_scan_buckets.md`
- Modify: `code/tests/test_multisite_stages.py`
- Test: `code/tests/test_m1_three_nodes.py`

**Interfaces:**
- Consumes: Task 3 的 `harvest_page`、Task 4 的 `classify_jobs`、Task 5 的 `plan_buckets`、
  计划 A 的 `SiteManual` / `validate_manual` / `tracker.get_site_manual` / `upsert_site_manual`
- Produces: `M1_STAGES = ("ensure_ready", "survey_structure", "plan_buckets", "scan_buckets", "write_pending_jobs")`

**注意**：`M1_STAGES` 有**第二个消费方**——前端第 2 层骨架经 `/api/multisite/stages` 读它。`_compile` 会在建图时对着 `stage_names()` 对账，改一处漏一处会当场炸（这是设计好的）。

- [ ] **Step 1: 写失败的测试**

```python
"""m1 的三节点形状。

拆之前 `find_jobs` 一个 ReAct 节点混着三件事：摸清站点结构（探索）、决定打哪几个桶
（纯判断）、逐条读岗位判类别落袋（机械+判断）。三件事共享一个步数预算、一个上下文、
一个完成判据——**一段跑飞就把整轮预算吃光**，前端也只能看到"find_jobs 卡住了"。
"""
import pytest

from multisite.layer1_agent import M1_STAGES, build_select_graph, stage_names


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeTracker:
    def get_pending_jobs(self):
        return []

    def get_site_manual(self, site):
        return None

    def get_site_brief(self, site):
        return None

    def get_golden_category_examples(self, limit=20):
        return []


def _kw():
    names = ["navigate_page", "take_snapshot", "click", "upload_file", "wait_for",
             "list_pages", "select_page", "close_page"]
    return dict(tools=[FakeTool(n) for n in names], personal_info={},
                tracker=FakeTracker(), quotas={"开发": 1})


class TestM1HasThreeNodes:
    def test_stage_order(self):
        assert stage_names("m1") == ("ensure_ready", "survey_structure",
                                     "plan_buckets", "scan_buckets", "write_pending_jobs")

    def test_find_jobs_is_gone(self):
        """旧节点必须真的消失，不能留着当死代码——留着会让"到底跑的是哪条路"
        变成一个需要读代码才能回答的问题。"""
        assert "find_jobs" not in M1_STAGES

    def test_graph_builds(self):
        assert build_select_graph(**_kw()) is not None

    def test_m2_is_untouched(self):
        """m2 与 m1 共用 `_make_nodes` 和 `ensure_ready`，改 m1 不能把 m2 带坏。"""
        from multisite.layer1_agent import M2_STAGES, build_survey_graph
        assert M2_STAGES == ("ensure_ready", "open_application",
                             "scan_and_classify_fields", "write_pending_application")
        assert build_survey_graph(**_kw()) is not None

    def test_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        import multisite.layer1_agent as mod
        monkeypatch.setattr(mod, "M1_STAGES", ("ensure_ready", "oops"))
        with pytest.raises(RuntimeError, match="阶段表"):
            build_select_graph(**_kw())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_m1_three_nodes.py -q`
Expected: FAIL —— `stage_names("m1")` 还是老的三站

- [ ] **Step 3: 写实现**

在 `_make_nodes` 里加三个节点函数，删掉 `find_jobs`：

**`survey_structure`（ReAct）**
1. 先读旧手册：`tracker.get_site_manual(site)`；有的话跑 `validate_manual`
   - 过了 → 直接返回 `{"manual": 旧手册}`，**不进 agent**（省 15 步）
   - 不过 → 丢弃整份重探，把失败原因记进 run 日志（`logger.log`）
2. 探测：agent 带 `record_site_manual` 工具（新写一个，照 `make_record_site_limit_tool` 的样子），
   prompt 用 `layer1_survey_structure`
3. **结束时由代码重新 `navigate_page` 回入口页重置筛选**（spec §3.4：不依赖 agent 自己撤销，
   因为快照不报 `checked`，它无从确认）
4. 探到的手册 `tracker.upsert_site_manual(site, manual)`
5. agent 报"搞不定" → 手册为 None，节点抛，让 run 失败（**诚实失败，不硬填**）

**`plan_buckets`（不是 ReAct）**：调 Task 5 的 `plan_buckets(manual, quotas, constraints)`，
结果进 state。

**`scan_buckets`（ReAct）**：prompt 用 `layer1_scan_buckets`，工具是
`_agent_tools(_PASSTHROUGH_FIND_JOBS)` + 一个 `harvest_current_page` 工具
（包 Task 3 的 `harvest_page`，`classify` 注入 Task 4 的 `classify_jobs`，
`sink` 是本节点的 `found_jobs` 列表，`known_urls` 来自 tracker，
`limit` 用 `candidates_per_bucket`）+ `record_site_limit` + `record_site_brief`。

`write_pending_jobs` 沿用现成的 `record_candidates`（Task 2 之后要把 `jd` 一起写进去）。

**`layer1_find_jobs.md` 这个 prompt 不要删**——把它的「判断岗位时注意」那一节搬进
`layer1_classify_jobs.md`（Task 4 已做），剩下的导航经验搬进 `layer1_scan_buckets.md`。
搬完再删文件，并从 `EDITABLE_PROMPTS` 里去掉（如果在的话）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_m1_three_nodes.py tests/test_multisite_stages.py -q`
（`test_multisite_stages.py` 里断言 m1 三站的那几条要跟着改成五站——**这是设计变更**。）
然后 `cd code && python -m pytest -q` 确认退出码 0。

- [ ] **Step 5: 提交**

```bash
git add code/multisite/layer1_agent.py prompts/ code/tests/
git commit -m "refactor(multisite): m1 拆成 survey_structure / plan_buckets / scan_buckets"
```

---

### Task 7: 三段 prompt 进可编辑清单

**Files:**
- Modify: `code/services/prompt_manager.py`
- Test: `code/tests/test_prompt_override.py`（**已确认存在**，把新测试加进去，不要新建文件）

**Interfaces:**
- Consumes: Task 4/5/6 建的三个 `.md`
- Produces: `EDITABLE_PROMPTS` 含 layer1 那几个

**用户明确要求**：「prompt 必须拆成可编辑资产并且接线到前端的 prompt 相关设置里」。
`/api/prompts` 遍历 `EDITABLE_PROMPTS`，Settings 页 `prompts.map(...)` 自动列出——
**加名字即接线，前端零改动**。

- [ ] **Step 1: 写失败的测试**

```python
class TestLayer1PromptsAreEditable:
    """用户要亲自调 ReAct，那这几段 prompt 就必须能在设置页改，
    而不是只能改文件。加名字即接线：端点遍历 EDITABLE_PROMPTS，前端自动列出。"""

    @pytest.mark.parametrize("name", [
        "layer1_survey_structure", "layer1_plan_buckets",
        "layer1_scan_buckets", "layer1_classify_jobs",
        "layer1_open_application",
    ])
    def test_is_in_the_editable_list(self, name):
        from services.prompt_manager import EDITABLE_PROMPTS
        assert name in EDITABLE_PROMPTS

    @pytest.mark.parametrize("name", [
        "layer1_survey_structure", "layer1_plan_buckets",
        "layer1_scan_buckets", "layer1_classify_jobs",
        "layer1_open_application",
    ])
    def test_the_file_actually_exists(self, name):
        """在清单里但文件不存在 = 设置页打开就 500。"""
        from services.prompt_manager import PromptManager
        assert PromptManager().get_default(name)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_prompt_override.py -q -k Layer1`
Expected: FAIL（这几个名字都不在清单里）

- [ ] **Step 3: 写实现**

把五个名字加进 `EDITABLE_PROMPTS`。**顺带把 m2 的 `layer1_open_application` 也加上**
——它同样只能靠改文件才能调，这个缺口不该只补一半。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_prompt_override.py -q`
然后 `cd code && python -m pytest -q` 确认退出码 0（**占位符校验也会跑**：编辑后
`{{...}}` 集合必须与默认一致，所以模板里的占位符要跟代码 `render` 时传的键对得上）。

- [ ] **Step 5: 提交**

```bash
git add code/services/prompt_manager.py code/tests/
git commit -m "feat(multisite): layer1 的五段 prompt 进可编辑清单，设置页自动列出"
```

---

## 完成判据

- `cd code && python -m pytest -q` 退出码 0
- `stage_names("m1")` 返回五站；`/api/multisite/stages` 跟着变（它读的就是这个）
- 设置页能看到并编辑 layer1 的五段 prompt
- **真机验证留给计划 B 之后**：跑一次 m1 看三个节点各自的产出，特别是
  `survey_structure` 探出来的手册对不对（这是整条链的地基，错了下游全错）

## 明确不做

- **前端**：手册视图、`candidates_per_bucket` 可调、`important_notes` 强提醒、
  JD 进审批页——全部留给计划 C。理由：前端的形状取决于后端定型，反过来做一定返工。
- **`site_limits` 的消费**：那是 m3 的活儿（唯一会真提交的一环），不在本计划。
- **判据②的双向检测**：spec §3.5 已列出三条可行路径，但要等 `_NODE_RE` 保留
  `description` 之后再做，不在本计划。
