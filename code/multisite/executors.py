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


def _matched_nodes(snapshot_text: str) -> list[_MatchedNode]:
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


# `spans` 只有在锚点数量 >= 2 时才非空（`zip(positions, positions[1:])` 至少要
# 两个点才能求出一个间距）；`_anchor_row_windows` 已经把 0 个锚点的情况提前
# return 掉了，所以这个回退值只在**恰好 1 个锚点**时触发。没有真实数据支持这个
# 具体值——15 只是"总比 0 强"的保守兜底，不是某个站点的观察值。
_SINGLE_ANCHOR_SPAN_FALLBACK = 15


def _anchor_row_windows(
    snapshot_text: str, manual: SiteManual
) -> tuple[list[_MatchedNode], list[tuple[str, int, int]]]:
    """按 `row_anchor` 切出每一行在 `_matched_nodes()` 下标里的窗口 `[start, end)`。

    返回 `(nodes, windows)`：`nodes` 是 `_matched_nodes()` 的结果，`windows` 是
    `[(anchor_uid, start, end), ...]`。`split_rows` 用窗口取行文本，
    `job_url_offline`（`link_in_row`）用同一份窗口限定"这一行"的链接搜索范围——
    两处共用这一个函数，不各自重算一遍。

    **按 uid 查找窗口是"首个命中优先"，是有意的**：真实 a11y 快照的 uid 不保证
    唯一（本仓库 fixture 里 `uid=1_7` 就出现了两次），`job_url_offline` 按
    `uid == row.anchor_uid` 用 `next(...)` 取第一个匹配的窗口，重复 uid 时后面
    那个永远取不到——目前没有站点撞上这个边界，先记录取舍，不提前设计。
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
    span = min(spans) if spans else _SINGLE_ANCHOR_SPAN_FALLBACK
    windows = []
    for pos in anchor_positions:
        start = max(0, pos - span + 2)
        end = pos + 2
        windows.append((nodes[pos].uid, start, end))
    return nodes, windows


_URL_ATTR_RE = re.compile(r'url="([^"]*)"')


def _split_rows_container_per_row(snapshot_text: str, manual: SiteManual) -> list[JobRow]:
    """bambulab 这类站：每个岗位就是**一个 link 节点**，标题/地点/部门/JD 全部拼在
    它的 accessible name 里，没有 join.qq.com 那种"必现且仅现一次的锚点文本"可用
    （岗位卡片没有容器包裹，行文本各不相同，anchor_text 无从下手）。

    **怎么认出"哪些 link 是岗位卡片"**：bambulab 真机快照里同一页有 15 个 link，
    10 个岗位 + 5 个导航（"职位"/"产品官网"/"招聘官网首页"/"社会招聘"/"校招FAQ"）。
    唯一稳定区分二者的信号是 **url**——岗位详情页 url 都带 `/position/`，导航链接
    不带。标题、role、缩进层级三者在这个站的快照里岗位和导航完全一样，唯独 url
    不同，所以取 `manual.row_anchor` 当"url 必须包含的子串"，而不是复用
    anchor_text 那种"节点 name 精确匹配"。

    这里**不限定 role**（没有硬编码检查 `role == "link"`）：判据是"这一行有没有
    `url="..."` 属性、且这个 url 包含 row_anchor"，天然只命中带 url 的节点。
    真实数据只见过这一种"容器＝link"的形状；如果将来出现"容器是别的 role 但
    也带 url"的站，这条判据仍然成立，不需要改。若某站的容器根本没有 url 属性
    （标题和链接分离到两个子节点），那是另一种几何，需要新的 row_split 执行器，
    不是往这里加分支。"""
    rows = []
    for n in _matched_nodes(snapshot_text):
        m = _URL_ATTR_RE.search(n.line)
        if m and manual.row_anchor in m.group(1):
            rows.append(JobRow(anchor_uid=n.uid, text=n.name))
    return rows


def split_rows(snapshot_text: str, manual: SiteManual) -> list[JobRow]:
    """把平铺的快照切成一行一个岗位。`anchor_text` 的窗口算法（等距回切 + `+2`）
    绑定了两条站点几何假设，写在 `_anchor_row_windows` 的注释里——不成立的站需要新的
    row_split 执行器，不是调那两个数字。`container_per_row` 见
    `_split_rows_container_per_row`。"""
    if manual.row_split == "container_per_row":
        return _split_rows_container_per_row(snapshot_text, manual)

    nodes, windows = _anchor_row_windows(snapshot_text, manual)
    rows = []
    for anchor_uid, start, end in windows:
        chunk = nodes[start:end]
        rows.append(JobRow(anchor_uid=anchor_uid,
                           text=" ".join(n.name for n in chunk if n.name.strip())))
    return rows


def read_total_count(snapshot_text: str, manual: SiteManual) -> int | None:
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
        # `SiteManual.from_dict` 已经在入口把不合法正则拦下了（见
        # `site_manual.py` `TestTotalCountLocatorMustBeValidRegex`），所以这条
        # 分支现在近乎死代码——**不要删**：`from_dict` 只挡得住经过它构造出来的
        # manual，直接构造 dataclass（测试就是这么干的，也不排除将来有别的路径）
        # 仍能绕过去，这里是那条路径的兜底。
        return None
    if not m or not m.groups():
        return None
    try:
        return int(m.group(1))
    except (ValueError, IndexError):
        return None


_ID_RE = re.compile(r"\b(\d{4,})\b")


def job_url_offline(row: JobRow, snapshot_text: str, manual: SiteManual) -> str | None:
    """不碰浏览器就能取到的 URL。取不到返回 None。

    **None 而不是空串**：调用方要能区分"这一行没有链接"（记一次失败并计数）和
    "链接是空的"（会被当成合法 URL 写进库）。
    """
    if manual.job_url_source == "new_tab_on_click":
        raise ValueError("new_tab_on_click 要走 job_url_online()——它必须真的点一下浏览器")

    if manual.job_url_source == "link_in_row":
        if manual.row_split == "container_per_row":
            # 容器模式下**行本身就是那个 link 节点**：`row.anchor_uid` 就是要取
            # url 的节点，不需要（也不能）走下面 anchor_text 的窗口搜索——窗口
            # 算法是为"锚点只是行内众多节点之一、标题在窗口别处"设计的，容器模式
            # 下没有"别处"，`_anchor_row_windows` 按 `manual.row_anchor == n.name`
            # 找锚点位置也无从匹配（container_per_row 下 row_anchor 是 url 子串，
            # 不是节点 name）。直接按 uid 定位这一行自己，取它自己的 url。
            node = next((n for n in _matched_nodes(snapshot_text)
                         if n.uid == row.anchor_uid), None)
            if node is None:
                return None
            m = re.search(r'url="([^"]*)"', node.line)
            return m.group(1) if m else None

        # 锚点所在行的**同一张卡片**里那个 link 节点，**限定在这一行的窗口内搜索**。
        #
        # **不能扫全文**：快照是平铺的，锚点之前几乎总有导航栏/页脚链接。真实 fixture
        # 实测过：不限定窗口时，"这一行没有链接"不会返回 None，而是返回一个完全无关的
        # 链接（10 行全部返回同一个页脚"部门介绍"链接）——`validate_manual` 的判据③
        # 还拦不住它，因为那个链接照样以 http 开头。
        #
        # `next(...)` 按 `uid == row.anchor_uid` 取**第一个**匹配的窗口——真实
        # a11y 快照的 uid 不保证唯一（见 `_anchor_row_windows` 的 docstring），
        # 这里"首个命中优先"是有意的，不是漏了去重。
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

    if manual.job_url_source == "id_template":
        m = _ID_RE.search(row.text)
        return manual.url_template.replace("{id}", m.group(1)) if m else None

    # `from_dict` 的闭集校验让这里理论上不可达——但"不可达"是靠**另一个函数**
    # 保证的，直接构造 dataclass（绕过 `from_dict`）就能送进来任意字符串。不能
    # 隐式落进上面的 id_template 分支：那样会静默地拿"看起来像 ID 的数字"去拼
    # 一个空的 url_template，产出一批指哪儿都不对的 URL。
    raise ValueError(f"job_url_offline 不认识 job_url_source={manual.job_url_source!r}")


_PAGE_LINE_RE = re.compile(r"^\s*(?P<idx>\d+):\s*.*?\((?P<url>https?://[^)]+)\)(?P<sel>.*)$", re.M)


def _parse_pages(text: str) -> list[tuple[int, str, bool]]:
    """`list_pages` 的输出 → [(idx, url, is_selected)]。"""
    return [(int(m.group("idx")), m.group("url"), "[selected]" in m.group("sel"))
            for m in _PAGE_LINE_RE.finditer(text or "")]


def _flat(result) -> str:
    # 与 chrome_mcp_client / safe_tools 里"摊平 MCP content block"的逻辑重复——同一处
    # 刻意取舍见文件顶部 `_NODE_RE` 的注释：这里保持复制，不反向依赖上层模块。
    if isinstance(result, list):
        return "\n".join(b.get("text", "") for b in result if isinstance(b, dict))
    return str(result)


async def job_url_online(row: JobRow, tools, manual: SiteManual) -> tuple[str, str] | None:
    """点开卡片、从新标签页读 URL **和 JD 快照**、关掉。取不到仍返回 None。

    返回 `(url, detail_snapshot)`：`detail_snapshot` 是切到新标签页**之后**读到的
    快照文本，即详情页正文，不是列表页——spec §5.1 的成本论证就建立在"取 URL 和取
    JD 是同一次访问"上：这个站本来就必须点开详情页才能拿到 URL，既然已经在这一页
    上了，顺手读走快照近乎免费；分成两次访问会让 run 时长翻倍（每个岗位 ≈8 秒 →
    ≈16 秒）。

    **拿完必须关**：不关的话标签页越积越多，`list_pages` 里"哪个是刚开的"就判不准了，
    第 11 个岗位会拿到第 3 个岗位的 URL——而这种错完全不会报错，只会让库里躺着
    一批指错地方的记录。读快照这一步插在 `close_page` 之前，不改变这条约束。

    **异常安全性**：本函数不吞异常（fail fast）。如果 `close_page` 本身调用失败，
    异常会原样上抛，新开的那个标签页**不会**被关闭。计划 B 的 harvest 循环会连续
    调用本函数几十次，这种残留会累积，并让后续调用里"哪个是刚开的"判定失准——
    调用方需要知晓这一点（例如捕获异常时考虑是否需要额外清理）。

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
    # **在同一次访问里把详情页快照也读走**（spec §5.1）：这个站本来就必须点开才能
    # 拿到 URL，既然已经在这一页上，读快照近乎免费。分成两次访问会让 run 时长翻倍。
    # 必须先 select_page 切过去再 take_snapshot——不切的话读到的是列表页快照，
    # 每个岗位拿到一样的 JD，而这个错不会报错、不崩溃，分类照跑不误。
    # chrome-devtools-mcp 的 select_page/close_page 参数名是 pageId。之前这里和
    # 测试假工具都多打了三个字母（旧参数名比这个多一个 "Idx" 后缀），两边互相
    # 印证却都跟真实 MCP 服务器的参数名不一致，真机会直接因为多出未知参数 /
    # 缺少必填参数而报错。已核对 chrome-devtools-mcp/build/src/tools/pages.js
    # 的 select_page/close_page schema：两者都是 `pageId: zod.number()`。
    await get_tool(tools, "select_page").ainvoke({"pageId": idx})
    detail = _flat(await get_tool(tools, "take_snapshot").ainvoke({}))
    await get_tool(tools, "close_page").ainvoke({"pageId": idx})
    return url, detail


async def validate_manual(snapshot_text: str, tools, manual: SiteManual) -> tuple[bool, str]:
    """旧手册还成不成立。返回 `(过了没有, 人看得懂的原因)`。

    只验三条（spec §3.5），约 3–5 步，远低于全量重探。**任一条不过整份作废**——
    不做部分沿用：手册字段之间有耦合（`filter_interaction` 变了往往意味着筛选区重写，
    `dimensions` 也不可信），逐格判断"哪格还能用"的成本接近重探，而判错的产物是
    半对的手册，最难查。

    **判据①②是可选的**：`total_count_locator` / `dimensions` 为空时对应那条判据
    直接跳过，不算失败。返回的 reason 里如实列出**实际执行了哪几条**、跳过了哪几条
    ——不能不管跑没跑都说"手册仍然成立"，那样一份只配了 `row_anchor` 的手册会
    退化成几乎什么都没验，却看起来跟全验过一样。

    **调用 `job_url_online` 的副作用**：判据③在 `job_url_source=new_tab_on_click`
    时会调 `job_url_online`，它抛异常时**可能残留一个未关闭的标签页**——细节见
    `job_url_online` 自己的 docstring，这里重复一句是因为只读本函数文档的人看不到。
    """
    checked = []
    skipped = []

    # ① 计数文本仍在（可选：手册没配 total_count_locator 就跳过）
    if manual.total_count_locator:
        if read_total_count(snapshot_text, manual) is None:
            return False, f"计数文本读不到了（locator={manual.total_count_locator!r}），站点可能已改版"
        checked.append("计数文本")
    else:
        skipped.append("计数文本（手册未配置 total_count_locator）")

    # ② 第一个维度的选项集合没变（可选：手册没配 dimensions 就跳过）
    if manual.dimensions:
        want = set(manual.dimensions[0].get("options") or [])
        # 直接用 `_matched_nodes()`——判据②只要节点名。将来要把比对限定到
        # checkbox/radio（spec §3.5 列的出路②），`n.role` 就在手边。
        have = {n.name for n in _matched_nodes(snapshot_text) if n.name}
        missing = want - have
        if missing:
            return False, f"筛选维度「{manual.dimensions[0].get('name')}」的选项变了，快照里找不到：{sorted(missing)}"
        checked.append("首个维度选项")
    else:
        skipped.append("首个维度选项（手册未配置 dimensions）")

    # ③ 对第一个岗位实取一次 URL（必做，无法跳过）
    rows = split_rows(snapshot_text, manual)
    if not rows:
        return False, f"按 row_anchor={manual.row_anchor!r} 一行都切不出来"
    if manual.job_url_source == "new_tab_on_click":
        got = await job_url_online(rows[0], tools, manual)
        url = got[0] if got is not None else None
    else:
        url = job_url_offline(rows[0], snapshot_text, manual)
    if not (url or "").startswith("http"):
        return False, f"按 job_url_source={manual.job_url_source} 取不到第一个岗位的 URL"
    checked.append("取 URL")

    reason = f"已验：{' / '.join(checked)}"
    if skipped:
        reason += f"；跳过：{'；'.join(skipped)}"
    return True, reason
