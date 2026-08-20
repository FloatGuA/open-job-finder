"""站点操作手册：`survey_structure` 的产出，节点之间的接口。

**为什么闭集字段必须是枚举而不是自由描述**：下游是**代码**（`match manual.job_url_source`）。
agent 写一句"点标题会在新窗口打开"的散文，代码没法据此分派。这组枚举就是通用性的
预算所在——遇到新站的正确反应是**加一个执行器**（一次，全站通用），而不是给某个站
打 prompt 补丁。

设计与取舍见 `docs/superpowers/specs/2026-08-19-m1-survey-plan-scan-design.md` §3。
"""
import re
from copy import deepcopy
from dataclasses import dataclass, field


class ManualError(ValueError):
    """手册不合法。**刻意用异常而不是返回 None**——一份不可执行的手册继续往下走，
    产物是"抓回一堆垃圾"，而那跟"这个站没岗位"长得一模一样。"""


JOB_URL_SOURCES = ("link_in_row", "new_tab_on_click", "id_template")
PAGINATIONS = ("next_button", "url_param", "infinite_scroll", "none")
FILTER_INTERACTIONS = ("direct_click", "expand_group_then_click")
ROW_SPLITS = ("container_per_row", "anchor_text")

# ROW_SPLITS 记录的是设计空间（手册字段"应该"能取的值），IMPLEMENTED_ROW_SPLITS 记录
# 代码实际能执行的子集——两者一旦不一致，`from_dict` 必须挡在 ROW_SPLITS 允许、
# IMPLEMENTED_ROW_SPLITS 不允许的那部分值上面。**新实现一个 row_split 执行器时，
# 记得同步把它加进这里**（另见 `executors.split_rows` 里 `container_per_row` 分支的
# 注释，两处互相指向）。
IMPLEMENTED_ROW_SPLITS = ("anchor_text", "container_per_row")

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
    # `row_anchor` 的含义由 `row_split` 决定，两种 row_split 各自要求它非空：
    #   row_split=anchor_text        → 每个岗位行里必现且仅现一次的**文本**（节点 name）
    #   row_split=container_per_row  → 岗位容器节点 **url 属性**必须包含的子串
    #                                   （如 bambulab 的 "/position/"，用来把岗位
    #                                   link 和导航 link 分开）
    row_anchor: str = ""
    dimensions: list = field(default_factory=list)
    important_notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SiteManual":
        for name, allowed in _ENUMS.items():
            value = d.get(name)
            if value not in allowed:
                raise ManualError(f"{name} 只能是 {allowed} 之一，收到 {value!r}")
        if d["row_split"] not in IMPLEMENTED_ROW_SPLITS:
            raise ManualError(
                f"row_split={d['row_split']!r} 还没有对应的执行器（已实现："
                f"{IMPLEMENTED_ROW_SPLITS}）；遇到这种站请报搞不定，或先在 "
                "executors.split_rows 里加一个执行器再放开这个取值")
        if d["row_split"] in ("anchor_text", "container_per_row") \
                and not (d.get("row_anchor") or "").strip():
            raise ManualError(f"row_split={d['row_split']!r} 时 row_anchor 不能为空")
        if d["job_url_source"] == "id_template":
            template = (d.get("url_template") or "").strip()
            if not template:
                raise ManualError("job_url_source=id_template 时 url_template 不能为空")
            if "{id}" not in template:
                raise ManualError(
                    f"job_url_source=id_template 时 url_template 必须包含 {{id}} 占位符"
                    f"（job_url_offline 用 .replace('{{id}}', ...) 填值，没有占位符会"
                    f"静默无操作，所有岗位拿到同一个 URL），收到 {template!r}")

        locator = (d.get("total_count_locator") or "").strip()
        if locator:
            try:
                compiled = re.compile(locator)
            except re.error as exc:
                raise ManualError(
                    f"total_count_locator 不是合法正则，收到 {locator!r}：{exc}") from exc
            if compiled.groups < 1:
                raise ManualError(
                    f"total_count_locator 必须有一个捕获组（用于取出数字），收到 {locator!r} "
                    "——没有捕获组时 read_total_count 会一直返回 None，validate_manual 会"
                    "把它误诊成「站点已改版」")

        raw_reload = d.get("filters_survive_reload", False)
        if not isinstance(raw_reload, bool):
            raise ManualError(
                f"filters_survive_reload 必须是 bool，收到 {raw_reload!r}"
                f"（{type(raw_reload).__name__}）——手册是 LLM 产的 JSON，"
                f"字符串 'false' 这类值 bool() 会静默转成 True")

        dimensions = d.get("dimensions") or []
        for i, dim in enumerate(dimensions):
            if not isinstance(dim, dict) or "options" not in dim:
                raise ManualError(
                    f"dimensions[{i}] 缺 options 键（收到 {dim!r}）——validate_manual 的判据②"
                    "靠 dimensions[0].get('options') 拿期望的选项集合，缺这个键会让判据"
                    "静默变成永远通过")
            if not isinstance(dim["options"], list):
                raise ManualError(
                    f"dimensions[{i}].options 必须是列表，收到 {dim['options']!r}")

        return cls(
            job_url_source=d["job_url_source"],
            pagination=d["pagination"],
            filter_interaction=d["filter_interaction"],
            row_split=d["row_split"],
            filters_survive_reload=raw_reload,
            url_template=d.get("url_template", ""),
            total_count_locator=d.get("total_count_locator", ""),
            row_anchor=d.get("row_anchor", ""),
            # 深拷贝：`list(d.get("dimensions") or [])` 只拷外层列表，内部 dict 仍与
            # 输入共享引用——调用方事后改自己那份 d["dimensions"][0]["options"] 会
            # 悄悄改到已构造好的 manual 上。
            dimensions=deepcopy(dimensions),
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
