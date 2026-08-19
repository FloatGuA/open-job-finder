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
