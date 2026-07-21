from tools.browser.w3.search_locate_conversation import SearchLocateConversation


def register_w3_browser_tools(registry, browser) -> None:
    """Register the W3-only browser tools (search-locate) into a ToolRegistry.

    Delivery verification is NOT a W3-only tool: W3 re-uses W2's read_messages
    (re-scan the thread) + write_hr_messages (persist) to confirm the sent
    message actually landed. The old DOM-prefix probe (verify_reply_delivered)
    was removed as unreliable.
    """
    registry.register(SearchLocateConversation(browser=browser))
