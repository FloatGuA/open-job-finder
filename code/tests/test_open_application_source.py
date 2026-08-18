"""`open_application` 的岗位从哪来。

拆图之后 m2 的图里**没有 `find_jobs` 节点**，`state["found_jobs"]` 永远是空的。
而 `open_application` 原本读的正是它，于是会返回一句

    note="没有找到符合条件的岗位"

——不崩、不报错，一个**看起来完全合理、其实是接线错误**的结论。真实 m2 会静默空跑：
不打开表单、不上传简历，却报告这个岗位不符合条件。本项目反复栽在这种形状上
（动作做没做 ≠ 结果发生没发生），静默的错误结论比崩溃危险得多。

解析逻辑提到模块级 `job_from_state`，跟 `record_candidates` / `describe_message` 同一个套路：
关在需要真浏览器的闭包里就永远测不到。
"""
import pytest

from multisite.layer1_agent import job_from_state


class TestJobFromState:
    def test_reads_the_job_straight_from_state(self):
        got = job_from_state({
            "job_url": "https://example.com/position/1/detail",
            "job_title": "后端开发实习生",
            "company": "甲公司",
        })
        assert got == ("https://example.com/position/1/detail", "后端开发实习生", "甲公司")

    def test_title_and_company_are_optional(self):
        """m2 由 pending_job_id 触发时标题/公司一般都有；`--job-url` 调试路径可能只给得出 URL。"""
        assert job_from_state({"job_url": "https://example.com/x"}) == (
            "https://example.com/x", "", "")

    def test_missing_job_url_raises_instead_of_returning_a_note(self):
        """返回一句 note 正是这次事故的形状：把接线错误伪装成业务结论。
        缺 job_url 是调用方的错，要当场炸。"""
        with pytest.raises(ValueError, match="job_url"):
            job_from_state({"resume_pdf_path": "x.pdf", "site_name": "s"})

    def test_blank_job_url_also_raises(self):
        with pytest.raises(ValueError, match="job_url"):
            job_from_state({"job_url": "   "})

    def test_found_jobs_is_never_consulted(self):
        """就算 found_jobs 里有东西也不看它——m2 的岗位只有一个来源。
        两个来源意味着"哪个说了算"要靠读代码才知道。"""
        with pytest.raises(ValueError, match="job_url"):
            job_from_state({"found_jobs": [object()]})
