"""求职偏好渲染的测试。

守两件事：①应届/日常实习这类**整个项目共用**的范围真的进到了 agent 看得见的
约束里（用户明确要求过"我说应届，日常实习，整个项目的考虑范围"）；②Boss 专用的
枚举字段（financing/position_types 之类）**没有**混进去——那些值只有 Boss 认得，
喂给别的站点的 agent 只会让它去猜语义。
"""
from services.profile_loader import JobSeeking, Profile
from multisite.preferences import render_constraints


def _profile(**kw) -> Profile:
    base = dict(
        cities=["深圳"],
        degree=["本科", "硕士"],
        job_seeking=JobSeeking(
            recruit_types=["校招", "应届", "日常实习"],
            target_roles=["运营", "产品", "Agent 开发"],
            exclude=["社招", "有经验要求"],
        ),
    )
    base.update(kw)
    return Profile(**base)


class TestRenderConstraints:
    def test_includes_recruit_types(self):
        text = render_constraints(_profile())
        assert "日常实习" in text and "应届" in text and "校招" in text

    def test_includes_city_and_degree_from_profile_top_level(self):
        # 城市/学历刻意复用 profile 顶层字段，不在 job_seeking 里再存一份。
        text = render_constraints(_profile())
        assert "深圳" in text
        assert "本科" in text and "硕士" in text

    def test_includes_exclusions(self):
        text = render_constraints(_profile())
        assert "社招" in text and "有经验要求" in text

    def test_excludes_boss_specific_enum_fields(self):
        # 这些是喂 boss_search_url 拼 URL 的站点专用值，不该出现在通用约束里。
        text = render_constraints(_profile(
            financing=["已上市"], position_types=["技术"], industries=["互联网"],
            job_types=["全职"], salary="10-20K", keywords=["ai"],
        ))
        for boss_only in ("已上市", "技术", "互联网", "全职", "10-20K"):
            assert boss_only not in text

    def test_empty_profile_tells_agent_to_be_uncertain(self):
        # 没配置偏好时**不能**渲染成空字符串——那等于给 agent 一个"无约束"的
        # 提示，它会把所有岗位都当成符合条件。
        text = render_constraints(Profile())
        assert text.strip()
        assert "不确定" in text

    def test_partial_config_only_renders_present_fields(self):
        text = render_constraints(Profile(
            cities=["深圳"], job_seeking=JobSeeking(recruit_types=["日常实习"]),
        ))
        assert "日常实习" in text and "深圳" in text
        assert "学历" not in text  # degree 为空就不该渲染这一行
