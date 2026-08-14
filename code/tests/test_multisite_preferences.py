"""求职偏好渲染的测试。

守两件事：①应届/日常实习这类**整个项目共用**的范围真的进到了 agent 看得见的
约束里（用户明确要求过"我说应届，日常实习，整个项目的考虑范围"）；②Boss 专用的
枚举字段（financing/position_types 之类）**没有**混进去——那些值只有 Boss 认得，
喂给别的站点的 agent 只会让它去猜语义。
"""
from services.profile_loader import JobCategory, JobSeeking, Profile
from multisite.preferences import render_constraints


def _profile(**kw) -> Profile:
    base = dict(
        cities=["深圳"],
        degree=["本科", "硕士"],
        job_seeking=JobSeeking(
            recruit_types=["校招", "应届", "日常实习"],
            categories=[JobCategory("产品", 3), JobCategory("开发", 5)],
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

    def test_categories_carry_their_quota(self):
        """名额必须出现在 agent 看得见的约束里。

        只渲染类别名不渲染数量的话，agent 不知道"产品够了没"，就退回到上一版
        那个失败模式：按总数记满就停，某一类占光所有名额而没人看得出来。
        """
        text = render_constraints(_profile())
        assert "产品" in text and "开发" in text
        assert "3" in text and "5" in text

    def test_says_off_category_jobs_do_not_count(self):
        # 不属于任何类别的岗位必须明确排除，否则 agent 会把"顺带看到的好岗位"
        # 也记进来，而它根本没有名额可归。
        text = render_constraints(_profile())
        assert "不属于" in text

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


class TestRenderGoldenExamples:
    """人工纠正回灌 prompt。

    这是"写死规则治不了下一条"的兜底：类别之间天然重叠（AI NATIVE vs 开发 尤其），
    真机第一次跑 agent 就把职责写着 CV/多模态/LLM/Agent 的「数据算法工程师」归成了
    「开发」，还占掉开发最后一个名额把 AI NATIVE 饿死。人工纠正是唯一持续产出真实
    标注的地方。
    """

    class _FakeTracker:
        def __init__(self, rows):
            self._rows = rows

        def get_golden_category_examples(self, limit=20):
            return self._rows[:limit]

    @staticmethod
    def _row(title="数据算法工程师", category="AI NATIVE", category_agent="开发", why=""):
        from schemas import PendingJob
        return PendingJob(id=1, site_name="s", url="https://x/1", title=title,
                          category=category, category_agent=category_agent, why=why)

    def test_renders_both_the_wrong_and_the_right_category(self):
        from multisite.preferences import render_golden_examples
        text = render_golden_examples(self._FakeTracker([self._row()]))
        # 只说"应该归 AI NATIVE"教不会它——它得知道自己错在把这种岗位当成了开发。
        assert "开发" in text and "AI NATIVE" in text
        assert "数据算法工程师" in text

    def test_empty_set_is_not_an_empty_string(self):
        # 空字符串会在 prompt 里留下一个光秃秃的小标题，看起来像模板渲染坏了。
        from multisite.preferences import render_golden_examples
        text = render_golden_examples(self._FakeTracker([]))
        assert text.strip()

    def test_why_is_truncated(self):
        """例子要给判别线索，不是复述职责全文；20 条 × 全文能吃掉 DeepSeek 上下文
        的一大块，而上下文是这条链上最紧张的资源。"""
        from multisite.preferences import render_golden_examples
        text = render_golden_examples(self._FakeTracker([self._row(why="x" * 500)]))
        assert len(text) < 300

    def test_multiline_why_does_not_break_the_list(self):
        from multisite.preferences import render_golden_examples
        text = render_golden_examples(self._FakeTracker([self._row(why="a\nb\nc")]))
        assert "a b c" in text


class TestPerSiteCategorySkip:
    """本站不存在的类别必须能去掉。

    不只是省步数：选岗的**主终止条件是“所有名额已满”**，配一个本站
    没有的类别就等于那个条件永远不成立，agent 只能靠翻页预算耗尽来停。
    """

    @staticmethod
    def _js(**kw):
        from services.profile_loader import JobCategory, JobSeeking
        base = dict(categories=[JobCategory("产品", 3), JobCategory("游戏", 2)])
        base.update(kw)
        return JobSeeking(**base)

    def test_skipped_category_is_removed_for_that_site(self):
        js = self._js(site_skip={"bambulab": ["游戏"]})
        assert js.quotas_for_site("bambulab") == {"产品": 3}

    def test_other_sites_are_unaffected(self):
        js = self._js(site_skip={"bambulab": ["游戏"]})
        assert js.quotas_for_site("huawei") == {"产品": 3, "游戏": 2}

    def test_no_overrides_means_the_full_table(self):
        assert self._js().quotas_for_site("bambulab") == {"产品": 3, "游戏": 2}

    def test_unknown_category_name_in_skip_is_harmless(self):
        # profile 里写了个已经删掉的类别名，不该炸也不该影响别的。
        js = self._js(site_skip={"bambulab": ["不存在的类"]})
        assert js.quotas_for_site("bambulab") == {"产品": 3, "游戏": 2}
