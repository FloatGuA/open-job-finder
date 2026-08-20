"""Checkpoint 1 的持久化（pending_jobs）测试。

守的核心是**两列类别**：`category_agent` 记 agent 最初报的，`category` 是当前值。
只留一列的话，人一改，"agent 原本报的是什么"当场蒸发——而两列不等的行正好是一批
带标注的纠错样本（用户 2026-08-14 提出要留作训练数据）。这条不变量没有别的地方
守得住：它不影响任何功能，坏掉了不会有任何东西报错。
"""
import pytest

from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


def _add(tracker, url="https://x/1", category="产品", **kw):
    return tracker.add_pending_job(site_name="bambulab", url=url, category=category, **kw)


class TestAddPendingJob:
    def test_agent_category_is_seeded_from_the_same_value(self, tracker):
        job_id = _add(tracker, category="产品")
        job = tracker.get_pending_job(job_id)
        assert job.category == "产品"
        assert job.category_agent == "产品"

    def test_duplicate_url_returns_none_instead_of_raising(self, tracker):
        """重复不是错误：选岗 agent 跨 run 没有记忆，再跑一次同一个站必然重新
        找到还在待审批的岗位。抛异常会让整次 run 白跑。"""
        first = _add(tracker, url="https://x/1")
        second = _add(tracker, url="https://x/1")
        assert first is not None
        assert second is None
        assert len(tracker.get_pending_jobs()) == 1

    def test_stores_the_fields_the_reviewer_needs(self, tracker):
        job_id = _add(tracker, url="https://x/9", title="产品经理", company="甲公司",
                      category="产品", why="深圳 + 27届秋招 + 产品方向")
        job = tracker.get_pending_job(job_id)
        assert (job.title, job.company, job.why) == (
            "产品经理", "甲公司", "深圳 + 27届秋招 + 产品方向")
        assert job.status == "pending"
        assert job.found_at


class TestDecidePendingJob:
    def test_approve_without_category_keeps_both_columns(self, tracker):
        job_id = _add(tracker, category="产品")
        assert tracker.decide_pending_job(job_id, "approved") == 1
        job = tracker.get_pending_job(job_id)
        assert job.status == "approved"
        assert job.category == "产品" and job.category_agent == "产品"

    def test_decide_does_not_write_category(self, tracker):
        """`category` 只有 set_pending_job_review 一个写入口。

        decide_pending_job 曾经也收 category 参数——同一列两个写入口，正是这个项目
        连抓四例漂移的形状，趁还没长歪拆掉了。这条守着它别被加回来。
        """
        import inspect
        sig = inspect.signature(tracker.decide_pending_job)
        assert "category" not in sig.parameters


class TestUndoPendingJobDecision:
    """撤销审批——2026-08-20 真机事故：用户误批了两个岗位，approved 之后
    `decide_pending_job` 的 `WHERE status='pending'` 让它改不动，只能由维护者
    直接跑 SQL 改库。这里补上唯一的正规撤销入口。"""

    def test_undo_approved_goes_back_to_pending(self, tracker):
        job_id = _add(tracker)
        tracker.decide_pending_job(job_id, "approved")

        assert tracker.undo_pending_job_decision(job_id) == 1

        job = tracker.get_pending_job(job_id)
        assert job.status == "pending"

    def test_undo_clears_reason_and_decided_at(self, tracker):
        """留着旧值会自相矛盾：一行显示"已因 Y 被拒绝"但状态是待审。本项目在
        状态机"回到中性状态时残留旧值"上已经栽过好几次。"""
        job_id = _add(tracker)
        tracker.decide_pending_job(job_id, "rejected", reason="其实是客服岗")

        assert tracker.undo_pending_job_decision(job_id) == 1

        job = tracker.get_pending_job(job_id)
        assert job.status == "pending"
        assert job.reason is None
        assert job.decided_at is None

    def test_undo_rejected_goes_back_to_pending(self, tracker):
        job_id = _add(tracker)
        tracker.decide_pending_job(job_id, "rejected", reason="x")

        assert tracker.undo_pending_job_decision(job_id) == 1
        assert tracker.get_pending_job(job_id).status == "pending"

    def test_undo_on_already_pending_job_is_a_no_op(self, tracker):
        # 对称于 decide_pending_job 对已决定行的 no-op。
        job_id = _add(tracker)
        assert tracker.undo_pending_job_decision(job_id) == 0
        assert tracker.get_pending_job(job_id).status == "pending"


class TestSetPendingJobReview:
    def test_correcting_the_category_never_touches_category_agent(self, tracker):
        """整个文件的重点。人把「产品」改成「运营」之后，仍然要能看出 agent
        当初报的是「产品」——那个差值就是纠错信号。"""
        job_id = _add(tracker, category="产品")
        tracker.set_pending_job_review(job_id, category="运营")

        job = tracker.get_pending_job(job_id)
        assert job.category == "运营", "人改的值应该生效"
        assert job.category_agent == "产品", "agent 原始上报绝不能被覆写"

    def test_none_leaves_a_column_alone(self, tracker):
        # 两个参数都是三态：None = 不动这一列。UI 要能只确认 golden 而不重发类别。
        job_id = _add(tracker, category="产品")
        tracker.set_pending_job_review(job_id, category="运营")
        tracker.set_pending_job_review(job_id, is_golden=True)

        job = tracker.get_pending_job(job_id)
        assert job.category == "运营" and job.is_golden is True

    def test_works_after_the_job_was_already_decided(self, tracker):
        """跟 decide_pending_job 不同，这里刻意不卡 status='pending'——批准之后才
        发现归类错了是常事，而整理样例库跟审批生命周期本来就是两件事。"""
        job_id = _add(tracker, category="产品")
        tracker.decide_pending_job(job_id, "approved")
        assert tracker.set_pending_job_review(job_id, category="运营", is_golden=True) == 1
        assert tracker.get_pending_job(job_id).category == "运营"

    def test_no_op_when_nothing_given(self, tracker):
        job_id = _add(tracker)
        assert tracker.set_pending_job_review(job_id) == 0


class TestGoldenExamples:
    def test_only_confirmed_corrections_are_returned(self, tracker):
        corrected_confirmed = _add(tracker, url="https://x/1", category="开发", title="A")
        tracker.set_pending_job_review(corrected_confirmed, category="AI NATIVE", is_golden=True)

        corrected_unconfirmed = _add(tracker, url="https://x/2", category="开发", title="B")
        tracker.set_pending_job_review(corrected_unconfirmed, category="AI NATIVE")

        rows = tracker.get_golden_category_examples()
        assert [r.id for r in rows] == [corrected_confirmed], \
            "没确认过的改动不该进 prompt——随手一改不代表那是标准案例"

    def test_confirmed_but_unchanged_is_excluded(self, tracker):
        """确认了但类别没变 = "agent 判对了"。当正例塞进 prompt 只是占上下文，
        而上下文正是这条链上最紧张的资源。"""
        job_id = _add(tracker, category="产品")
        tracker.set_pending_job_review(job_id, category="产品", is_golden=True)
        assert tracker.get_golden_category_examples() == []

    def test_newest_first_and_capped(self, tracker):
        for i in range(5):
            jid = _add(tracker, url=f"https://x/{i}", category="开发", title=f"J{i}")
            tracker.set_pending_job_review(jid, category="AI NATIVE", is_golden=True)
        rows = tracker.get_golden_category_examples(limit=3)
        assert len(rows) == 3
        assert [r.title for r in rows] == ["J4", "J3", "J2"], "归类口径会漂移，新的更代表当前标准"

    def test_reject_records_the_reason(self, tracker):
        job_id = _add(tracker)
        assert tracker.decide_pending_job(job_id, "rejected", reason="其实是客服岗") == 1
        job = tracker.get_pending_job(job_id)
        assert job.status == "rejected"
        assert job.reason == "其实是客服岗"
        assert job.decided_at

    def test_deciding_twice_is_a_no_op(self, tracker):
        # 已经进入填表阶段的岗位不能被二次审批改掉——WHERE status='pending' 守着。
        job_id = _add(tracker)
        assert tracker.decide_pending_job(job_id, "approved") == 1
        assert tracker.decide_pending_job(job_id, "rejected", reason="反悔") == 0
        assert tracker.get_pending_job(job_id).status == "approved"

    def test_invalid_decision_is_rejected(self, tracker):
        job_id = _add(tracker)
        with pytest.raises(AssertionError):
            tracker.decide_pending_job(job_id, "maybe")


class TestQueries:
    def test_filter_by_status(self, tracker):
        a = _add(tracker, url="https://x/1")
        _add(tracker, url="https://x/2")
        tracker.decide_pending_job(a, "approved")

        assert len(tracker.get_pending_jobs()) == 2
        assert len(tracker.get_pending_jobs("pending")) == 1
        assert len(tracker.get_pending_jobs("approved")) == 1

    def test_missing_job_returns_none(self, tracker):
        assert tracker.get_pending_job(9999) is None


class TestSourceJobLink:
    def test_pending_application_can_point_back_to_its_job(self, tracker):
        """Checkpoint 1 → Checkpoint 2 是 1:N。断了这条链，就没法从一条字段
        审批记录回答"这岗位当初是 agent 按什么理由选的"。"""
        job_id = _add(tracker, url="https://x/5")
        app_id = tracker.add_pending_application(
            site_name="bambulab", job_title="产品经理", fields=[],
            job_url="https://x/5", source_job_id=job_id,
        )
        row = tracker.conn.execute(
            "SELECT source_job_id FROM pending_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["source_job_id"] == job_id

    def test_source_job_id_is_optional(self, tracker):
        # --job-url 那条调试路径没有选岗阶段，这一列必须允许为空。
        app_id = tracker.add_pending_application(
            site_name="bambulab", job_title="x", fields=[])
        row = tracker.conn.execute(
            "SELECT source_job_id FROM pending_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["source_job_id"] is None


class TestBucketColumn:
    def test_bucket_roundtrip(self, tracker):
        jid = _add(tracker, url="https://x/9", bucket="27届秋招（研发类）")
        assert tracker.get_pending_job(jid).bucket == "27届秋招（研发类）"

    def test_bucket_defaults_to_empty(self, tracker):
        jid = _add(tracker)
        assert tracker.get_pending_job(jid).bucket == ""

    def test_decide_does_not_touch_bucket(self, tracker):
        # bucket 是"在哪找到的"，审批改不了这个事实。
        jid = _add(tracker, url="https://x/1", bucket="研发类")
        tracker.decide_pending_job(jid, "approved")
        assert tracker.get_pending_job(jid).bucket == "研发类"


class TestPendingJobCarriesJD:
    """JD 要跟岗位一起落库。

    **不是"以后可能有用"**：①W1 的评分器吃的就是 JD，抓一次两处用；②Checkpoint 1
    审批时人要看得到（现在只有标题，是盲批的另一半）；③eval 要攒真实样本。
    """

    def test_jd_round_trips(self, tracker):
        jid = tracker.add_pending_job(site_name="s", url="https://x/1", title="t",
                                      jd="职责：做 Agent 工具开发")
        assert tracker.get_pending_job(jid).jd == "职责：做 Agent 工具开发"

    def test_jd_defaults_to_empty_not_none(self, tracker):
        """空串而不是 NULL——消费方是字符串处理（评分器切词、前端渲染），
        None 会让每个消费方各写一次 `or ''`。"""
        jid = tracker.add_pending_job(site_name="s", url="https://x/2", title="t")
        assert tracker.get_pending_job(jid).jd == ""

    def test_existing_rows_migrate_with_empty_jd(self, tracker):
        """加列前就存在的行读出来 jd 必须是空串，不能炸也不能是 None。"""
        tracker.conn.execute("INSERT INTO pending_jobs (site_name, url, title, status, found_at) "
                             "VALUES ('s', 'https://x/old', 'old', 'pending', '2026-01-01T00:00:00Z')")
        tracker.conn.commit()
        row = next(j for j in tracker.get_pending_jobs() if j.url == "https://x/old")
        assert row.jd == ""
