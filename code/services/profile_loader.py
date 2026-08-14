from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

_DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "profile.yaml"


@dataclass
class JobCategory:
    """一个求职方向 + 本次最多找几个。

    `max` 是**上限也是导航信号**：选岗 agent 每记一条就被告知各类还差几个，配额
    全满即为完成条件。上限设成 0 等于"这一类不找"，但更清楚的做法是直接不写这一类。
    """
    name: str
    max: int = 3


@dataclass
class JobSeeking:
    """站点无关的求职范围——**整个项目共用**，不是某一个站点的筛选参数。

    与上面 Profile 里那些字段的区别：`keywords`/`experience`/`job_types` 等是
    直接喂 `services/boss_search_url.py` 拼 Boss URL 的**站点专用枚举值**（取值
    必须是 Boss 认得的字符串）；这里的三个字段是**用自然语言表达的意图**，由各
    站点的 agent 自己翻译成本站的筛选项。多站点 Layer 1 判断"这个岗位算不算数"
    读的是这一份。

    刻意**不**包含城市/学历：那两个 profile 顶层已经有（`cities`/`degree`），
    再存一份就是同一份数据两个写入口。要用请读 Profile 上的同名字段。
    """
    recruit_types: List[str] = field(default_factory=list)   # 校招 / 应届 / 日常实习
    # 方向 + 每个方向最多找几个。**取代了旧的 target_roles**（那只是不带配额的
    # 同一份数据，两份并存必漂移）。配额不是装饰：没有它，选岗 agent 会一路记满
    # 总数就停——真机跑过一次，5 个名额全被"运营"占了，产品/开发/日常实习一个
    # 都没有，而且这种偏斜在结果里完全看不出来（每一条单看都符合条件）。
    # 类别同时是 agent 上报 category 的枚举约束：不在这个表里的类别会被拒绝。
    categories: List["JobCategory"] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)         # 社招 / 有经验要求
    # 按站点跳过某些类别：`{"bambulab": ["游戏"]}`。
    # **必须由人来配，不能让 agent 自己推断**——它这轮"没找到游戏岗"的真实原因是
    # 筛选器把非研发类整个挡住了，不是站上没有。"没找到"≠"不存在"，跟站点投递
    # 上限那个三态是同一个错误。agent 只汇报，人来定论。
    #
    # 而且这不只是省步数：选岗的主终止条件是"所有名额已满"，配一个本站不存在的
    # 类别就等于那个条件永远不成立，agent 只能靠翻页预算耗尽来停。
    site_skip: dict = field(default_factory=dict)

    @property
    def category_names(self) -> List[str]:
        return [c.name for c in self.categories]

    @property
    def quotas(self) -> dict:
        return {c.name: c.max for c in self.categories}

    def quotas_for_site(self, site_name: str) -> dict:
        """去掉该站点明确不做的类别后的名额表。"""
        skip = {s.strip() for s in (self.site_skip.get(site_name) or [])}
        return {name: cap for name, cap in self.quotas.items() if name not in skip}


@dataclass
class Profile:
    """Layer 2 用户求职偏好画像。字段与 build_search_url 的筛选项一一对应。"""
    keywords: List[str] = field(default_factory=list)
    cities: List[str] = field(default_factory=list)
    experience: List[str] = field(default_factory=list)
    degree: List[str] = field(default_factory=list)
    salary: str = ""
    job_types: List[str] = field(default_factory=list)
    financing: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)
    position_types: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    boss_online: bool = False
    # 用户自定义 prompt 注入（global 系统层 + 各 task 层）；见 PromptManager。
    prompt_injection: dict = field(default_factory=dict)
    # 站点无关的求职范围，多站点 Layer 1 用；见 JobSeeking 的说明。
    job_seeking: JobSeeking = field(default_factory=JobSeeking)


class ProfileLoader:
    def __init__(self, profile_path: Optional[Path] = None) -> None:
        self._path = Path(profile_path) if profile_path is not None else _DEFAULT_PROFILE_PATH

    def load(self) -> Profile:
        if not self._path.exists():
            raise FileNotFoundError(f"Profile not found: {self._path}")

        with self._path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        # 注意：`name` 字段已于 v2.22.0 从 profile.yaml 删除 —— 投递的打招呼语由
        # Boss 平台自动发送，全流程不消费它，早期的必填校验是残留（曾无谓拦住 W1）。
        js_raw = dict(raw.get("job_seeking") or {})
        return Profile(
            keywords=list(raw.get("keywords") or []),
            cities=list(raw.get("cities") or []),
            experience=list(raw.get("experience") or []),
            degree=list(raw.get("degree") or []),
            salary=str(raw.get("salary") or ""),
            job_types=list(raw.get("job_types") or []),
            financing=list(raw.get("financing") or []),
            districts=list(raw.get("districts") or []),
            position_types=list(raw.get("position_types") or []),
            industries=list(raw.get("industries") or []),
            boss_online=bool(raw.get("boss_online", False)),
            prompt_injection=dict(raw.get("prompt_injection") or {}),
            job_seeking=JobSeeking(
                recruit_types=list(js_raw.get("recruit_types") or []),
                categories=_parse_categories(js_raw.get("categories")),
                exclude=list(js_raw.get("exclude") or []),
                site_skip={
                    str(site): list(cfg.get("skip") or [])
                    for site, cfg in (js_raw.get("site_overrides") or {}).items()
                },
            ),
        )


def _parse_categories(raw) -> List[JobCategory]:
    """`categories: [{name: 产品, max: 3}, ...]`。

    也接受纯字符串项（`- 产品`）当作 max 取默认值——手写 YAML 时少写一层很常见，
    直接报错除了膈应人没有好处。但**不接受缺 name 的项**：那说明配置写错了，静默
    跳过会表现为"agent 莫名其妙不找这一类"，极难查。
    """
    out: List[JobCategory] = []
    for item in (raw or []):
        if isinstance(item, str):
            out.append(JobCategory(name=item))
            continue
        name = str((item or {}).get("name") or "").strip()
        if not name:
            raise ValueError(f"profile.yaml job_seeking.categories 里有缺少 name 的项：{item!r}")
        out.append(JobCategory(name=name, max=int(item.get("max", 3))))
    return out
