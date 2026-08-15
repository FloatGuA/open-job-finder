"""重置多站点数据（开发期反复要做：清干净再完整验证一遍）。

**这组测试守的是"别删错东西"**。这个脚本删的是真实数据库里的行，写错一个表名的
代价是 Boss 那条线几百条投递记录没了——而那是不可逆的。所以：删什么、不删什么、
删之前有没有留下能恢复的东西，三件都得钉住。
"""
import json

import pytest

from schemas import ApplicationRecord
from scripts.reset_multisite import reset_multisite
from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    t = ApplicationTracker(db_path=str(tmp_path / "jobs.db"))
    # 多站点这边的数据
    job_id = t.add_pending_job(site_name="s", url="https://x/1", title="t")
    t.decide_pending_job(job_id, "approved")
    t.add_pending_application(site_name="s", job_title="t", fields=[], source_job_id=job_id)
    t.upsert_site_limit("s", "limited", max_applications=2, evidence="原文")
    t.upsert_site_brief("s", "这个站按研发/非研发分两个招聘项目。")
    # Boss 那条线的数据——**绝对不能被碰**
    t.upsert(ApplicationRecord(job_id="boss-1", title="岗位", company="公司",
                               url="https://zhipin/1", status="APPLIED"))
    return t


class TestWhatItDeletes:
    def test_clears_all_four_multisite_tables(self, tracker, tmp_path):
        reset_multisite(tracker, backup_dir=tmp_path / "bk")
        assert tracker.get_pending_jobs() == []
        assert tracker.get_pending_applications() == []
        assert tracker.get_site_limits("s") == []
        assert tracker.get_site_brief("s") is None


class TestWhatItMustNotTouch:
    def test_boss_applications_survive(self, tracker, tmp_path):
        """W1/W2 攒了几百条投递与会话记录，跟多站点毫无关系。删错表不可逆。"""
        reset_multisite(tracker, backup_dir=tmp_path / "bk")
        assert [a.job_id for a in tracker.get_all()] == ["boss-1"]


class TestBackupBeforeDeleting:
    def test_writes_a_restorable_backup(self, tracker, tmp_path):
        """**先备份再删**，且备份要能看懂——出问题时人得能从里面把行捞回来。"""
        bk = tmp_path / "bk"
        path = reset_multisite(tracker, backup_dir=bk)

        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["pending_jobs"]) == 1
        assert len(data["pending_applications"]) == 1
        assert len(data["site_limits"]) == 1
        assert len(data["site_briefs"]) == 1
        assert data["pending_jobs"][0]["url"] == "https://x/1"

    def test_creates_the_backup_dir_if_missing(self, tracker, tmp_path):
        bk = tmp_path / "nested" / "deep" / "bk"
        reset_multisite(tracker, backup_dir=bk)
        assert list(bk.glob("*.json"))

    def test_unusable_backup_dir_stops_it_before_anything_is_deleted(self, tracker, tmp_path):
        """路径被一个文件占住 = 连备份目录都建不出来，此时一行都不该删。"""
        blocked = tmp_path / "not-a-dir"
        blocked.write_text("x", encoding="utf-8")

        with pytest.raises(OSError):
            reset_multisite(tracker, backup_dir=blocked)

        assert len(tracker.get_pending_jobs()) == 1

    def test_nothing_is_deleted_when_writing_the_backup_fails(self, tracker, tmp_path,
                                                              monkeypatch):
        """**这条才真正钉住"先备份再删"的顺序**：目录建得出来、数据也读出来了，
        但写盘失败（磁盘满 / 只读挂载）——数据必须原封不动。

        上面那条 `unusable_backup_dir` 钉不住顺序：它在 mkdir 就炸了，删除挪到
        备份之前也照样过（做变异验证时实测如此）。所以这里只能把写盘打成故障点，
        这是少数 mock 不可避免的地方——没有别的干净办法造出"磁盘写失败"。
        """
        from pathlib import Path

        def boom(self, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)

        with pytest.raises(OSError):
            reset_multisite(tracker, backup_dir=tmp_path / "bk")

        assert len(tracker.get_pending_jobs()) == 1
        assert len(tracker.get_pending_applications()) == 1
        assert len(tracker.get_site_limits("s")) == 1

    def test_counts_are_reported_back(self, tracker, tmp_path):
        """调用方（和人）要能核对"删掉的正好是刚才看到的那些"。"""
        path = reset_multisite(tracker, backup_dir=tmp_path / "bk")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["counts"] == {"pending_jobs": 1, "pending_applications": 1,
                                  "site_limits": 1, "site_briefs": 1}
