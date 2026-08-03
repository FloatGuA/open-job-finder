from tools.browser.verify_current_url import VerifyCurrentUrl
from tools.browser.w1.capture_screenshot import CaptureScreenshot
from tools.browser.w2.navigate_to_chat_list import NavigateToChatList
from tools.browser.w2.extract_conversation_list import ExtractConversationList
from tools.browser.w2.scroll_chat_list import ScrollChatList
from tools.browser.w2.navigate_to_conversation import NavigateToConversation
from tools.browser.w2.read_messages import ReadMessages
from tools.browser.w2.send_chat_message import SendChatMessage
from tools.browser.w2.accept_resume_card import AcceptResumeCard
from tools.browser.w2.accept_wechat_card import AcceptWechatCard
from tools.browser.w2.click_toolbar_send_resume import ClickToolbarSendResume
from tools.browser.w2.upload_resume_file import UploadResumeFile


def register_w2_browser_tools(registry, browser) -> None:
    """Register all W2 browser tools into a ToolRegistry.

    Args:
        registry: ToolRegistry instance (from tools.registry)
        browser:  DrissionPage ChromiumPage object (the live browser page)
    """
    for tool_cls in (
        VerifyCurrentUrl,
        CaptureScreenshot,
        NavigateToChatList,
        ExtractConversationList,
        ScrollChatList,
        NavigateToConversation,
        ReadMessages,
        SendChatMessage,
        AcceptResumeCard,
        AcceptWechatCard,
        ClickToolbarSendResume,
        UploadResumeFile,
    ):
        registry.register(tool_cls(browser=browser))
