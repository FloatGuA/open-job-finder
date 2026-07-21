from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

_DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "profile.yaml"


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
    extra_notes: str = ""
    name: str = ""  # 投递不使用（Boss 招呼全自动）；保留仅为兼容历史引用


class ProfileLoader:
    def __init__(self, profile_path: Optional[Path] = None) -> None:
        self._path = Path(profile_path) if profile_path is not None else _DEFAULT_PROFILE_PATH

    def load(self) -> Profile:
        if not self._path.exists():
            raise FileNotFoundError(f"Profile not found: {self._path}")

        with self._path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        # 注意：不再强制 name 非空 —— 投递的打招呼语由 Boss 平台自动发送，
        # 全流程不消费 profile.name。早期的必填校验是残留，会无谓拦住 W1。
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
            extra_notes=str(raw.get("extra_notes") or ""),
            name=str(raw.get("name") or ""),
        )
