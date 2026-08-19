"""手册的执行器：给定快照与手册，代码就能干活。

这里的每个函数对应手册里一个闭集字段的一个取值。**加一个执行器＝多支持一类站点**，
而且是一次性的、全站通用的——这正是"不给某个站打补丁"的落点。
设计见 spec §3.2 / §3.7。
"""
import re
from dataclasses import dataclass

from multisite.chrome_mcp_client import get_tool
from multisite.site_manual import SiteManual

# 与 safe_tools.py 的 `_SNAPSHOT_LINE_RE` 逐字节相同、`_flat` 与 chrome_mcp_client 等处的
# 摊平逻辑也重复。**刻意保留这份复制**而不是导入共享：executors.py 是最底层的工具层，
# 不应该反过来依赖 safe_tools（上层安全包装）或别的兄弟模块——单向依赖比省几行更重要。
# 如果哪天两边的正则需要一起改，那才是该提到更底层共享模块的信号，不是现在。
_NODE_RE = re.compile(r'uid=(?P<uid>\S+)\s+(?P<role>\w+)(?:\s+"(?P<name>[^"]*)")?')


@dataclass
class JobRow:
    anchor_uid: str   # 取 URL 时点它；真机验证事件会冒泡到整张卡片
    text: str         # 这一行所有节点的文本，交给分类 LLM 读


@dataclass
class _MatchedNode:
    uid: str
    role: str
    name: str
    line: str   # 原始行文本，供需要读其他属性（如 url="..."）的调用方自己正则


def _matched_nodes(snapshot_text: str) -> list:
    """快照里所有匹配 `uid=...` 的行，按原文顺序，带上角色和原始行文本。

    这是 `split_rows` 和 `job_url_offline`（`link_in_row` 分支）共用的唯一节点索引来源
    ——两处都要按锚点算"这一行的窗口"，必须用同一份解析结果，否则窗口定义会漂移
    （2026-08 审查抓到的 FIX-2：`link_in_row` 原来不限定窗口，10 行全部返回同一个
    页脚链接）。
    """
    out = []
    for line in snapshot_text.splitlines():
        m = _NODE_RE.search(line)
        if m:
            out.append(_MatchedNode(m.group("uid"), m.group("role"),
                                     m.group("name") or "", line))
    return out


def _nodes(snapshot_text: str) -> list:
    """`(uid, name)` 视图，供只需要名字的调用方用（`validate_manual` 判据②）。"""
    return [(n.uid, n.name) for n in _matched_nodes(snapshot_text)]


def _anchor_row_windows(snapshot_text: str, manual: SiteManual):
    """按 `row_anchor` 切出每一行在 `_matched_nodes()` 下标里的窗口 `[start, end)`。

    返回 `(nodes, windows)`：`nodes` 是 `_matched_nodes()` 的结果，`windows` 是
    `[(anchor_uid, start, end), ...]`。`split_rows` 用窗口取行文本，
    `job_url_offline`（`link_in_row`）用同一份窗口限定"这一行"的链接搜索范围——
    两处共用这一个函数，不各自重算一遍。
    """
    nodes = _matched_nodes(snapshot_text)
    anchor_positions = [i for i, n in enumerate(nodes) if n.name == manual.row_anchor]
    if not anchor_positions:
        return nodes, []

    # 按锚点间距**等宽回切**，所有行一视同仁。
    #
    # **不能用「上一个锚点到本锚点」**：`_matched_nodes()` 解析的是整张快照（含导航栏、
    # 筛选器、推广文案），那样第一行会从快照开头一路吞到第一个锚点，把「不确定适合哪个
    # 岗位？」那几条推广文案当成岗位的一部分。等宽回切对第一行和其余行用同一个规则，
    # 不开特例。
    #
    # `+2` 是因为地点那一串通常紧跟在锚点之后，属于本行。
    #
    # **这两条编码了 join.qq.com 的站点几何假设，不是通用规律**：①锚点在列表区内
    # 等距分布（`span = min(相邻锚点间距)`——如果某一行恰好比其他行多一个节点，
    # 所有更宽的行会从头部被"截短"，而头部正是标题，且不会报错，只是标题从行文本里
    # 消失）；②锚点后 2 个节点属于本行（`+2` 是这个站的观察值，换一个站点结构不成立）。
    # 不满足这两条假设的站需要新的 row_split 执行器，而不是调这两个数字。
    spans = [b - a for a, b in zip(anchor_positions, anchor_positions[1:])]
    span = min(spans) if spans else 15
    windows = []
    for pos in anchor_positions:
        start = max(0, pos - span + 2)
        end = pos + 2
        windows.append((nodes[pos].uid, start, end))
    return nodes, windows


def split_rows(snapshot_text: str, manual: SiteManual) -> list:
    """把平铺的快照切成一行一个岗位。`anchor_text` 的窗口算法（等距回切 + `+2`）
    绑定了两条站点几何假设，写在 `_anchor_row_windows` 的注释里——不成立的站需要新的
    row_split 执行器，不是调那两个数字。"""
    if manual.row_split == "container_per_row":
        raise NotImplementedError(
            "container_per_row 执行器还没实现——还没有真实站点需要它。"
            "需要时在这里补一个，不要退化成返回空列表：返回空等于谎报「这一页没有岗位」。"
            "实现后记得把 'container_per_row' 加进 site_manual.IMPLEMENTED_ROW_SPLITS，"
            "否则 from_dict 会一直挡在门口，这个分支永远走不到。")

    nodes, windows = _anchor_row_windows(snapshot_text, manual)
    rows = []
    for anchor_uid, start, end in windows:
        chunk = nodes[start:end]
        rows.append(JobRow(anchor_uid=anchor_uid,
                           text=" ".join(n.name for n in chunk if n.name.strip())))
    return rows


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


_ID_RE = re.compile(r"\b(\d{4,})\b")


def job_url_offline(row: JobRow, snapshot_text: str, manual: SiteManual):
    """不碰浏览器就能取到的 URL。取不到返回 None。

    **None 而不是空串**：调用方要能区分"这一行没有链接"（记一次失败并计数）和
    "链接是空的"（会被当成合法 URL 写进库）。
    """
    if manual.job_url_source == "new_tab_on_click":
        raise ValueError("new_tab_on_click 要走 job_url_online()——它必须真的点一下浏览器")

    if manual.job_url_source == "link_in_row":
        # 锚点所在行的**同一张卡片**里那个 link 节点，**限定在这一行的窗口内搜索**。
        #
        # **不能扫全文**：快照是平铺的，锚点之前几乎总有导航栏/页脚链接。真实 fixture
        # 实测过：不限定窗口时，"这一行没有链接"不会返回 None，而是返回一个完全无关的
        # 链接（10 行全部返回同一个页脚"部门介绍"链接）——`validate_manual` 的判据③
        # 还拦不住它，因为那个链接照样以 http 开头。
        nodes, windows = _anchor_row_windows(snapshot_text, manual)
        window = next(((s, e) for uid, s, e in windows if uid == row.anchor_uid), None)
        if window is None:
            return None
        start, end = window
        for n in nodes[start:end]:
            if n.role == "link" and 'url="' in n.line:
                m = re.search(r'url="([^"]*)"', n.line)
                if m:
                    return m.group(1)
        return None

    # id_template
    m = _ID_RE.search(row.text)
    return manual.url_template.replace("{id}", m.group(1)) if m else None


_PAGE_LINE_RE = re.compile(r"^\s*(?P<idx>\d+):\s*.*?\((?P<url>https?://[^)]+)\)(?P<sel>.*)$", re.M)


def _parse_pages(text: str) -> list:
    """`list_pages` 的输出 → [(idx, url, is_selected)]。"""
    return [(int(m.group("idx")), m.group("url"), "[selected]" in m.group("sel"))
            for m in _PAGE_LINE_RE.finditer(text or "")]


def _flat(result) -> str:
    # 与 chrome_mcp_client / safe_tools 里"摊平 MCP content block"的逻辑重复——同一处
    # 刻意取舍见文件顶部 `_NODE_RE` 的注释：这里保持复制，不反向依赖上层模块。
    if isinstance(result, list):
        return "\n".join(b.get("text", "") for b in result if isinstance(b, dict))
    return str(result)


async def job_url_online(row: JobRow, tools, manual: SiteManual):
    """点开卡片、从新标签页读 URL、关掉。取不到返回 None。

    **拿完必须关**：不关的话标签页越积越多，`list_pages` 里"哪个是刚开的"就判不准了，
    第 11 个岗位会拿到第 3 个岗位的 URL——而这种错完全不会报错，只会让库里躺着
    一批指错地方的记录。

    **异常安全性**：本函数不吞异常（fail fast）。如果 `close_page` 本身调用失败，
    异常会原样上抛，新开的那个标签页**不会**被关闭。计划 B 的 harvest 循环会连续
    调用本函数几十次，这种残留会累积，并让后续调用里"哪个是刚开的"判定失准——
    调用方需要知晓这一点（例如捕获异常时考虑是否需要额外清理）。

    **只取 URL，不读 JD**——拿到 URL 就立刻 `close_page`。spec §5.1 的成本论证建立在
    "在 new_tab_on_click 类站点上，取 URL 和取 JD 是同一次访问"上（本来就要点开详情页
    才能拿到 URL，顺手读 JD 近乎免费），但**这个函数目前没有兑现那半句"顺手"**——
    详情页开了又关，JD 正文从没被读过。这不是本次改动要修的东西：计划 B 的
    `harvest_current_page` 才是唯一的消费方，且它还没写；届时改这里的签名（多返回一段
    JD 文本）比现在猜一个还没有调用方验证过的形状更划算。

    **用索引集合而不是 URL 集合做"新开的是哪一页"的判定**（见下方实现）：`list_pages`
    出错时 chrome-devtools-mcp 会把错误文本当正常内容返回（`isError=False`，
    见 `safe_tools.py` `_result_text` 的注释），这不是异常路径，是常态。用 URL 集合
    做基准时，出错文本解析出的 `before` 是空集，`after` 里每一页（包括列表页本身，
    索引 0）都会被判成"新开的"，函数会把**列表页 URL**当成岗位 URL 返回，并把
    **列表页本身**关掉——这个错不会抛异常，只会让调用方悄悄拿到一批错的 URL。
    """
    if manual.job_url_source != "new_tab_on_click":
        raise ValueError(f"job_url_online 只处理 new_tab_on_click，收到 {manual.job_url_source}")

    before_raw = _flat(await get_tool(tools, "list_pages").ainvoke({}))
    before = _parse_pages(before_raw)
    if not before:
        # 页面数不可能是 0（至少有当前这一个列表页）。空解析结果几乎总是工具调用出错，
        # 而不是真的没有页面——继续往下走会把 `after` 里的每一页都误判成"新开的"，
        # 详见上面的 docstring。fail fast，把原始返回内容带出来方便诊断。
        raise RuntimeError(
            "list_pages 在点击前解析不出任何页面（页面数至少应为 1，很可能是工具调用"
            f"出错而非真的没有页面）。原始返回：{before_raw!r}")
    before_indices = {idx for idx, _, _ in before}
    # 点击前处于 [selected] 的那一页——即使索引集合判定出于某种原因失灵，也不能把
    # 点击前的当前页误判成"新开的"。
    selected_before = {idx for idx, _, is_selected in before if is_selected}

    await get_tool(tools, "click").ainvoke({"uid": row.anchor_uid})
    after = _parse_pages(_flat(await get_tool(tools, "list_pages").ainvoke({})))

    fresh = [(idx, url) for idx, url, _ in after
             if idx not in before_indices and idx not in selected_before]
    if not fresh:
        # 点了没开新页。返回 None 让调用方计一次失败——**绝不能把当前列表页的 URL
        # 当成岗位 URL**。
        return None
    idx, url = fresh[0]
    await get_tool(tools, "close_page").ainvoke({"pageIdx": idx})
    return url


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
