"""快照保留策略——**一份实现，两个调用方**（信息池 YAML、jobs.db）。

策略本身是 v2.17.1 定的，理由记在 DECISION：单纯「保留最近 N 个」有个要命的
缺陷——**一天内连点十几次保存，会把几天前那个完好版本挤掉，而那恰恰是最需要
回滚的那个**。所以是「最近 N 个 + 最近 N 天里每天最早的各一个」。

抽出来是因为 jobs.db 也要用它。**再抄一份就是同一契约两份实现**，而这个项目
已经栽过五次；抄错的表现还特别隐蔽：保留策略错了不会报错，只会在你真的需要
回滚的那天发现文件已经没了。
"""
from services.snapshot_retention import keepers


def _names(days_and_times):
    """构造快照文件名（YYYYMMDD_HHMMSS），返回倒序（新→旧），跟真实目录一致。"""
    return sorted([f"2026{d:02d}{t}" for d, t in days_and_times], reverse=True)


class TestKeepRecent:
    def test_the_newest_n_always_survive(self):
        files = _names([(1, f"{h:02d}0000") for h in range(20)])
        kept = keepers(files, keep_recent=10, keep_days=14)
        assert set(files[:10]) <= kept

    def test_fewer_files_than_the_limit_all_survive(self):
        files = _names([(1, "010000"), (1, "020000")])
        assert keepers(files, keep_recent=10, keep_days=14) == set(files)


class TestDailyKeepers:
    def test_the_earliest_of_each_day_survives_a_busy_day(self):
        """**这条是这个策略存在的全部理由。** 今天狂存 15 次，
        三天前那个存档必须还在。"""
        old = "20260801_090000"
        today = [f"20260804_{h:02d}0000" for h in range(9, 24)]
        files = sorted(today + [old], reverse=True)

        kept = keepers(files, keep_recent=10, keep_days=14)
        assert old in kept, "三天前的存档被今天的连续保存挤掉了"

    def test_earliest_not_latest_is_the_one_kept(self):
        """留当天**最早**的：那是这一天开始时的状态，改坏之前的样子。"""
        files = sorted(["20260804_090000", "20260804_100000", "20260804_230000",
                        "20260801_090000"], reverse=True)
        kept = keepers(files, keep_recent=1, keep_days=14)
        assert "20260804_090000" in kept
        assert "20260804_100000" not in kept

    def test_days_beyond_the_window_are_dropped(self):
        files = sorted([f"202608{d:02d}_090000" for d in range(1, 21)], reverse=True)
        kept = keepers(files, keep_recent=1, keep_days=3)
        # 最近 3 天的每日守护 + 最近 1 个（本身就在里面）
        assert kept == {"20260820_090000", "20260819_090000", "20260818_090000"}


class TestEmptyInput:
    def test_no_files_no_keepers(self):
        assert keepers([], keep_recent=10, keep_days=14) == set()
