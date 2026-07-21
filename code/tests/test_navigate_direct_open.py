"""navigate_to_conversation treatment-D: direct-open via chat?id=<encryptBossId>&
jobId=<encryptJobId>, verified by the chat editor input (present only when a
conversation is open). Falls back to DOM scroll-search when ids are missing/unusable."""
import tools.browser.w2.navigate_to_conversation as nav
from tools.browser.w2.navigate_to_conversation import NavigateToConversation


class FakePage:
    def __init__(self, input_present):
        self._input = input_present
        self.gets = []
        self.url = "https://www.zhipin.com/web/geek/chat"

    def get(self, url):
        self.gets.append(url)

    def run_js(self, js, *args):
        if "boss-chat-editor-input" in js:      # the "conversation open" probe
            return self._input
        return None                              # match_js / scroll_js -> nothing (DOM search fails)


def _no_pause(monkeypatch):
    monkeypatch.setattr(nav, "_human_pause", lambda *a, **k: None)


def test_direct_open_success(monkeypatch):
    _no_pause(monkeypatch)
    page = FakePage(input_present=True)
    res = NavigateToConversation(browser=page).execute(
        conv_id="JOBX", company="C", hr_name="H", boss_conv_id="BOSSX", job_id="JOBX")
    assert res.ok is True
    assert res.data["method"] == "direct_url"
    assert page.gets == ["https://www.zhipin.com/web/geek/chat?id=BOSSX&jobId=JOBX"]


def test_direct_open_verify_fails_falls_back(monkeypatch):
    _no_pause(monkeypatch)
    page = FakePage(input_present=False)  # input absent -> not opened -> fall through to DOM search
    res = NavigateToConversation(browser=page).execute(
        conv_id="JOBX", company="C", hr_name="H", boss_conv_id="BOSSX", job_id="JOBX")
    assert page.gets  # it DID try the direct URL
    assert res.data.get("method") != "direct_url"  # but reported via DOM path (not found here)


def test_skips_direct_open_without_job_id(monkeypatch):
    _no_pause(monkeypatch)
    page = FakePage(input_present=True)
    NavigateToConversation(browser=page).execute(
        conv_id="sha256key", company="C", hr_name="H", boss_conv_id="BOSSX", job_id="")
    assert page.gets == []  # no job_id -> never tries the direct URL


def test_skips_direct_open_for_useless_dc_bossid(monkeypatch):
    _no_pause(monkeypatch)
    page = FakePage(input_present=True)
    NavigateToConversation(browser=page).execute(
        conv_id="JOBX", company="C", hr_name="H", boss_conv_id="62001", job_id="JOBX")
    assert page.gets == []  # '62001' is the useless DOM d-c value, not a real encryptBossId
