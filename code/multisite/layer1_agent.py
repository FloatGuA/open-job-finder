"""Layer 1（识别/判断）agent —— docs/multi-site-expansion-design.md 四层架构的第一层。

**自主度按层拆分，不是全链路统一**（v2.22.0 与用户重新对齐后的形态，取舍见
DECISION.md「Layer 1 的导航/找入口/选岗交给 agent 自主决策」）：

| 环节 | 谁来决策 | 为什么 |
|------|---------|--------|
| 找岗位、翻页、判断岗位符不符合偏好 | **agent** | 每个站点长得都不一样，写死选择器就退化成"每站一个适配器"——正是设计文档否掉的路线 |
| 找投递入口、上传简历 | **agent** | 同上；入口按钮的叫法/位置各站不同 |
| 解析快照里哪些是空字段 | 代码 | 结构化解析，没有判断成分 |
| 字段分类（人口学/开放题/证件） | LLM 单次调用 | 需要语义判断，但不需要多轮自主 |
| 取 personal_info 的值、写库 | 代码 | 确定性映射 |

**硬边界**（代码强制，不是 prompt 叮嘱）：
1. **提交类点击被 `safe_tools.make_guarded_click` 拒绝。** 旧版靠"工具集里没有
   提交能力"守法；agent 拿到自由 `click` 之后那个守法就失效了（同一个工具既能点
   「申请」也能点「提交」），所以换成点击工具自己拦。见 safe_tools 模块 docstring。
2. government_id 类字段的候选值在 `_enforce_government_id_blank()` 里被无条件
   清空，不管 LLM 分类节点返回了什么。
3. 整个 Layer 1 的产出只有一条 `pending_applications` 待审批记录——不做任何对外
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
import re
from pathlib import Path
from typing import Literal, Optional, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from multisite import agent_runtime, chrome_mcp_client, preferences, safe_tools
from multisite.personal_info_loader import load_personal_info, match_value
from services.prompt_manager import PromptManager
from services.tracker import ApplicationTracker

# ── LLM 结构化输出。用 LangChain 的 with_structured_output（DeepSeek function
#    calling），不走项目自己的 ModelRouter——DeepSeek 走项目 OpenAICompatibleProvider
#    时会直接忽略 output_schema 参数，这里改用 LangChain 原生结构化输出更可靠。
#    这是本模块唯一游离于项目现有 LLM 路由之外的调用点，取舍见 DECISION.md。──

_FieldKind = Literal["demographic", "open_question", "government_id"]


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
    why: str = Field(default="", description="一句话说明对上了哪几条求职条件")


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
    # 选岗 agent 的产出
    found_jobs: list[FoundJob]
    # 导航 agent 的产出
    open_result: OpenApplicationOutput
    snapshot_text: str
    empty_elements: list[ScannedElement]
    classified_fields: list[FieldClassification]
    pending_application_id: Optional[int]


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
    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if not m:
            continue
        role = m.group("role")
        name = (m.group("name") or "").strip()

        if role not in _INPUT_ROLES or role == "radio":
            # "*"(必填星号)和 YYYY/MM/DD 这类日期占位符格式提示不是真地标，
            # 真机验证撞到过"起止时间"字段被离它更近的占位符"MM"抢走地标位。
            if name and name != "*" and not _PLACEHOLDER_HINT_RE.fullmatch(name):
                landmark = name
            continue

        value_m = _VALUE_RE.search(m.group("rest") or "")
        current_value = value_m.group(1) if value_m else ""
        if current_value.strip():
            continue  # 已有值（含简历解析自动回填的），不需要 Layer 1 处理

        label = name or landmark
        if not label or label in seen_labels:
            continue  # 既没自己的名字也没地标可用，或者是同一字段的重复节点
        seen_labels.add(label)
        elements.append({"uid": m.group("uid"), "role": role, "label": label})
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
    active: Optional[dict] = None  # {"uid","label","any_checked"}
    last_radio_name = None

    def _flush():
        if active is not None and not active["any_checked"]:
            groups.append({"uid": active["uid"], "role": "radio", "label": active["label"]})

    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if not m:
            continue
        role = m.group("role")
        name = (m.group("name") or "").strip()
        if role == "radio":
            if active is None:
                active = {"uid": m.group("uid"), "label": landmark_name or name, "any_checked": False}
            if "checked" in (m.group("rest") or ""):
                active["any_checked"] = True
            last_radio_name = name
            continue
        # 非 radio 行：跟刚才那个选项同名就当装饰性重复，不打断当前组；
        # 否则视为下一个单选题的候选地标，并把当前组收尾。
        if name and name != last_radio_name:
            if active is not None:
                _flush()
                active = None
                last_radio_name = None
            landmark_name = name
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


def _dump_debug_snapshot(tag: str, snapshot_text: str) -> None:
    """调试用：某个定位失败时把当时的原始 a11y 快照存下来，省得只能靠报错
    字符串猜页面长什么样——上一次真机排查就是因为没有这个才多跑了一轮。"""
    _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (_DEBUG_DIR / f"{tag}.txt").write_text(snapshot_text, encoding="utf-8")


def _looks_blank(snapshot_text: str) -> bool:
    """about:blank 或还没渲染出任何实质内容的空壳快照。"""
    return 'url="about:blank"' in snapshot_text or len(snapshot_text.strip().splitlines()) <= 2


def _looks_logged_out(snapshot_text: str) -> bool:
    lowered = snapshot_text.lower()
    return "登录" in snapshot_text or "login" in lowered or "sign in" in lowered


def make_record_job_tool(sink: list) -> "object":
    """一个让 agent **随时把找到的岗位落袋**的工具，而不是憋到最后一次性输出。

    **这是选岗 agent 能不能收敛的关键**，不是锦上添花。前两次真机跑都死在同一个
    模式上：agent 每翻一页都说"让我分析当前页面的岗位"，然后又去点下一页，从不
    产出结论，一路撞到 recursion limit。第一次是在筛选器上打转，加了点击预算后
    换成在翻页上打转——**换个地方犯同一个错，说明不是预算不够，是"答案必须最后
    一次性给出"这个结构本身在逼它继续探索**（它永远觉得还没看够）。

    改成随时记录之后有三个好处：
    1. agent 每记一条就拿到一次正反馈，探索有了明确的进展信号；
    2. 即使最后超时/超限，已经记下的岗位仍然拿得到（部分结果不再全丢）；
    3. 不需要它把所有候选一直记在上下文里——这本来就是 DeepSeek 64k 上下文
       最吃不消的用法。
    """
    from langchain_core.tools import StructuredTool

    async def record_job(url: str, title: str = "", company: str = "", why: str = "") -> str:
        if not url or not url.startswith("http"):
            return "记录失败：url 必须是完整的 http(s) 链接。请从快照里那一行的 url=\"...\" 取。"
        if any(j.url == url for j in sink):
            return f"这个岗位已经记过了（当前共 {len(sink)} 个），不用重复记，继续看下一个。"
        sink.append(FoundJob(url=url, title=title, company=company, why=why))
        return (f"已记录第 {len(sink)} 个：{title or url}。"
                "继续找下一个；如果这一页看完了就翻页，全部看完就直接给出最终结论。")

    return StructuredTool.from_function(
        coroutine=record_job,
        name="record_job",
        description=(
            "记录一个符合求职条件的岗位。每找到一个就立刻调用一次，不要攒到最后。"
            "url 必须是完整链接（从快照里 link 行的 url=\"...\" 取）。"
        ),
    )


def build_agent_toolset(
    tools: list,
    snapshot_provider,
    snapshot_taker,
) -> list:
    """agent 能拿到的工具集：原始 `click` 被换成拒绝提交类点击的守法版本，
    原始 `take_snapshot` 被换成会写快照缓存的版本，其余原样透传。

    **抽成模块级函数（而不是留在 build_graph 的闭包里）就是为了能单测。**
    整个模块最危险的一条不变量是"agent 拿到的 click 必须是守法版"——守法本身
    有测试（tests/test_safe_tools.py），但"守法有没有真的接上去"如果测不到，
    有人把这行改回原始 click 也不会有任何东西变红。
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
    passthrough = [t for t in tools if t.name not in {"take_snapshot", "click"}]
    return [snap_tool, guarded_click, *passthrough]


# 注：`_find_uid_by_label` / `_find_uid_near_text` 于 v2.22.0 删除。它们是旧版
# "代码写死点哪个 uid"路线的产物——找投递入口/上传控件现在由 agent 自己看页面
# 决定（DECISION.md 记的方向调整）。按标签定位元素这件事本身在 Layer 3 的"代码
# 填写"工具里还会需要，但那时的输入是**审批过的字段名**而不是猜出来的关键词，
# 语义不同，届时重写即可，不留一个没有消费方的函数在这里等着被误用。


def _enforce_government_id_blank(fields: list[FieldClassification]) -> list[FieldClassification]:
    """硬约束：government_id 类字段的 candidate_value 无条件清空。见模块 docstring。"""
    for f in fields:
        if f.kind == "government_id" and f.candidate_value:
            f.candidate_value = ""
    return fields


def build_graph(
    tools: list,
    personal_info: Optional[dict] = None,
    tracker: Optional[ApplicationTracker] = None,
    max_pages: int = 3,
    max_jobs: int = 5,
    max_filter_clicks: int = 4,
    select_only: bool = False,
):
    """组装 Layer 1 的 LangGraph。tools 来自 chrome_mcp_client.get_tools()，通过
    闭包绑定进各节点——不放进 state（不是可序列化/可 checkpoint 的东西）。

    外层是确定性编排，`find_jobs` / `open_application` 两个节点内部才是 agent
    循环（见模块 docstring 的分工表）。
    """
    take_snapshot = chrome_mcp_client.get_tool(tools, "take_snapshot")

    personal_info = personal_info if personal_info is not None else load_personal_info()
    tracker = tracker or ApplicationTracker()
    pm = PromptManager()

    # agent 用的快照缓存：guarded click 需要知道"agent 是基于哪张快照决定点这个
    # uid 的"。不在守法里自己重新截图——见 safe_tools.make_guarded_click 注释。
    _latest_snapshot = {"text": ""}

    async def _snapshot_and_cache() -> str:
        text = _extract_text(await take_snapshot.ainvoke({}))
        _latest_snapshot["text"] = text
        return text

    def _agent_tools() -> list:
        return build_agent_toolset(
            tools,
            snapshot_provider=lambda: _latest_snapshot["text"],
            snapshot_taker=_snapshot_and_cache,
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
            print("检测到可能未登录，请在弹出的 Chrome 窗口里手动登录（最多等待 10 分钟）...")
            for _ in range(60):
                await asyncio.sleep(10)
                snapshot = await _snapshot_and_cache()
                if not _looks_logged_out(snapshot):
                    print("检测到登录态，继续。")
                    break
            else:
                raise RuntimeError("等待手动登录超时（10 分钟），请重新运行")
        return {"snapshot_text": snapshot}

    async def find_jobs(state: Layer1State) -> dict:
        """选岗 agent：从入口页自己浏览、筛选、判断岗位符不符合求职偏好。

        给了 job_url 就整个跳过——那是"我已经知道要投哪个"的调试/复现路径。
        """
        if state.get("job_url"):
            return {"found_jobs": [FoundJob(url=state["job_url"], title=state.get("job_title", ""),
                                            company=state.get("company", ""), why="由调用方直接指定")]}

        prompt = pm.render(
            "layer1_find_jobs",
            {
                "constraints": preferences.render_constraints(),
                "max_pages": str(max_pages),
                "max_jobs": str(max_jobs),
                # 筛选器点击预算。第一次真机跑就是死在这里：agent 正确点了
                # 深圳/产品/研发/日常实习，但每次截图后又去点下一个筛选器，
                # 始终不收敛，一路撞到 recursion limit。"最多翻 N 页"约束不住
                # 这种打转——翻页和调筛选器是两件事，必须分别给预算。
                "max_filter_clicks": str(max_filter_clicks),
            },
        )
        # 岗位随时经 record_job 落到这个 sink 里，不依赖 agent 最后一次性输出。
        sink: list[FoundJob] = []
        tools_for_agent = [*_agent_tools(), make_record_job_tool(sink)]
        agent = agent_runtime.build_agent(tools_for_agent, prompt)
        try:
            await agent_runtime.run_agent(agent, f"入口页面：{state['search_url']}\n请开始。")
        except GraphRecursionError:
            # 兜圈子超限**不再是全损**：已经 record 下来的岗位照样用。这正是把
            # 结果外置到工具里的主要收益，别改成向上抛——那等于把"找到 3 个但
            # 第 4 页开始打转"退化成"什么都没有"。
            print(f"[layer1] 选岗 agent 达到步数上限，采用已记录的 {len(sink)} 个岗位。", flush=True)
        return {"found_jobs": sink[:max_jobs]}

    async def open_application(state: Layer1State) -> dict:
        """导航 agent：打开第一个候选岗位的申请表并上传简历。

        只处理第一个候选——一次 Layer 1 run 产出一条待审批记录。多岗位批量由
        调用方循环 run 来做，不在图里展开：那会让"哪个岗位失败了"变得难以定位，
        而且各岗位之间本来就没有共享状态。
        """
        jobs = state.get("found_jobs") or []
        if not jobs:
            return {"open_result": OpenApplicationOutput(
                form_opened=False, resume_uploaded=False, note="没有找到符合条件的岗位")}

        job = jobs[0]
        prompt = pm.render("layer1_open_application", {"resume_path": state["resume_pdf_path"]})
        agent = agent_runtime.build_agent(_agent_tools(), prompt, response_format=OpenApplicationOutput)
        result = await agent_runtime.run_agent(agent, f"岗位详情页：{job.url}\n请开始。")
        outcome: OpenApplicationOutput = result.get("structured_response") or OpenApplicationOutput(
            form_opened=False, resume_uploaded=False,
            note="agent 未给出结构化结论：" + agent_runtime.last_text(result)[:300],
        )
        # 字段扫描读的是**代码自己拍的**最后一张快照，不是 agent 的自述——agent
        # 可能说"打开了"但实际停在别的页面上。快照是唯一可核对的事实来源。
        snapshot = await _snapshot_and_cache()
        return {
            "open_result": outcome,
            "snapshot_text": snapshot,
            "job_title": state.get("job_title") or job.title,
            "company": state.get("company") or job.company,
            "job_url": job.url,
        }

    async def scan_and_classify_fields(state: Layer1State) -> dict:
        _dump_debug_snapshot("scan_raw_snapshot", state.get("snapshot_text", ""))
        empty_elements = _parse_empty_input_elements(state.get("snapshot_text", ""))
        if not empty_elements:
            return {"empty_elements": [], "classified_fields": []}

        fields_desc = "\n".join(f"- field_id={e['label']!r}, role={e['role']}" for e in empty_elements)
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
        classified = _enforce_government_id_blank(result.fields)
        return {"empty_elements": empty_elements, "classified_fields": classified}

    async def write_pending_application(state: Layer1State) -> dict:
        # 一个字段都没扫到就不写记录：一条空的待审批记录对人没有任何信息量，
        # 只会让审批队列里堆垃圾，还会让人误以为"这个岗位处理过了"。
        if not state.get("classified_fields"):
            return {"pending_application_id": None}

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
            }
            for f in state.get("classified_fields", [])
        ]
        app_id = tracker.add_pending_application(
            site_name=state.get("site_name", ""),
            job_title=state.get("job_title") or "",
            fields=fields_payload,
            company=state.get("company") or "",
            job_url=state["job_url"],
        )
        return {"pending_application_id": app_id}

    graph = StateGraph(Layer1State)
    graph.add_node("ensure_ready", ensure_ready)
    graph.add_node("find_jobs", find_jobs)
    graph.add_edge(START, "ensure_ready")
    graph.add_edge("ensure_ready", "find_jobs")

    if select_only:
        # 只跑到选岗为止。**整个 Layer 1 里只有选岗是零副作用的**（纯浏览），
        # 后面上传简历是对真实企业系统的真实动作。把这条短路做成"图里根本没有
        # 后续节点"而不是"节点里判断一下要不要跳过"——少一条能走到上传的路径，
        # 就少一个"某个条件写反了就真传上去了"的可能。
        graph.add_edge("find_jobs", END)
        return graph.compile()

    graph.add_node("open_application", open_application)
    graph.add_node("scan_and_classify_fields", scan_and_classify_fields)
    graph.add_node("write_pending_application", write_pending_application)
    graph.add_edge("find_jobs", "open_application")
    graph.add_edge("open_application", "scan_and_classify_fields")
    graph.add_edge("scan_and_classify_fields", "write_pending_application")
    graph.add_edge("write_pending_application", END)

    return graph.compile()


async def run_layer1(
    resume_pdf_path: str,
    site_name: str,
    job_url: str = "",
    search_url: str = "",
    headless: bool = False,
    tracker: Optional[ApplicationTracker] = None,
    max_pages: int = 3,
    max_jobs: int = 5,
    max_filter_clicks: int = 4,
    select_only: bool = False,
) -> dict:
    """跑一次 Layer 1。

    `job_url` 和 `search_url` 二选一：
      - `search_url`：正常用法，选岗 agent 从这个入口自己按偏好找岗位。
      - `job_url`：调试/复现用，跳过选岗直接处理指定岗位。

    返回整个 state（不只是 id）——**因为现在有"跑完了但一条记录都没写"的合法
    结果**（没找到符合条件的岗位、或表单里没有空字段）。只返回一个 id 会把这三
    种情况压成同一个 None，调用方无从区分是哪一种，也就无从判断该不该重试。
    """
    if bool(job_url) == bool(search_url):
        raise ValueError("job_url 与 search_url 必须且只能给一个")

    profile_dir = chrome_mcp_client.profile_dir_for_site(site_name)
    client = chrome_mcp_client.build_client(profile_dir, headless=headless)
    # 必须是同一个 session 贯穿全程（一个 Chrome 实例），不能每次工具调用各开
    # 一个——见 chrome_mcp_client.open_session() 注释，真机验证撞过这个坑。
    async with chrome_mcp_client.open_session(client) as session:
        tools = await chrome_mcp_client.get_tools(session)
        app = build_graph(tools, tracker=tracker, max_pages=max_pages, max_jobs=max_jobs,
                          max_filter_clicks=max_filter_clicks, select_only=select_only)
        return await app.ainvoke({
            "job_url": job_url,
            "search_url": search_url,
            "resume_pdf_path": resume_pdf_path,
            "site_name": site_name,
        })
