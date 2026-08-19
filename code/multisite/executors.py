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

    # 按锚点间距**等宽回切**，所有行一视同仁。
    #
    # **不能用「上一个锚点到本锚点」**：`_nodes()` 解析的是整张快照（含导航栏、筛选器、
    # 推广文案），那样第一行会从快照开头一路吞到第一个锚点，把「不确定适合哪个岗位？」
    # 那几条推广文案当成岗位的一部分。等宽回切对第一行和其余行用同一个规则，不开特例。
    #
    # `+2` 是因为地点那一串通常紧跟在锚点之后，属于本行。
    spans = [b - a for a, b in zip(anchor_positions, anchor_positions[1:])]
    span = min(spans) if spans else 15
    rows = []
    for pos in anchor_positions:
        chunk = nodes[max(0, pos - span + 2):pos + 2]
        rows.append(JobRow(anchor_uid=nodes[pos][0],
                           text=" ".join(n for _, n in chunk if n.strip())))
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

    **异常安全性**：本函数不吞异常（fail fast）。如果 `close_page` 本身调用失败，
    异常会原样上抛，新开的那个标签页**不会**被关闭。计划 B 的 harvest 循环会连续
    调用本函数几十次，这种残留会累积，并让后续调用里"哪个是刚开的"判定失准——
    调用方需要知晓这一点（例如捕获异常时考虑是否需要额外清理）。
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
