# Task 019 — 工作区域 / 职位类型 / 公司行业 数据提取与 Dashboard 集成

## 背景

Boss直聘 搜索页有三个筛选字段尚未集成：

| 字段 | URL 参数 | 特点 |
|------|----------|------|
| 工作区域 | `district` | 随城市变化；含区县 + 地铁线 |
| 职位类型 | `position` | 二级树形，数量较多 |
| 公司行业 | `industry` | 二级树形，数量较多 |

目标：一次性提取这三个字段的完整数据，存为 JSON，再集成进 Dashboard（求职偏好编辑页 + URL 构建）。

---

## 步骤一：提取原始数据

项目已有提取脚本 `code/tools/fetch_boss_filters.py`（使用 DrissionPage 打开 Boss直聘 并抓取网络请求与 DOM）。

运行：

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code
python tools/fetch_boss_filters.py
```

脚本会将原始数据保存到 `data/boss_filters_raw.json`。

**如果脚本运行失败**（无法打开浏览器），尝试以下备选方案：

1. 用 `requests` + `session.json` 中的 Cookie 直接请求 Boss直聘 的初始化接口，例如：
   - `https://www.zhipin.com/wapi/zpCommon/data/navIndustry.json`
   - `https://www.zhipin.com/wapi/zpCommon/data/position.json`
   - `https://www.zhipin.com/wapi/zpgeek/search/condition.json?city=101280600`
   这些是 Boss直聘 常见的配置接口，尝试发现并请求，将响应存入 `data/boss_filters_raw.json`

2. 如果上述接口都返回 403/需要登录，从 `data/browser_profile` 中读取 Cookie，加入 `requests.Session` 再请求。

---

## 步骤二：解析并整理为干净的 JSON

写脚本 `code/tools/parse_boss_filters.py`，读取 `data/boss_filters_raw.json`，生成以下三个文件：

### `data/boss_districts.json`
```json
{
  "深圳": [
    {"label": "南山区", "code": "440305"},
    {"label": "福田区", "code": "440304"},
    {"label": "地铁1号线", "code": "..."},
    ...
  ],
  "北京": [...],
  ...
}
```

### `data/boss_positions.json`
```json
[
  {"label": "技术", "code": "100020", "children": [
    {"label": "后端开发", "code": "100020.10"},
    {"label": "前端开发", "code": "100020.20"},
    ...
  ]},
  ...
]
```
若没有树形结构则存扁平列表 `[{"label": "...", "code": "..."}]`。

### `data/boss_industries.json`
结构同 `boss_positions.json`。

**解析要求**：
- 从 `_raw_network` 里找 Response body 为 JSON 且包含 `position`/`industry`/`district` 字段的条目
- 从 `_raw_filter_links` 里提取 `district`/`position`/`industry` 参数
- 从 `_window_globals` 里提取相关字段
- 对 `districts` 直接使用 fetch 脚本已按城市分组的结果

---

## 步骤三：集成进 Dashboard

### 3.1 新增 API 端点（`dashboard/server.py`）

```python
@app.get("/api/filters/districts")
async def get_districts(city: str = "") -> JSONResponse:
    """返回指定城市的区县+地铁列表"""
    ...

@app.get("/api/filters/positions")
async def get_positions() -> JSONResponse:
    """返回职位类型列表（扁平或树形）"""
    ...

@app.get("/api/filters/industries")
async def get_industries() -> JSONResponse:
    """返回公司行业列表"""
    ...
```

三个接口读取对应 JSON 文件，文件不存在时返回空列表（`{"items": []}`）。

### 3.2 更新 profile 接口（`dashboard/server.py`）

`GET /api/profile` 和 `POST /api/profile` 新增三个字段：
- `districts: list[str]`
- `position_types: list[str]`
- `industries: list[str]`

### 3.3 更新 URL 构建（`dashboard/server.py`）

`_build_boss_search_url()` 新增三段：

```python
districts = profile.get("districts") or []
# district 是单值参数（Boss直聘 不支持多选区县），只取第一个
if districts:
    params.append(("district", districts[0]))

position_types = profile.get("position_types") or []
# position 支持多选，逗号分隔
if position_types:
    params.append(("position", ",".join(position_types)))

industries = profile.get("industries") or []
if industries:
    params.append(("industry", ",".join(industries)))
```

> 注：如果实测 Boss直聘 district 支持多选，改为与 experience 相同的 comma-join 处理。

### 3.4 前端更新（`dashboard/static/app.js` + `index.html`）

**index.html**：在求职偏好编辑页（融资阶段字段之后）新增三个字段：

```html
<div class="field-group">
  <label class="field-label">工作区域</label>
  <div id="profile-districts" class="tag-group tag-group-dynamic"></div>
  <div class="field-hint">依据「目标城市」第一个城市动态加载</div>
</div>
<div class="field-group">
  <label class="field-label">职位类型</label>
  <div id="profile-position-types" class="tag-group tag-group-dynamic"></div>
</div>
<div class="field-group">
  <label class="field-label">公司行业</label>
  <div id="profile-industries" class="tag-group tag-group-dynamic"></div>
</div>
```

**app.js**：

1. 新增三个参数的 URL 构建（`buildBossSearchUrl`）：
```js
const districts    = profile.districts      || [];
const posTypes     = profile.position_types || [];
const industries   = profile.industries     || [];

if (districts.length)  parts.push(`district=${districts[0]}`);
if (posTypes.length)   parts.push(`position=${posTypes.join(',')}`);
if (industries.length) parts.push(`industry=${industries.join(',')}`);
```

2. `loadProfile()` 里加载完 profile 后，根据第一个城市调用 `GET /api/filters/districts?city=XXX`，用返回的 items 渲染工作区域标签组；职位类型和行业调用对应接口。

3. profile 保存 payload 加入三个字段。

4. profile 展示区（`setup` 页）加入三行：
```js
<div class="setup-profile-row">
  <span class="setup-profile-label">工作区域</span>
  <span class="setup-profile-val">${tagList(profile.districts || [])}</span>
</div>
<div class="setup-profile-row">
  <span class="setup-profile-label">职位类型</span>
  <span class="setup-profile-val">${tagList(profile.position_types || [])}</span>
</div>
<div class="setup-profile-row">
  <span class="setup-profile-label">公司行业</span>
  <span class="setup-profile-val">${tagList(profile.industries || [])}</span>
</div>
```

---

## 验收标准

1. `data/boss_districts.json` 存在，至少包含深圳、北京、上海三个城市的区县数据
2. `data/boss_positions.json` 存在，至少包含 5 个以上职位类型条目
3. `data/boss_industries.json` 存在，至少包含 5 个以上行业条目
4. `GET /api/filters/districts?city=深圳` 返回深圳的区县列表
5. `GET /api/filters/positions` 返回职位类型列表
6. `GET /api/filters/industries` 返回行业列表
7. Dashboard 求职偏好编辑页显示工作区域、职位类型、公司行业三个多选字段，选项从 API 动态加载
8. 三个字段正确写入 `profile.yaml` 并在保存后正确回显
9. `buildBossSearchUrl` 生成的 URL 包含对应的 `district`/`position`/`industry` 参数
10. `python -m py_compile dashboard/server.py` 通过
