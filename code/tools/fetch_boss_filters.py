#!/usr/bin/env python3
"""
One-time script to dump Boss直聘 filter metadata:
  - districts per city (工作区域)
  - position type tree (职位类型, param: position)
  - industry tree (公司行业, param: industry)

Saves results to data/boss_filters.json
"""
import time
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR  = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "browser_profile"

BASE_URL = "https://www.zhipin.com"
SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=AI"

CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "深圳": "101280600",
    "广州": "101280100", "杭州": "101210100", "成都": "101270100",
    "武汉": "101200100", "南京": "101190100", "西安": "101110100",
    "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
}

# JS: try to extract filter trees from window globals and page DOM
EXTRACT_FILTERS_JS = """
(function() {
    const out = {};

    // ── 1. Try common window globals ──────────────────────────────
    const GLOBALS = [
        '__INIT_DATA__', '__INITIAL_STATE__', '__NEXT_DATA__',
        'window.__cfg', 'bossConfig', 'initData', 'pageData',
    ];
    for (const key of GLOBALS) {
        try {
            const val = eval(key);
            if (val && typeof val === 'object') {
                out['_global_' + key] = JSON.parse(JSON.stringify(val));
            }
        } catch(e) {}
    }

    // ── 2. Scan all inline <script> tags for JSON blobs ──────────
    const scripts = [];
    document.querySelectorAll('script:not([src])').forEach(s => {
        const t = s.textContent;
        // Look for scripts that contain position/industry/district keywords
        if (/(position|industry|district|subCity|areaCode)/i.test(t) && t.length < 200000) {
            scripts.push(t.substring(0, 5000));
        }
    });
    if (scripts.length) out['_scripts'] = scripts;

    // ── 3. Check if filter config is in Redux/Vuex store ─────────
    try {
        const store = window.__vue_store__ || window.__store__;
        if (store && store.state) out['_store_state_keys'] = Object.keys(store.state);
    } catch(e) {}

    return out;
})()
"""

# JS: extract district filter options from DOM after city selection
EXTRACT_DISTRICTS_JS = """
(function() {
    const results = [];
    // Look for district/area filter items in the filter bar
    const sels = [
        '[class*="district"] a', '[class*="area"] a',
        '[class*="subway"] a', '[class*="metro"] a',
        '[data-type="district"] a', '[data-type="area"] a',
    ];
    for (const sel of sels) {
        const items = document.querySelectorAll(sel);
        if (items.length > 0) {
            items.forEach(el => {
                const txt = el.textContent.trim();
                const href = el.getAttribute('href') || '';
                // Extract code from href or data attribute
                const code = el.getAttribute('data-code') || el.getAttribute('data-value')
                    || (href.match(/[?&](?:district|subCity|area)=([^&]+)/) || [])[1]
                    || '';
                if (txt && txt !== '不限' && txt.length <= 15) {
                    results.push({label: txt, code, sel});
                }
            });
            if (results.length) break;
        }
    }

    // Fallback: scan all links on page whose href contains district/area params
    if (!results.length) {
        document.querySelectorAll('a[href]').forEach(el => {
            const href = el.getAttribute('href') || '';
            const m = href.match(/[?&](district|subCity|areaCode)=([^&]+)/);
            if (m) {
                const txt = el.textContent.trim();
                if (txt && txt.length <= 10) {
                    results.push({label: txt, param: m[1], code: m[2]});
                }
            }
        });
    }

    return results;
})()
"""

# JS: extract all filter option links from the page (broad sweep)
EXTRACT_ALL_FILTER_LINKS_JS = """
(function() {
    const params = {};
    document.querySelectorAll('a[href]').forEach(el => {
        const href = el.getAttribute('href') || '';
        const txt = el.textContent.trim();
        if (!txt || txt.length > 20 || txt.length < 1) return;
        // Parse query params from the href
        const m = href.match(/\\?(.+)/);
        if (!m) return;
        m[1].split('&').forEach(part => {
            const [k, v] = part.split('=');
            if (!k || !v) return;
            if (['city','query'].includes(k)) return;
            if (!params[k]) params[k] = {};
            params[k][v] = txt;
        });
    });
    return params;
})()
"""

# JS: look for position/industry dropdowns or expand them
EXPAND_AND_EXTRACT_JS = """
(function() {
    // Try clicking "更多" or "职位类型" to expand
    const triggers = document.querySelectorAll(
        '[class*="more"], [class*="expand"], [class*="position"], [class*="industry"]'
    );
    const results = {clicked: [], found: []};
    triggers.forEach(el => {
        const txt = el.textContent.trim();
        if (['更多','职位类型','行业','展开'].includes(txt)) {
            results.clicked.push(txt);
            try { el.click(); } catch(e) {}
        }
    });

    // After click, find any newly visible dropdown items
    setTimeout(() => {}, 500);

    document.querySelectorAll('a[href*="position="], a[href*="industry="]').forEach(el => {
        const href = el.getAttribute('href');
        const txt = el.textContent.trim();
        const pm = href.match(/position=([^&]+)/);
        const im = href.match(/industry=([^&]+)/);
        if (pm) results.found.push({type: 'position', code: pm[1], label: txt});
        if (im) results.found.push({type: 'industry', code: im[1], label: txt});
    });

    return results;
})()
"""


def _to_jsonable(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return value


def main():
    from DrissionPage import ChromiumOptions, ChromiumPage

    opts = ChromiumOptions()
    opts.set_user_data_path(str(PROFILE_DIR))
    opts.headless(False)
    opts.set_argument("--disable-blink-features=AutomationControlled")
    opts.set_argument("--no-first-run")
    opts.set_argument("--no-default-browser-check")

    print("Starting browser...")
    page = ChromiumPage(opts)
    time.sleep(2)

    # ── Enable network request listening ─────────────────────────
    page.listen.start(targets=["zhipin.com"])

    print(f"Loading search page...")
    page.get(SEARCH_URL)
    time.sleep(5)

    current = page.url
    print(f"Current URL: {current}")
    if any(x in current for x in ("login", "passport", "account", "safe")):
        print("Not logged in — run `python main.py --onboarding` first.")
        page.quit()
        return

    all_data = {
        "districts": {},
        "position": {},
        "industry": {},
        "_raw_network": [],
        "_raw_filter_links": {},
    }

    # ── Capture network requests ──────────────────────────────────
    print("\nCapturing network requests (waiting for all requests to settle)...")
    time.sleep(3)
    captured = []
    try:
        for packet in page.listen.steps(count=200, timeout=8):
            url = getattr(packet, 'url', '') or ''
            if any(kw in url for kw in ('option', 'config', 'filter', 'district',
                                         'position', 'industry', 'metro', 'subway',
                                         'area', 'geek', 'common')):
                resp_url = url
                try:
                    body = packet.response.body
                    if body and len(body) < 500_000:
                        captured.append({"url": resp_url, "body": body})
                        print(f"  Captured: {resp_url[:100]}")
                except Exception:
                    captured.append({"url": resp_url, "body": None})
                    print(f"  Captured (no body): {resp_url[:100]}")
    except Exception as e:
        print(f"  Network capture ended: {e}")

    all_data["_raw_network"] = _to_jsonable(captured)

    # ── Extract from page globals / inline scripts ────────────────
    print("\nExtracting from window globals and inline scripts...")
    try:
        globals_data = page.run_js(EXTRACT_FILTERS_JS)
        if globals_data:
            all_data["_window_globals"] = globals_data
            print(f"  Found keys: {list(globals_data.keys())}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Extract all filter links from base page ───────────────────
    print("\nExtracting filter option links from DOM...")
    try:
        filter_links = page.run_js(EXTRACT_ALL_FILTER_LINKS_JS)
        if filter_links:
            all_data["_raw_filter_links"] = filter_links
            print(f"  Found params: {list(filter_links.keys())}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Try to expand position/industry dropdowns ─────────────────
    print("\nAttempting to expand position/industry dropdowns...")
    try:
        expanded = page.run_js(EXPAND_AND_EXTRACT_JS)
        if expanded:
            print(f"  Clicked: {expanded.get('clicked')}")
            print(f"  Found {len(expanded.get('found', []))} items")
            all_data["_expanded"] = expanded
    except Exception as e:
        print(f"  Error: {e}")

    # ── District extraction: iterate cities ───────────────────────
    print("\nExtracting districts per city...")
    for city_name, city_code in CITY_CODES.items():
        url = f"{BASE_URL}/web/geek/jobs?city={city_code}&query=AI"
        print(f"  {city_name} ({city_code})...")
        try:
            page.get(url)
            time.sleep(3)
            districts = page.run_js(EXTRACT_DISTRICTS_JS)
            if districts:
                all_data["districts"][city_name] = districts
                print(f"    → {len(districts)} items")
            else:
                # Fallback: check filter links for district/subCity params
                links = page.run_js(EXTRACT_ALL_FILTER_LINKS_JS) or {}
                for param in ("district", "subCity", "areaCode"):
                    if param in links:
                        all_data["districts"][city_name] = [
                            {"label": v, "code": k, "param": param}
                            for k, v in links[param].items()
                        ]
                        print(f"    → {len(all_data['districts'][city_name])} items (via link scan, param={param})")
                        break
                else:
                    print(f"    → (not found)")
        except Exception as e:
            print(f"    Error: {e}")

    page.quit()

    # ── Save ──────────────────────────────────────────────────────
    out = DATA_DIR / "boss_filters_raw.json"
    out.write_text(json.dumps(_to_jsonable(all_data), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved raw dump to: {out}")

    # ── Summary ───────────────────────────────────────────────────
    print("\n\nSUMMARY")
    print("="*50)
    print(f"Network requests captured: {len(all_data['_raw_network'])}")
    print(f"Filter link params found:  {list(all_data['_raw_filter_links'].keys())}")
    print(f"Cities with districts:     {list(all_data['districts'].keys())}")
    if "_expanded" in all_data:
        found = all_data["_expanded"].get("found", [])
        positions = [x for x in found if x.get("type") == "position"]
        industries = [x for x in found if x.get("type") == "industry"]
        print(f"Position items found:      {len(positions)}")
        print(f"Industry items found:      {len(industries)}")


if __name__ == "__main__":
    main()
