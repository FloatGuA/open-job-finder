"""快照保留策略：**最近 N 个 + 最近 N 天里每天最早的各一个**。

单纯「保留最近 N 个」有个要命的缺陷（v2.17.1 定这个策略时的原话）：
**一天内连点十几次保存，会把几天前那个完好版本挤掉，而那恰恰是最需要回滚的。**

这里只有策略，不碰文件系统——两个调用方（信息池 YAML、jobs.db）各自负责扩展名、
目录和删除动作。**抽出来是为了不存在第二份实现**：保留策略抄错了不会报错，
只会在你真的需要回滚的那天才发现文件已经没了。
"""

# 文件名形如 YYYYMMDD_HHMMSS[_n].<ext>，按字符串倒序排就是「新 → 旧」。
_DAY_LEN = 8


def daily_keepers(files: list, keep_days: int) -> set:
    """最近 keep_days 天里，每天**最早**的那个快照。

    留最早的而不是最晚的：那是这一天开始时的状态，也就是当天改坏之前的样子。
    """
    by_day: dict = {}
    for name in files:                    # files 是倒序，越往后越早
        by_day[name[:_DAY_LEN]] = name    # 同日反复覆盖 → 最终留下当天最早的
    return {by_day[d] for d in sorted(by_day, reverse=True)[:keep_days]}


def keepers(files: list, keep_recent: int, keep_days: int) -> set:
    """该保留哪些快照。`files` 需按文件名倒序（新 → 旧）。"""
    if not files:
        return set()
    return set(files[:keep_recent]) | daily_keepers(files, keep_days)
