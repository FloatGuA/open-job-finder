"""fixture 里不许出现真实个人信息。

2026-08-03 的事故：把真机验证里的真实学校信息手抄进测试和文档，推送前才扫出 10 处，
只能 filter-branch 重写 12 个提交。`data/` 的位置隔离对**必须进 git 的文件**结构上无效，
而 `precommit_pii_scan.py` 只认 jobs.db 的第三方公司/HR，不认用户自己的昵称/学校。

所以这条守门写在测试里。**新增任何 fixture 都要过这一关。**
"""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# 真机快照里出现过的、属于用户本人的东西。占位符必须是虚构的。
_FORBIDDEN = ("浮瓜",)


class TestFixturesCarryNoRealIdentity:
    def test_joinqq_fixture_exists(self):
        assert (FIXTURES / "joinqq_post_list.txt").is_file()

    def test_joinqq_fixture_is_a_real_sized_snapshot(self):
        """fixture 被误换成一份小快照时，失败信息应该是「fixture 被换小了」这句直白的话，
        而不是下游一堆"切不出行"/"取不到 URL"的间接症状——2026-08-19 的教训就是旧裁剪
        测试拿 10 字符的 `"SNAPSHOT-1"` 当快照，真实快照 6613 字符，量级差本身就是判据。"""
        text = (FIXTURES / "joinqq_post_list.txt").read_text(encoding="utf-8")
        assert len(text) >= 5000, \
            f"fixture 只有 {len(text)} 字符，看起来被换成了不真实的小快照"

    def test_no_real_nickname_in_any_fixture(self):
        for path in FIXTURES.glob("*.txt"):
            text = path.read_text(encoding="utf-8")
            for bad in _FORBIDDEN:
                assert bad not in text, f"{path.name} 里有真实个人信息：{bad}"

    def test_the_greeting_node_is_a_placeholder(self):
        """登录问候那一行要保留（它是「已登录」的证据，有测试价值），但名字换成虚构的。"""
        text = (FIXTURES / "joinqq_post_list.txt").read_text(encoding="utf-8")
        assert '你好，张三' in text
