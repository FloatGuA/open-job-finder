"""Layer 1（识别/判断）agent —— docs/multi-site-expansion-design.md 四层架构的第一层。

给一个具体的目标网站职位 URL，跑一遍：登录检查 → 打开申请表并上传简历触发对方
解析 → 扫描解析后仍为空的表单字段并分类/生成候选值 → 写一条 pending_applications
记录，交给已经做完的 Layer 2（Dashboard 审批页）人工审批。

**硬边界，写在代码结构里，不是靠 prompt 叮嘱**：
1. `build_graph()` 只绑定了 navigate_page/take_snapshot/click/upload_file/wait_for
   这几个只读+局部交互的工具——工具集里根本没有任何"提交/下一步"能力，不是靠
   指令让 agent 别点，是压根没给它点的手段。
2. government_id 类字段的候选值在 `_enforce_government_id_blank()` 里被无条件
   清空，不管 LLM 分类节点返回了什么。

只处理"上传简历解析后，第一个可见 wizard 步骤"里的空字段——华为申请表是分步
表单，不填完当前步就进不去下一步，而 Layer 1 本身不填表单（那是 Layer 3 的
职责），所以结构上只能看到这一步，见 docs/multi-site-expansion-design.md 和
DECISION.md 对应记录。

用 LangGraph StateGraph 编排（而不是一路到底的函数）是为了两点：①每个节点独立
可观测（对应旧 W1/W2 pipeline 里 Step 的价值）；②浏览器自动化容易在任意一步
失败（登录超时/上传失败/网络抖动），节点划分让失败定位更精确，未来要加断点续跑
也有自然的挂载点——这次先不做 checkpointer，留着接口。
"""
import asyncio
import os
import re
from pathlib import Path
from typing import Literal, Optional, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from multisite import chrome_mcp_client
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
    job_url: str
    resume_pdf_path: str
    site_name: str
    job_title: str
    company: str
    snapshot_text: str
    empty_elements: list[ScannedElement]
    classified_fields: list[FieldClassification]
    pending_application_id: int


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


def _find_uid_by_label(snapshot_text: str, keywords: list[str], roles: Optional[set] = None) -> Optional[str]:
    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if not m:
            continue
        if roles and m.group("role") not in roles:
            continue
        name = m.group("name") or ""
        if any(k.lower() in name.lower() for k in keywords):
            return m.group("uid")
    return None


def _find_uid_near_text(snapshot_text: str, landmark_keywords: list[str], roles: set) -> Optional[str]:
    """兜底策略：目标控件本身经常没有可读的 accessible name（真机验证在拓竹
    的投递表单上撞到过——`<input type=file>` 没有 name/label，`_find_uid_by_label`
    对它必然无解）。改成先找到附近的文字地标（比如"将你的简历拖拽至此处"这类
    提示语，它作为普通文本节点是有 name 的），命中地标之后，取文档序里紧跟着的
    第一个目标 role 元素——不要求这个元素本身可读，只要求它离一段可读的说明文字
    够近。"""
    seen_landmark = False
    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if not m:
            continue
        name = m.group("name") or ""
        if any(k.lower() in name.lower() for k in landmark_keywords):
            seen_landmark = True
            continue
        if seen_landmark and m.group("role") in roles:
            return m.group("uid")
    return None


def _enforce_government_id_blank(fields: list[FieldClassification]) -> list[FieldClassification]:
    """硬约束：government_id 类字段的 candidate_value 无条件清空。见模块 docstring。"""
    for f in fields:
        if f.kind == "government_id" and f.candidate_value:
            f.candidate_value = ""
    return fields


def build_graph(tools: list, personal_info: Optional[dict] = None, tracker: Optional[ApplicationTracker] = None):
    """组装 Layer 1 的 LangGraph。tools 来自 chrome_mcp_client.get_tools()，通过
    闭包绑定进各节点——不放进 state（不是可序列化/可 checkpoint 的东西）。"""
    navigate = chrome_mcp_client.get_tool(tools, "navigate_page")
    take_snapshot = chrome_mcp_client.get_tool(tools, "take_snapshot")
    click = chrome_mcp_client.get_tool(tools, "click")
    upload_file = chrome_mcp_client.get_tool(tools, "upload_file")
    wait_for = chrome_mcp_client.get_tool(tools, "wait_for")

    personal_info = personal_info if personal_info is not None else load_personal_info()
    tracker = tracker or ApplicationTracker()
    pm = PromptManager()

    async def navigate_and_check_login(state: Layer1State) -> dict:
        await navigate.ainvoke({"type": "url", "url": state["job_url"]})
        # navigate_page 只保证浏览器导航本身完成，不保证 SPA 客户端渲染完成
        # （真机验证撞到过：不等就立刻截图，拿到的是 about:blank，后面所有步骤
        # 都在一张空页面上找元素，必然全部落空）。轮询直到快照不再是空壳。
        snapshot = _extract_text(await take_snapshot.ainvoke({}))
        for _ in range(10):
            if not _looks_blank(snapshot):
                break
            await asyncio.sleep(1)
            snapshot = _extract_text(await take_snapshot.ainvoke({}))
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
                snapshot = _extract_text(await take_snapshot.ainvoke({}))
                if not _looks_logged_out(snapshot):
                    print("检测到登录态，继续。")
                    break
            else:
                raise RuntimeError("等待手动登录超时（10 分钟），请重新运行")
        return {"snapshot_text": snapshot}

    async def open_application_and_upload_resume(state: Layer1State) -> dict:
        snapshot = state["snapshot_text"]
        apply_uid = _find_uid_by_label(snapshot, ["申请", "apply", "投递"])
        if apply_uid:
            await click.ainvoke({"uid": apply_uid})
            await wait_for.ainvoke({"text": ["上传", "upload", "简历"]})
            snapshot = _extract_text(await take_snapshot.ainvoke({}))

        # 先按可读标签找上传控件；找不到就退回"离'简历'相关文字最近的可交互
        # 元素"（真机验证在拓竹的投递表单上撞到过：<input type=file> 本身没有
        # accessible name，直接按标签匹配必然落空，见 _find_uid_near_text 注释）。
        upload_uid = _find_uid_by_label(
            snapshot, ["简历", "resume", "选择文件", "upload"], roles={"button", "textbox"}
        ) or _find_uid_near_text(
            snapshot, ["简历", "resume", "拖拽", "drag"], roles={"button", "textbox"}
        )
        if upload_uid is None:
            _dump_debug_snapshot("upload_uid_not_found", snapshot)
            raise RuntimeError("找不到简历上传入口，需人工看一下当前页面结构（目标站点表单可能与预期不同，已把快照存到 data/multisite_debug/）")

        await upload_file.ainvoke({"uid": upload_uid, "filePath": state["resume_pdf_path"]})
        # 不是所有站点都像华为那样有"解析成功/失败"的文字反馈（DECISION.md「表单
        # 字段填写简化」已记录这个前提不总成立）——固定等几秒让上传/预览渲染完，
        # 不强求一个可能压根不存在的成功信号。
        await asyncio.sleep(3)

        return {"snapshot_text": _extract_text(await take_snapshot.ainvoke({}))}

    async def scan_and_classify_fields(state: Layer1State) -> dict:
        _dump_debug_snapshot("scan_raw_snapshot", state["snapshot_text"])
        empty_elements = _parse_empty_input_elements(state["snapshot_text"])
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
        llm = ChatOpenAI(
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )
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
    graph.add_node("navigate_and_check_login", navigate_and_check_login)
    graph.add_node("open_application_and_upload_resume", open_application_and_upload_resume)
    graph.add_node("scan_and_classify_fields", scan_and_classify_fields)
    graph.add_node("write_pending_application", write_pending_application)

    graph.add_edge(START, "navigate_and_check_login")
    graph.add_edge("navigate_and_check_login", "open_application_and_upload_resume")
    graph.add_edge("open_application_and_upload_resume", "scan_and_classify_fields")
    graph.add_edge("scan_and_classify_fields", "write_pending_application")
    graph.add_edge("write_pending_application", END)

    return graph.compile()


async def run_layer1(
    job_url: str,
    resume_pdf_path: str,
    site_name: str,
    headless: bool = False,
    tracker: Optional[ApplicationTracker] = None,
) -> int:
    """跑一次 Layer 1，返回写入的 pending_applications id。"""
    profile_dir = chrome_mcp_client.profile_dir_for_site(site_name)
    client = chrome_mcp_client.build_client(profile_dir, headless=headless)
    # 必须是同一个 session 贯穿全程（一个 Chrome 实例），不能每次工具调用各开
    # 一个——见 chrome_mcp_client.open_session() 注释，真机验证撞过这个坑。
    async with chrome_mcp_client.open_session(client) as session:
        tools = await chrome_mcp_client.get_tools(session)
        app = build_graph(tools, tracker=tracker)
        result = await app.ainvoke(
            {"job_url": job_url, "resume_pdf_path": resume_pdf_path, "site_name": site_name}
        )
    return result["pending_application_id"]
