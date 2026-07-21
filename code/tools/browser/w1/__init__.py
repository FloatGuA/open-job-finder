from tools.browser.verify_current_url import VerifyCurrentUrl
from tools.browser.w1.navigate_search_url import NavigateSearchUrl
from tools.browser.w1.extract_card_list import ExtractCardList
from tools.browser.w1.scroll_search_results import ScrollSearchResults
from tools.browser.w1.click_card_open_panel import ClickCardOpenPanel
from tools.browser.w1.read_panel_jd import ReadPanelJD
from tools.browser.w1.click_apply_button import ClickApplyButton
from tools.browser.w1.handle_apply_dialog import HandleApplyDialog
from tools.browser.w1.capture_screenshot import CaptureScreenshot


def register_w1_browser_tools(registry, browser) -> None:
    """Register all W1 browser tools into a ToolRegistry.

    Args:
        registry: ToolRegistry instance (from tools.registry)
        browser:  DrissionPage ChromiumPage object (the live browser page)
    """
    for tool_cls in (
        VerifyCurrentUrl,
        NavigateSearchUrl,
        ExtractCardList,
        ScrollSearchResults,
        ClickCardOpenPanel,
        ReadPanelJD,
        ClickApplyButton,
        HandleApplyDialog,
        CaptureScreenshot,
    ):
        registry.register(tool_cls(browser=browser))
