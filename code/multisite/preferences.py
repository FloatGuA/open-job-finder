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
    if js.categories:
        quota_desc = "、".join(f"{c.name} 最多 {c.max} 个" for c in js.categories)
        lines.append(
            f"- 目标方向与名额：{quota_desc}。"
            "按岗位**实际做什么**归类，不要只看标题里有没有这些字。"
            "不属于以上任何一类的岗位一律不算符合。"
        )
    if p.degree:
        lines.append(f"- 学历：我是 {('/'.join(p.degree))} 学历，学历要求高于此的不算符合。")
    if js.exclude:
        lines.append(f"- 明确排除：{('、'.join(js.exclude))}。命中任意一条就不算符合。")

    return "\n".join(lines) if lines else "（未配置求职偏好，请把所有岗位都标为不确定）"


def render_golden_examples(tracker=None, limit: int = 20) -> str:
    """把人工确认过的归类纠正渲染成 few-shot 例子，喂回选岗 agent。

    **为什么需要它**：类别之间天然有重叠（"AI NATIVE" 和 "开发" 尤其），靠 prompt
    里写死规则只能覆盖我预先想到的情况。真机第一次跑就撞上了：「数据算法工程师」
    职责里写着 CV/多模态/LLM/Agent 工具开发，agent 归成了「开发」，还顺手占掉开发
    的最后一个名额、把 AI NATIVE 饿死。写死的规则治得了这一条，治不了下一条。
    人工纠正是唯一持续产出真实标注的地方，把它接回 prompt 才能自我修正。

    只用 `is_golden` 标记过的（不是所有改动过的）——随手改一下不代表那是标准案例，
    没确认过的例子进 prompt 只会教偏。

    `why` 截断到 60 字：例子的作用是给出判别线索，不是复述职责全文；20 条 × 全文
    足够把 DeepSeek 的 64k 上下文吃掉一大块。
    """
    if tracker is None:
        from services.tracker import ApplicationTracker
        tracker = ApplicationTracker()
    rows = tracker.get_golden_category_examples(limit=limit)
    if not rows:
        return "（暂无历史纠正案例）"
    lines = []
    for r in rows:
        clue = (r.why or "").strip().replace("\n", " ")
        clue = f"（{clue[:60]}）" if clue else ""
        lines.append(f"- 「{r.title or r.url}」{clue}\n"
                     f"  归类为「{r.category_agent}」是错的，应该归「{r.category}」")
    return "\n".join(lines)


def describe_for_log(profile: Optional[Profile] = None) -> str:
    """一行摘要，给 CLI 打印用——跑之前让人一眼看清 agent 是按什么条件在筛。"""
    p = profile if profile is not None else load_profile()
    js = p.job_seeking
    return (
        f"类型={js.recruit_types or '-'} 地点={p.cities or '-'} "
        f"名额={js.quotas or '-'} 排除={js.exclude or '-'}"
    )
