"""每条填表记录要写明「这次实际传上去的是哪一份简历」。

**为什么**：2026-08-21 真机跑完 m2 之后想核对"刚才发的是哪份"，只能翻 run 日志——
`pending_applications` 里没有这个信息。现在库里只有一份可发的，还看不出问题；
勾了好几份之后，这条不落库就会变成哑谜，而它恰恰是**事后唯一能追责的那一条**
（简历库的内容会变、兜底会改、run 日志会滚动）。

存的是**库里的文件名**而不是显示名：显示名可以改，文件名是那次真正传出去的那个字节流的标识。
"""
import pytest

from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    t = ApplicationTracker(db_path=str(tmp_path / "t.db"))
    yield t
    t.close()


class TestResumeFileIsRecorded:
    def test_it_round_trips(self, tracker):
        app_id = tracker.add_pending_application(
            site_name="bambulab", job_title="服务运营", fields=[],
            resume_file="Agent开发_2026-08-17.pdf")
        got = tracker.get_pending_applications()[0]
        assert got.id == app_id
        assert got.resume_file == "Agent开发_2026-08-17.pdf"

    def test_it_defaults_to_empty_not_null(self, tracker):
        """老记录和"没传简历"的路径都是空串——空串是"没有这个信息"，
        不是"有个叫 None 的简历"。前端据此决定显示不显示。"""
        tracker.add_pending_application(site_name="s", job_title="t", fields=[])
        assert tracker.get_pending_applications()[0].resume_file == ""

    def test_a_legacy_row_without_the_column_still_loads(self, tmp_path):
        """迁移不能让老库打不开——这张表里躺着真实投递过的记录。"""
        import sqlite3

        db = str(tmp_path / "legacy.db")
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE pending_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, site_name TEXT NOT NULL,
            job_title TEXT NOT NULL, company TEXT DEFAULT '', job_url TEXT DEFAULT '',
            fields TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT, created_at TEXT NOT NULL, decided_at TEXT)""")
        con.execute("INSERT INTO pending_applications (site_name, job_title, fields,"
                    " status, created_at) VALUES ('s','老记录','[]','pending','2026-01-01')")
        con.commit()
        con.close()

        t = ApplicationTracker(db_path=db)
        try:
            rows = t.get_pending_applications()
            assert len(rows) == 1
            assert rows[0].job_title == "老记录"
            assert rows[0].resume_file == ""
        finally:
            t.close()


class TestM2RecordsWhatItActuallyUploaded:
    """m2 落库时写的必须是**真正传上去的那个文件**，不是在这里另算一遍。

    `state["resume_pdf_path"]` 就是交给 `upload_file` 的那个暂存路径，
    它的 basename 正是库里的文件名（`staged_resume` 保留原名）。
    **从那个值取**——重新去库里 pick 一次就是同一件事两份实现，
    而两次之间兜底/勾选都可能已经变了。
    """

    def test_it_records_the_basename_of_the_uploaded_path(self, tracker):
        from multisite.layer1_agent import record_application

        out = record_application(
            tracker,
            {"site_name": "bambulab", "job_title": "服务运营", "job_url": "https://x/1",
             "empty_elements": [{"label": "姓名", "required": True}],
             "classified_fields": [],
             "resume_pdf_path": r"C:\Temp\ojf_resume_ab12\Agent开发_2026-08-17.pdf"},
            {},
        )
        got = tracker.get_pending_application(out["pending_application_id"])
        assert got.resume_file == "Agent开发_2026-08-17.pdf"

    def test_no_resume_path_records_an_empty_string(self, tracker):
        """m1 那条路径不传简历——空串是诚实的空。"""
        from multisite.layer1_agent import record_application

        out = record_application(
            tracker,
            {"site_name": "s", "job_title": "t", "job_url": "u",
             "empty_elements": [{"label": "姓名", "required": True}],
             "classified_fields": [], "resume_pdf_path": ""},
            {},
        )
        assert tracker.get_pending_application(out["pending_application_id"]).resume_file == ""
