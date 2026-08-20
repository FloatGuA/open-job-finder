"""把平铺的快照切成一行一个岗位。

**为什么按锚点切而不是找标题**：join.qq.com 的岗位卡片在 a11y 快照里没有容器节点，
整页是一串平铺的 StaticText。而列表区开头还夹着推广文案（「不确定适合哪个岗位？…」
三条），按"第一个文本节点即标题"会直接抓错。

锚点＝每个岗位行里必现且仅现一次的文本（本站是「工作地点：」）。真机验证过：
**click 锚点节点会打开它所在那一行的岗位**（事件冒泡到卡片 onClick），
所以切行不需要精确定位标题——标题交给本来就要读这一段的分类 LLM。
"""
from pathlib import Path

from multisite.executors import job_url_offline, split_rows
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "row_split": "anchor_text",
         "row_anchor": "工作地点：", "total_count_locator": r"共(\d+)个岗位"}
    d.update(over)
    return SiteManual.from_dict({**d, "url_template": "", "filters_survive_reload": False,
                                 "dimensions": [], "important_notes": ""})


class TestSplitRowsByAnchor:
    def test_finds_every_job_row(self):
        # 真机这一页恰好 10 个岗位，锚点也恰好 10 个。
        assert len(split_rows(SNAPSHOT, _manual())) == 10

    def test_each_row_carries_the_anchor_uid_to_click(self):
        rows = split_rows(SNAPSHOT, _manual())
        # 真机实测：锚点等距分布，周期 9。
        assert [r.anchor_uid for r in rows][:4] == ["1_78", "1_87", "1_96", "1_105"]

    def test_row_text_contains_the_job_title(self):
        """行文本要覆盖到标题——分类 LLM 要从这段里读出岗位叫什么。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert "Agent开发工程师" in rows[1].text

    def test_promo_text_is_not_a_row(self):
        """列表区开头的推广文案不是岗位。按锚点切天然排除它——但要断言，
        因为"多切出一行垃圾"会一路流到分类和落库。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert not any("知识库" in r.text for r in rows)

    def test_an_anchor_that_matches_nothing_yields_no_rows(self):
        """锚点选错了要表现为"切出 0 行"，而不是切出一堆错的。
        0 行会被上层当成"这一页没岗位"——所以调用方必须自己区分，见 Task 8 的轻校验。"""
        assert split_rows(SNAPSHOT, _manual(row_anchor="这个文本不存在")) == []


class TestExactlyOneAnchor:
    """`span`（相邻锚点间距）需要至少 2 个锚点才能求出来；0 个锚点在
    `_anchor_row_windows` 里提前 return 掉了，所以"恰好 1 个"是唯一会触发
    `_SINGLE_ANCHOR_SPAN_FALLBACK` 回退值的情况——之前只覆盖了 0 个和 10 个
    两端，这里补上中间这一档。"""

    SINGLE_ANCHOR_SNAPSHOT = (
        '## Latest page snapshot\n'
        'uid=1_0 RootWebArea "岗位列表"\n'
        'uid=1_1 StaticText "推广文案A"\n'
        'uid=1_2 StaticText "推广文案B"\n'
        'uid=1_3 StaticText "唯一岗位标题"\n'
        'uid=1_4 StaticText "工作地点："\n'
        'uid=1_5 StaticText "深圳"\n'
        'uid=1_6 StaticText "全职"\n'
    )

    def test_yields_exactly_one_row(self):
        manual = _manual(row_anchor="工作地点：")
        rows = split_rows(self.SINGLE_ANCHOR_SNAPSHOT, manual)
        assert len(rows) == 1

    def test_the_row_covers_the_title_and_the_node_right_after_the_anchor(self):
        """回退窗口用 `_SINGLE_ANCHOR_SPAN_FALLBACK` 往前回切、`+2` 往后扩——
        标题在锚点前几个节点，`+2` 之后的「深圳」也该在窗口内。"""
        manual = _manual(row_anchor="工作地点：")
        rows = split_rows(self.SINGLE_ANCHOR_SNAPSHOT, manual)
        assert "唯一岗位标题" in rows[0].text
        assert "深圳" in rows[0].text


BAMBULAB_SNAPSHOT = (Path(__file__).parent / "fixtures" / "bambulab_job_list.txt").read_text(encoding="utf-8")

# bambulab 真机快照里的 15 个 link uid：10 个岗位 + 5 个导航（"职位"/"产品官网"/
# "招聘官网首页"/"社会招聘"/"校招FAQ"）。导航链接的 url 不含 "/position/"。
BAMBULAB_NAV_UIDS = {"6_1", "6_3", "6_5", "6_7", "6_9"}
BAMBULAB_JOB_UIDS = {"6_53", "6_60", "6_67", "6_73", "6_80", "6_87", "6_94", "6_101", "6_108", "6_115"}


def _container_manual(**over) -> SiteManual:
    d = {"job_url_source": "link_in_row", "pagination": "next_button",
         "filter_interaction": "direct_click", "row_split": "container_per_row",
         "row_anchor": "/position/", "total_count_locator": ""}
    d.update(over)
    return SiteManual.from_dict({**d, "url_template": "", "filters_survive_reload": False,
                                 "dimensions": [], "important_notes": ""})


class TestContainerPerRow:
    """bambulab：每个岗位就是一个 `link` 节点，没有 join.qq.com 那种"必现且仅现一次
    的锚点文本"可用——但 url 里带 `/position/` 的 link 才是岗位，导航链接（"职位"/
    "产品官网"…）的 url 不带。`row_anchor` 在这个模式下复用为"容器节点 url 必须包含
    的片段"，见 site_manual.py 的字段注释。"""

    def test_finds_every_job_row(self):
        # 真机这一页 15 个 link，其中 10 个是岗位，5 个是导航。
        assert len(split_rows(BAMBULAB_SNAPSHOT, _container_manual())) == 10

    def test_nav_links_are_excluded(self):
        rows = split_rows(BAMBULAB_SNAPSHOT, _container_manual())
        uids = {r.anchor_uid for r in rows}
        assert uids == BAMBULAB_JOB_UIDS
        assert uids.isdisjoint(BAMBULAB_NAV_UIDS)

    def test_row_text_contains_the_job_title(self):
        rows = split_rows(BAMBULAB_SNAPSHOT, _container_manual())
        by_uid = {r.anchor_uid: r for r in rows}
        assert "AI Agent算法工程师" in by_uid["6_53"].text
        assert "海外市场公关" in by_uid["6_60"].text

    def test_each_row_has_its_own_distinct_url(self):
        """容器模式下行本身就是那个 link——`job_url_offline` 的 `link_in_row` 分支
        必须直接按 `row.anchor_uid` 取这一行自己的 url，不是复用 anchor_text 的窗口
        搜索（那套窗口算法是给"锚点在行内、行是好几个节点"的场景设计的，这里行
        本身只有一个节点）。"""
        manual = _container_manual()
        rows = split_rows(BAMBULAB_SNAPSHOT, manual)
        urls = {row.anchor_uid: job_url_offline(row, BAMBULAB_SNAPSHOT, manual) for row in rows}
        assert all(u is not None and u.startswith("http") for u in urls.values())
        assert len(set(urls.values())) == 10, "10 行应该拿到 10 个不同的 url，不是重复同一个"
        assert urls["6_53"].endswith("/7675998559749048626/detail")
        assert urls["6_60"].endswith("/7674908422903941412/detail")
