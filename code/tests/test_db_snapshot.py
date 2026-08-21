"""`jobs.db` 的备份。它是唯一权威库（applications + hr_conversations +
hr_messages，几周真实投递与 HR 会话历史），而 `tracker` 此前**零备份、零恢复路径**。

不是假想风险：这个库历史上已经因 schema 漂移做过**三次**紧急重建
（`migrate_030` / `migrate_app_rebuild` / `migrate_hrconv_rebuild`）。
`info_pool.yaml` 在 v2.17.1 被判定「唯一主库却零备份」后加了快照+回滚，
同样的教训一直没推广到更关键的这个库。

**用 `VACUUM INTO` 而不是复制文件**：库是 WAL 模式且随时可能有写入，
`shutil.copy` 拷到的可能是一个缺了 -wal 内容的半截库——那种备份**看起来成功、
恢复时才发现少数据**，比没有备份更坏。`VACUUM INTO` 由 SQLite 保证一致性。
"""
import sqlite3

import pytest

from services.db_snapshot import list_db_snapshots, snapshot_db


def _db(path, rows=3):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"r{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


class TestItActuallyBacksUpTheData:
    def test_the_snapshot_is_a_readable_database_with_the_same_rows(self, tmp_path):
        """**断言的是能读出来的数据，不是"文件生成了"。**
        备份最常见的坏法就是文件在、内容不对。"""
        src = _db(tmp_path / "jobs.db", rows=5)
        dest = snapshot_db(str(src))

        conn = sqlite3.connect(dest)
        assert [r[0] for r in conn.execute("SELECT v FROM t ORDER BY id")] == \
               ["r0", "r1", "r2", "r3", "r4"]
        conn.close()

    def test_it_survives_being_taken_while_the_db_is_open_in_wal(self, tmp_path):
        """真实调用点就是「库已经打开着」的时候。WAL 下未 checkpoint 的写
        不在主文件里——直接复制文件会丢掉它们。"""
        src = tmp_path / "jobs.db"
        conn = sqlite3.connect(str(src))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('written-in-wal')")
        conn.commit()

        dest = snapshot_db(str(src))       # 连接仍开着

        got = sqlite3.connect(dest).execute("SELECT v FROM t").fetchall()
        assert got == [("written-in-wal",)]
        conn.close()


class TestWhenItSkips:
    def test_a_missing_database_is_skipped_not_an_error(self, tmp_path):
        """全新安装、以及绝大多数测试，都是「库还不存在」。"""
        assert snapshot_db(str(tmp_path / "nope.db")) == ""

    def test_at_most_one_per_day(self, tmp_path):
        """构造 tracker 的地方很多（每个 API 请求线程都可能），
        每次都存一份会把保留窗口冲掉。"""
        src = _db(tmp_path / "jobs.db")
        first = snapshot_db(str(src))
        second = snapshot_db(str(src))

        assert first and second == ""
        assert len(list_db_snapshots(str(src))) == 1

    def test_a_new_day_snapshots_again(self, tmp_path, monkeypatch):
        src = _db(tmp_path / "jobs.db")
        snapshot_db(str(src))

        import services.db_snapshot as mod
        monkeypatch.setattr(mod, "_stamp", lambda: "20991231_235959")
        assert snapshot_db(str(src)) != ""
        assert len(list_db_snapshots(str(src))) == 2


class TestRetention:
    def test_it_uses_the_shared_policy(self, tmp_path):
        """保留策略只有一份实现（`snapshot_retention`），信息池也用它。"""
        src = _db(tmp_path / "jobs.db")
        d = tmp_path / "db_snapshots"
        d.mkdir(exist_ok=True)
        # 今天以前的一堆快照：最近 10 个 + 每天最早的各一个该留下
        for day in range(1, 26):
            (d / f"202607{day:02d}_090000.db").write_bytes(b"x")
            (d / f"202607{day:02d}_100000.db").write_bytes(b"x")

        import services.db_snapshot as mod
        mod._prune(str(d))

        left = sorted(p.name for p in d.iterdir())
        assert "20260725_100000.db" in left          # 最近的
        assert "20260712_090000.db" in left          # 某天最早的（14 天窗口内）
        assert "20260701_100000.db" not in left      # 窗口外、且不是最近 10 个
