from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

_DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "profile.yaml"


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
    target_roles: List[str] = field(default_factory=list)    # 运营 / 产品 / Agent 开发
    exclude: List[str] = field(default_factory=list)         # 社招 / 有经验要求


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
                target_roles=list(js_raw.get("target_roles") or []),
                exclude=list(js_raw.get("exclude") or []),
            ),
        )
