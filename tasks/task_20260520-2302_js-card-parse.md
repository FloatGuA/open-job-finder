# Task: 用 JS 批量提取卡片数据，修复 _parse_job_card 对 SPA 子节点无法查询的问题

## 目标

修复 `search_with_panel` 中绝大多数卡片解析失败的 bug：将 DrissionPage element-scoped `ele()` 查询替换为 JS 批量查询，完全绕开 DrissionPage 不能查 SPA 动态子节点的限制。

## 背景

`search_with_panel` 通过 `_eles_any(_SELECTORS["job_card"])` 得到 `.job-card-wrap` 元素列表，再对每个元素调用 `_parse_job_card(card, ...)` 提取 href/title/salary。

`_parse_job_card` 内部调用 `_first_attr(card, ["a.job-name", ...], "href")`，最终执行 `scope.ele(selector, timeout=0)`——这是 DrissionPage 的 element-scoped CSS 查询。

**根本原因**：DrissionPage element-scoped `ele()` 不能查 Vue SPA 的动态子节点（MEMORY.md 已知陷阱）。实际运行日志显示 7/8 张卡片返回 "no href found"，只有视口内已渲染的 1-2 张能成功查到 href，导致看 2 张就触发 `search_exhausted`。

**修复方向**：在 `do_search()` 里改用 `page.run_js(...)` 的 `querySelectorAll` 批量提取全部卡片数据（返回 dict 列表），不再依赖 DrissionPage element scope。

涉及文件：`code/services/browser_agent.py`

不改动：orchestrator、tracker、tests、其他工具。

## 实现要求

### 1. 新增 `_job_from_dict` 方法（browser_agent.py）

在 `_parse_job_card` 方法附近（约 1844 行）新增：

```python
def _job_from_dict(self, data: dict, keywords: str, default_city: str) -> Optional[Job]:
    """Build a Job from a dict produced by the JS card-scrape snippet."""
    href = data.get("href", "")
    if href and href.startswith("/"):
        href = f"{self.BASE_URL}{href}"
    if not href:
        logger.debug("_job_from_dict: no href in card data, skipping")
        return None
    job_id = self._extract_job_id(href)
    if not job_id:
        job_id = hashlib.md5(href.encode("utf-8")).hexdigest()[:12]
    city_text = data.get("location", "")
    city = self._extract_city(city_text) or default_city
    salary = _decode_boss_numbers(data.get("salary", ""))
    return Job(
        job_id=job_id,
        title=data.get("title", ""),
        company=data.get("company", ""),
        city=city,
        salary=salary,
        url=href,
        jd_text="",
        source_keyword=keywords,
        discovered_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status=AppStatus.DISCOVERED.value,
    )
```

### 2. 新增 `_scrape_cards_js` 方法（browser_agent.py）

在 `_job_from_dict` 附近新增，封装 JS 查询：

```python
def _scrape_cards_js(self) -> list:
    """Return list of raw card dicts using JS querySelectorAll (bypasses DrissionPage SPA limits)."""
    page = self._require_page()
    result = page.run_js("""
        return Array.from(document.querySelectorAll('.job-card-wrap')).map(function(c) {
            var a = c.querySelector('a.job-name') || c.querySelector('a[href*="/job_detail/"]');
            var sal = c.querySelector('.job-salary');
            var comp = c.querySelector('.company-name') || c.querySelector('.boss-name') || c.querySelector('.company-text');
            var loc = c.querySelector('.company-location') || c.querySelector('.job-area');
            return {
                href: a ? (a.getAttribute('href') || '') : '',
                title: a ? (a.textContent || '').trim() : '',
                salary: sal ? (sal.textContent || '').trim() : '',
                company: comp ? (comp.textContent || '').trim() : '',
                location: loc ? (loc.textContent || '').trim() : '',
            };
        });
    """)
    return result if isinstance(result, list) else []
```

### 3. 修改 `search_with_panel` 的 `do_search()` 主循环（约 525–562 行）

**改动 A：主循环——找下一张未处理卡片**

将：
```python
cards = self._eles_any(_SELECTORS["job_card"])

# Find the first visible card that hasn't been processed yet.
next_card = None
next_job = None
for card in cards:
    candidate = self._parse_job_card(card, keywords, city)
    if candidate is None or candidate.job_id in seen_job_ids:
        continue
    next_card = card
    next_job = candidate
    break
```

改为：
```python
cards_data = self._scrape_cards_js()

# Find the first visible card that hasn't been processed yet.
next_job = None
for card_data in cards_data:
    candidate = self._job_from_dict(card_data, keywords, city)
    if candidate is None or candidate.job_id in seen_job_ids:
        continue
    next_job = candidate
    break
```

同时将后续所有 `next_card is None` 改为 `next_job is None`，以及 `next_card.click()` 改为：通过 job_id 或 href 找到对应 DOM 元素再点击（见下方改动 C）。

**改动 B：`next_card is None` 分支内的滚屏后检查**

将：
```python
for card in self._eles_any(_SELECTORS["job_card"]):
    candidate = self._parse_job_card(card, keywords, city)
    if candidate is not None and candidate.job_id not in seen_job_ids:
        has_new_job_id = True
        break
```

改为：
```python
for card_data in self._scrape_cards_js():
    candidate = self._job_from_dict(card_data, keywords, city)
    if candidate is not None and candidate.job_id not in seen_job_ids:
        has_new_job_id = True
        break
```

**改动 C：卡片点击**

原代码 `next_card.click()` 依赖 DrissionPage element 对象。替换为通过 JS 找到对应 `<a class="job-name">` 元素并点击，或通过 DrissionPage 查 `a[href*='{job_id}']`：

```python
# 替换 next_card.click()
try:
    # Use job_id fragment to locate the specific card link
    job_id_fragment = next_job.job_id
    card_link = self._ele_any(
        [f"a[href*='{job_id_fragment}']"],
        timeout=3,
    )
    if card_link:
        card_link.click()
    else:
        logger.warning("search_with_panel: card link not found for %s, skipping", job_id_fragment)
        continue
    self._human_pause(1.5, 2.5)
except Exception as exc:
    logger.warning(
        "search_with_panel: card click failed for %s: %s",
        next_job.job_id, exc,
    )
    continue
```

**注意**：
- 删除 `next_card = None` 和 `next_card` 相关变量（不再需要 DOM element 引用）
- 其余逻辑（`seen_job_ids.add`、`cards_checked`、`on_card` 调用等）保持不变

### 4. 同样修复 `search()` 方法（约 403–456 行）

`search()` 方法（旧版，非 panel 版本）有同样的 bug。将其主循环内的卡片遍历也改为 `_scrape_cards_js()` + `_job_from_dict()`：

```python
# 改动前
cards = self._eles_any(_SELECTORS["job_card"])
for card in cards:
    ...
    job = self._parse_job_card(card, keywords, city)

# 改动后
cards_data = self._scrape_cards_js()
for card_data in cards_data:
    ...
    job = self._job_from_dict(card_data, keywords, city)
```

滚屏后的等待检查也同样替换。

## 验收标准

- [ ] `search_with_panel` 运行时，每一张 `.job-card-wrap` 卡片都能成功解析出 job_id（不再出现大量 "no href found" 日志）
- [ ] 搜索数量上限 30 时，不再在看了 2 张之后就 `search_exhausted`
- [ ] `_parse_job_card` 方法本身保留不变（其他调用路径可能还在用）
- [ ] `pytest tests/` 全部通过，无回归
