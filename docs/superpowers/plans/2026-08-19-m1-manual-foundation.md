# 计划 A：站点手册地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立「站点操作手册」的数据模型、执行器与持久化，使得给定一份 a11y 快照和一份手册，代码能切出岗位行、读出总数、取到每个岗位的 URL——全部可单测，且**不改动 m1 现有行为**。

**Architecture:** 手册是一个受约束的数据结构：几个**闭集枚举字段**（代码据此分派到执行器）+ 少量开放数据 + 一格 `important_notes`。执行器是一组纯函数/薄协程，输入快照文本与手册，输出结构化结果。持久化走 `tracker`（本项目铁律：状态写操作归 tracker 独占）。

**Tech Stack:** Python 3.11+ / dataclass / sqlite3（经 `services/tracker.py`）/ pytest。浏览器交互经 `multisite/chrome_mcp_client.py` 拿到的 LangChain `BaseTool`。

**Spec:** `docs/superpowers/specs/2026-08-19-m1-survey-plan-scan-design.md`

## Global Constraints

- **不改 m1 现有行为。** 本计划只新增模块与表；`layer1_agent.py` 的图、节点、prompt 一律不动。
- **`layer1_agent.py` 已 1530 行，不许再往里加。** 新代码进新模块 `multisite/site_manual.py` 与 `multisite/executors.py`。
- **状态写操作归 `tracker` 独占**：`site_manuals` 的 schema、迁移、读写只能有一份 SQL，落在 `services/tracker.py`。
- **fail fast**：手册枚举字段拿到未知值必须抛，不许兜底成默认值。
- **测试 fixture 必须用真实尺寸的快照**，且**必须脱敏**（见 Task 2）。
- **CJK 转义规则只适用于 JS/HTML/TSX**；本计划全是 `.py` 与 `.txt`，直接写中文。
- 每个 task 结束跑 `cd code && python -m pytest -q`，全绿才提交。

---

### Task 1: 手册数据模型与枚举校验

**Files:**
- Create: `code/multisite/site_manual.py`
- Test: `code/tests/test_site_manual.py`

**Interfaces:**
- Consumes: 无
- Produces: `SiteManual` dataclass；`SiteManual.from_dict(d: dict) -> SiteManual`；
  `SiteManual.to_dict() -> dict`；异常 `ManualError(ValueError)`。
  字段：`job_url_source: str`、`url_template: str`、`pagination: str`、
  `filter_interaction: str`、`filters_survive_reload: bool`、`total_count_locator: str`、
  `row_split: str`、`row_anchor: str`、`dimensions: list[dict]`、`important_notes: str`。

- [ ] **Step 1: 写失败的测试**

```python
"""手册的每个闭集字段拿到未知值必须当场抛。

**为什么必须 fail fast**：这些字段是代码分派的依据（`match manual.job_url_source`）。
一个未知值如果被兜底成默认值，表现是 harvest 按错误方式抓回一堆垃圾——而那看起来
跟"这个站没岗位"一模一样，是本项目反复吃亏的那类假信号。
"""
import pytest

from multisite.site_manual import ManualError, SiteManual


def _valid() -> dict:
    return {
        "job_url_source": "new_tab_on_click",
        "url_template": "",
        "pagination": "next_button",
        "filter_interaction": "expand_group_then_click",
        "filters_survive_reload": False,
        "total_count_locator": r"共(\d+)个岗位",
        "row_split": "anchor_text",
        "row_anchor": "工作地点：",
        "dimensions": [{"name": "应聘项目", "options": ["2027校园招聘"], "multi_select": True}],
        "important_notes": "",
    }


class TestEnumsAreClosed:
    @pytest.mark.parametrize("field,bad", [
        ("job_url_source", "scrape_the_api"),
        ("pagination", "magic"),
        ("filter_interaction", "just_click_harder"),
        ("row_split", "vibes"),
    ])
    def test_unknown_enum_value_raises(self, field, bad):
        d = _valid()
        d[field] = bad
        with pytest.raises(ManualError, match=field):
            SiteManual.from_dict(d)

    def test_a_valid_manual_round_trips(self):
        d = _valid()
        assert SiteManual.from_dict(d).to_dict() == d


class TestAnchorTextRequiresAnAnchor:
    def test_anchor_text_without_row_anchor_raises(self):
        """`row_split=anchor_text` 而 `row_anchor` 为空 = 一份不可执行的手册。
        让它在构造时炸，而不是等 harvest 切出 0 行、报「这一页没有岗位」。"""
        d = _valid()
        d["row_anchor"] = ""
        with pytest.raises(ManualError, match="row_anchor"):
            SiteManual.from_dict(d)

    def test_container_per_row_does_not_need_an_anchor(self):
        d = _valid()
        d["row_split"] = "container_per_row"
        d["row_anchor"] = ""
        assert SiteManual.from_dict(d).row_anchor == ""


class TestIdTemplateRequiresATemplate:
    def test_id_template_without_url_template_raises(self):
        d = _valid()
        d["job_url_source"] = "id_template"
        with pytest.raises(ManualError, match="url_template"):
            SiteManual.from_dict(d)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_site_manual.py -q`
Expected: 收集期就失败，`ImportError: cannot import name 'ManualError' from 'multisite.site_manual'`（模块不存在）。

- [ ] **Step 3: 写最小实现**

```python
"""站点操作手册：`survey_structure` 的产出，节点之间的接口。

**为什么闭集字段必须是枚举而不是自由描述**：下游是**代码**（`match manual.job_url_source`）。
agent 写一句"点标题会在新窗口打开"的散文，代码没法据此分派。这组枚举就是通用性的
预算所在——遇到新站的正确反应是**加一个执行器**（一次，全站通用），而不是给某个站
打 prompt 补丁。

设计与取舍见 `docs/superpowers/specs/2026-08-19-m1-survey-plan-scan-design.md` §3。
"""
from dataclasses import dataclass, field


class ManualError(ValueError):
    """手册不合法。**刻意用异常而不是返回 None**——一份不可执行的手册继续往下走，
    产物是"抓回一堆垃圾"，而那跟"这个站没岗位"长得一模一样。"""


JOB_URL_SOURCES = ("link_in_row", "new_tab_on_click", "id_template")
PAGINATIONS = ("next_button", "url_param", "infinite_scroll", "none")
FILTER_INTERACTIONS = ("direct_click", "expand_group_then_click")
ROW_SPLITS = ("container_per_row", "anchor_text")

_ENUMS = {
    "job_url_source": JOB_URL_SOURCES,
    "pagination": PAGINATIONS,
    "filter_interaction": FILTER_INTERACTIONS,
    "row_split": ROW_SPLITS,
}


@dataclass
class SiteManual:
    job_url_source: str
    pagination: str
    filter_interaction: str
    row_split: str
    filters_survive_reload: bool = False
    url_template: str = ""
    total_count_locator: str = ""
    row_anchor: str = ""
    dimensions: list = field(default_factory=list)
    important_notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SiteManual":
        for name, allowed in _ENUMS.items():
            value = d.get(name)
            if value not in allowed:
                raise ManualError(f"{name} 只能是 {allowed} 之一，收到 {value!r}")
        if d["row_split"] == "anchor_text" and not (d.get("row_anchor") or "").strip():
            raise ManualError("row_split=anchor_text 时 row_anchor 不能为空")
        if d["job_url_source"] == "id_template" and not (d.get("url_template") or "").strip():
            raise ManualError("job_url_source=id_template 时 url_template 不能为空")
        return cls(
            job_url_source=d["job_url_source"],
            pagination=d["pagination"],
            filter_interaction=d["filter_interaction"],
            row_split=d["row_split"],
            filters_survive_reload=bool(d.get("filters_survive_reload", False)),
            url_template=d.get("url_template", ""),
            total_count_locator=d.get("total_count_locator", ""),
            row_anchor=d.get("row_anchor", ""),
            dimensions=list(d.get("dimensions") or []),
            important_notes=d.get("important_notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "job_url_source": self.job_url_source,
            "url_template": self.url_template,
            "pagination": self.pagination,
            "filter_interaction": self.filter_interaction,
            "filters_survive_reload": self.filters_survive_reload,
            "total_count_locator": self.total_count_locator,
            "row_split": self.row_split,
            "row_anchor": self.row_anchor,
            "dimensions": self.dimensions,
            "important_notes": self.important_notes,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_site_manual.py -q`
Expected: 10 passed。

- [ ] **Step 5: 提交**

```bash
git add code/multisite/site_manual.py code/tests/test_site_manual.py
git commit -m "feat(multisite): 站点手册数据模型，闭集字段拿到未知值当场抛"
```

---

### Task 2: 真实快照 fixture（**必须脱敏**）

**Files:**
- Create: `code/tests/fixtures/joinqq_post_list.txt`（目录由 Step 3 的脚本 `mkdir` 出来）
- Test: `code/tests/test_fixtures_clean.py`

**Interfaces:**
- Consumes: 无
- Produces: fixture 文件路径常量 `code/tests/fixtures/joinqq_post_list.txt`，供 Task 3–8 使用。

**背景（务必读）**：源快照在 `logs/joinqq_snapshot.txt`（gitignore，不在仓库里）。它的第 17 行是
`uid=1_16 button "你好，<用户真实昵称> "`——**已登录问候，含用户个人信息**。本项目 2026-08-03 曾
因为把真机信息手抄进 git 跟踪文件而不得不 `filter-branch` 重写 12 个提交。
**pre-commit 扫描器只认 jobs.db 的第三方公司/HR，不认用户自己的昵称**，不会拦住你。

- [ ] **Step 1: 写失败的测试**

```python
"""fixture 里不许出现真实个人信息。

2026-08-03 的事故：把真机验证里的真实学校信息手抄进测试和文档，推送前才扫出 10 处，
只能 filter-branch 重写 12 个提交。`data/` 的位置隔离对**必须进 git 的文件**结构上无效，
而 `precommit_pii_scan.py` 只认 jobs.db 的第三方公司/HR，不认用户自己的昵称/学校。

所以这条守门写在测试里。**新增任何 fixture 都要过这一关。**
"""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# 真机快照里出现过的、属于用户本人的东西。占位符必须是虚构的。
_FORBIDDEN = ("浮瓜",)


class TestFixturesCarryNoRealIdentity:
    def test_joinqq_fixture_exists(self):
        assert (FIXTURES / "joinqq_post_list.txt").is_file()

    def test_no_real_nickname_in_any_fixture(self):
        for path in FIXTURES.glob("*.txt"):
            text = path.read_text(encoding="utf-8")
            for bad in _FORBIDDEN:
                assert bad not in text, f"{path.name} 里有真实个人信息：{bad}"

    def test_the_greeting_node_is_a_placeholder(self):
        """登录问候那一行要保留（它是「已登录」的证据，有测试价值），但名字换成虚构的。"""
        text = (FIXTURES / "joinqq_post_list.txt").read_text(encoding="utf-8")
        assert '你好，张三' in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_fixtures_clean.py -q`
Expected: FAIL，`assert (FIXTURES / "joinqq_post_list.txt").is_file()` 为 False。

- [ ] **Step 3: 生成脱敏 fixture**

**不要手抄**。写一个一次性脚本从源快照生成，并当场校验：

```python
# 放进 $CLAUDE_JOB_DIR/tmp/make_fixture.py 跑一次即可，不要提交这个脚本
import re
from pathlib import Path

ROOT = Path(r"C:\Coding\AI-factory-projects\open-job-finder")
src = (ROOT / "logs" / "joinqq_snapshot.txt").read_text(encoding="utf-8")

# 登录问候里的昵称 → 虚构占位。保留这一行本身：它是「已登录」的证据。
out = re.sub(r'(button "你好，)[^"]*(")', r'\1张三 \2', src)

assert "浮瓜" not in out, "脱敏没生效"
assert '你好，张三' in out, "占位符没写进去"
assert "共940个岗位" in out, "计数行丢了"
assert out.count("工作地点：") == 10, "岗位行数变了"

dst = ROOT / "code" / "tests" / "fixtures" / "joinqq_post_list.txt"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(out, encoding="utf-8")
print("ok", len(out), "字符")
```

Run: `python $CLAUDE_JOB_DIR/tmp/make_fixture.py`
Expected: 打印 `ok 6613 字符` 左右。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_fixtures_clean.py -q`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add code/tests/fixtures/joinqq_post_list.txt code/tests/test_fixtures_clean.py
git commit -m "test(multisite): 真实尺寸的 join.qq.com 快照 fixture（已脱敏）+ fixture 守门"
```

---

### Task 3: 行切分执行器

**Files:**
- Create: `code/multisite/executors.py`
- Test: `code/tests/test_executors_rows.py`

**Interfaces:**
- Consumes: `SiteManual`（Task 1）、fixture（Task 2）
- Produces: `split_rows(snapshot_text: str, manual: SiteManual) -> list[JobRow]`；
  `@dataclass JobRow: anchor_uid: str; text: str`（`text` 是这一行所有节点的文本拼接，
  给分类 LLM 读；`anchor_uid` 是取 URL 时要点的那个节点）。

- [ ] **Step 1: 写失败的测试**

```python
"""把平铺的快照切成一行一个岗位。

**为什么按锚点切而不是找标题**：join.qq.com 的岗位卡片在 a11y 快照里没有容器节点，
整页是一串平铺的 StaticText。而列表区开头还夹着推广文案（「不确定适合哪个岗位？…」
三条），按"第一个文本节点即标题"会直接抓错。

锚点＝每个岗位行里必现且仅现一次的文本（本站是「工作地点：」）。真机验证过：
**click 锚点节点会打开它所在那一行的岗位**（事件冒泡到卡片 onClick），
所以切行不需要精确定位标题——标题交给本来就要读这一段的分类 LLM。
"""
from pathlib import Path

from multisite.executors import split_rows
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "row_split": "anchor_text",
         "row_anchor": "工作地点：", "total_count_locator": r"共(\d+)个岗位"}
    d.update(over)
    return SiteManual.from_dict({**d, "url_template": "", "filters_survive_reload": False,
                                 "dimensions": [], "important_notes": ""})


class TestSplitRowsByAnchor:
    def test_finds_every_job_row(self):
        # 真机这一页恰好 10 个岗位，锚点也恰好 10 个。
        assert len(split_rows(SNAPSHOT, _manual())) == 10

    def test_each_row_carries_the_anchor_uid_to_click(self):
        rows = split_rows(SNAPSHOT, _manual())
        # 真机实测：锚点等距分布，周期 9。
        assert [r.anchor_uid for r in rows][:4] == ["1_78", "1_87", "1_96", "1_105"]

    def test_row_text_contains_the_job_title(self):
        """行文本要覆盖到标题——分类 LLM 要从这段里读出岗位叫什么。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert "Agent开发工程师" in rows[1].text

    def test_promo_text_is_not_a_row(self):
        """列表区开头的推广文案不是岗位。按锚点切天然排除它——但要断言，
        因为"多切出一行垃圾"会一路流到分类和落库。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert not any("知识库" in r.text for r in rows)

    def test_an_anchor_that_matches_nothing_yields_no_rows(self):
        """锚点选错了要表现为"切出 0 行"，而不是切出一堆错的。
        0 行会被上层当成"这一页没岗位"——所以调用方必须自己区分，见 Task 8 的轻校验。"""
        assert split_rows(SNAPSHOT, _manual(row_anchor="这个文本不存在")) == []


class TestContainerPerRowIsNotImplementedYet:
    def test_it_raises_instead_of_silently_returning_nothing(self):
        """还没有哪个真实站点需要它。**抛，不要返回空列表**——返回空等于
        谎报"这一页没有岗位"，是本项目反复吃亏的那类假信号。"""
        import pytest
        with pytest.raises(NotImplementedError, match="container_per_row"):
            split_rows(SNAPSHOT, _manual(row_split="container_per_row", row_anchor=""))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_executors_rows.py -q`
Expected: 收集期失败，`ImportError: cannot import name 'split_rows'`。

- [ ] **Step 3: 写最小实现**

```python
"""手册的执行器：给定快照与手册，代码就能干活。

这里的每个函数对应手册里一个闭集字段的一个取值。**加一个执行器＝多支持一类站点**，
而且是一次性的、全站通用的——这正是"不给某个站打补丁"的落点。
设计见 spec §3.2 / §3.7。
"""
import re
from dataclasses import dataclass

from multisite.site_manual import SiteManual

_NODE_RE = re.compile(r'uid=(?P<uid>\S+)\s+(?P<role>\w+)(?:\s+"(?P<name>[^"]*)")?')


@dataclass
class JobRow:
    anchor_uid: str   # 取 URL 时点它；真机验证事件会冒泡到整张卡片
    text: str         # 这一行所有节点的文本，交给分类 LLM 读


def _nodes(snapshot_text: str) -> list:
    out = []
    for line in snapshot_text.splitlines():
        m = _NODE_RE.search(line)
        if m:
            out.append((m.group("uid"), (m.group("name") or "")))
    return out


def split_rows(snapshot_text: str, manual: SiteManual) -> list:
    if manual.row_split == "container_per_row":
        raise NotImplementedError(
            "container_per_row 执行器还没实现——还没有真实站点需要它。"
            "需要时在这里补一个，不要退化成返回空列表：返回空等于谎报「这一页没有岗位」。")

    nodes = _nodes(snapshot_text)
    anchor_positions = [i for i, (_, name) in enumerate(nodes) if name == manual.row_anchor]
    if not anchor_positions:
        return []

    rows = []
    prev_end = 0
    for pos in anchor_positions:
        # 一行 = 上一个锚点之后到本锚点（含）之间的所有节点，再带上锚点后一个节点
        # （地点那一串通常在锚点之后）。取宽一点没有坏处：这段文本只用来给 LLM 读。
        chunk = nodes[prev_end:pos + 2]
        rows.append(JobRow(anchor_uid=nodes[pos][0],
                           text=" ".join(n for _, n in chunk if n.strip())))
        prev_end = pos + 2
    return rows
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_executors_rows.py -q`
Expected: 6 passed。若 `test_promo_text_is_not_a_row` 红，说明第一行把列表区开头的推广文案
带进来了——把第一行的起点改成"第一个锚点往前推一个周期"，并把断言留着。

- [ ] **Step 5: 提交**

```bash
git add code/multisite/executors.py code/tests/test_executors_rows.py
git commit -m "feat(multisite): 行切分执行器，按锚点切、带上要点的 uid"
```

---

### Task 4: 总数读取执行器

**Files:**
- Modify: `code/multisite/executors.py`
- Test: `code/tests/test_executors_count.py`

**Interfaces:**
- Consumes: `SiteManual`、fixture
- Produces: `read_total_count(snapshot_text: str, manual: SiteManual) -> int | None`

- [ ] **Step 1: 写失败的测试**

```python
"""「共 N 个岗位」是整个试探机制的 oracle。

判定筛选维度是多选还是互斥，**只能靠「勾一个 → 回读总数」**——a11y 快照里根本没有
勾选状态（真机实测：整张快照 0 处 `checked`）。这个数字没了，`survey_structure`
就失去了唯一可靠的反馈信号。
"""
from pathlib import Path

from multisite.executors import read_total_count
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(locator: str) -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
        "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
        "total_count_locator": locator, "row_split": "anchor_text",
        "row_anchor": "工作地点：", "dimensions": [], "important_notes": ""})


class TestReadTotalCount:
    def test_reads_the_real_count(self):
        assert read_total_count(SNAPSHOT, _manual(r"共(\d+)个岗位")) == 940

    def test_missing_locator_returns_none_not_zero(self):
        """**None 和 0 语义完全不同**：None＝这个站没有计数（试探判定要退化成数行数），
        0＝筛得一个岗位都不剩（是个有效结果）。合并成 0 会让「筛太窄」和「读不到」
        变得无法区分。"""
        assert read_total_count(SNAPSHOT, _manual("")) is None

    def test_locator_that_matches_nothing_returns_none(self):
        assert read_total_count(SNAPSHOT, _manual(r"共(\d+)个职位")) is None

    def test_locator_without_a_capture_group_returns_none(self):
        """手册写错正则（忘了捕获组）要表现为 None，不要抛——这一格是 agent 填的，
        它写错的概率不低，而整条 run 不该因此崩掉。"""
        assert read_total_count(SNAPSHOT, _manual(r"共\d+个岗位")) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_executors_count.py -q`
Expected: `ImportError: cannot import name 'read_total_count'`。

- [ ] **Step 3: 写最小实现**

追加到 `code/multisite/executors.py`：

```python
def read_total_count(snapshot_text: str, manual: SiteManual):
    """按手册的正则读「共 N 个岗位」。读不到返回 None。

    **None ≠ 0**：None 是"这个站没有计数/读不到"，0 是"筛得一个不剩"。合并会让
    「筛太窄」和「locator 失效」无法区分，而这两件事的处理完全不同。

    正则写错（没有捕获组）也返回 None 而不抛——这一格是 agent 填的，写错概率不低，
    整条 run 不该因此崩掉；轻校验（Task 8）会把它拦下来。
    """
    pattern = (manual.total_count_locator or "").strip()
    if not pattern:
        return None
    try:
        m = re.search(pattern, snapshot_text)
    except re.error:
        return None
    if not m or not m.groups():
        return None
    try:
        return int(m.group(1))
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_executors_count.py -q`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add code/multisite/executors.py code/tests/test_executors_count.py
git commit -m "feat(multisite): 总数读取执行器，None 与 0 语义分开"
```

---

### Task 5: 取 URL 执行器 —— `link_in_row` 与 `id_template`

**Files:**
- Modify: `code/multisite/executors.py`
- Test: `code/tests/test_executors_url_offline.py`

**Interfaces:**
- Consumes: `SiteManual`、`JobRow`（Task 3）
- Produces: `job_url_offline(row: JobRow, snapshot_text: str, manual: SiteManual) -> str | None`
  ——只处理**不需要碰浏览器**的两种取法。`new_tab_on_click` 在 Task 6。

- [ ] **Step 1: 写失败的测试**

```python
"""不碰浏览器就能取到 URL 的两种站点形状。

分成 offline / online 两个函数**不是为了好看**：offline 这两种可以纯单测，
online 那种要 fake 浏览器工具。混在一个函数里，可测的那部分就被不可测的部分拖下水了。
"""
import pytest

from multisite.executors import JobRow, job_url_offline
from multisite.site_manual import SiteManual


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "link_in_row", "url_template": "", "pagination": "none",
         "filter_interaction": "direct_click", "filters_survive_reload": False,
         "total_count_locator": "", "row_split": "anchor_text",
         "row_anchor": "地点", "dimensions": [], "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


ROW_SNAPSHOT = (
    '## Latest page snapshot\n'
    'uid=1_0 RootWebArea "岗位列表" url="https://example.com/jobs"\n'
    'uid=1_5 link "后端开发工程师" url="https://example.com/job/12345"\n'
    'uid=1_6 StaticText "地点"\n'
)


class TestLinkInRow:
    def test_reads_the_url_from_the_row(self):
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 地点")
        assert job_url_offline(row, ROW_SNAPSHOT, _manual()) == "https://example.com/job/12345"

    def test_row_without_a_link_returns_none(self):
        """**返回 None，不要返回空串**：调用方要能区分"这一行没有链接"和"链接是空的"。
        None 会被 harvest 记成"这条取 URL 失败"并计数，空串会被当成合法 URL 写进库。"""
        snap = '## Latest page snapshot\nuid=1_6 StaticText "地点"\n'
        assert job_url_offline(JobRow(anchor_uid="1_6", text="x"), snap, _manual()) is None


class TestIdTemplate:
    def test_fills_the_template_with_the_id_found_in_the_row(self):
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 编号 98765 地点")
        manual = _manual(job_url_source="id_template",
                         url_template="https://example.com/detail?id={id}")
        assert job_url_offline(row, ROW_SNAPSHOT, manual) == "https://example.com/detail?id=98765"

    def test_row_without_a_number_returns_none(self):
        manual = _manual(job_url_source="id_template",
                         url_template="https://example.com/detail?id={id}")
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 地点")
        assert job_url_offline(row, ROW_SNAPSHOT, manual) is None


class TestNewTabIsNotHandledHere:
    def test_it_raises_so_the_caller_uses_the_online_path(self):
        """静默返回 None 会让调用方以为"这一行没有 URL"，而真相是"你用错函数了"。"""
        manual = _manual(job_url_source="new_tab_on_click")
        with pytest.raises(ValueError, match="new_tab_on_click"):
            job_url_offline(JobRow(anchor_uid="1_6", text="x"), ROW_SNAPSHOT, manual)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_executors_url_offline.py -q`
Expected: `ImportError: cannot import name 'job_url_offline'`。

- [ ] **Step 3: 写最小实现**

追加到 `code/multisite/executors.py`：

```python
_ID_RE = re.compile(r"\b(\d{4,})\b")


def job_url_offline(row: JobRow, snapshot_text: str, manual: SiteManual):
    """不碰浏览器就能取到的 URL。取不到返回 None。

    **None 而不是空串**：调用方要能区分"这一行没有链接"（记一次失败并计数）和
    "链接是空的"（会被当成合法 URL 写进库）。
    """
    if manual.job_url_source == "new_tab_on_click":
        raise ValueError("new_tab_on_click 要走 job_url_online()——它必须真的点一下浏览器")

    if manual.job_url_source == "link_in_row":
        # 锚点所在行的**同一张卡片**里那个 link 节点。快照是平铺的，取锚点之前
        # 最近的一个带 url= 的 link。
        best = None
        for line in snapshot_text.splitlines():
            m = _NODE_RE.search(line)
            if not m:
                continue
            if m.group("role") == "link" and 'url="' in line:
                best = re.search(r'url="([^"]*)"', line).group(1)
            if m.group("uid") == row.anchor_uid:
                return best or None
        return None

    # id_template
    m = _ID_RE.search(row.text)
    return manual.url_template.replace("{id}", m.group(1)) if m else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_executors_url_offline.py -q`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add code/multisite/executors.py code/tests/test_executors_url_offline.py
git commit -m "feat(multisite): link_in_row / id_template 两种取 URL，纯离线可测"
```

---

### Task 6: 取 URL 执行器 —— `new_tab_on_click`

**Files:**
- Modify: `code/multisite/executors.py`
- Test: `code/tests/test_executors_url_online.py`

**Interfaces:**
- Consumes: `JobRow`、`SiteManual`、一组 LangChain `BaseTool`（`click` / `list_pages` / `close_page`）
- Produces: `async job_url_online(row, tools, manual) -> str | None`

**背景**：真机验证过，点岗位卡片里**任意**节点（包括锚点「工作地点：」）都会
`window.open` 一个详情页，而 `take_snapshot` 只看当前选中那一页——所以必须用
`list_pages` 才看得见新开的那一页。这正是 2026-08-19 死循环的根因。

- [ ] **Step 1: 写失败的测试**

```python
"""点开新标签页拿 URL，拿完必须关掉。

**为什么必须关**：不关的话标签页会越积越多，而 `list_pages` 的输出里"哪个是刚开的"
就再也判不准了——第 11 个岗位会拿到第 3 个岗位的 URL，而这种错**完全不会报错**，
只会让库里躺着一批指错地方的记录。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.executors import JobRow, job_url_online
from multisite.site_manual import SiteManual


def _manual() -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "none",
        "filter_interaction": "direct_click", "filters_survive_reload": False,
        "total_count_locator": "", "row_split": "anchor_text", "row_anchor": "工作地点：",
        "dimensions": [], "important_notes": ""})


PAGES_TWO = ("## Pages\n"
             "0: 岗位投递 (https://join.qq.com/post.html) [selected]\n"
             "1: 岗位详情 (https://join.qq.com/post_detail.html?postid=999)\n")
PAGES_ONE = "## Pages\n0: 岗位投递 (https://join.qq.com/post.html) [selected]\n"


def _tools(pages_after_click=PAGES_TWO):
    calls = []
    state = {"pages": PAGES_ONE}

    async def click(uid: str):
        calls.append(("click", uid))
        state["pages"] = pages_after_click
        return "Successfully clicked on the element"

    async def list_pages():
        calls.append(("list_pages", None))
        return state["pages"]

    async def close_page(pageIdx: int):
        calls.append(("close_page", pageIdx))
        state["pages"] = PAGES_ONE
        return "closed"

    return [StructuredTool.from_function(coroutine=f, name=n, description=n)
            for f, n in ((click, "click"), (list_pages, "list_pages"),
                         (close_page, "close_page"))], calls


def _run(c):
    return asyncio.run(c)


class TestJobUrlOnline:
    def test_returns_the_url_of_the_newly_opened_page(self):
        tools, _ = _tools()
        url = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert url == "https://join.qq.com/post_detail.html?postid=999"

    def test_clicks_the_anchor_uid(self):
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert ("click", "1_87") in calls

    def test_closes_the_tab_afterwards(self):
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert any(c[0] == "close_page" for c in calls), "开了不关，下一个岗位就会取错 URL"

    def test_click_that_opens_nothing_returns_none_and_closes_nothing(self):
        """有的行点了不跳转（比如那一行其实是广告）。要返回 None 让调用方计一次失败，
        **而不是把当前列表页的 URL 当成岗位 URL 写进库**。"""
        tools, calls = _tools(pages_after_click=PAGES_ONE)
        url = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert url is None
        assert not any(c[0] == "close_page" for c in calls)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_executors_url_online.py -q`
Expected: `ImportError: cannot import name 'job_url_online'`。

- [ ] **Step 3: 写最小实现**

追加到 `code/multisite/executors.py`：

```python
_PAGE_LINE_RE = re.compile(r"^\s*(?P<idx>\d+):\s*.*?\((?P<url>https?://[^)]+)\)(?P<sel>.*)$", re.M)


def _parse_pages(text: str) -> list:
    """`list_pages` 的输出 → [(idx, url, is_selected)]。"""
    return [(int(m.group("idx")), m.group("url"), "[selected]" in m.group("sel"))
            for m in _PAGE_LINE_RE.finditer(text or "")]


def _flat(result) -> str:
    if isinstance(result, list):
        return "\n".join(b.get("text", "") for b in result if isinstance(b, dict))
    return str(result)


def _tool(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise RuntimeError(f"工具集里没有 {name}——new_tab_on_click 必须有 click/list_pages/close_page")


async def job_url_online(row: JobRow, tools, manual: SiteManual):
    """点开卡片、从新标签页读 URL、关掉。取不到返回 None。

    **拿完必须关**：不关的话标签页越积越多，`list_pages` 里"哪个是刚开的"就判不准了，
    第 11 个岗位会拿到第 3 个岗位的 URL——而这种错完全不会报错，只会让库里躺着
    一批指错地方的记录。
    """
    if manual.job_url_source != "new_tab_on_click":
        raise ValueError(f"job_url_online 只处理 new_tab_on_click，收到 {manual.job_url_source}")

    before = {u for _, u, _ in _parse_pages(_flat(await _tool(tools, "list_pages").ainvoke({})))}
    await _tool(tools, "click").ainvoke({"uid": row.anchor_uid})
    after = _parse_pages(_flat(await _tool(tools, "list_pages").ainvoke({})))

    fresh = [(idx, url) for idx, url, _ in after if url not in before]
    if not fresh:
        # 点了没开新页。返回 None 让调用方计一次失败——**绝不能把当前列表页的 URL
        # 当成岗位 URL**。
        return None
    idx, url = fresh[0]
    await _tool(tools, "close_page").ainvoke({"pageIdx": idx})
    return url
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_executors_url_online.py -q`
Expected: 4 passed。

- [ ] **Step 5: 变异验证**

把 `close_page` 那一行注释掉，重跑：`test_closes_the_tab_afterwards` 必须变红。
确认后恢复。**这一步不能跳**——"开了不关"是这个函数唯一会静默产生错数据的方式。

- [ ] **Step 6: 提交**

```bash
git add code/multisite/executors.py code/tests/test_executors_url_online.py
git commit -m "feat(multisite): new_tab_on_click 取 URL，点锚点读新标签页再关掉"
```

---

### Task 7: `site_manuals` 表与 tracker 读写

**Files:**
- Modify: `code/services/tracker.py`
- Test: `code/tests/test_site_manuals_store.py`

**Interfaces:**
- Consumes: `SiteManual`（Task 1）
- Produces: `tracker.upsert_site_manual(site_name: str, manual: SiteManual) -> None`；
  `tracker.get_site_manual(site_name: str) -> tuple[SiteManual, str] | None`
  （返回 `(manual, updated_at_iso)`；没有则 None）。

**约定**：照抄 `upsert_site_brief` / `get_site_brief`（`services/tracker.py:1515-1530`）的写法与
迁移风格（`ALTER TABLE` 那一族，见文件 108/176 行附近）。**手册与 brief 并存、职责分开**：
手册＝本轮可执行的事实（结构化，代码消费），brief＝跨轮经验笔记（自由文本，喂 prompt）。

- [ ] **Step 1: 写失败的测试**

```python
"""手册的持久化。与 site_briefs **并存**，不是替代。

职责分开：手册＝本轮可执行的事实（结构化，代码消费），brief＝跨轮经验笔记
（自由文本，喂进 prompt 给模型看，明确标注可能过期）。
"""
import pytest

from multisite.site_manual import SiteManual
from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


def _manual(anchor="工作地点：") -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
        "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
        "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
        "row_anchor": anchor, "dimensions": [{"name": "工作城市", "options": ["深圳"],
                                              "multi_select": True}],
        "important_notes": ""})


class TestSiteManualStore:
    def test_missing_site_returns_none(self, tracker):
        assert tracker.get_site_manual("从来没跑过的站") is None

    def test_round_trips(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        got, updated_at = tracker.get_site_manual("joinqq")
        assert got.to_dict() == _manual().to_dict()
        assert updated_at

    def test_upsert_overwrites_and_bumps_updated_at(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        first = tracker.get_site_manual("joinqq")[1]
        tracker.upsert_site_manual("joinqq", _manual(anchor="工作城市："))
        got, second = tracker.get_site_manual("joinqq")
        assert got.row_anchor == "工作城市："
        assert second >= first

    def test_sites_do_not_leak_into_each_other(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        tracker.upsert_site_manual("bambulab", _manual(anchor="Location"))
        assert tracker.get_site_manual("joinqq")[0].row_anchor == "工作地点："
        assert tracker.get_site_manual("bambulab")[0].row_anchor == "Location"


class TestBriefIsUntouched:
    def test_manual_and_brief_coexist(self, tracker):
        """两者并存是**有意的职责分离**，不是冗余。谁要是把 brief 删了合并进手册，
        这条会红。"""
        tracker.upsert_site_manual("joinqq", _manual())
        tracker.upsert_site_brief("joinqq", "这个站要登录，筛选器在顶部")
        assert tracker.get_site_manual("joinqq")[0].row_anchor == "工作地点："
        assert "要登录" in tracker.get_site_brief("joinqq").brief
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_site_manuals_store.py -q`
Expected: `AttributeError: 'ApplicationTracker' object has no attribute 'get_site_manual'`。

- [ ] **Step 3: 写最小实现**

在 `code/services/tracker.py` 的 schema 初始化里（跟 `site_briefs` 那张表挨着建，grep `CREATE TABLE IF NOT EXISTS site_briefs` 定位）加：

```sql
CREATE TABLE IF NOT EXISTS site_manuals (
    site_name  TEXT PRIMARY KEY,
    manual     TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

并紧挨 `get_site_brief`（约 1530 行）之后加：

```python
    def upsert_site_manual(self, site_name: str, manual) -> None:
        """站点操作手册。与 `site_briefs` **并存、职责分开**——手册是本轮可执行的
        结构化事实（代码消费），brief 是跨轮经验笔记（喂 prompt 给模型看）。
        列集不同、消费方不同，不是分叉。"""
        import json
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO site_manuals (site_name, manual, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(site_name) DO UPDATE SET manual=excluded.manual, "
            "updated_at=excluded.updated_at",
            (site_name, json.dumps(manual.to_dict(), ensure_ascii=False), now))
        self.conn.commit()

    def get_site_manual(self, site_name: str):
        """返回 `(SiteManual, updated_at)`；没有则 None。"""
        import json

        from multisite.site_manual import SiteManual
        row = self.conn.execute(
            "SELECT manual, updated_at FROM site_manuals WHERE site_name = ?",
            (site_name,)).fetchone()
        if row is None:
            return None
        return SiteManual.from_dict(json.loads(row[0])), row[1]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_site_manuals_store.py -q`
Expected: 5 passed。再跑全量确认没碰坏 tracker：`cd code && python -m pytest -q`。

- [ ] **Step 5: 提交**

```bash
git add code/services/tracker.py code/tests/test_site_manuals_store.py
git commit -m "feat(multisite): site_manuals 表与读写，与 site_briefs 并存"
```

---

### Task 8: 轻校验

**Files:**
- Modify: `code/multisite/executors.py`
- Test: `code/tests/test_manual_validation.py`

**Interfaces:**
- Consumes: 全部前序
- Produces: `async validate_manual(manual, snapshot_text, tools) -> tuple[bool, str]`
  ——返回 `(过了没有, 人看得懂的原因)`。

**判据（spec §3.5，三条全过才算过）**：① 计数文本仍在 ② `dimensions[0].options`
与本次快照一致 ③ 对第一个岗位实取一次 URL，拿到合法 http(s)。

- [ ] **Step 1: 写失败的测试**

```python
"""手册过期比没有手册更糟，所以每轮都要轻校验。

- `job_url_source` 变了 → harvest 抓回一堆空 URL → 表现是"这个站突然没岗位了"
- `filter_interaction` 变了 → 筛选点不动 → 回到 2026-08-19 那个死循环

但"校验"如果做成重新探一遍就没有意义（成本一样），所以只验最要命的三条，约 3–5 步。
**任一条不过整份作废**——不做部分沿用：手册字段之间有耦合，逐格判断"哪格还能用"
的成本接近重探，而判错的产物是半对的手册，最难查。
"""
import asyncio
from pathlib import Path

from langchain_core.tools import StructuredTool

from multisite.executors import validate_manual
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
         "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
         "row_anchor": "工作地点：",
         "dimensions": [{"name": "应聘项目",
                         "options": ["应届毕业生", "2027校园招聘"], "multi_select": True}],
         "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


def _tools(url="https://join.qq.com/post_detail.html?postid=999"):
    pages_one = "## Pages\n0: 列表 (https://join.qq.com/post.html) [selected]\n"
    pages_two = pages_one + f"1: 详情 ({url})\n"
    state = {"pages": pages_one}

    async def click(uid: str):
        state["pages"] = pages_two
        return "Successfully clicked on the element"

    async def list_pages():
        return state["pages"]

    async def close_page(pageIdx: int):
        state["pages"] = pages_one
        return "closed"

    return [StructuredTool.from_function(coroutine=f, name=n, description=n)
            for f, n in ((click, "click"), (list_pages, "list_pages"),
                         (close_page, "close_page"))]


def _run(c):
    return asyncio.run(c)


class TestValidateManual:
    def test_an_unchanged_site_passes(self):
        ok, why = _run(validate_manual(_manual(), SNAPSHOT, _tools()))
        assert ok is True, why

    def test_missing_count_text_fails(self):
        """计数是整个试探机制的 oracle，它没了后面全塌。"""
        ok, why = _run(validate_manual(_manual(total_count_locator=r"共(\d+)个职位"),
                                       SNAPSHOT, _tools()))
        assert ok is False and "计数" in why

    def test_changed_filter_options_fail(self):
        """招聘站改版最先体现在筛选项增删上（2027校园招聘 → 2028校园招聘）。
        这条**会在每年招聘季准时触发一次重探**，那是对的。"""
        m = _manual(dimensions=[{"name": "应聘项目",
                                 "options": ["应届毕业生", "2028校园招聘"],
                                 "multi_select": True}])
        ok, why = _run(validate_manual(m, SNAPSHOT, _tools()))
        assert ok is False and "选项" in why

    def test_url_extraction_that_stops_working_fails(self):
        """job_url_source 是手册里最要命的一格，错了整轮白抓。而它**只能靠实做验**
        ——读快照看不出"点下去会不会开新标签页"。"""
        tools = _tools()

        async def click_that_opens_nothing(uid: str):
            return "Successfully clicked on the element"

        tools[0] = StructuredTool.from_function(coroutine=click_that_opens_nothing,
                                                name="click", description="click")
        ok, why = _run(validate_manual(_manual(), SNAPSHOT, tools))
        assert ok is False and "URL" in why

    def test_the_reason_is_human_readable(self):
        """失败原因要能直接进 run 日志给人看。空字符串等于"验失败了但不知道为什么"。"""
        _, why = _run(validate_manual(_manual(total_count_locator=r"共(\d+)个职位"),
                                      SNAPSHOT, _tools()))
        assert len(why) > 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd code && python -m pytest tests/test_manual_validation.py -q`
Expected: `ImportError: cannot import name 'validate_manual'`。

- [ ] **Step 3: 写最小实现**

追加到 `code/multisite/executors.py`：

```python
async def validate_manual(manual: SiteManual, snapshot_text: str, tools) -> tuple:
    """旧手册还成不成立。返回 `(过了没有, 人看得懂的原因)`。

    只验三条（spec §3.5），约 3–5 步，远低于全量重探。**任一条不过整份作废**——
    不做部分沿用：手册字段之间有耦合（`filter_interaction` 变了往往意味着筛选区重写，
    `dimensions` 也不可信），逐格判断"哪格还能用"的成本接近重探，而判错的产物是
    半对的手册，最难查。
    """
    # ① 计数文本仍在
    if manual.total_count_locator and read_total_count(snapshot_text, manual) is None:
        return False, f"计数文本读不到了（locator={manual.total_count_locator!r}），站点可能已改版"

    # ② 第一个维度的选项集合没变
    if manual.dimensions:
        want = set(manual.dimensions[0].get("options") or [])
        have = {name for _, name in _nodes(snapshot_text) if name}
        missing = want - have
        if missing:
            return False, f"筛选维度「{manual.dimensions[0].get('name')}」的选项变了，快照里找不到：{sorted(missing)}"

    # ③ 对第一个岗位实取一次 URL
    rows = split_rows(snapshot_text, manual)
    if not rows:
        return False, f"按 row_anchor={manual.row_anchor!r} 一行都切不出来"
    if manual.job_url_source == "new_tab_on_click":
        url = await job_url_online(rows[0], tools, manual)
    else:
        url = job_url_offline(rows[0], snapshot_text, manual)
    if not (url or "").startswith("http"):
        return False, f"按 job_url_source={manual.job_url_source} 取不到第一个岗位的 URL"

    return True, "手册仍然成立"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd code && python -m pytest tests/test_manual_validation.py -q`
Expected: 5 passed。

- [ ] **Step 5: 跑全量 + 提交**

Run: `cd code && python -m pytest -q`
Expected: 全绿（本计划不改动任何现有行为，既有用例一条都不该红）。

```bash
git add code/multisite/executors.py code/tests/test_manual_validation.py
git commit -m "feat(multisite): 手册轻校验三条判据，任一不过整份作废"
```

---

## 完成判据

- `cd code && python -m pytest -q` 全绿
- 新增 8 个测试文件、2 个新模块、1 张新表，**`layer1_agent.py` 一行未改**
- `python -c "from multisite.executors import split_rows"` 可导入
- fixture 过 PII 守门（`tests/test_fixtures_clean.py`）

## 计划 A 之后

计划 B（三节点重构 + prompt + harvest + JD 落库）依赖本计划的全部产出，
接口以本文件各 Task 的 **Interfaces** 块为准。
