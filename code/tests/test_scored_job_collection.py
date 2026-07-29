"""W1 评分数据采集（阶段2 地基）：tracker 存取 + 滚动上限 + card_pipeline 两侧都采。

投递的和被跳过的岗位都要记进 scored_jobs，且带 jd_text / above_threshold，
这样未来能重新打分做评分质量 eval。
"""
from pipeline.w1.card_pipeline import CardInput, CardPipeline
from services.tracker import ApplicationTracker


# ── tracker 层 ────────────────────────────────────────────────────────────────
def test_record_and_get_roundtrip(tmp_path):
    t = ApplicationTracker(db_path=str(tmp_path / "jobs.db"))
    t.record_scored_job(
        job_id="j1", title="后端", company="A", jd_text="JD文本",
        score=80, dimensions={"skill_match": 90}, reason="fit",
        provider_used="ollama", threshold=72, above_threshold=True,
    )
    t.record_scored_job(
        job_id="j2", title="前端", company="B", jd_text="JD2",
        score=40, dimensions={}, threshold=72, above_threshold=False,
    )
    rows = t.get_scored_jobs()
    assert len(rows) == 2
    newest = rows[0]  # newest first
    assert newest["job_id"] == "j2"
    assert newest["above_threshold"] == 0
    j1 = next(r for r in rows if r["job_id"] == "j1")
    assert j1["jd_text"] == "JD文本"
    assert j1["dimensions"] == {"skill_match": 90}  # parsed back to dict
    assert j1["above_threshold"] == 1


def test_rolling_cap_trims_oldest(tmp_path):
    t = ApplicationTracker(db_path=str(tmp_path / "jobs.db"))
    for i in range(5):
        t.record_scored_job(
            job_id=f"j{i}", title="t", company="c", jd_text="x",
            score=i, threshold=0, above_threshold=True, cap=3,
        )
    rows = t.get_scored_jobs()
    assert len(rows) == 3  # only newest 3 kept
    assert {r["job_id"] for r in rows} == {"j2", "j3", "j4"}


# ── card_pipeline 两侧都采 ────────────────────────────────────────────────────
class _Res:
    def __init__(self, ok=True, data=None, error=None):
        self.ok, self.data, self.error = ok, data or {}, error


class _Reg:
    def __init__(self, score):
        self._score = score
        self.recorded = []  # 捕获 record_scored_job 的 kwargs

    def set_context(self, *a, **kw):
        pass

    def call(self, tool, **kw):
        if tool == "score_job":
            return _Res(data={"score": self._score, "reason": "r",
                              "dimensions": {"skill_match": self._score}, "provider_used": "ollama"})
        if tool == "read_panel_jd":
            return _Res(data={"jd_text": "the JD", "hr_name": "HR", "salary_raw": "20-30K"})
        if tool == "click_card_open_panel":
            return _Res(data={"panel_loaded": True, "matched_selector": ".x"})
        if tool == "decode_job_salary":
            return _Res(data={"decoded_salary": "20-30K"})
        if tool == "click_apply_button":
            return _Res(data={"result": "dry_run"})
        if tool == "record_scored_job":
            self.recorded.append(kw)
            return _Res(data={})
        return _Res(data={})


class _Logger:
    run_id = "w1_test"

    def log_step(self, *a, **kw):
        pass

    def log(self, *a, **kw):
        pass

    def emit_step_running(self, *a, **kw):
        pass


class _Config:
    def __init__(self):
        self.dry_run = True
        self.score_threshold = 60
        self.url = ""
        self.max_cards = None


def _card():
    return CardInput(job_id="j1", title="Eng", company="Co", salary_raw="20-30K",
                     city="SZ", hr_name="", card_dom_index=0)


def test_applied_side_recorded():
    reg = _Reg(score=90)  # >= threshold 60 -> applied
    CardPipeline(reg, {}, _Logger(), _Config()).run(_card())
    assert len(reg.recorded) == 1
    rec = reg.recorded[0]
    assert rec["above_threshold"] is True
    assert rec["jd_text"] == "the JD"
    assert rec["score"] == 90


def test_skipped_side_recorded():
    reg = _Reg(score=30)  # < threshold 60 -> skipped, but still recorded
    CardPipeline(reg, {}, _Logger(), _Config()).run(_card())
    assert len(reg.recorded) == 1
    rec = reg.recorded[0]
    assert rec["above_threshold"] is False
    assert rec["jd_text"] == "the JD"
    assert rec["score"] == 30
