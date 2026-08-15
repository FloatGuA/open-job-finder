"""把多站点（m1/m2）的数据清回白纸，用来完整验证一遍。

**只碰多站点自己的四张表**：`pending_jobs` / `pending_applications` /
`site_limits` / `site_briefs`。Boss 那条线的 `applications` / `hr_conversations`
/ `hr_messages` 一行不动——那是几百条不可逆的真实投递记录，删错的代价跟"清一下
测试数据"完全不是一个量级，所以这条边界有测试守着
（`tests/test_reset_multisite.py::TestWhatItMustNotTouch`）。

**登录态目录 `data/browser_profile_multisite/<site>/` 也不动**：清它等于要重新
人工登录一遍每个站，跟"重新验证一遍流程"是两回事。

先备份再删，备份是能读的 JSON（人能从里面把行捞回来）。

用法（在 code/ 目录下）：

    python scripts/reset_multisite.py            # 列出要删什么，不删
    python scripts/reset_multisite.py --yes      # 真删

⚠️ **清库不撤销已经发生的事**：`pending_applications` 里的记录意味着简历已经传到
过那个企业申请表（未提交），删掉数据库行不会让那件事消失，重跑会再传一次。
"""
import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# 这四张、且只有这四张。加表时**必须**同时加进备份，否则备份看着成功、实际缺一块。
MULTISITE_TABLES = ("pending_jobs", "pending_applications", "site_limits", "site_briefs")


def _rows(tracker, table: str) -> list:
    """整表读出来存备份。用 SELECT * 而不是各表的 getter：getter 返回的是 dataclass，
    加了列而 dataclass 没跟上时备份会**静默少存一列**，而备份的全部意义就是完整。"""
    cur = tracker.conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def reset_multisite(tracker, backup_dir: Path) -> Path:
    """备份四张表 → 清空它们。返回备份文件路径。"""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    payload = {t: _rows(tracker, t) for t in MULTISITE_TABLES}
    payload["counts"] = {t: len(payload[t]) for t in MULTISITE_TABLES}
    payload["taken_at"] = datetime.now(timezone.utc).isoformat()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"multisite_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")

    # 备份落盘之后才删。顺序反了的话，删成功而备份失败时数据就真没了。
    with tracker.conn:
        for table in MULTISITE_TABLES:
            tracker.conn.execute(f"DELETE FROM {table}")
    return path


def _describe(tracker) -> dict:
    return {t: len(_rows(tracker, t)) for t in MULTISITE_TABLES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="真的删（不加只列出要删什么）")
    args = parser.parse_args()

    from services.tracker import ApplicationTracker

    tracker = ApplicationTracker()
    counts = _describe(tracker)
    print("多站点数据现状：")
    for table, n in counts.items():
        print(f"  {table:24s} {n}")
    print(f"  {'(applications 等 Boss 表)':24s} 不动")

    if not any(counts.values()):
        print("已经是空的，不用清。")
        return 0
    if not args.yes:
        print("\n加 --yes 才会真的删。删之前会自动备份到 data/backups/。")
        return 0

    path = reset_multisite(tracker, CODE_DIR / "data" / "backups")
    print(f"\n已备份到 {path}")
    print("已清空：", ", ".join(MULTISITE_TABLES))
    print("剩余：", _describe(tracker))
    return 0


if __name__ == "__main__":
    sys.exit(main())
