"""
真机会话对账：扫描 Boss 当前会话列表，与 DB 做 conv_id 差集，
彻底证伪/证实「有会话在 Boss 但不在数据库里」。

存在理由：排查「有些会话没出现在控制台」时，DB(924) 已多于上次扫描(909)，
超集证据强烈提示没有系统性漏库，但要 100% 证伪只能真机扫一次当前列表对账。

做什么：复用 W2 的 ScanStep（同一套 getGeekFriendList 分页 + 滚动到底逻辑）
抓取当前 Boss 会话列表全量 conv_id，然后与 hr_conversations 差集：
  - in_boss_not_db：在 Boss 但不在 DB（真正的漏库，理论上应为空/极少）
  - in_db_not_boss：在 DB 但已不在 Boss 列表（历史/归档，预期较多，无害）
另报告：当前列表里命中 DB 却 intent 为空的「卡死」会话数（供 filter 修复参考）。
只读会话列表，不导航进会话、不发任何消息。

！！必须先停掉 Dashboard 再跑 ！！open_browser 会 _kill_stale_chrome
杀掉占用同一 browser_profile 的 Chrome——Dashboard 在跑时会连它的浏览器一起杀。
脚本默认检测 8765 端口，占用则拒绝执行（--force 可强制）。

用法（在 code/ 目录下，先停 Dashboard）：
  python scripts/reconcile_conversations.py [--headless] [--force]
"""
import argparse
import socket
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from pipeline.common.verify_session import VerifySessionStep
from pipeline.base import StepStatus
from pipeline.w2.scan_step import ScanStep
from services.browser_context import open_browser, close_browser
from services.tracker import ApplicationTracker
from tools.browser.w2 import register_w2_browser_tools
from tools.registry import ToolRegistry


def _dashboard_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", 8765)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="真机扫描 Boss 会话列表与 DB 对账")
    ap.add_argument("--headless", action="store_true", help="无头模式（默认有头，便于观察）")
    ap.add_argument("--force", action="store_true", help="即使 Dashboard 在跑也强制执行（危险：会杀其浏览器）")
    args = ap.parse_args()

    if _dashboard_running() and not args.force:
        print("[abort] 检测到 Dashboard 在 8765 运行。open_browser 会杀掉它的浏览器。")
        print("        请先停掉 Dashboard 再跑，或 --force 强制（不推荐）。")
        return 2

    data_dir = CODE_DIR / "data"
    tracker = ApplicationTracker()
    db_ids = {c.conv_id: c for c in tracker.get_hr_conversations()}
    print(f"[db] hr_conversations 总量: {len(db_ids)}")

    page = open_browser(data_dir, headless=args.headless)
    try:
        session = VerifySessionStep(page).run()
        if session.status != StepStatus.SUCCESSFUL:
            print(f"[abort] 未登录/会话校验失败: {session.reason} (error={session.error})")
            return 1
        print(f"[verify] 已登录: {session.username!r}")

        registry = ToolRegistry(browser=page, db=tracker)
        register_w2_browser_tools(registry, page)

        # 复用 ScanStep 的分页扫描（同一套 getGeekFriendList 逻辑），重试 3 次取非空
        scan = ScanStep(registry)
        all_convs: dict = {}
        for attempt in range(1, 4):
            all_convs, _url, err, stop_reason = scan._scan_once(logger=None, force_reload=(attempt > 1))
            print(f"[scan] 第{attempt}次: {len(all_convs)} 条  stop={stop_reason}  err={err}")
            if all_convs:
                break

        live_ids = set(all_convs)
        print(f"\n[scan] 当前 Boss 列表会话: {len(live_ids)} 条")

        in_boss_not_db = live_ids - set(db_ids)
        in_db_not_boss = set(db_ids) - live_ids
        print(f"\n=== 对账结果 ===")
        print(f"  在 Boss 但不在 DB（真漏库，应≈0）: {len(in_boss_not_db)}")
        print(f"  在 DB 但不在 Boss 列表（历史/归档，预期多）: {len(in_db_not_boss)}")

        if in_boss_not_db:
            print(f"\n  ** 漏库会话样例（最多 20）:")
            for cid in list(in_boss_not_db)[:20]:
                it = all_convs[cid]
                print(f"    {cid}  {it.get('company','')[:16]:<16} {it.get('hr_name','')[:8]:<8} "
                      f"unread={it.get('has_unread')} ts={it.get('last_msg_ts',0)}")

        # 当前列表里命中 DB 却 intent 为空的「卡死」会话（filter 修复参考）
        stuck = [cid for cid in (live_ids & set(db_ids)) if not (db_ids[cid].intent or '').strip()]
        print(f"\n  当前列表中命中 DB 但 intent 为空（卡死待重分析）: {len(stuck)}")

        return 0
    finally:
        close_browser(page)


if __name__ == "__main__":
    sys.exit(main())
