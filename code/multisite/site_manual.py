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
