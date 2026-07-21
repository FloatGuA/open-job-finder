#!/usr/bin/env python3
"""
Boss直聘 filter code probe.

Navigates to the search URL with each candidate code, then:
  1. Checks job count — if 0, the code is invalid (skip immediately).
  2. Checks which filter option is highlighted — that's the label for this code.
  3. If nothing detected, dumps raw DOM debug info to help tune selectors.

Usage:
    cd C:/Coding/AI-factory-projects/open-job-finder/code
    python tools/probe_boss_codes.py
"""
import time
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR  = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "browser_profile"

# Use a broad search likely to return many results so invalid codes show 0 clearly
BASE_URL = "https://www.zhipin.com/web/geek/jobs?city=101280600&query=AI"

# Candidate ranges — deliberately wider than expected so we catch everything.
# Invalid codes will be detected via zero-job-count guard and skipped.
CANDIDATES = {
    "experience": [str(i) for i in range(100, 116)],
    "degree":     [str(i) for i in range(200, 216)],
    "salary":     [str(i) for i in range(400, 416)],
    "jobType":    [str(i) for i in list(range(1, 8)) + list(range(1900, 1910))],
    "scale":      [str(i) for i in range(300, 314)],
    "financing":  [str(i) for i in range(1, 21)],
}

# ── JS helpers ────────────────────────────────────────────────────────────────

# Count visible job cards on the page.
COUNT_JOBS_JS = """
(function() {
    const selectors = [
        '.job-card-wrapper',
        '.job-card',
        '.job-item',
        '[class*="job-card"]',
        '[class*="jobCard"]',
        '.card-area',
    ];
    for (const sel of selectors) {
        const items = document.querySelectorAll(sel);
        if (items.length > 0) return items.length;
    }
    // Fallback: look for the count text like "共 X 个职位"
    const countEl = document.querySelector(
        '[class*="count"], [class*="total"], [class*="num"]'
    );
    if (countEl) {
        const m = countEl.textContent.match(/\\d+/);
        if (m) return parseInt(m[0]);
    }
    return -1;  // unknown
})()
"""

# Find currently highlighted/selected filter option labels.
# Uses four independent strategies and returns the union.
FIND_SELECTED_JS = """
(function() {
    const IGNORE = new Set([
        "AI","全国","北京","上海","深圳","广州","杭州","成都","武汉","南京",
        "不限","更多","筛选","搜索","确定","重置","收起","展开","全部",
        "求职","工作","岗位","职位","薪资","学历","经验","规模","类型",
        "融资","阶段","公司","阶段","条件","筛选条件",
    ]);

    function ok(txt) {
        if (!txt) return false;
        // Only first line (avoids grabbing child text from container elements)
        const t = txt.split(/[\\n\\r]/)[0].trim();
        return t.length >= 2 && t.length <= 15 && !IGNORE.has(t) && !/^\\d+$/.test(t);
    }
    function firstLine(el) {
        return ((el.innerText !== undefined ? el.innerText : el.textContent) || '')
                .split(/[\\n\\r]/)[0].trim();
    }

    const found = new Set();

    // Strategy 1: ARIA attributes (most reliable)
    document.querySelectorAll(
        '[aria-selected="true"],[aria-pressed="true"],[aria-checked="true"],[aria-current="true"]'
    ).forEach(el => {
        const t = firstLine(el);
        if (ok(t)) found.add(t);
    });

    // Strategy 2: common active CSS class patterns (substring, no word-boundary)
    const CLS = /active|selected|\\bcur\\b|checked|current|choose|chosen|highlight/i;
    document.querySelectorAll('a, span, div, li, button, label').forEach(el => {
        const cls = el.getAttribute('class') || '';
        if (!CLS.test(cls)) return;
        const t = firstLine(el);
        if (ok(t)) found.add(t);
    });

    // Strategy 3: data attributes
    document.querySelectorAll(
        '[data-selected="true"],[data-active="true"],[data-checked="true"],[data-current="true"]'
    ).forEach(el => {
        const t = firstLine(el);
        if (ok(t)) found.add(t);
    });

    // Strategy 4: filter chips — elements that contain a "×" sibling/child are
    // active filter tags; grab the text of the sibling that is NOT "×"
    document.querySelectorAll('*').forEach(el => {
        const children = Array.from(el.children);
        const hasClose = children.some(c => /×|✕|✗|\\u00d7|close/i.test(c.textContent + c.getAttribute('class')));
        if (!hasClose) return;
        const labelChild = children.find(c => !/×|✕|✗|\\u00d7|close/i.test(c.textContent + c.getAttribute('class')));
        const t = labelChild ? firstLine(labelChild) : firstLine(el).replace(/[×✕✗].*/, '').trim();
        if (ok(t)) found.add(t);
    });

    return [...found];
})()
"""

# Debug dump — runs when FIND_SELECTED_JS returns nothing.
# Prints the first N elements that look "active" in ANY way,
# so we can see what class names Boss直聘 is actually using.
DEBUG_DOM_JS = """
(function() {
    const out = [];

    // Dump all elements with "active-ish" classes
    const CLS = /active|select|\\bcur\\b|check|current|choose|chosen|highlight|on\\b/i;
    document.querySelectorAll('a, span, li, button, label').forEach(el => {
        const cls = el.getAttribute('class') || '';
        if (!CLS.test(cls)) return;
        const txt = (el.innerText || el.textContent || '').split(/[\\n\\r]/)[0].trim().substring(0, 20);
        if (!txt || txt.length < 2) return;
        out.push(cls.substring(0, 60) + ' | ' + txt);
    });

    // Also dump filter/condition container HTML snippet
    const FILTER_SELS = [
        '[class*="filter"]', '[class*="condition"]',
        '[class*="search-box"]', '[class*="job-search"]',
        '[class*="search-filter"]',
    ];
    for (const s of FILTER_SELS) {
        const el = document.querySelector(s);
        if (el) {
            out.push('FILTER_CONTAINER[' + s + ']: ' + el.innerHTML.substring(0, 300));
            break;
        }
    }

    return out.slice(0, 30);
})()
"""


def get_job_count(page) -> int:
    try:
        n = page.run_js(COUNT_JOBS_JS)
        return int(n) if n is not None and n != -1 else -1
    except Exception:
        return -1


def get_selected(page) -> list:
    try:
        return page.run_js(FIND_SELECTED_JS) or []
    except Exception:
        return []


def get_debug_dump(page) -> list:
    try:
        return page.run_js(DEBUG_DOM_JS) or []
    except Exception:
        return []


def probe_param(page, param: str, codes: list, baseline_count: int) -> dict:
    results = {}
    consecutive_empty = 0
    debug_printed = False  # Print DOM debug once per param if nothing detected

    for code in codes:
        url = f"{BASE_URL}&{param}={code}"
        try:
            page.get(url)
        except Exception as e:
            print(f"    [ERROR] get() failed for {param}={code}: {e}")
            continue
        time.sleep(2.5)

        # ── Guard: check job count ────────────────────────────────────
        count = get_job_count(page)
        if count == 0:
            consecutive_empty += 1
            print(f"    {param}={code:>6}  →  0 jobs (invalid code, skipped)")
            if consecutive_empty >= 3:
                print(f"    3 consecutive empty — stopping this parameter early")
                break
            continue
        else:
            consecutive_empty = 0

        # ── Check which filter is highlighted ─────────────────────────
        selected = get_selected(page)
        if selected:
            debug_printed = True  # We got something — no need to debug
            for label in selected:
                if label not in results:
                    results[label] = code
                    print(f"    {param}={code:>6}  →  '{label}'  (jobs: {count})")
        else:
            print(f"    {param}={code:>6}  →  (no highlight, jobs: {count})")
            # Dump DOM debug for first valid-but-no-highlight code per param
            if not debug_printed and count != -1:
                debug_printed = True
                dump = get_debug_dump(page)
                if dump:
                    print(f"    [DEBUG] Active-looking elements on page:")
                    for line in dump[:15]:
                        print(f"      {line}")
                else:
                    print(f"    [DEBUG] No active-class elements found at all — possible CAPTCHA?")

    return results


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

    print(f"Navigating to base URL: {BASE_URL}")
    page.get(BASE_URL)
    time.sleep(4)

    current = page.url
    print(f"Current URL: {current}")

    if any(x in current for x in ("login", "passport", "account", "safe")):
        print("\nNot logged in — run `python main.py --onboarding` first.")
        page.quit()
        return

    if "zhipin" not in current:
        print(f"\nUnexpected redirect: {current}")
        page.quit()
        return

    # ── Baseline job count (no filter applied) ───────────────────────
    baseline = get_job_count(page)
    print(f"\nBaseline job count (no filter): {baseline}")
    if baseline == 0:
        print("WARNING: baseline is 0 — search might be empty, results may be unreliable.")
    elif baseline == -1:
        print("WARNING: could not detect job count — selector may need updating.")

    baseline_selected = get_selected(page)
    print(f"Baseline highlighted items: {baseline_selected}")

    if baseline == -1:
        print("\n[DEBUG] Running DOM dump on base URL to diagnose selectors:")
        dump = get_debug_dump(page)
        for line in dump[:10]:
            print(f"  {line}")
    print()

    # ── Probe each parameter ─────────────────────────────────────────
    all_results = {}
    for param, codes in CANDIDATES.items():
        print(f"\n{'='*58}")
        print(f"Probing  {param!r}  ({len(codes)} candidates: {codes[0]} … {codes[-1]})")
        print("="*58)
        all_results[param] = probe_param(page, param, codes, baseline)

    page.quit()

    # ── Summary ──────────────────────────────────────────────────────
    print("\n\n" + "="*58)
    print("FINAL MAPPINGS  (copy → fix source code)")
    print("="*58)
    for param, mapping in all_results.items():
        print(f"\n# {param}")
        if not mapping:
            print("  (no matches found — check [DEBUG] lines above for clues)")
        for label, code in sorted(mapping.items(), key=lambda x: int(x[1]) if x[1].isdigit() else 9999):
            print(f"  '{label}': '{code}'")

    out = DATA_DIR / "probe_boss_codes_result.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
