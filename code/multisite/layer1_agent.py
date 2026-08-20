"""Layer 1（识别/判断）agent —— docs/multi-site-expansion-design.md 四层架构的第一层。

**自主度按层拆分，不是全链路统一**（v2.22.0 与用户重新对齐后的形态，取舍见
DECISION.md「Layer 1 的导航/找入口/选岗交给 agent 自主决策」）。

**三节点重构（m1-three-nodes）之后，"选岗"本身又拆成了三段，ReAct 只留在真正
需要"看一眼再决定下一步"的地方**——这是这次重构的核心决定，不是随手拆分：

| 环节 | 节点 | 谁来决策 | 为什么 |
|------|------|---------|--------|
| 这个站怎么分桶（勘察结构、试探筛选器） | `survey_structure` | **agent（ReAct）** | 要勾选筛选器、回读总数、边看边决定下一步试探什么，纯脚本判断不出多选/互斥这类信息 |
| 打哪几个桶 | `plan_buckets` | 普通 LLM 单次调用（**非 ReAct**） | 手册已经探到手，这一步是对着已知结构和求职条件做判断，不需要多轮自主——做成单次调用换来可单测、可 eval（spec §2.1） |
| 去哪个桶、还要不要翻页 | `scan_buckets` | **agent（ReAct）** | 桶内列表页长什么样、还有没有下一页因站而异，agent 只决定"去哪、翻不翻"，抓取和分类不占它的轮次 |
| 这个岗位算哪一类 | `classify_jobs` | 普通 LLM 调用（批量，**非 ReAct**） | 对已抓到的岗位批量判断类别，不碰浏览器、不需要多轮 |
| 找投递入口、上传简历（m2） | `open_application` | **agent（ReAct）** | 入口按钮的叫法/位置各站不同 |
| 解析快照里哪些是空字段 | `scan_and_classify_fields` | 代码 | 结构化解析，没有判断成分 |
| 字段分类（人口学/开放题/证件） | `scan_and_classify_fields` | LLM 单次调用 | 需要语义判断，但不需要多轮自主 |
| 取 personal_info 的值、写库 | `record_application` 等 | 代码 | 确定性映射 |

**硬边界**（代码强制，不是 prompt 叮嘱）：
1. **提交类点击被 `safe_tools.make_guarded_click` 拒绝。** 旧版靠"工具集里没有
   提交能力"守法；agent 拿到自由 `click` 之后那个守法就失效了（同一个工具既能点
   「申请」也能点「提交」），所以换成点击工具自己拦。见 safe_tools 模块 docstring。
   **这条只有配合下面第 2 条才成立**——守法点击拦得住 `click`，拦不住"换个工具做
   同一件事"。
2. **agent 只拿得到白名单里的 MCP 工具**（`_PASSTHROUGH_*`，按节点分开）。这在
   v2.22.1 之前是黑名单，于是 `evaluate_script`（任意 JS，一行就绕过守法点击）、
   `press_key`、`take_screenshot` 等 27 个工具全在 agent 手上，上面那条"代码强制"
   实际上是不成立的。见 DECISION.md 对应条目。
3. 除开放问题外，字段的候选值在 `_enforce_no_invented_values()` 里被无条件
   清空，不管 LLM 分类节点返回了什么。
4. 整个 Layer 1 的产出只有一条 `pending_applications` 待审批记录——不做任何对外
   动作。

只处理"上传简历解析后，第一个可见 wizard 步骤"里的空字段——分步表单不填完当前
步就进不去下一步，而 Layer 1 本身不填表单（那是 Layer 3 的职责），所以结构上只能
看到这一步。见 docs/multi-site-expansion-design.md 与 DECISION.md 对应记录。

用 LangGraph StateGraph 编排最外层（而不是一路到底的函数）是为了：①每个阶段独立
可观测；②浏览器自动化容易在任意一步失败，节点划分让失败定位更精确；③未来加
checkpointer 断点续跑有自然的挂载点（这次先不做，留着接口）。**节点内部**才是
agent 循环——两层结构：外层确定性编排，内层自主决策。
"""
import asyncio
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Literal, Optional, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from multisite import agent_runtime, chrome_mcp_client, preferences, safe_tools
from multisite.bucket_plan import plan_buckets as compute_bucket_plan
from multisite.classify import classify_jobs
from multisite.executors import validate_manual
from multisite.harvest import harvest_page
from multisite.observability import agent_step_sink, run_scope, traced_stage
from multisite.personal_info_loader import load_candidates, load_personal_info, match_value
from multisite.site_manual import ManualError, SiteManual
from services.console_utf8 import safe_print
from services.prompt_manager import PromptManager
from services.tracker import ApplicationTracker

# ── LLM 结构化输出。用 LangChain 的 with_structured_output（DeepSeek function
#    calling），不走项目自己的 ModelRouter——DeepSeek 走项目 OpenAICompatibleProvider
#    时会直接忽略 output_schema 参数，这里改用 LangChain 原生结构化输出更可靠。
#    这是本模块唯一游离于项目现有 LLM 路由之外的调用点，取舍见 DECISION.md。──

# unknown_fact = 事实性字段（学校、城市、日期…），但已知资料里没有 → 留空请人填。
# 没有这一档时，凡不在 personal_info 里的字段都会掉进 open_question，而
# open_question 的指令是"生成一段候选文本"——于是机器对着事实编答案。
_FieldKind = Literal["demographic", "open_question", "government_id", "unknown_fact"]


class FieldClassification(BaseModel):
    field_id: str
    kind: _FieldKind
    demographic_key: Optional[str] = None
    candidate_value: str = ""


class ClassifyFieldsOutput(BaseModel):
    fields: list[FieldClassification]


class FoundJob(BaseModel):
    """选岗 agent 找到的一个候选岗位。`why` 不是装饰——审批页上人要能看出 agent
    为什么认为它符合条件，否则"选错岗"这类新错误类型无从判断。"""
    url: str = Field(description="岗位详情页的完整 URL")
    title: str = Field(default="", description="岗位标题")
    company: str = Field(default="", description="公司名，页面上没有就留空")
    category: str = Field(default="", description="归到哪个方向，必须是 profile 里配置的类别之一")
    bucket: str = Field(default="", description="在站点的哪个招聘项目/顶层分类里找到的")
    why: str = Field(default="", description="一句话说明对上了哪几条求职条件")
    jd: str = Field(default="", description="职责详情正文——评分/审批页/eval 三个消费方都靠它")


class FindJobsOutput(BaseModel):
    jobs: list[FoundJob] = Field(default_factory=list)


class OpenApplicationOutput(BaseModel):
    """导航 agent 的自评。**刻意让 agent 自己报成败**：它比外面的代码更清楚自己
    卡在哪一步，而这个结论会被下游用来决定要不要继续扫描字段。"""
    form_opened: bool = Field(description="是否成功打开了申请表")
    resume_uploaded: bool = Field(description="简历是否上传成功")
    note: str = Field(default="", description="失败时卡在哪一步、页面上看到什么")


class ScannedElement(TypedDict):
    uid: str
    role: str
    label: str
    required: bool   # 页面上标了必填星号


_INPUT_ROLES = {"textbox", "combobox", "radio", "checkbox", "listbox", "searchbox"}
_SNAPSHOT_LINE_RE = re.compile(r'uid=(?P<uid>\S+)\s+(?P<role>\w+)(?:\s+"(?P<name>[^"]*)")?(?P<rest>.*)')
_VALUE_RE = re.compile(r'value="([^"]*)"')
_PLACEHOLDER_HINT_RE = re.compile(r"[YyMmDd\-/]+")


# ── graph state ───────────────────────────────────────────────────────────────

class Layer1State(TypedDict, total=False):
    # 输入：二选一。给 job_url = 直接处理这一个岗位（调试/复现用）；
    # 给 search_url = 让选岗 agent 从这个入口自己找（正常用法）。
    job_url: str
    search_url: str
    resume_pdf_path: str
    site_name: str
    job_title: str
    company: str
    # survey_structure 的产出：这个站怎么运作的结构化事实，plan_buckets/scan_buckets
    # 两个下游节点都读它。
    manual: SiteManual
    # plan_buckets 的产出：这一轮该扫哪几个桶，每项 {dimension, option, why, targets}。
    bucket_plan: list[dict]
    # 选岗 agent 的产出
    found_jobs: list[FoundJob]
    pending_job_ids: list[int]   # Checkpoint 1 落库后的 id（重复 url 不在内）
    # 本次要处理的岗位（found_jobs[0]）在 pending_jobs 里的 id，透传给 Checkpoint 2
    source_job_id: Optional[int]
    # 导航 agent 的产出
    open_result: OpenApplicationOutput
    snapshot_text: str
    # truncated: 这一段的 agent 循环是不是**步数耗尽**才停的（不是干完了）。
    # traced_stage 读它决定阶段状态是 partial 还是 successful。
    truncated: bool
    empty_elements: list[ScannedElement]
    classified_fields: list[FieldClassification]
    form_screenshot: str          # 表单整页截图文件名（给审批人看，不给 agent）
    pending_application_id: Optional[int]


# 纯数字（年份 2019、月份 09）、纯分隔符（- / ~ 等）。日期控件在 a11y 树里被拆成
# 一堆这样的 StaticText 平铺在输入框前面，是抢地标的主力。
_DIGITS_ONLY_RE = re.compile(r"^\d+$")
_PUNCT_ONLY_RE = re.compile(r"^[\s\-–—/~·:：.,，、|]+$")
# 字段名里至少得有一个字母或汉字。纯数字/纯符号的"名字"不是字段名。
_HAS_WORD_RE = re.compile(r"[A-Za-z一-鿿]")
# 长文本要不要当地标：光看长度分不开。真机同一张表单上有两个 17 字的串——
#   "您从哪些渠道了解到该岗位招聘信息？"   ← 真字段名（开放问题）
#   "无准确的毕业时间可填写预计毕业时间"    ← 页面说明文字
# 卡长度会连真字段名一起误杀（试过 12 字，那个问句就变成了前面的"邮箱"）。
#
# 区别在**收尾**：长的字段名几乎总是问句或以冒号提示后面要填什么；说明文字是
# 陈述句，没有这些收尾。短串（≤12）一律放行——"起止时间""学校名称"都是 4 字。
#
# 这是启发式，只在一张真实表单上调过。失败方式是：某个站的说明文字碰巧以问号结尾
# （会漏进来当字段名，表现为审批页多一项名字很怪的字段——看得见、能人工驳回），
# 或者某个长字段名不带问号（会被拒，地标回退到前一个字段名——表现为两个字段同名，
# 去重后少一项）。两种都比"给不存在的问题编答案"轻。
_SHORT_LANDMARK_LEN = 12
_LABEL_ENDINGS = ("？", "?", "：", ":")
# 文档结构节点，它们的 name 不是页面上给人看的文字标签。
_STRUCTURAL_ROLES = {"RootWebArea", "WebArea", "document"}


def _is_usable_landmark(name: str) -> bool:
    """这行文字能不能当"离它最近的字段名"用。

    真机踩过两次（都是同一个日期控件）：
      - `MM` / `YYYY` 这类格式提示抢走了「起止时间」的地标位；
      - 年月被拆成 `StaticText "2019"` `"-"` `"09"` 平铺在输入框前面，**离得比
        「起止时间」更近**，于是字段名成了 `09`。

    第二次的后果比第一次严重得多：`09` 被当成 open_question 交给 LLM，而 LLM
    拿到岗位上下文之后**认真编了一段期望薪资**——一个凭空生成的数字会跟着审批流
    走到 Layer 3，真填进企业表单。
    """
    if not name or name == "*":
        return False
    if _PLACEHOLDER_HINT_RE.fullmatch(name):      # YYYY / MM / DD
        return False
    if _DIGITS_ONLY_RE.fullmatch(name):           # 2019 / 09 / 11
        return False
    if _PUNCT_ONLY_RE.fullmatch(name):            # - / ~ ·
        return False
    if len(name) > _SHORT_LANDMARK_LEN and not name.endswith(_LABEL_ENDINGS):
        return False                              # 长陈述句 = 页面说明文字
    return True


_REQUIRED_STAR = ("*", "＊")


def _parse_rows(snapshot_text: str) -> list[dict]:
    """把 a11y 文本快照拆成结构化行。两个解析器共用——地标判据要往前看一行
    （见 `_accepts_landmark`），逐行流式处理做不到。"""
    rows = []
    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if m:
            rows.append({
                "uid": m.group("uid"),
                "role": m.group("role"),
                "name": (m.group("name") or "").strip(),
                "rest": m.group("rest") or "",
                "indent": len(line) - len(line.lstrip()),
            })
    return rows


def _has_descendant_value(rows: list[dict], i: int) -> bool:
    """复合控件的值挂在**子节点**上：下拉框外壳 `combobox` 自己没有 value，
    真正的值在缩进更深的那个 `textbox value="..."` 上。

    真机 2026-08-17：「学校名称」页面上明明已经由简历解析填好了，外壳没有 value
    就被判成空字段送进了 LLM——而 LLM 只能对着一个字段名编，编出来的是一句
    「请填写您的学校名称（例如：…）」。填写说明冒充答案，还可能覆盖掉正确值。
    """
    indent = rows[i]["indent"]
    for row in rows[i + 1:]:
        if row["indent"] <= indent:
            break
        m = _VALUE_RE.search(row["rest"])
        if m and m.group(1).strip():
            return True
    return False


def _accepts_landmark(rows: list[dict], i: int, latched: bool) -> bool:
    """rows[i] 这行文字能不能当"接下来那个输入框的字段名"。

    真机 2026-08-17：「意向城市」下面印着一行「最多可选 2 个城市」，它比字段名
    **更靠近**输入框，于是成了字段名——审批页上就出现了一个叫「最多可选 2 个城市」
    的字段。它只有 9 个字，卡长度那道闸（>12 字且不是问句）根本拦不住。

    区别不在长度，在**位置**：星号之后、输入框之前的文字是说明。所以星号一落下就
    上闩，闩住期间不再接受新地标；输入框来了才解闩（`_parse_empty_input_elements`
    里连必填标记一起吃掉——那个星号是它的，不能漏给下一个字段）。

    唯一能压过闩的是"后面紧跟星号"——那是字段名最硬的信号。没有这条例外，
    「手机号码 * +86 138-… 邮箱 * 输入框」这种版式里（手机号是纯展示、没有输入框，
    闩永远等不到解），「邮箱」会被闩住，输入框最后认领到的是手机号那一段。
    """
    row = rows[i]
    if row["role"] in _INPUT_ROLES or row["role"] in _STRUCTURAL_ROLES:
        return False
    if not _is_usable_landmark(row["name"]):
        return False
    if i + 1 < len(rows) and rows[i + 1]["name"] in _REQUIRED_STAR:
        return True
    return not latched


def _looks_like_field_label(label: str) -> bool:
    """这个名字像不像一个真的表单字段名。不像就整个丢掉这个元素。

    **宁可漏一个字段，也不要交出一个名字是垃圾的字段**：漏了的表现是"审批页上少
    一项"，人看截图能发现；而交出去的表现是"LLM 给一个不存在的问题编了个答案"，
    它会一路走到真实表单里，没人拦得住。两种错误的代价不对称。
    """
    label = (label or "").strip()
    return bool(label) and bool(_HAS_WORD_RE.search(label))


def _parse_empty_input_elements(snapshot_text: str) -> list[ScannedElement]:
    """从 a11y 树文本快照里，用正则筛出「值当前为空的输入类元素」。这一步是
    确定性代码，不用 LLM——「哪些行是候选表单元素」是结构化解析，真正需要判断
    的是"这个字段是什么意思、该填什么"，那部分交给 classify_and_generate 节点。

    radio 单独处理（`_parse_radio_groups`）：真机验证发现 chrome-devtools-mcp
    的快照里单选题**没有 radiogroup 包裹节点**，"推荐方式"这类问题标签和"无/
    内推/大使推荐"这类选项是平铺的同级行——如果照 textbox/combobox 那样每行
    独立处理，一个单选题会被拆成 N 个假字段（真机验证撞到过，见 DECISION.md）。

    无 accessible name 的元素落回"离它最近的文字地标"：真机验证撞到过不止一次
    （上传按钮、"学校名称"/"学历"/来源渠道这三个必填 combobox）——**如果直接跳过
    没有 name 的元素，这些必填字段会在 Layer 1 眼里完全隐形，Layer 2 审批时根本
    看不到这里还差着字段没填**，比"分类分错了"严重得多，不能只处理上传按钮那
    一个特例。地标沿用 `_parse_radio_groups` 同款启发式：最近一行非空、非"*"
    （必填星号，不是真地标）的文字。同一地标可能被同一逻辑字段的多层节点各贴
    一次（比如 combobox 外层 + 内层 textbox 都没 name），按 label 去重只保留第
    一次出现。
    """
    elements: list[ScannedElement] = []
    seen_labels: set[str] = set()
    landmark = ""
    # 自上一个**有效地标**以来见没见过必填星号。被拒的地标（数字碎片、说明文字）
    # 不重置它——「起止时间」的星号正好落在日期碎片前面，重置了就检测不到。
    required_seen = False
    # 星号落下就上闩，输入框来了才解闩。见 `_accepts_landmark`。
    latched = False
    # 自上一个地标以来见过纯数字碎片＝后面那个复合控件**已经选好了值**。
    # 见下面 `_DIGITS_ONLY_RE` 那一支。
    value_fragments = False
    rows = _parse_rows(snapshot_text)
    for i, row in enumerate(rows):
        role, name = row["role"], row["name"]

        if role not in _INPUT_ROLES:
            # RootWebArea 的 name 是**页面标题**（"投递简历 - 欢迎加入 XX"），
            # 是文档根节点不是页面上的文字标签。真实快照里因为标题和第一个输入框
            # 之间总隔着别的文字所以没露馅，但它随时可能变成某个字段的名字。
            if name in _REQUIRED_STAR:
                required_seen = True
                latched = True
            elif _accepts_landmark(rows, i, latched):
                landmark = name
                required_seen = False
                value_fragments = False
            elif _DIGITS_ONLY_RE.fullmatch(name):
                # 日期这类复合控件**已经选好**的值是平铺在输入框前面的 StaticText
                # （"2019" "-" "09"），输入框自己永远是空的。没填的时候这里是
                # `YYYY` / `MM` 格式占位符——数字 vs 占位符，正好把两种状态分开。
                value_fragments = True
            continue

        # 走到这里一定是输入类元素。**先把星号和闩吃掉**——不管这一行最后有没有
        # 产出字段（可能已经有值、可能跟前面重名），前面那个星号都是它的；漏给
        # 下一个字段的表现是"一个选填项被标成必填"，真机上就这么发生过。
        is_required = required_seen or "*" in name
        had_value_fragments = value_fragments
        required_seen = False
        latched = False
        value_fragments = False
        if role == "radio":
            continue  # 单选题统一交给 _parse_radio_groups

        value_m = _VALUE_RE.search(row["rest"])
        current_value = value_m.group(1) if value_m else ""
        if current_value.strip():
            continue  # 已有值（含简历解析自动回填的），不需要 Layer 1 处理
        if _has_descendant_value(rows, i):
            continue  # 值挂在内层节点上，外壳没有——照样是"已填"
        if not name and had_value_fragments:
            continue  # 没有自己名字的输入框 + 前面摆着已选好的值 = 复合控件，已填

        label = name or landmark
        if not label or label in seen_labels:
            continue  # 既没自己的名字也没地标可用，或者是同一字段的重复节点
        if not _looks_like_field_label(label):
            # 最后一道闸：宁可漏一个字段，也不要交出一个名字是垃圾的字段。
            # 见 _looks_like_field_label 的说明——上一版放它过去的后果是 LLM
            # 给「09」编了一段期望薪资。
            continue
        seen_labels.add(label)
        elements.append({"uid": row["uid"], "role": role, "label": label,
                         "required": is_required})
    elements.extend(_parse_radio_groups(snapshot_text))
    return elements


def _parse_radio_groups(snapshot_text: str) -> list[ScannedElement]:
    """把连续的 radio 行聚成一个逻辑单选题，而不是每个选项各算一个字段。

    没有 radiogroup 包裹，只能靠顺序启发式：单选题标签是紧挨着第一个 radio 前面
    的那一行非 radio 文本（真机验证里是 `StaticText "推荐方式"`）；选项自带的
    `StaticText "无"` 这类和刚出现过的 radio 同名的重复文本行不算新地标，不会
    打断当前组。任意一个选项带 `checked`（已选中）就整题跳过——已经有答案，
    不需要 Layer 1 处理。
    """
    groups: list[ScannedElement] = []
    landmark_name = ""
    required_seen = False
    latched = False
    active: Optional[dict] = None  # {"uid","label","any_checked"}
    last_radio_name = None
    rows = _parse_rows(snapshot_text)

    def _flush():
        if active is not None and not active["any_checked"]:
            groups.append({"uid": active["uid"], "role": "radio", "label": active["label"],
                           "required": bool(active.get("required"))})

    for i, row in enumerate(rows):
        role, name = row["role"], row["name"]
        if role == "radio":
            if active is None:
                active = {"uid": row["uid"], "label": landmark_name or name,
                          "any_checked": False, "required": required_seen}
            if "checked" in row["rest"]:
                active["any_checked"] = True
            last_radio_name = name
            # 单选题也是输入元素：它吃掉前面那个星号和那道闩。
            required_seen = False
            latched = False
            continue
        # 非 radio 行：跟刚才那个选项同名就当装饰性重复，不打断当前组；
        # 否则视为下一个单选题的候选地标，并把当前组收尾。
        # 地标可用性走跟 _parse_empty_input_elements 同一个判据——两处各写一套的话，
        # 修好了一边另一边照样会把 `09` 当字段名（同一个日期控件两条路径都路过）。
        if name in _REQUIRED_STAR:
            required_seen = True
            latched = True
            continue
        if name and name != last_radio_name:
            if active is not None:
                _flush()
                active = None
                last_radio_name = None
            if _accepts_landmark(rows, i, latched):
                landmark_name = name
                required_seen = False
    _flush()
    return groups


def _extract_text(tool_result) -> str:
    """chrome-devtools-mcp tool results come back through langchain_mcp_adapters
    as either a plain str (single text content block) or a list of content-block
    dicts (multiple blocks) -- never guess which, always normalize here."""
    if isinstance(tool_result, str):
        return tool_result
    if isinstance(tool_result, list):
        return "\n".join(
            block.get("text", "") for block in tool_result
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(tool_result)


_DEBUG_DIR = Path(__file__).resolve().parent.parent / "data" / "multisite_debug"


def _dump_debug_snapshot(tag: str, snapshot_text: str, target_dir: Optional[Path] = None) -> None:
    """调试用：某个定位失败时把当时的原始 a11y 快照存下来，省得只能靠报错
    字符串猜页面长什么样——上一次真机排查就是因为没有这个才多跑了一轮。

    `target_dir` 不给就落回老位置 `data/multisite_debug/`（图之外的调用点还在用它）。
    run 里的失败走 `logs/runs/{run_id}/`：那是 run 证据，跟 run 同生死、整目录删得干净
    （见 spec §7.5）。
    """
    dest = Path(target_dir) if target_dir is not None else _DEBUG_DIR
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{tag}.txt").write_text(snapshot_text, encoding="utf-8")


_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "multisite_screenshots"

# 注入的样式表 id 和打标属性名：解锁和还原必须用同一份名字，散成两处必漂移。
_UNLOCK_NAMES = {
    "style": "__ojf_capture_unlock__",
    "mark": "data-ojf-capture-unlock",
    "fixed": "data-ojf-capture-fixed",
}

# 判据是"谁在滚"（overflowY + scrollHeight > clientHeight），不是某个站点的 class 名。
# 拓竹那个容器叫 `section.atsx-layout`，写死它等于只修好这一个站。
# position:fixed 一并落到文档流：整页截图里那种"提交"悬浮条会停在原视口底部，
# 正好压住一整行字段（真机看到它盖掉了「您从哪些渠道了解到该岗位招聘信息？」）。
_UNLOCK_JS = """() => {
  document.querySelectorAll('*').forEach(el => {
    const cs = getComputedStyle(el);
    const oy = cs.overflowY;
    if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
        && el.scrollHeight > el.clientHeight + 20) {
      el.setAttribute('%(mark)s', '1');
    }
    if (cs.position === 'fixed') el.setAttribute('%(fixed)s', '1');
  });
  const st = document.createElement('style');
  st.id = '%(style)s';
  st.textContent =
    'html,body{height:auto!important;max-height:none!important;overflow:visible!important}'
    + '[%(mark)s]{height:auto!important;max-height:none!important;overflow:visible!important}'
    + '[%(fixed)s]{position:absolute!important}';
  document.head.appendChild(st);
  return {docScrollHeight: document.documentElement.scrollHeight};
}""" % _UNLOCK_NAMES

_RESTORE_JS = """() => {
  const st = document.getElementById('%(style)s');
  if (st) st.remove();
  document.querySelectorAll('[%(mark)s],[%(fixed)s]').forEach(el => {
    el.removeAttribute('%(mark)s');
    el.removeAttribute('%(fixed)s');
  });
  return {docScrollHeight: document.documentElement.scrollHeight};
}""" % _UNLOCK_NAMES


async def capture_form_screenshot(tools, dest_dir: Path = _SCREENSHOT_DIR) -> str:
    """给当前表单拍一张**完整**截图，返回存进 dest_dir 的文件名。

    **代码拍，不是 agent 拍。** DeepSeek 没有视觉，`take_screenshot` 也刻意不在
    agent 的工具白名单里——这张图是给**审批人**看的：字段名本身常常不足以判断
    该填什么（「学校名称」是问本科还是硕士？），得看它在页面上处于哪个分区。

    **`fullPage` 一个人不够。** 它量的是 `documentElement/body.scrollHeight`；
    站点把表单放进内部滚动容器时（拓竹 2026-08-17：容器 clientHeight 1269 /
    scrollHeight 2403，而文档本身恒等于视口高度），fullPage 拍出来就是视口截图，
    只有上半页——而审批人真正要核对的「学校名称」「起止时间」全在下半页。
    所以先临时解锁页面上所有真正在滚的容器，让文档自己变长，再 fullPage。

    改动是临时的，`finally` 里一定还原：留在页面上会让之后的 agent 操作面对一个
    变形的表单。解锁失败则整个放弃这次截图——半截图比没有更糟，它会让审批人以为
    "表单就这些字段"。截图失败不阻断流程：为一张辅助图丢掉整条待审批记录不划算。

    先写系统临时目录再搬——chrome-devtools-mcp 没协商 MCP roots 时把文件写限制在
    OS temp，直接给项目内路径会被它自己拒掉（`upload_file` 已经栽过一次）。
    """
    try:
        evaluate = chrome_mcp_client.get_tool(tools, "evaluate_script")
        shot_tool = chrome_mcp_client.get_tool(tools, "take_screenshot")
        tmp = Path(tempfile.gettempdir()) / f"ojf_form_{os.getpid()}_{int(time.time())}.png"

        await evaluate.ainvoke({"function": _UNLOCK_JS})
        try:
            await shot_tool.ainvoke({"filePath": str(tmp), "fullPage": True, "format": "png"})
        finally:
            await evaluate.ainvoke({"function": _RESTORE_JS})

        if not tmp.is_file():
            return ""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d_%H%M%S')}_form.png"
        shutil.move(str(tmp), str(dest_dir / name))
        return name
    except Exception as exc:  # noqa: BLE001 — 见 docstring：截图失败不该毁掉整次 run
        # safe_print 而不是 print：异常消息的内容不受我们控制（其余几处打的
        # 都是固定文案 + 整数，不会有写不出去的字符）。
        safe_print(f"[layer1] 表单截图失败（不影响落库）：{exc}", flush=True)
        return ""


# 根节点那一行。标题与 url 是同一行上**互相独立**的两样东西——中间可能夹着别的属性，
# 也可能只有其中一个（页面没渲染时是 `RootWebArea url="about:blank"`，根本没有标题）。
# 用位置把它们绑在一起，真机上就出现过 title 有值而 url 为空（2026-08-18）。
_ROOT_LINE_RE = re.compile(r"^.*RootWebArea.*$", re.M)
_ROOT_TITLE_RE = re.compile(r'RootWebArea\s+"([^"]*)"')
_URL_ATTR_RE = re.compile(r'url="([^"]*)"')


def _describe_page(snapshot_text: str) -> dict:
    """`ensure_ready` 的产出：它把浏览器带到了哪个页面。

    以前这一步只报 `snapshot_chars`（快照字符数）。那个数字只能回答"页面渲染了吗"，
    答不了任何你实际会问的问题——停在哪个 URL、标题是什么。而这两样就在快照第一行
    （`RootWebArea "标题" url="..."`），一直白放着。

    字符数保留为**次要信号**：判断"是不是空壳"仍然只有它能便宜地回答。
    解析不到根节点不抛异常——这一步的职责是导航，不是解析快照。
    """
    line_m = _ROOT_LINE_RE.search(snapshot_text or "")
    line = line_m.group(0) if line_m else ""
    title_m = _ROOT_TITLE_RE.search(line)
    # url 只在**根节点那一行**上找：子节点（链接）也带 url=，全文搜会抓到别处去。
    url_m = _URL_ATTR_RE.search(line)
    return {
        "url": url_m.group(1) if url_m else "",
        "title": title_m.group(1) if title_m else "",
        "snapshot_chars": len(snapshot_text or ""),
    }


def _looks_blank(snapshot_text: str) -> bool:
    """about:blank 或还没渲染出任何实质内容的空壳快照。"""
    return 'url="about:blank"' in snapshot_text or len(snapshot_text.strip().splitlines()) <= 2


def _looks_logged_out(snapshot_text: str) -> bool:
    lowered = snapshot_text.lower()
    return "登录" in snapshot_text or "login" in lowered or "sign in" in lowered


# ── MCP 原生工具白名单，按节点分开 ────────────────────────────────────────────
#
# **必须是白名单，不能是黑名单。** 这里原本写的是
# `[t for t in tools if t.name not in {"take_snapshot", "click"}]`，
# 结果 chrome-devtools-mcp 那 29 个工具里的另外 27 个全交给了 agent，其中：
#   - `evaluate_script`：任意 JS，`document.querySelector(...).click()` 一行就
#     绕过 make_guarded_click，"提交防线是代码强制"这句话直接不成立；
#   - `press_key`：输入框里回车在多数表单上等于提交；
#   - `take_screenshot`：DeepSeek 没有视觉，返回的图像块不但白烧一步，还因为不在
#     `agent_runtime._BULKY_TOOLS` 里而永远不会被裁剪，卡死 64k 上下文；
#   - `fill` / `fill_form` / `type_text`：选岗阶段根本不该填任何东西。
# 黑名单挡不住"同一件事换个工具做"——每次 MCP 上游加一个新工具，黑名单就自动漏一个。
# 详见 DECISION.md 对应条目。
# 标签页管理。**不是可有可无的补充**：join.qq.com 的岗位卡片点开是新标签页，
# 而 `take_snapshot` 只返回当前选中的那一页——点完页面一字未变，agent 拿不到
# 任何"发生过什么"的信号，真机上就是这么卡进死循环的（2026-08-19）。
# 这三个都不可能提交表单，不动 `make_guarded_click` 守的那条线。
_PASSTHROUGH_TABS = ("list_pages", "select_page", "close_page")

_PASSTHROUGH_FIND_JOBS = ("navigate_page", "wait_for", *_PASSTHROUGH_TABS)
_PASSTHROUGH_OPEN_APPLICATION = ("navigate_page", "wait_for", "upload_file",
                                 *_PASSTHROUGH_TABS)

# 图节点的名字与顺序。**第二个消费方是前端第 2 层骨架**（经 /api/multisite/stages），
# 所以它不能只活在 build_select_graph / build_survey_graph 的局部变量里。真正的
# 函数与 summarizer 仍在 `_make_nodes` 返回的节点工厂字典里，两者由 `_compile`
# 建图时对着 `stage_names()` 的对账保证不漂移。
#
# 两张图各自完整的节点顺序。**刻意不写成「m2 = m1 + 后缀」**——那正是拆图前的形状
# （`STAGE_ORDER[:3]`），它把一个错误的假设编码进了代码：m2 根本不选岗，它拿到的是
# 调用方指定的那一个岗位，`find_jobs` / `write_pending_jobs` 在 m2 里是幽灵节点。
#
# m1 三站拆五站（2026-08-20）：原来的 `find_jobs` 是一个巨大的 ReAct 节点，混着
# 性质完全不同的三件事——摸清站点结构（探索）、决定打哪几个桶（纯判断，不碰
# 浏览器）、逐条读岗位判类别落袋（机械+判断）。三件事共享一个步数预算、一个
# 完成判据，表现是"一段跑飞就把整轮预算吃光"，前端也只看得到"find_jobs 卡住了"。
# 拆成 survey_structure（ReAct，产出站点手册）/ plan_buckets（普通 LLM 调用，
# 不是 ReAct，可单测可 eval）/ scan_buckets（ReAct，逐桶调 harvest 工具）三站，
# 各自独立的步数预算和完成判据。详见
# docs/superpowers/specs/2026-08-19-m1-survey-plan-scan-design.md。
M1_STAGES = ("ensure_ready", "survey_structure", "plan_buckets", "scan_buckets",
             "write_pending_jobs")
M2_STAGES = ("ensure_ready", "open_application",
             "scan_and_classify_fields", "write_pending_application")

_STAGES_BY_WORKFLOW = {"m1": M1_STAGES, "m2": M2_STAGES}


def stage_names(workflow: str) -> tuple[str, ...]:
    """这个 workflow 会经过哪些图节点。前端第 2 层「地铁站」的骨架来源。

    未知 workflow 直接抛——静默返回空元组会让前端画出一张空骨架，
    跟「后端还没开始跑」长得一模一样。
    """
    try:
        return _STAGES_BY_WORKFLOW[workflow]
    except KeyError:
        raise ValueError(f"未知 workflow: {workflow!r}，只有 {sorted(_STAGES_BY_WORKFLOW)}") from None


@contextmanager
def staged_resume(resume_pdf_path: str):
    """把简历复制进系统临时目录，产出一个 chrome-devtools-mcp 允许读的路径。

    **为什么必须做这一步**：没协商 MCP roots capability 时，chrome-devtools-mcp 把
    文件操作限制在 OS 临时目录，`upload_file` 传项目内的路径会被它自己拒掉：
        Error: Access denied: path C:\\...\\exports\\xxx.pdf is not within
               the configured workspace roots
    启动时那行 "File-writing tools will be restricted to the OS temp directory"
    的警告说的就是这件事，我一直看见但没当回事，直到第一次真跑 open_application
    才撞上（2026-08-15）。

    **否掉了 `--allow-unrestricted-paths`**：那是给 agent 放开整个文件系统的读写，
    跟这一版刚做的工具白名单收窄正好相反。agent 只需要能读"我们明确交给它的那一份
    简历"，不需要读别的——复制一份进 temp 恰好就是这个语义。

    跑完删掉：临时目录里躺一份带真实个人信息的简历不合适。
    """
    src = Path(resume_pdf_path)
    if not src.is_file():
        raise FileNotFoundError(f"简历 PDF 不存在: {resume_pdf_path}")
    staged = Path(tempfile.gettempdir()) / f"ojf_resume_{os.getpid()}{src.suffix}"
    shutil.copy2(src, staged)
    try:
        yield str(staged)
    finally:
        staged.unlink(missing_ok=True)


def make_record_open_result_tool(sink: dict) -> "object":
    """导航 agent 汇报"表单打开了没、简历传上去了没"。

    **本来是用 `create_react_agent(response_format=...)` 做的，那条路在 DeepSeek 上
    直接不通**：LangGraph 的结构化输出节点写死了 `with_structured_output(schema)`
    不带 `method=`，ChatOpenAI 默认走 json_schema，而 DeepSeek 返回
    `400 This response_format type is unavailable now`（2026-08-15 首次真机跑
    open_application 撞到）。没有任何参数能把 method 传进去。

    改成工具上报，跟 `record_job` / `record_site_limit` 同一个套路——那两个在
    DeepSeek 上一直好用。顺带拿到同样的好处：**agent 半途没步数了，已经报上来的
    结论照样拿得到**，不像结构化输出那样必须跑到最后一步才有结果。
    """
    from langchain_core.tools import StructuredTool

    async def record_open_result(form_opened: bool, resume_uploaded: bool, note: str = "") -> str:
        sink.update({"form_opened": bool(form_opened),
                     "resume_uploaded": bool(resume_uploaded),
                     "note": (note or "").strip()[:500]})
        return "已记录本次结果。如果还有没做完的就继续；都做完了就结束，不用再调用任何工具。"

    return StructuredTool.from_function(
        coroutine=record_open_result,
        name="record_open_result",
        description=(
            "汇报申请表打开/简历上传的结果。**做完或卡住时都要调用一次**："
            "form_opened=申请表是否打开了，resume_uploaded=简历是否上传成功，"
            "note=失败时卡在哪一步、页面上看到什么。"
        ),
    )


def make_record_site_limit_tool(tracker, site_name: str) -> "object":
    """让 agent 把"这个站最多能投几个"报回来。

    **为什么是机会性发现、不专门去找**：不是每个站都有这类限制；专门加一步"翻投递
    须知"在没有限制的站上是纯浪费步数，而且找不到时**依然分不清"没有限制"和"没
    找到"**——多花的步数买不到确定性。

    `evidence` 必填且要求原文：「agent 说上限是 3」和「页面上写着"校招每人最多投递
    3 个岗位"」是两回事，前者没法核对。理由跟 record_job 外置结果完全一样。

    直接写库而不是像 record_job 那样先进 sink：这是一次按站点 upsert 的幂等写入，
    没有批量、没有审批语义，也不需要跟 run 的其他产出一起提交，穿一个 sink 过两个
    节点只是多一层。
    """
    from langchain_core.tools import StructuredTool

    async def record_site_limit(status: str, evidence: str, scope: str = "unclear",
                                scope_name: str = "", limit: int = 0,
                                applied_count: int = -1) -> str:
        status = (status or "").strip()
        scope = (scope or "unclear").strip()
        if status not in ("no_limit", "limited"):
            return ("记录失败：status 只能是 'limited'（看到了具体数量上限）或 "
                    "'no_limit'（明确写了不限量）。**没看到相关说明就根本不要调用这个工具**，"
                    "不用报 unknown。")
        if not (evidence or "").strip():
            return "记录失败：evidence 必须是页面上的原文，照抄那句话，不要自己转述。"
        if status == "limited" and limit < 1:
            return "记录失败：status='limited' 时 limit 必须是页面上写的那个数字（>=1）。"
        if scope not in ("site", "bucket", "unclear"):
            return ("记录失败：scope 只能是 'site'（全站通用）、'bucket'（只管某个招聘项目，"
                    "并填 scope_name）或 'unclear'（页面没写清楚）。")
        if scope == "bucket" and not (scope_name or "").strip():
            return "记录失败：scope='bucket' 时必须填 scope_name，就是那个招聘项目的名字。"
        tracker.upsert_site_limit(
            site_name=site_name,
            status=status,
            scope=scope,
            scope_name=scope_name.strip()[:80],
            max_applications=limit if status == "limited" else None,
            applied_count=applied_count,
            evidence=evidence.strip()[:500],
        )
        shown = f"最多 {limit} 个" if status == "limited" else "不限量"
        where = {"site": "全站", "bucket": f"「{scope_name}」这个招聘项目内",
                 "unclear": "范围不明"}[scope]
        return f"已记下投递限制：{where} {shown}。这条不用再报第二次。"

    return StructuredTool.from_function(
        coroutine=record_site_limit,
        name="record_site_limit",
        description=(
            "看到关于「一个人最多能投递几个岗位」的说明时调用一次。"
            "status='limited' 并给出 limit 数字，或 status='no_limit'（明确写了不限）。"
            "evidence 照抄页面原文。"
            "**scope 是这条限制管多大范围，你自己判断**："
            "'site'=全站通用；'bucket'=只管某个招聘项目/分类（把项目名填进 scope_name）；"
            "'unclear'=页面没写清楚。"
            "注意「在XX项目中最多投递N次」这种写法是 bucket 不是 site。"
            "**说不清就填 unclear，不要猜成 site**——猜错会让名额算错。"
            "页面还写了已投递数量的话一并填 applied_count。没看到相关说明就不要调用。"
        ),
    )


def make_record_site_brief_tool(tracker, site_name: str) -> "object":
    """让选岗 agent 在收尾时写一段这个站的现场笔记。

    **为什么值得单开一个工具**：agent 跨 run 没有记忆，每次都要重新发现"这站怎么
    分类的、要不要登录、投递有什么讲究"。把它记下来喂回下次的 prompt，跟 golden
    examples 是同一个思路——用真实观察替代我预先想象的规则。

    **它不是事实源**：真要拿来算数的东西（投递上限）有自己的结构化字段
    （`record_site_limit`）。这里是自由文本，只给人看、给下次的 agent 当背景。
    两者混在一起的话，"agent 随口写的一句话"和"页面上抄下来的数字"就分不开了。
    """
    from langchain_core.tools import StructuredTool

    async def record_site_brief(brief: str) -> str:
        text = (brief or "").strip()
        if len(text) < 10:
            return "记录失败：brief 太短了，用几句话说清这个站的分类方式、登录要求、投递讲究。"
        tracker.upsert_site_brief(site_name, text[:1200])
        return "已记下这个站的说明。下次再来这个站时你会先看到它。"

    return StructuredTool.from_function(
        coroutine=record_site_brief,
        name="record_site_brief",
        description=(
            "**结束前调用一次**，用几句话记下这个招聘网站的情况，供下次参考："
            "岗位是怎么分类的（有哪些招聘项目/大类）、要不要登录、投递次数有什么讲究、"
            "有没有什么坑（比如某个筛选器会把整类岗位藏起来）。写你**实际看到的**，"
            "不确定的就说不确定。"
        ),
    )


class _ManualDimensionInput(BaseModel):
    """`record_site_manual` 里 `dimensions` 一项的输入形状。**独立于
    `SiteManual.dimensions`**（那是宽松的 `list[dict]`，代码内部消费）——工具入参
    需要一份 pydantic 形状给 LangChain 校验 agent 传的结构化参数，两者字段虽然同名，
    但一个是"agent 汇报的接口"，一个是"代码执行的数据结构"，没有必要合并成一份。"""
    name: str = Field(description="维度名字，页面上筛选器的原文，比如「应聘项目」「工作地点」")
    options: list[str] = Field(default_factory=list, description="这个维度下所有选项的原文文字")
    multi_select: bool = Field(default=False, description="这个维度能不能同时勾多个（多选）；不确定就填 false")


# 必填四项——SiteManual.from_dict 的 _ENUMS 就是这四个，这里只是拿它们的名字
# 给 agent 报进度用，不重复它们的取值校验（校验唯一走 from_dict）。
_REQUIRED_MANUAL_FIELDS = ("job_url_source", "pagination", "filter_interaction", "row_split")

# 展示顺序：跟工具签名/docstring 里介绍字段的顺序保持一致，方便 agent 对照着看。
_ALL_MANUAL_FIELDS = (
    "job_url_source", "pagination", "filter_interaction", "row_split",
    "filters_survive_reload", "url_template", "total_count_locator", "row_anchor",
    "dimensions", "important_notes",
)


def _merge_manual_fields(fields: dict, **updates) -> None:
    """把这次调用里**非空**的字段并入累积的 `fields`（就地修改）。

    空值（None / 空串 / 空列表）一律跳过，**绝不覆盖已经确定的值**——agent 是
    分好几次报的，一次只报自己这次弄清楚的那部分，没提到的字段不代表"改成空"，
    只是这次没有新信息。`filters_survive_reload` 是唯一的例外：它的两个合法取值
    `True`/`False` 都不是"空"，用 `None`（工具签名的默认值）表示"没提供"。
    """
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        fields[key] = value


def _manual_progress_text(fields: dict, exc: Optional[ManualError]) -> str:
    """报给 agent 的进度：已经确定了哪几项、必填还差哪几项、（如果凑齐了必填但
    组合仍不合法）`SiteManual.from_dict` 抛出的原文。

    **只做"字段是否非空"这种存在性检查，不重新判断字段值合不合法**——合法性
    校验的唯一实现是 `SiteManual.from_dict`，这里的"必填还差"只是把它必然会
    因为某个必填字段为空而报错这件事，翻译成 agent 能一眼看懂的清单，不是
    另一份闭集规则。
    """
    confirmed = [k for k in _ALL_MANUAL_FIELDS if fields.get(k) not in (None, "", [])]
    missing = [k for k in _REQUIRED_MANUAL_FIELDS if not fields.get(k)]
    parts = [f"已确认：{', '.join(confirmed) if confirmed else '（无）'}"]
    if missing:
        parts.append(f"必填还差：{', '.join(missing)}")
    if exc is not None:
        parts.append(f"校验未通过：{exc}")
    return "\n".join(parts)


def make_record_site_manual_tool(sink: dict) -> "object":
    """让勘察 agent 把探到的站点操作手册结构化报回来——**随时落袋，不是最后一次性
    交卷**。

    **这是本项目第三次撞上"全有或全无"逼 agent 不收尾的坑**（PITFALLS 有整条记录，
    `record_job` 是第一次治好的样子）：早先这里要求 `job_url_source` /
    `pagination` / `filter_interaction` / `row_split` 四个必填参数一次性齐全才能
    调用一次，真机 19 轮全在做正事却因为凑不齐全部字段而从没成功调用，最后只交了
    一段总结文本、零工具调用。现在全部参数可选、探到一点报一点，`sink["fields"]`
    跨调用累积（非空字段合并，空值不覆盖已有值，见 `_merge_manual_fields`）；每次
    调用都尝试 `SiteManual.from_dict(fields)`：齐了就告诉 agent"手册已完整、可以
    结束了"，没齐就把**已确认/还差什么**的进度连同（如果有）`ManualError` 原文一起
    退回去，进度是 agent 判断"还要不要继续探"的主要信号，不用它自己记账。

    **校验只走 `SiteManual.from_dict`，不重新写一遍闭集规则**——那份校验已经是
    "手册要被代码执行"这条约束的唯一实现，这里重新写一份闭集校验就是同一条规则
    两份实现，改一处漏一处的经典形状。
    """
    from langchain_core.tools import StructuredTool

    async def record_site_manual(
        job_url_source: str = "",
        pagination: str = "",
        filter_interaction: str = "",
        row_split: str = "",
        filters_survive_reload: Optional[bool] = None,
        url_template: str = "",
        total_count_locator: str = "",
        row_anchor: str = "",
        dimensions: Optional[list[_ManualDimensionInput]] = None,
        important_notes: str = "",
    ) -> str:
        fields = sink.setdefault("fields", {})
        _merge_manual_fields(
            fields,
            job_url_source=job_url_source,
            pagination=pagination,
            filter_interaction=filter_interaction,
            row_split=row_split,
            filters_survive_reload=filters_survive_reload,
            url_template=url_template,
            total_count_locator=total_count_locator,
            row_anchor=row_anchor,
            dimensions=([{"name": d.name, "options": d.options, "multi_select": d.multi_select}
                         for d in dimensions] if dimensions is not None else None),
            important_notes=important_notes,
        )
        try:
            manual = SiteManual.from_dict(fields)
        except ManualError as exc:
            return "尚未记全，继续探。\n" + _manual_progress_text(fields, exc)
        sink["manual"] = manual
        return "手册已完整，可以结束了，不用再调用任何工具。\n" + _manual_progress_text(fields, None)

    return StructuredTool.from_function(
        coroutine=record_site_manual,
        name="record_site_manual",
        description=(
            "把探到的站点结构**边探边报**，探到哪项就调用一次报哪项，不用等全部搞清楚"
            "才第一次调用——多次调用会自动累积，已经报过的字段不用重复报，"
            "返回值会告诉你已确认什么、还差什么，照它决定下一步，不用自己记账。"
            "字段解释：\n"
            "job_url_source：怎么拿到岗位详情页 URL —— link_in_row（卡片本身就是带 url 的链接）/ "
            "new_tab_on_click（点了在新标签页打开，需配合 list_pages/select_page 确认）/ "
            "id_template（URL 靠一个数字 ID 拼出来，配合 url_template 用，须含 {id} 占位符）。\n"
            "pagination：next_button / url_param / infinite_scroll / none。\n"
            "filter_interaction：direct_click（选项直接可点） / expand_group_then_click"
            "（要先点开分组才能点选项）。\n"
            "row_split：目前只支持 anchor_text——给 row_anchor 填一段每个岗位行里必现"
            "且仅现一次的文字。真的找不到规律就不要硬填，可以只报你确定的其他字段"
            "并在 important_notes 里说明卡在哪，不要为了凑齐而编。\n"
            "total_count_locator：读「共 N 个岗位」这类计数文本的正则，须带一个数字捕获组"
            "（如 `共(\\d+)个岗位`）；没有这类计数就留空。\n"
            "dimensions：筛选维度列表，每项给 name/options/multi_select；multi_select 只能"
            "靠试探判定（勾一个、回读总数、再勾一个、看总数怎么变），不确定就填 false。\n"
            "important_notes：以上字段都装不下的情况才写，正常情况留空。"
        ),
    )


def build_agent_toolset(
    tools: list,
    snapshot_provider,
    snapshot_taker,
    passthrough: tuple,
) -> list:
    """agent 能拿到的工具集：受控的 `take_snapshot` + 守法的 `click` + `passthrough`
    里点名的那几个 MCP 原生工具，**别的一律不给**。

    `passthrough` 走 `chrome_mcp_client.get_tool`（点名取，取不到就抛）而不是过滤，
    这样 MCP 上游改了工具名会在这里当场炸掉，而不是静默少给 agent 一个工具、
    表现为"agent 莫名其妙不会翻页了"。

    **抽成模块级函数（而不是留在 build_graph 的闭包里）就是为了能单测。**
    整个模块最危险的一条不变量是"agent 拿到的 click 必须是守法版、且没有别的
    路子绕过它"——守法本身有测试（tests/test_safe_tools.py），但"守法有没有真的
    接上去""有没有从别的工具漏出去"如果测不到，改坏了不会有任何东西变红。
    """
    from langchain_core.tools import StructuredTool

    async def _snap() -> str:
        return await snapshot_taker()

    snap_tool = StructuredTool.from_function(
        coroutine=_snap,
        name="take_snapshot",
        description="给当前页面拍一张可访问性树快照，返回带 uid 的元素列表。点击/导航之后必须重新拍。",
    )
    guarded_click = safe_tools.make_guarded_click(
        chrome_mcp_client.get_tool(tools, "click"),
        snapshot_provider,
    )
    allowed = [chrome_mcp_client.get_tool(tools, name) for name in passthrough]
    # 每个工具都包一层防循环。**逐个包而不是只包 click**：真机（join.qq.com）循环
    # 的是 click，但同一个死法换成 navigate_page 或 wait_for 一模一样会发生——
    # 循环是 agent 的行为模式，不是某个工具的属性。
    # 包在**最外层**，所以它看到的是 guarded_click 的最终返回值；`REFUSED:` 不以
    # Error 开头、不计入失败，那条路本来就已经明确叫它别再试了。
    return [safe_tools.make_repeat_failure_guard(t)
            for t in (snap_tool, guarded_click, *allowed)]


# 注：`_find_uid_by_label` / `_find_uid_near_text` 于 v2.22.0 删除。它们是旧版
# "代码写死点哪个 uid"路线的产物——找投递入口/上传控件现在由 agent 自己看页面
# 决定（DECISION.md 记的方向调整）。按标签定位元素这件事本身在 Layer 3 的"代码
# 填写"工具里还会需要，但那时的输入是**审批过的字段名**而不是猜出来的关键词，
# 语义不同，届时重写即可，不留一个没有消费方的函数在这里等着被误用。


# 只有 open_question 允许带一段"生成"的值。demographic 的值由 record_application
# 从 personal_info 取（不经 LLM），另外两类一律留空。
_VALUE_ALLOWED_KINDS = ("open_question",)


def _enforce_no_invented_values(fields: list[FieldClassification]) -> list[FieldClassification]:
    """硬约束：除了开放问题，谁都不许带一段 LLM 生成的值。见模块 docstring。

    government_id 是老约束（证件号绝不代填）。`unknown_fact` 是 2026-08-17 补的：
    在那之前 kind 只有三档，"事实性字段、但资料里没有"没有地方可去，于是全部落进
    open_question——而 open_question 的指令是"生成一段候选文本"。真机结果是
    「学校名称」拿到了「请填写您的学校名称（例如：…）」，一句填写说明冒充答案。

    补桶是 prompt 的事，兜底是代码的事：prompt 不听话的那一次，值也不该漏出去。
    """
    for f in fields:
        if f.kind not in _VALUE_ALLOWED_KINDS and f.candidate_value:
            f.candidate_value = ""
    return fields


def job_from_state(state: dict) -> tuple[str, str, str]:
    """m2 要处理的那个岗位：`(url, title, company)`，**只从 state 直接读**。

    **不读 `found_jobs`。** 拆图之后 m2 的图里没有 `find_jobs` 节点，那个字段永远是空的；
    原来读它的后果是返回一句「没有找到符合条件的岗位」——不崩、不报错，一个看起来
    完全合理、其实是接线错误的结论。真实 m2 会静默空跑：不打开表单、不上传简历，
    却报告这个岗位不符合条件。**静默的错误结论比崩溃危险得多。**

    缺 `job_url` 是调用方的错（m2 由 pending_job_id 解析而来，一定有 URL），
    当场抛——伪装成业务结果正是上面那个事故的形状。

    提到模块级是为了能测：关在 `build_survey_graph` 的闭包里就得开真浏览器才跑得动，
    跟 `record_candidates` / `describe_message` 同一个理由。
    """
    url = (state.get("job_url") or "").strip()
    if not url:
        raise ValueError("open_application 需要 state['job_url']——m2 的岗位由调用方指定")
    return url, state.get("job_title") or "", state.get("company") or ""


def record_candidates(tracker, state: dict) -> dict:
    """Checkpoint 1 落库：把候选岗位写进 pending_jobs。

    **模块级函数、不是图里的闭包**：它一行浏览器代码都没有，关在需要 tools 的闭包
    里纯属结构问题——那样"落库到底对不对"只能靠真机跑一次才知道。

    同时解析 `source_job_id`：`found_jobs[0]` 是下一阶段真正会去打开的那个岗位，
    Checkpoint 2 的记录要靠它认出自己的来源。**按 url 回查、不用刚插入的 id**——
    m2 那条路径每次都命中 url 去重（岗位是审批过的、早就在表里），新 id 是 None。
    """
    jobs = state.get("found_jobs") or []
    ids: list[int] = []
    skipped = 0
    for job in jobs:
        new_id = tracker.add_pending_job(
            site_name=state.get("site_name", ""),
            url=job.url,
            title=job.title,
            company=job.company,
            category=job.category,
            why=job.why,
            bucket=job.bucket,
            jd=job.jd,
        )
        if new_id is None:
            skipped += 1  # 这个 url 已经在待审批表里了，正常情况不是错误
        else:
            ids.append(new_id)
    if skipped:
        print(f"[layer1] {skipped} 个岗位此前已入库（url 去重），跳过。", flush=True)

    source_job_id = None
    if jobs:
        row = next((j for j in tracker.get_pending_jobs() if j.url == jobs[0].url), None)
        source_job_id = row.id if row else None
    return {"pending_job_ids": ids, "source_job_id": source_job_id}


def record_application(tracker, state: dict, personal_info: dict) -> dict:
    """Checkpoint 2 落库：把待人工审批的字段清单写进 pending_applications。

    同 `record_candidates`——不碰浏览器，所以提到模块级让它可测。
    """
    # 一个字段都没扫到就不写记录：一条空的待审批记录对人没有任何信息量，
    # 只会让审批队列里堆垃圾，还会让人误以为"这个岗位处理过了"。
    if not state.get("empty_elements"):
        return {"pending_application_id": None}

    # 写库前再过一遍同一道闸。分类节点已经过了一次，但这里是**落库**——真正决定
    # 什么会被摆到审批人面前的是这一步，规则只有 `_enforce_no_invented_values`
    # 一份实现，两处调用不算分叉。
    classified = _enforce_no_invented_values(state.get("classified_fields") or [])

    fields_payload = [
        {
            "field_id": f.field_id,
            "label": f.field_id,
            "kind": f.kind,
            # demographic 的值只能原样来自 personal_info，不许 LLM 编。取值走
            # match_value 的同义解析而不是 dict.get：LLM 挑的 key 可能是页面
            # 上的叫法（「生日」）而存储里是 birth_date，直接 get 会静默返回
            # 空值——字段留空、但没有任何地方能看出是"没匹配上"还是"确实没
            # 这份资料"。这里也兜住 LLM 没给 demographic_key 的情况：退回用
            # 字段名本身去解析。
            "candidate_value": (
                match_value(f.demographic_key or f.field_id, personal_info)
                if f.kind == "demographic"
                else f.candidate_value
            ),
            # 池里对应不止一个值时（本科+硕士两段学历对一个「学校名称」框），
            # **不挑、不合并**，把候选连上下文一起摆给审批人点。连本人都需要
            # 看页面才知道该填哪个，系统更没资格猜。空列表 = 没有歧义。
            "candidates": load_candidates(f.demographic_key or f.field_id),
        }
        for f in classified
    ]
    # 选填项也进列表，但**值留空、不生成**——你得知道它们存在（对着截图能判断
    # 要不要顺手填），而机器不该替你编。kind 一律 open_question：没让 LLM 看过
    # 它们，硬给一个分类就是编造。
    answered = {f["field_id"] for f in fields_payload}
    fields_payload += [
        {"field_id": e["label"], "label": e["label"], "kind": "open_question",
         "candidate_value": "", "candidates": load_candidates(e["label"]),
         "required": False}
        for e in state.get("empty_elements", [])
        if not e.get("required") and e["label"] not in answered
    ]
    for f in fields_payload:
        f.setdefault("required", True)   # 上面 LLM 作答的那批都是必填项

    app_id = tracker.add_pending_application(
        site_name=state.get("site_name", ""),
        job_title=state.get("job_title") or "",
        fields=fields_payload,
        company=state.get("company") or "",
        job_url=state["job_url"],
        screenshot=state.get("form_screenshot", ""),
        # 来自 Checkpoint 1 的哪个岗位。None = 走的是 --job-url 调试路径（岗位没
        # 经过选岗/审批），是诚实的空，不是缺数据。
        source_job_id=state.get("source_job_id"),
    )
    return {"pending_application_id": app_id}


def _render_bucket_plan(plan: list[dict]) -> str:
    """把 `plan_buckets` 的产出渲染成给 `scan_buckets` agent 看的清单。纯函数，
    单独抽出来是为了能单测（不需要真浏览器/真 LLM）。"""
    if not plan:
        return "（本轮没有需要扫的桶）"
    lines = []
    for i, item in enumerate(plan, 1):
        targets = "、".join(item.get("targets") or []) or "（未指定）"
        why = item.get("why") or ""
        line = f"{i}. 「{item.get('dimension')}」= 「{item.get('option')}」 —— 目标类别：{targets}"
        if why:
            line += f"（{why}）"
        lines.append(line)
    return "\n".join(lines)


def _harvest_items_to_found_jobs(raw_items: list[dict]) -> list[FoundJob]:
    """把 `harvest_current_page`（经 `classify_jobs` 加工过）的原始字典列表转成
    `FoundJob` 列表。**`title`/`company` 必须来自 `classify_jobs` 的输出，绝不
    退回用原始整行文本兜底**（修复轮 1）：`harvest_page` 抓到的候选没有干净标题，
    只有整行卡片文本；分类模型读那段文本判类别时顺手抽取出标题/公司名，这里
    只管把结果原样接过来。

    提到模块级（不是留在 `scan_buckets` 闭包里）是为了能单测——这段转换逻辑
    正是修复轮 1 要守住的那条不变量（"标题不能是整段原文"），关在闭包里就得
    真浏览器+真 LLM 才测得到，跟 `record_candidates` 同一个理由。
    """
    return [
        FoundJob(
            url=j["url"],
            title=j.get("title") or "",
            company=j.get("company") or "",
            category=j.get("category") or "",
            bucket=j.get("bucket") or "",
            why=j.get("why") or "",
            jd=j.get("jd") or "",
        )
        for j in raw_items
    ]


def _make_nodes(
    tools: list,
    personal_info: Optional[dict] = None,
    tracker: Optional[ApplicationTracker] = None,
    quotas: Optional[dict] = None,
    max_pages: int = 8,
    max_filter_clicks: int = 4,
    candidates_per_bucket: int = 15,
    logger=None,
) -> tuple:
    """节点工厂：Layer 1 的八个阶段函数只在这里定义一份。`build_select_graph` /
    `build_survey_graph` 从返回的字典里各取自己需要的子集组装图——**拆的是接线，
    不是实现**：一张图要连哪些节点变了，不代表节点本身的行为该抄两份。

    tools 来自 chrome_mcp_client.get_tools()，通过闭包绑定进各节点——不放进
    state（不是可序列化/可 checkpoint 的东西）。外层是确定性编排，`survey_structure` /
    `scan_buckets` / `open_application` 三个节点内部才是 agent 循环，`plan_buckets`
    是纯判断的普通 LLM 调用（见模块 docstring 的分工表、spec §2.1）。

    `quotas` = {类别: 最多几个}，默认读 profile.yaml 的 job_seeking.categories。
    它是分类的枚举约束（`classify_jobs`）——不再是选岗的终止条件：候选上限已经
    拆给 `candidates_per_bucket`（见 spec §4），quotas 只决定"这条岗位算哪一类"，
    真正按名额精选发生在评分排序之后。

    `candidates_per_bucket`：`scan_buckets` 里每个桶最多抓多少份候选（决定取多少
    份 JD，也就决定 run 跑多长）——**这不是 profile.yaml 里的字段**，那需要改
    `services/profile_loader.py`/前端设置页，不在这次接线的范围内（spec §4 提到
    的"前端可调"留给计划 C，见 task-7-brief）；这里先按现成的 `max_pages`/
    `max_filter_clicks` 同款套路开一个带默认值的参数占位。

    返回 `(nodes, snapshot_provider)`：
      `nodes`：`{阶段名: (节点函数, run 日志摘要函数)}`。
      `snapshot_provider`：`traced_stage` 兜底读最新快照用的回调。
    """
    take_snapshot = chrome_mcp_client.get_tool(tools, "take_snapshot")

    personal_info = personal_info if personal_info is not None else load_personal_info()
    tracker = tracker or ApplicationTracker()
    # 名额按站点解析：profile 里 site_overrides.<site>.skip 列出的类别直接不参与。
    # 本站不存在的类别会让"所有名额已满"这个主终止条件永远不成立，见 JobSeeking。
    # 但这里拿不到 site_name（它在 state 里），所以只能给全局默认，按站点的解析
    # 在 run_layer1 里做完再传进来。
    quotas = quotas if quotas is not None else preferences.load_profile().job_seeking.quotas
    pm = PromptManager()

    # agent 用的快照缓存：guarded click 需要知道"agent 是基于哪张快照决定点这个
    # uid 的"。不在守法里自己重新截图——见 safe_tools.make_guarded_click 注释。
    _latest_snapshot = {"text": ""}

    async def _snapshot_and_cache() -> str:
        text = _extract_text(await take_snapshot.ainvoke({}))
        _latest_snapshot["text"] = text
        return text

    def _agent_tools(passthrough: tuple) -> list:
        return build_agent_toolset(
            tools,
            snapshot_provider=lambda: _latest_snapshot["text"],
            snapshot_taker=_snapshot_and_cache,
            passthrough=passthrough,
        )

    async def ensure_ready(state: Layer1State) -> dict:
        """导航到入口页，等页面真的渲染出来，必要时等人工登录。

        **刻意留在代码里而不是交给 agent**：这两件事都不是判断题，是等待循环。
        交给 agent 只会让它在一张空白页/登录页上反复截图、烧上下文，最后报一个
        含糊的失败——而且它没有"等 10 分钟"这种耐心（recursion_limit 会先到）。
        """
        entry = state.get("job_url") or state["search_url"]
        navigate = chrome_mcp_client.get_tool(tools, "navigate_page")
        await navigate.ainvoke({"type": "url", "url": entry})

        # navigate_page 只保证浏览器导航本身完成，不保证 SPA 客户端渲染完成
        # （真机验证撞到过：不等就立刻截图，拿到的是 about:blank，后面所有步骤
        # 都在一张空页面上找元素，必然全部落空）。轮询直到快照不再是空壳。
        snapshot = await _snapshot_and_cache()
        for _ in range(10):
            if not _looks_blank(snapshot):
                break
            await asyncio.sleep(1)
            snapshot = await _snapshot_and_cache()
        else:
            _dump_debug_snapshot("page_still_blank_after_wait", snapshot)
            raise RuntimeError("页面加载后仍是空白（等待 10 秒未渲染），已存快照到 data/multisite_debug/")

        if _looks_logged_out(snapshot):
            # 轮询而不是阻塞在 input()：这个函数经常被别的进程（比如 Claude Code
            # 自己的 Bash 工具）拉起，那种场景下没有真实 stdin 可等用户敲回车。
            # 用户在弹出的 Chrome 窗口里手动登录（鼠标/键盘直接操作那个窗口，不
            # 经过运行本脚本的终端），这里定期重新截图检测登录态是否已消失。
            #
            # **`print` 不够**（2026-08 真实事故）：它打进 uvicorn 的 stdout，没有
            # 读者，还被块缓冲吃掉——系统在等人、人不知道，run 日志 10 分钟只有
            # 一条 `run_start`，最后只留下一句「等待手动登录超时」。`logger.log`
            # 同时写 JSONL 和推 SSE，Dashboard 实时日志上看得见、事后回放也看得见，
            # 这才是主路径；`print` 保留是因为命令行直跑（`logger=None`）时它是
            # 唯一输出。
            print("检测到可能未登录，请在弹出的 Chrome 窗口里手动登录（最多等待 10 分钟）...")
            if logger is not None:
                logger.log("waiting_for_login", scope={},
                           data={"url": entry, "max_wait_seconds": 600})
            for _ in range(60):
                await asyncio.sleep(10)
                snapshot = await _snapshot_and_cache()
                if not _looks_logged_out(snapshot):
                    print("检测到登录态，继续。")
                    if logger is not None:
                        logger.log("login_detected", scope={}, data={"url": entry})
                    break
            else:
                raise RuntimeError("等待手动登录超时（10 分钟），请重新运行")
        return {"snapshot_text": snapshot}

    async def survey_structure(state: Layer1State) -> dict:
        """勘察 agent：摸清这个站怎么组织（分几个桶、URL 怎么拿、怎么翻页……），
        产出一份结构化的站点操作手册（`SiteManual`）。**允许试探筛选器**——多选
        还是互斥这类信息 a11y 快照里没有，唯一可靠的判定方式是"勾一个、回读总数、
        再勾一个"（spec §3.3）。

        **先试旧手册，省 15 步**：`tracker.get_site_manual` 有旧手册就先跑
        `validate_manual` 轻校验，过了直接用、不进 agent；不过就整份丢弃重探
        （**不做部分沿用**——一份半对的手册比没有更糟，spec §3.5）。

        **结束时由代码重新导航回入口页**，不依赖 agent 自己撤销试探时勾过的
        筛选器——a11y 快照不报 `checked` 状态，agent 无从确认自己恢复没恢复，
        那正是刚踩过的"动作做了但看不见结果"的坑（spec §3.4）。

        **搞不定就抛，绝不硬填**：手册为 None 时节点让 run 失败，因为硬填出的
        手册会让下游抓回一堆垃圾，而那看起来跟"这个站没有岗位"一模一样（spec §7）。
        """
        site_name = state.get("site_name", "")
        entry = state["search_url"]

        existing = tracker.get_site_manual(site_name)
        if existing is not None:
            old_manual, _updated_at = existing
            ok, reason = await validate_manual(state.get("snapshot_text", ""), tools, old_manual)
            if ok:
                return {"manual": old_manual, "truncated": False}
            if logger is not None:
                logger.log("site_manual_invalidated", scope={"site": site_name},
                           data={"reason": reason})

        prompt = pm.render(
            "layer1_survey_structure",
            {
                "site_brief": preferences.render_site_brief(tracker, site_name),
                "max_filter_clicks": str(max_filter_clicks),
            },
        )
        # 手册经 record_site_manual 累积到这个 sink["fields"] 里，跟 record_job
        # 同一个套路——agent 半途没步数了，只要已经调用过至少一次，探到的字段
        # 照样拿得到；不要求最后一次调用就凑齐全部必填项（那正是这个节点第一次
        # 真机跑不收敛的根因，见 PITFALLS「答案必须最后一次性给出」那条）。
        sink: dict = {}
        tools_for_agent = [
            *_agent_tools(_PASSTHROUGH_FIND_JOBS),
            make_record_site_manual_tool(sink),
        ]
        agent = agent_runtime.build_agent(tools_for_agent, prompt)
        try:
            result = await agent_runtime.run_agent(
                agent, f"入口页面：{entry}\n请开始。",
                on_step=agent_step_sink(logger, "survey_structure"))
            truncated = agent_runtime.hit_step_limit(result)
        except GraphRecursionError:
            truncated = True
            result = {}
            safe_print("[layer1] 勘察 agent 达到步数上限。", flush=True)

        # 结束时由代码重新导航回入口页，重置试探筛选器时留下的状态——不依赖 agent
        # 自己撤销，见 docstring。
        navigate = chrome_mcp_client.get_tool(tools, "navigate_page")
        await navigate.ainvoke({"type": "url", "url": entry})
        reset_snapshot = await _snapshot_and_cache()

        # agent 可能分好几次调用 record_site_manual，每次只报一部分字段——用累积
        # 到的 fields 在这里重新跑一次唯一的校验实现，而不是只信任 sink["manual"]
        # 是否曾经被某一次调用设置过（那要求"凑齐的那一刻恰好是最后一次调用"，
        # 没有必要的额外假设）。
        fields = sink.get("fields", {})
        try:
            manual = SiteManual.from_dict(fields)
        except ManualError as exc:
            _dump_debug_snapshot("survey_structure_no_manual", reset_snapshot)
            missing = [name for name in _REQUIRED_MANUAL_FIELDS if not fields.get(name)]
            reason = f"还差：{', '.join(missing)}" if missing else f"校验未通过：{exc}"
            raise RuntimeError(
                f"survey_structure 没能产出可用的站点手册（{site_name}）：{reason}。"
                f"最后一句：{agent_runtime.last_text(result)[:300]}"
            )

        tracker.upsert_site_manual(site_name, manual)
        return {"manual": manual, "truncated": truncated, "snapshot_text": reset_snapshot}

    async def plan_buckets(state: Layer1State) -> dict:
        """纯判断，不碰浏览器：对着 `survey_structure` 探到的手册和求职条件，
        决定这一轮该扫站点的哪几个桶。做成普通 LLM 调用而不是 ReAct，换来可单测、
        可 eval（spec §2.1）。空列表是合法结果（站上确实没有相关的桶）。
        """
        manual: SiteManual = state["manual"]
        plan = await compute_bucket_plan(manual, quotas, preferences.render_constraints())
        return {"bucket_plan": plan}

    async def scan_buckets(state: Layer1State) -> dict:
        """执行 agent：按 `plan_buckets` 给的桶计划逐桶切换，调 `harvest_current_page`
        工具把当前列表页的岗位抓下来。分工（spec §5）：**agent 只决定去哪个桶、
        勾哪个框、还要不要继续**；抓取一页 N 条 URL/JD 和批量分类是代码 + 一次
        LLM 调用，不占 ReAct 轮次。

        `bucket_plan` 为空是合法结果（手册探出的桶里没有一个匹配任何目标类别）
        ——没有活可干，不当失败处理。
        """
        manual: SiteManual = state["manual"]
        plan = state.get("bucket_plan") or []
        site_name = state.get("site_name", "")

        if not plan:
            return {"found_jobs": [], "truncated": False}

        # 岗位随时经 harvest_current_page 落到这个 sink 里（原始字典，形状见
        # harvest.harvest_page），不依赖 agent 最后一次性输出。
        raw_sink: list[dict] = []
        # 库里已经收录过的岗位不该重复抓；每次 harvest_current_page 调用后会把
        # 新记的 url 并入这个集合，防止同一岗位在本轮里被跨页/跨桶重复收录。
        known_urls = {j.url for j in tracker.get_pending_jobs()}
        # FIX-4：人工纠正的反馈回路。用户在 Checkpoint 1 把某条归类标成 golden，
        # `POST /api/checkpoint1/jobs/{id}/review` 一直在写 `is_golden`，但重构
        # 之后没有任何生产调用方读它——`render_golden_examples` 早就写好了，只是
        # 没接线，标了也教不到。这里读一次（本节点全程只调一次 harvest_page 之外
        # 的一次数据库查询，不必每页重查）。
        golden_examples = preferences.render_golden_examples(tracker)

        async def _classify(items: list[dict]) -> list[dict]:
            # harvest_page 产出 {url, jd, bucket, text}；classify_jobs 的 prompt
            # 要读 title/site_category 才谈得上"职责里出现 LLM/Agent 就归 AI
            # NATIVE"这条核心规则——这里把 harvest 的字段名接到 classify 期待的
            # 字段名上。两个模块的字段契约本来就不同（分属 Task 3/Task 4，各自
            # 独立可测），不是同一份数据的两处实现，这层适配只在接线处存在一次。
            #
            # **`text`（整行卡片文本）塞进输入的 `title` 只是给模型提供原始素材
            # 去读，不代表输出的 title 就是它**（修复轮 1）：classify_jobs 会用
            # 模型抽取出的干净标题覆盖这个输入值，`_harvest_items_to_found_jobs`
            # 读的是覆盖之后的结果，不会把这段整行文本当成标题落库。
            mapped = [{**it, "title": it.get("text", ""), "site_category": it.get("bucket", "")}
                     for it in items]
            return await classify_jobs(mapped, quotas, golden_examples=golden_examples)

        def _harvest_current_page_tool() -> "object":
            from langchain_core.tools import StructuredTool

            async def harvest_current_page(bucket: str) -> str:
                # candidates_per_bucket 是**按桶**的候选上限（spec §4），不是每次
                # 调用各自独立的上限——否则一个桶翻 5 页、每页各拿满 limit，会
                # 让这个旋钮形同虚设。按桶已收数量算出这次还能拿多少。
                already = sum(1 for j in raw_sink if j.get("bucket") == bucket)
                remaining = max(0, candidates_per_bucket - already)
                if remaining == 0:
                    return (f"「{bucket}」这个桶已经到候选上限（{candidates_per_bucket}），"
                            f"不要再翻这个桶了，切下一个桶。")
                before = len(raw_sink)
                counts = await harvest_page(
                    _latest_snapshot["text"], tools, manual, bucket=bucket,
                    classify=_classify, sink=raw_sink, known_urls=known_urls,
                    limit=remaining,
                )
                known_urls.update(j["url"] for j in raw_sink[before:])
                msg = (f"「{bucket}」这一页：解析出 {counts['rows']} 行，"
                      f"新记 {counts['collected']} 个，"
                      f"跳过已收录 {counts['skipped_known']} 个，"
                      f"取URL/JD失败 {counts['url_failed']} 个。")
                if counts["truncated"]:
                    msg += (f" **已到「{bucket}」的候选上限（{candidates_per_bucket}），"
                           f"停止翻这个桶，切下一个。**")
                elif counts["rows"] == 0:
                    msg += " 这一页没有可解析的岗位行——这个桶可能已经翻到头了。"
                return msg

            return StructuredTool.from_function(
                coroutine=harvest_current_page,
                name="harvest_current_page",
                description=(
                    "抓取当前列表页上的岗位：解析这一页、逐条取 URL 和职责详情、批量交给"
                    "分类模型、记进候选池。bucket 填你当前所在的那个招聘项目/顶层分类的名字。"
                    "**调用前必须先 take_snapshot**——它读的是你最近拍的那一张，不会自己去拍。"
                    "每翻一页新的列表页都要重新调用一次。"
                ),
            )

        tools_for_agent = [
            *_agent_tools(_PASSTHROUGH_FIND_JOBS),
            _harvest_current_page_tool(),
            make_record_site_limit_tool(tracker, site_name),
            make_record_site_brief_tool(tracker, site_name),
        ]
        prompt = pm.render(
            "layer1_scan_buckets",
            {
                "constraints": preferences.render_constraints(),
                "bucket_plan": _render_bucket_plan(plan),
                "max_pages": str(max_pages),
                "max_filter_clicks": str(max_filter_clicks),
                "candidates_per_bucket": str(candidates_per_bucket),
                "site_brief": preferences.render_site_brief(tracker, site_name),
            },
        )
        agent = agent_runtime.build_agent(tools_for_agent, prompt)
        try:
            result = await agent_runtime.run_agent(
                agent, f"入口页面：{state['search_url']}\n请开始。",
                on_step=agent_step_sink(logger, "scan_buckets"))
            truncated = agent_runtime.hit_step_limit(result)
            if truncated:
                safe_print(f"[layer1] ⚠ 扫桶未跑完就耗尽步数，只采用已记录的 {len(raw_sink)} 个岗位。",
                           flush=True)
        except GraphRecursionError:
            truncated = True
            safe_print(f"[layer1] 扫桶 agent 达到步数上限，采用已记录的 {len(raw_sink)} 个岗位。",
                       flush=True)

        return {"found_jobs": _harvest_items_to_found_jobs(raw_sink), "truncated": truncated}

    async def write_pending_jobs(state: Layer1State) -> dict:
        """Checkpoint 1：把候选岗位落库，然后**结束这次 run**。

        为什么是"写库+结束"而不是 LangGraph 的 interrupt()：审批是人的动作，时间
        尺度是分钟到小时，而 interrupt 要求整个进程和那个 Chrome 实例一直挂着等。
        更要命的是**浏览器状态不可序列化**——checkpointer 存得下 messages，存不下
        Chrome；恢复之后 agent 手里的 uid 全部过期，还是得重新截图。岗位详情页有
        自己的 URL，存进库里下一阶段直接从 URL 开始，比恢复现场干净得多。

        真正的落库在模块级的 `record_candidates`（那里没有浏览器，可以单测）。
        """
        return record_candidates(tracker, state)

    async def open_application(state: Layer1State) -> dict:
        """导航 agent：打开调用方指定的那个岗位的申请表并上传简历。

        一次 m2 run 处理一个岗位、产出一条待审批记录。多岗位批量由调用方循环 run 来做，
        不在图里展开：那会让"哪个岗位失败了"变得难以定位，而且各岗位之间本来就没有共享状态。

        岗位从 state 直接来（见 `job_from_state`）——**不经 `found_jobs`**：m2 的图里
        没有 `find_jobs` 节点，读它会得到一个看起来合理、其实是接线错误的结论。
        """
        job_url, job_title, company = job_from_state(state)
        prompt = pm.render("layer1_open_application", {"resume_path": state["resume_pdf_path"]})
        # 注意这里**不给** record_job：那是选岗阶段的工具，导航阶段拿到它只会
        # 诱导它去"记录"而不是去打开表单。
        # record_site_limit 反而要给：投递须知那类文字最常出现在申请页上，而不是
        # 岗位列表页——只在选岗阶段给它，最可能出现的位置正好错过。真机验证确认了
        # 这一点：拓竹的投递次数上限就印在申请页上，选岗阶段永远看不到。
        result_sink: dict = {}
        tools_for_agent = [
            *_agent_tools(_PASSTHROUGH_OPEN_APPLICATION),
            make_record_site_limit_tool(tracker, state.get("site_name", "")),
            make_record_open_result_tool(result_sink),
        ]
        # 不用 response_format：那条路在 DeepSeek 上直接 400，见
        # make_record_open_result_tool 的说明。
        agent = agent_runtime.build_agent(tools_for_agent, prompt)
        result = await agent_runtime.run_agent(
            agent, f"岗位详情页：{job_url}\n请开始。",
            on_step=agent_step_sink(logger, "open_application"))
        truncated = agent_runtime.hit_step_limit(result)
        if truncated:
            safe_print("[layer1] ⚠ 导航 agent 步数耗尽，结果可能不完整。", flush=True)
        outcome = OpenApplicationOutput(
            form_opened=bool(result_sink.get("form_opened")),
            resume_uploaded=bool(result_sink.get("resume_uploaded")),
            note=result_sink.get("note") or (
                "agent 没调用 record_open_result，最后一句：" + agent_runtime.last_text(result)[:300]
            ),
        ) if result_sink else OpenApplicationOutput(
            form_opened=False, resume_uploaded=False,
            note="agent 未汇报结果，最后一句：" + agent_runtime.last_text(result)[:300],
        )
        # 字段扫描读的是**代码自己拍的**最后一张快照，不是 agent 的自述——agent
        # 可能说"打开了"但实际停在别的页面上。快照是唯一可核对的事实来源。
        snapshot = await _snapshot_and_cache()
        return {
            "open_result": outcome,
            "truncated": truncated,
            "snapshot_text": snapshot,
            "job_title": job_title,
            "company": company,
            "job_url": job_url,
        }

    async def scan_and_classify_fields(state: Layer1State) -> dict:
        _dump_debug_snapshot("scan_raw_snapshot", state.get("snapshot_text", ""))
        empty_elements = _parse_empty_input_elements(state.get("snapshot_text", ""))
        if not empty_elements:
            # 没有要补的字段就不拍照——照片是给人核对用的，没东西要核对时拍它
            # 只是在磁盘上多堆一张带个人信息的图。
            return {"empty_elements": [], "classified_fields": [], "form_screenshot": ""}

        shot = await capture_form_screenshot(tools)

        # **只把必填项交给 LLM 作答。** 这类站点会解析上传的简历自动回填，剩下还空
        # 着的多半是选填——给全部字段生成内容，产出的就是「起止时间 → "请填写您在
        # 教育或工作经历中的起止时间，格式如：2020.09 - 2024.06"」这种：一句填写
        # 说明冒充答案（2026-08-15 真机）。
        #
        # 选填项**仍然进审批列表**，只是值留空、不生成——你得知道它们存在（对着截图
        # 能判断要不要顺手填），但不该由机器替你编。
        required_elements = [e for e in empty_elements if e.get("required")]
        if not required_elements:
            return {"empty_elements": empty_elements, "classified_fields": [],
                    "form_screenshot": shot}

        fields_desc = "\n".join(f"- field_id={e['label']!r}, role={e['role']}"
                                for e in required_elements)
        keys_desc = "\n".join(f"- {k}" for k in personal_info) or "(无)"
        prompt = pm.render(
            "classify_field",
            {
                "job_title": state.get("job_title") or "(未知)",
                "company": state.get("company") or "(未知)",
                "personal_info_keys": keys_desc,
                "fields": fields_desc,
            },
        )
        llm = agent_runtime.build_model()
        # method="function_calling"：LangChain 对 with_structured_output 的默认策略
        # 会尝试 OpenAI 较新的 json_schema response_format，DeepSeek 的 API 不支持
        # （真机验证撞到 400 Error: "This response_format type is unavailable
        # now"）。function calling 是更通用、DeepSeek 明确支持的结构化输出方式。
        result: ClassifyFieldsOutput = await llm.with_structured_output(
            ClassifyFieldsOutput, method="function_calling"
        ).ainvoke(prompt)
        classified = _enforce_no_invented_values(result.fields)
        return {"empty_elements": empty_elements, "classified_fields": classified,
                "form_screenshot": shot}

    async def write_pending_application(state: Layer1State) -> dict:
        return record_application(tracker, state, personal_info)

    # 节点名 → (函数, run 日志摘要函数)。**加节点只能改这里**——两个 builder 都从
    # 这个字典里取，漏加的表现是某张图的 stage 表拼不出对应节点，_stages_for 的
    # `.get` 兜底会让它落到 _compile 的对账炸掉，而不是悄悄跑一个 None 节点。
    return {
        "ensure_ready": (ensure_ready,
                         lambda out: _describe_page(out.get("snapshot_text") or "")),
        "survey_structure": (survey_structure,
                             lambda out: {"job_url_source": getattr(out.get("manual"), "job_url_source", ""),
                                          "row_split": getattr(out.get("manual"), "row_split", ""),
                                          "dimensions": len(getattr(out.get("manual"), "dimensions", None) or [])}),
        "plan_buckets": (plan_buckets,
                        lambda out: {"buckets": len(out.get("bucket_plan") or [])}),
        "scan_buckets": (scan_buckets,
                        lambda out: {"found": len(out.get("found_jobs") or []),
                                     "by_category": dict(Counter(j.category for j in
                                                                 (out.get("found_jobs") or [])))}),
        "write_pending_jobs": (write_pending_jobs,
                               lambda out: {"new": len(out.get("pending_job_ids") or [])}),
        "open_application": (open_application,
                             lambda out: {"form_opened": bool(getattr(out.get("open_result"),
                                                                      "form_opened", False)),
                                          "resume_uploaded": bool(getattr(out.get("open_result"),
                                                                          "resume_uploaded", False))}),
        "scan_and_classify_fields": (scan_and_classify_fields,
                                     lambda out: {"empty": len(out.get("empty_elements") or []),
                                                  "required": sum(1 for e in (out.get("empty_elements") or [])
                                                                  if e.get("required")),
                                                  "classified": len(out.get("classified_fields") or [])}),
        "write_pending_application": (write_pending_application,
                                      lambda out: {"pending_application_id": out.get("pending_application_id")}),
    }, (lambda: _latest_snapshot["text"])


def _compile(stages, workflow, edges, logger, snapshot_provider):
    """把阶段表接成一张图。两个 builder 共用，避免接线逻辑写两遍。"""
    built = tuple(name for name, _, _ in stages)
    if built != stage_names(workflow):
        raise RuntimeError(f"阶段表与 stage_names({workflow!r}) 不一致：{built} vs {stage_names(workflow)}")
    graph = StateGraph(Layer1State)
    for name, fn, summarize in stages:
        graph.add_node(name, traced_stage(name, fn, logger, summarize,
                                          snapshot_provider=snapshot_provider) if logger else fn)
    for a, b in edges:
        graph.add_edge(a, b)
    return graph.compile()


def _stages_for(nodes: dict, stage_order: tuple) -> list:
    """按阶段名顺序从节点工厂产出里取出 (name, fn, summarize)。

    **用 `.get` 兜底、不用 `nodes[name]` 严格取**：阶段名一旦漂移（比如 stage_order
    被 monkeypatch 成一个不存在的节点名），要让它落到 `_compile` 里那句对着
    `stage_names()` 的对账上、报一个看得懂的"阶段表不一致"，而不是在这里先炸一个
    "KeyError: 'oops'"——两种失败都对，但后者看不出问题出在"阶段表跟前端契约对
    不上"，得靠人再往回查一层。
    """
    return [(name, *nodes.get(name, (None, None))) for name in stage_order]


def build_select_graph(
    tools: list,
    personal_info: Optional[dict] = None,
    tracker: Optional[ApplicationTracker] = None,
    quotas: Optional[dict] = None,
    max_pages: int = 8,
    max_filter_clicks: int = 4,
    candidates_per_bucket: int = 15,
    logger=None,
):
    """m1：入口页 → 探结构 → 定桶计划 → 扫桶 → 落库 → 结束。**没有 open_application**，
    对外零副作用。

    参数与旧版 `build_graph` 一致，去掉了 `select_only`——这张图本身就是那条
    select_only=True 的路径，不用再传布尔量去挑分支。
    """
    nodes, snapshot_provider = _make_nodes(
        tools, personal_info=personal_info, tracker=tracker, quotas=quotas,
        max_pages=max_pages, max_filter_clicks=max_filter_clicks,
        candidates_per_bucket=candidates_per_bucket, logger=logger,
    )
    # 阶段名读**活的**模块全局 M1_STAGES（不是拷贝一份字面量）：_compile 里对着的
    # stage_names() 读的是导入时就定住的 _STAGES_BY_WORKFLOW 字典，只有这里也读
    # "活的" M1_STAGES，两者才可能真的对不上——drift 测试 monkeypatch M1_STAGES
    # 才有意义，不然 patch 了也没人读它。
    stages = _stages_for(nodes, M1_STAGES)
    edges = [(START, "ensure_ready"), ("ensure_ready", "survey_structure"),
             ("survey_structure", "plan_buckets"), ("plan_buckets", "scan_buckets"),
             ("scan_buckets", "write_pending_jobs"), ("write_pending_jobs", END)]
    return _compile(stages, "m1", edges, logger, snapshot_provider)


def build_survey_graph(
    tools: list,
    personal_info: Optional[dict] = None,
    tracker: Optional[ApplicationTracker] = None,
    quotas: Optional[dict] = None,
    max_pages: int = 8,
    max_filter_clicks: int = 4,
    candidates_per_bucket: int = 15,
    logger=None,
):
    """m2：直接从调用方给定的岗位 URL 开表单。**没有 m1 那五站里除 ensure_ready
    之外的任何一站**——m2 拿到的是已经批准过的那一个岗位，不需要再探结构/定桶/选。

    `candidates_per_bucket` 在这张图里不生效（m2 没有 `scan_buckets` 节点），
    留着只是为了跟 `build_select_graph` 签名对称——两个 builder 共用同一个
    `_make_nodes`，参数表历来是对称的（`max_filter_clicks` 同理）。
    """
    nodes, snapshot_provider = _make_nodes(
        tools, personal_info=personal_info, tracker=tracker, quotas=quotas,
        max_pages=max_pages, max_filter_clicks=max_filter_clicks,
        candidates_per_bucket=candidates_per_bucket, logger=logger,
    )
    stages = _stages_for(nodes, M2_STAGES)
    edges = [(START, "ensure_ready"), ("ensure_ready", "open_application"),
             ("open_application", "scan_and_classify_fields"),
             ("scan_and_classify_fields", "write_pending_application"),
             ("write_pending_application", END)]
    return _compile(stages, "m2", edges, logger, snapshot_provider)


async def run_layer1(
    workflow: str,
    site_name: str,
    resume_pdf_path: str = "",
    job_url: str = "",
    search_url: str = "",
    headless: bool = False,
    tracker: Optional[ApplicationTracker] = None,
    quotas: Optional[dict] = None,
    max_pages: int = 8,
    max_filter_clicks: int = 4,
    candidates_per_bucket: int = 15,
    emitter=None,
    job_title: str = "",
    company: str = "",
    source_job_id: Optional[int] = None,
) -> dict:
    """跑一次 Layer 1。

    `workflow` 是权威输入（`"m1"` / `"m2"`），决定跑哪张图；`job_url` / `search_url`
    不再是"谁非空就是谁"的推断依据，而是按 `workflow` 分别校验的入参：
      - `"m1"`（选岗）：需要 `search_url`——站点招聘入口页，agent 从这里按偏好自己
        找岗位。图里没有 `open_application`，对外零副作用。
      - `"m2"`（勘察表单）：需要 `job_url`——调用方已经指定要处理的那个岗位（通常是
        Checkpoint 1 审批过的），以及 `resume_pdf_path`——要往企业系统传简历。

    `job_title` / `company` / `source_job_id`：**m2 调用方（`_run_multisite_fill`）
    手里已经有的那个 pending_job 行的信息，原样传进来**，不要指望图里哪个节点替
    你反查。拆图之前 m2 会经过一个 `find_jobs` 幽灵节点，靠它按 `job_url` 反查
    `pending_jobs` 表拿到 title/company/id；拆图之后 m2 的图里根本没有那个节点
    （也没有 `write_pending_jobs`，`source_job_id` 同理算不出来）——不传的后果是
    `pending_applications.job_title`/`company` 写成空字符串、`source_job_id` 写成
    NULL。`source_job_id` 尤其要命：它是"开始填表 N"差集（已批准 − 已填表 − 已在
    队列）的依据，写不进去会导致同一个岗位被重复排队，等于再往企业系统传一次简历。
    m1 不需要传这三个——它自己会在 `write_pending_jobs` 里把 `source_job_id` 解出来。

    返回整个 state（不只是 id）——**因为现在有"跑完了但一条记录都没写"的合法
    结果**（没找到符合条件的岗位、或表单里没有空字段）。只返回一个 id 会把这三
    种情况压成同一个 None，调用方无从区分是哪一种，也就无从判断该不该重试。
    """
    # 入参按 workflow 分别校验。**不再靠"谁非空"推断身份**——那让同一件事有两个
    # 输入来源，必然存在两者矛盾的组合，而那种组合的行为只有读代码才知道。
    builders = {"m1": build_select_graph, "m2": build_survey_graph}
    if workflow not in builders:
        raise ValueError(f"未知 workflow: {workflow!r}，只有 {sorted(builders)}")
    if workflow == "m1" and not search_url:
        raise ValueError("m1（选岗）需要 search_url——站点招聘入口页")
    if workflow == "m2":
        if not job_url:
            raise ValueError("m2（勘察表单）需要 job_url——由调用方指定要处理哪个岗位")
        if not resume_pdf_path:
            # 缺简历要当场炸：跑到一半才发现，浏览器已经开出去了。
            raise ValueError("m2（勘察表单）需要 resume_pdf_path——它要往企业系统传简历")

    # 按站点解析名额（去掉 site_overrides 里标记本站没有的类别）。调用方显式传了
    # quotas 就以调用方为准——CLI 的 --category 是"我这次就要找这些"，不该被
    # profile 的站点配置二次过滤。
    if quotas is None:
        quotas = preferences.load_profile().job_seeking.quotas_for_site(site_name)

    profile_dir = chrome_mcp_client.profile_dir_for_site(site_name)
    client = chrome_mcp_client.build_client(profile_dir, headless=headless)
    # 必须是同一个 session 贯穿全程（一个 Chrome 实例），不能每次工具调用各开
    # 一个——见 chrome_mcp_client.open_session() 注释，真机验证撞过这个坑。
    # m1 用不到简历（它的图里根本没有上传节点），所以不做无谓的复制。
    run_meta = {"trigger": "manual",
                "params": {"site": site_name, "quotas": quotas, "max_pages": max_pages,
                           "headless": headless}}
    with run_scope(workflow, emitter=emitter, meta=run_meta) as run, ExitStack() as stack:
        staged_path = ""
        if resume_pdf_path and workflow == "m2":
            staged_path = stack.enter_context(staged_resume(resume_pdf_path))

        async with chrome_mcp_client.open_session(client) as session:
            tools = await chrome_mcp_client.get_tools(session)
            app = builders[workflow](tools, tracker=tracker, quotas=quotas,
                                     max_pages=max_pages,
                                     max_filter_clicks=max_filter_clicks,
                                     candidates_per_bucket=candidates_per_bucket,
                                     logger=run.logger)
            state = await app.ainvoke({
                "job_url": job_url,
                "search_url": search_url,
                "resume_pdf_path": staged_path,
                "site_name": site_name,
                # m2 专用：见函数 docstring——m2 的图里没有节点会反查这三样。
                # m1 忽略它们（自己在 write_pending_jobs 里算 source_job_id）。
                "job_title": job_title,
                "company": company,
                "source_job_id": source_job_id,
            })
        # 按 workflow 分开报：m2 拆图后 found_jobs 恒空（它的图里没有 find_jobs），
        # 混着报 "found: 0" 会被读成"这次什么都没找到"——那描述的是 m1 的活儿。
        if workflow == "m1":
            run.summary.update({"found": len(state.get("found_jobs") or []),
                                "new_pending_jobs": len(state.get("pending_job_ids") or [])})
        else:
            run.summary.update({"pending_application_id": state.get("pending_application_id"),
                                "fields": len(state.get("classified_fields") or [])})
        return state
