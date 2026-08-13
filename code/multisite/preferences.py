"""把 profile.yaml 的求职偏好渲染成给 agent 看的自然语言约束。

**为什么要有这一层转换**：`profile.yaml` 里 `cities`/`degree`/`keywords` 这些字段
的取值是 Boss 直聘认得的**枚举字符串**（喂 `services/boss_search_url.py` 拼 URL），
而多站点 agent 需要的是"用人话说清楚我要什么"。直接把 dataclass 丢给 LLM 会让它
去猜字段语义，也会把 Boss 专用字段（financing/position_types 之类）当成通用条件。

所以这里只挑**跨站点通用**的几项，翻译成一段说明。要加新条件，先问一句：这一条
在别的招聘站上也成立吗？只对 Boss 成立的东西不属于这里。
"""
from typing import Optional

from services.profile_loader import Profile, ProfileLoader


def load_profile(profile_path=None) -> Profile:
    return ProfileLoader(profile_path).load()


def render_constraints(profile: Optional[Profile] = None) -> str:
    """渲染成一段中文约束描述，直接嵌进 agent 的 system prompt。"""
    p = profile if profile is not None else load_profile()
    js = p.job_seeking

    lines: list[str] = []
    if js.recruit_types:
        lines.append(f"- 招聘类型：只看 {('、'.join(js.recruit_types))}。其他类型一律不算符合。")
    if p.cities:
        lines.append(f"- 工作地点：必须在 {('、'.join(p.cities))}。地点不符的一律不算符合。")
    if js.target_roles:
        lines.append(
            f"- 目标方向：{('、'.join(js.target_roles))} 相关的岗位。"
            "按岗位**实际做什么**判断，不要只看标题里有没有这些字。"
        )
    if p.degree:
        lines.append(f"- 学历：我是 {('/'.join(p.degree))} 学历，学历要求高于此的不算符合。")
    if js.exclude:
        lines.append(f"- 明确排除：{('、'.join(js.exclude))}。命中任意一条就不算符合。")

    return "\n".join(lines) if lines else "（未配置求职偏好，请把所有岗位都标为不确定）"


def describe_for_log(profile: Optional[Profile] = None) -> str:
    """一行摘要，给 CLI 打印用——跑之前让人一眼看清 agent 是按什么条件在筛。"""
    p = profile if profile is not None else load_profile()
    js = p.job_seeking
    return (
        f"类型={js.recruit_types or '-'} 地点={p.cities or '-'} "
        f"方向={js.target_roles or '-'} 排除={js.exclude or '-'}"
    )
