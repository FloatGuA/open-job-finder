"""
Browser context helpers for the pipeline runners.

Extracted from BrowserAgent.start() / stop() so that w1_runner and w2_runner
can open/close a DrissionPage ChromiumPage without importing BrowserAgent.
"""
import logging
import subprocess
import sys
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage

logger = logging.getLogger(__name__)

_STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    if (!window.chrome) {
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
    }
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
"""

# XHR/fetch hook. Boss chat pulls its full conversation list from the
# getGeekFriendList API on first load and renders conversation switches purely
# client-side, so the ONLY way to read the list (with the hard-association key
# encryptJobId, plus real lastTS timestamps) is to capture that XHR. It MUST be
# injected BEFORE the page loads (addScriptToEvaluateOnNewDocument, same timing
# as stealth) — a post-load run_js hook misses the first, full-list response.
# Captured responses land in window.__xhrLog for extract_conversation_list /
# extract_conversation_job_id to drain. Only job-relevant responses are kept so
# the log stays bounded over a long scroll-through scan.
_XHR_HOOK_JS = r"""
(function(){
  if (window.__xhrHooked) return;
  window.__xhrHooked = true; window.__xhrLog = [];
  function relevant(url, body){
    if (url && (url.indexOf('getGeekFriendList') !== -1 || url.indexOf('getBossData') !== -1
        || url.indexOf('historyMsg') !== -1)) return true;
    if (body && body.indexOf('encryptJobId') !== -1) return true;
    return false;
  }
  function keep(url, body){
    try { if (relevant(url, body)) {
      window.__xhrLog.push({url: url, ts: Date.now(), body: (body || '').slice(0, 400000)});
      if (window.__xhrLog.length > 200) window.__xhrLog.shift();
    } } catch (e) {}
  }
  var _o = XMLHttpRequest.prototype.open, _s = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, u){ this.__u = u; return _o.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(){ var s = this;
    this.addEventListener('load', function(){ keep(s.__u, s.responseText); });
    return _s.apply(this, arguments); };
  var _f = window.fetch;
  if (_f) { window.fetch = function(){ var u = arguments[0];
    return _f.apply(this, arguments).then(function(r){
      try { r.clone().text().then(function(t){ keep((u && u.url) || u, t); }); } catch (e) {}
      return r; }); }; }
})();
"""


def _kill_stale_chrome(profile_dir: Path) -> None:
    """Kill Chrome processes that are still using our automation profile.

    Prevents 'port 9222 already in use' errors when a previous run's Chrome
    process was not properly closed (e.g. user closed the window mid-run).
    """
    profile_str = str(profile_dir)
    try:
        if sys.platform == "win32":
            # NOTE: wmic is deprecated and absent on recent Windows (11 / stripped
            # installs); a `wmic` call there silently fails, leaving stale Chrome holding
            # the profile → the next open_browser dies with BrowserConnectError (port 9222
            # conflict). Get-CimInstance is the modern, always-present replacement. Match
            # by exact profile path via .Contains (no -like wildcard pitfalls with [ ] in
            # paths), Stop-Process each, and echo the killed PIDs back for logging.
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -and $_.CommandLine.Contains('"
                + profile_str.replace("'", "''")
                + "') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                "-ErrorAction SilentlyContinue; $_.ProcessId }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=15,
            )
            killed = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
            if killed:
                logger.info(
                    "Killed %d stale Chrome process(es) using our profile: %s",
                    len(killed), ",".join(killed),
                )
        else:
            result = subprocess.run(
                ["pgrep", "-f", f"chrome.*{profile_str}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in result.stdout.splitlines():
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    subprocess.run(
                        ["kill", "-9", pid_str],
                        capture_output=True,
                        timeout=5,
                    )
                    logger.info(
                        "Killed stale Chrome process PID %s using our profile",
                        pid_str,
                    )
    except Exception as exc:
        logger.debug("_kill_stale_chrome: %s", exc)


def open_browser(data_dir: Path, headless: bool = True) -> ChromiumPage:
    """Open a DrissionPage browser and return the ChromiumPage object."""
    profile_dir = data_dir / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Kill any Chrome that is still open with our automation profile.
    _kill_stale_chrome(profile_dir)

    # Clean stale LOCK files left by crashed sessions.
    for lock_path in [
        profile_dir / "LOCK",
        profile_dir / "Default" / "LOCK",
    ]:
        try:
            lock_path.unlink()
            logger.info("Removed stale browser LOCK: %s", lock_path)
        except OSError:
            pass

    options = ChromiumOptions()
    options.set_user_data_path(str(profile_dir))
    options.headless(headless)

    # Anti-bot: remove Chrome automation fingerprints that Boss detects.
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument("--no-first-run")
    options.set_argument("--no-default-browser-check")
    options.remove_argument("--enable-automation")
    # Mimic a real desktop Chrome session.
    options.set_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    page = ChromiumPage(addr_or_opts=options)

    # Inject stealth script via CDP so it runs on every page navigation.
    try:
        page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=_STEALTH_JS)
    except Exception:
        try:
            page.run_js(_STEALTH_JS)
        except Exception:
            pass

    # Inject the XHR/fetch hook the same way. CDP-only (no run_js fallback): a
    # post-load hook is useless here — Boss has already pulled the full
    # getGeekFriendList response by the time run_js could run. If CDP injection
    # fails, extract_conversation_list surfaces an empty API log and falls back
    # to DOM scraping rather than silently under-reading.
    try:
        page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=_XHR_HOOK_JS)
    except Exception as exc:
        logger.warning("XHR hook CDP injection failed: %s", exc)

    logger.info("Browser started with DrissionPage, profile at %s", profile_dir)
    return page


def close_browser(page) -> None:
    """Safely close a ChromiumPage."""
    try:
        page.quit()
    except Exception:
        pass
