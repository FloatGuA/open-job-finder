"""`jobs.db` 的只读备份：每天一份，`VACUUM INTO` 落到 `data/db_snapshots/`。

这个库是唯一权威库（applications + hr_conversations + hr_messages，几周真实
投递与 HR 会话历史），此前**零备份、零恢复路径**。不是假想风险：它历史上已经
因 schema 漂移做过三次紧急重建（`migrate_030` / `migrate_app_rebuild` /
`migrate_hrconv_rebuild`）。`info_pool.yaml` 在 v2.17.1 被判定「唯一主库却零
备份」后加了快照+回滚，同样的教训一直没推广到更关键的这个库。

**为什么是 `VACUUM INTO` 而不是 `shutil.copy`**：库跑在 WAL 模式，且备份发生在
库已经打开着的时候——直接复制主文件会漏掉尚未 checkpoint 的写。那种备份
**看起来成功、恢复时才发现少数据**，比没有备份更坏。一致性交给 SQLite。

**为什么不做「写前快照」**（信息池是那么做的）：那边一天写几次，这边一次 W2 跑
几百次写。频率完全不同类，写前快照在这里是荒谬的。改成**每天第一次打开库时**
存一份——顺带覆盖了最想防的那个场景：`_create_tables()` 里的 ALTER TABLE 迁移
就在这之后跑。

**恢复是人工的，故意的**：停掉后端，把 `db_snapshots/` 里的文件复制成
`data/jobs.db`。不做一键回滚端点——服务还开着的时候换掉库文件，
持有连接的线程会拿到一个半死不活的句柄，而"点一下就能恢复"会让人在最慌的时候
去点它。
"""
import os
import sqlite3
import time

from services import snapshot_retention as retention

SNAPSHOT_KEEP_RECENT = 10   # 无论哪天，最近 N 个一律保留
SNAPSHOT_KEEP_DAYS = 14     # 再额外保留最近 N 天里「每天最早的那一个」


def _stamp() -> str:
    """快照文件名的时间戳。**当天判断和文件名共用这一个时钟**——
    分成两次调用的话，"今天存过没有"和"这份叫什么名字"会来自两个时间点，
    测试里一 patch 就露馅（真机上表现为跨日那一刻多存/少存一份）。"""
    return time.strftime("%Y%m%d_%H%M%S")


def snapshot_dir(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path) or ".", "db_snapshots")


def list_db_snapshots(db_path: str) -> list:
    """快照文件名列表（新 → 旧）。"""
    d = snapshot_dir(db_path)
    if not os.path.isdir(d):
        return []
    return sorted([f for f in os.listdir(d) if f.endswith(".db")], reverse=True)


def _prune(d: str) -> None:
    files = sorted([f for f in os.listdir(d) if f.endswith(".db")], reverse=True)
    keep = retention.keepers(files, SNAPSHOT_KEEP_RECENT, SNAPSHOT_KEEP_DAYS)
    for name in files:
        if name in keep:
            continue
        try:
            os.remove(os.path.join(d, name))
        except OSError:
            pass


def snapshot_db(db_path: str) -> str:
    """当天还没存过就存一份，返回快照路径；跳过时返回空串。

    **每天至多一份**：构造 tracker 的地方很多（每个 API 请求线程都可能新建
    连接），每次都存会把保留窗口冲掉。
    """
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return ""      # 全新安装 / 绝大多数测试：库还不存在，没什么可备份的

    stamp = _stamp()
    if any(name.startswith(stamp[:8]) for name in list_db_snapshots(db_path)):
        return ""

    d = snapshot_dir(db_path)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{stamp}.db")
    if os.path.exists(dest):
        return ""

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        # 参数化不能用于 VACUUM INTO 的目标，只能拼串——所以路径是我们自己拼的
        # （快照目录 + 时间戳），从不来自外部输入。
        conn.execute("VACUUM INTO ?", (dest,))
    finally:
        conn.close()
    _prune(d)
    return dest
