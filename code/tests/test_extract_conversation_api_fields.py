"""`getGeekFriendList` 到底给了哪些字段——**报键名，不报值**。

会话列表要显示岗位名，而 `hr_conversations` 上没有它，真机覆盖率只有 59%
（v2.34.5）。`backfill_application_from_conversation` 的注释提过一句
「friend-list API 的 title 没有持久化到会话上」，但**这个 API 到底返不返回岗位名，
代码里看不出来、历史 run 日志也没留档**——只能真机看一眼。

于是把「它有哪些字段」做成工具的常驻诊断输出，而不是临时加一行 print 跑完再删：
下次 Boss 改字段（加了、没了、改名）时，run 日志里就有据可查。

**只报键名。** 值里全是真实 HR 名、公司名、消息正文——那是要进 run 日志的，
而 run 日志进过 PII 事故（`precommit_pii_scan` 就是为此存在的）。
键名没有这个问题，而且回答的正是"有没有这个字段"。
"""
from tools.browser.w2.extract_conversation_list import ExtractConversationList


class _FakePage:
    def __init__(self, items):
        self._items = items

    def run_js(self, _js):
        return self._items


def test_it_reports_which_fields_the_api_returned():
    page = _FakePage([{
        "encryptJobId": "j1", "name": "张三", "brandName": "甲公司",
        "_fields": ["encryptJobId", "jobName", "name", "brandName"],
    }])
    out = ExtractConversationList(page).execute()
    assert out.ok
    assert out.data["api_fields"] == ["brandName", "encryptJobId", "jobName", "name"]


def test_fields_are_the_union_across_items():
    """不同会话可能带不同字段（例如只有部分带 jobName）。看一条会漏。"""
    page = _FakePage([
        {"encryptJobId": "j1", "_fields": ["encryptJobId"]},
        {"encryptJobId": "j2", "_fields": ["encryptJobId", "jobName"]},
    ])
    assert ExtractConversationList(page).execute().data["api_fields"] == \
        ["encryptJobId", "jobName"]


def test_no_values_leak_into_the_diagnostic():
    """run 日志会记这个 data。值里是真实 HR 名/公司名/消息正文。"""
    page = _FakePage([{
        "encryptJobId": "j1", "name": "张三", "brandName": "甲公司",
        "lastMsg": "你好在吗", "_fields": ["name", "lastMsg"],
    }])
    blob = repr(ExtractConversationList(page).execute().data["api_fields"])
    assert "张三" not in blob and "你好在吗" not in blob


def test_the_marker_never_reaches_the_conversation_rows():
    """`_fields` 是诊断用的，不能混进落库的会话字典里。"""
    page = _FakePage([{"encryptJobId": "j1", "name": "h", "brandName": "c",
                       "_fields": ["encryptJobId"]}])
    conv = ExtractConversationList(page).execute().data["items"][0]
    assert "_fields" not in conv


def test_an_api_without_the_marker_still_works():
    """DOM 兜底那条路没有 `_fields`——不能因此炸掉整个扫描。"""
    page = _FakePage([{"encryptJobId": "j1", "name": "h", "brandName": "c"}])
    out = ExtractConversationList(page).execute()
    assert out.ok and out.data["api_fields"] == []
    assert out.data["item_count"] == 1
