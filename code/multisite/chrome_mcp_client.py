"""Bridges chrome-devtools-mcp (a Node.js MCP server, spawned via `npx`) into
LangGraph-consumable tools, via `langchain_mcp_adapters`.

This is a DIFFERENT browser automation stack from the rest of the project
(DrissionPage everywhere else, chosen specifically because it evades Boss 直聘's
CDP detection — see DECISION.md "DrissionPage 而非 Playwright"). chrome-devtools-mcp
is itself CDP-based (via Puppeteer), so it inherits the same detectability profile
Playwright would have. Whether that matters for a given target site is unverified —
this is the "反自动化验证" risk the design doc flags as unresolved, and using this
stack for Layer 1 doubles as the first live signal for it (see docs/multi-site-
expansion-design.md "风险与开放问题" #1).

Kept intentionally separate from `services/browser_context.py` / `tools/browser/` —
those exist for the W1/W2/W3 pipelines and their DrissionPage stack; nothing here
should be imported by that code, and vice versa.
"""
from pathlib import Path
from typing import Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

# Persistent Chrome profiles dedicated to this agent, separate from the Boss 直聘
# profile at data/browser_profile/ -- different sites, different logins. One
# subdirectory PER SITE (not one shared profile): Layer 1 targets more than one
# site (Huawei, Bambu Lab 拓竹, ...), each with its own account/login, so sharing
# a single profile would mix unrelated sessions and cookies across sites.
PROFILE_ROOT = Path(__file__).resolve().parent.parent / "data" / "browser_profile_multisite"

SERVER_NAME = "chrome-devtools"


def profile_dir_for_site(site_name: str) -> Path:
    return PROFILE_ROOT / site_name


def build_client(
    user_data_dir: Path,
    headless: bool = False,
) -> MultiServerMCPClient:
    """Configure (but do not yet connect) the MCP client for chrome-devtools-mcp.

    headless defaults to False: the first run against any new target site needs a
    real, visible window for the user to log in by hand (same pattern as the
    existing Boss profile -- session persists in user_data_dir after that).
    """
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return MultiServerMCPClient(
        {
            SERVER_NAME: {
                "transport": "stdio",
                "command": "npx",
                "args": [
                    "--yes",
                    "chrome-devtools-mcp@latest",
                    f"--userDataDir={user_data_dir}",
                    f"--headless={'true' if headless else 'false'}",
                ],
            }
        }
    )


def open_session(client: MultiServerMCPClient):
    """Async context manager for ONE persistent MCP session -- i.e. one Chrome
    instance that survives across the whole Layer 1 run.

    Deliberately NOT using `client.get_tools(server_name=...)`: that convenience
    method opens a fresh short-lived session PER TOOL CALL (confirmed by real-machine
    debugging -- every navigate_page/take_snapshot call was spinning up a brand new
    npx chrome-devtools-mcp subprocess with a brand new blank browser, so a page
    navigated in one call was never visible to the next call; every snapshot came
    back `about:blank`). All tools for a single Layer 1 run must come from ONE
    `load_mcp_tools(session)` call bound to ONE `async with open_session(...)` block.
    """
    return client.session(SERVER_NAME)


async def get_tools(session) -> list[BaseTool]:
    """Tools bound to an already-open session (from `open_session()`), as LangChain
    BaseTool instances ready to bind to a LangGraph agent/node. Concrete tool names
    this project's layer1_agent.py relies on (confirmed against the installed
    package, not guessed): navigate_page, take_snapshot, click, fill, upload_file,
    wait_for."""
    return await load_mcp_tools(session)


def get_tool(tools: list[BaseTool], name: str) -> BaseTool:
    """Look up one tool by name from get_tools()'s result. Raises loudly (fail
    fast) if chrome-devtools-mcp's tool surface ever changes under us -- silently
    returning None here would turn into a confusing AttributeError three calls
    later instead of a clear error at the point of the actual mismatch."""
    for tool in tools:
        if tool.name == name:
            return tool
    available = sorted(t.name for t in tools)
    raise RuntimeError(f"chrome-devtools-mcp does not expose a '{name}' tool. Available: {available}")
