# 配置说明（Configuration）

OpenJobFinder 的配置采用**三层模型**，按"谁拥有 / 能不能改 / git 跟不跟踪"分文件存放。
这样系统配置、用户画像、运行旋钮各得其所，避免双写源和把用户数据写进 git。

---

## 一、三层模型总览

| 层 | 文件 | git | 拥有者 | 装什么 |
|----|------|-----|--------|--------|
| **Layer 1** 系统配置 | `code/config.yaml` | ✅ 跟踪 | 开发者 | 模型/路由/端口等基础设施。前端基本只读。 |
| **Layer 2** 用户画像 | `code/data/profile.yaml` | ❌ ignore | 用户 | "你是谁、想找什么职位"——搜索筛选条件 + 评分补充。 |
| **Layer 3** 运行参数 | `code/config.yaml`（`w1:`/`w2:` 出厂默认）<br>+ `code/data/user_settings.yaml`（用户保存的默认） | 出厂默认✅ / 用户默认❌ | 开发者给出厂值，用户可覆盖 | 每次跑 W1/W2 的旋钮：阈值、规模、天数、dry_run、headless。 |

**判断一个参数属于哪层，问一句话：**
- 改它是在改"系统怎么跑"吗？ → Layer 1
- 改它是在改"我想要什么职位"吗？ → Layer 2
- 改它是在调"这一次任务的力度/范围"吗？ → Layer 3

---

## 二、优先级链（Layer 3 运行参数如何解析）

```
本次请求 override (API body / CLI)
        ▼  覆盖
data/user_settings.yaml[workflow]   ← 用户点"设为默认"保存的（懒创建，没点过则不存在）
        ▼  覆盖
config.yaml 的 w1: / w2:            ← 出厂默认（最低优先级 fallback）
```

由 `services/settings_resolver.py` 的 `resolve_params(workflow, overrides, config, data_dir)` 实现：
后者覆盖前者；`overrides` 里值为 `None` 的键**忽略**（不覆盖默认），这样"本次没传"和"本次显式传 0"区分得开。

---

## 三、字段参考

### `config.yaml` — Layer 1 系统配置

| 键 | 用于 | 说明 |
|----|------|------|
| `llm.capabilities.{fast,balanced,powerful}` | W1+W2 | 各能力档的 provider fallback 链 |
| `llm.tool_providers.{score_job,analyze_intent}` | W1 / W2 | `null`=按 capability 路由；填 provider 名可覆盖单个工具 |
| `dashboard.port` | Dashboard | 服务端口（默认 8765） |

### `config.yaml` — Layer 3 运行参数出厂默认

| `w1:` 键 | 含义 |
|----------|------|
| `score_threshold` | 低于此分不投递 |
| `max_cards` | 本次最多处理卡片数（`0` = 不限） |
| `daily_limit` | 每日投递上限（当前仅用于 stats 显示，pipeline 未接限流） |
| `dry_run` | `true` = 演练不真实投递 |
| `headless` | 浏览器无头模式 |

| `w2:` 键 | 含义 |
|----------|------|
| `max_conversations` | 本次最多处理会话数 |
| `no_response_days` | 投递后多少天无回应判超时拒绝 |
| `stale_conv_days` | 会话多少天无更新判陈旧关闭 |
| `dry_run` | `true` = 不真实发送简历/回复 |
| `headless` | 浏览器无头模式 |

| `m1:` 键 | 含义 |
|----------|------|
| `site` | 站点标识，决定用哪个持久化登录目录 `data/browser_profile_multisite/<site>/` |
| `search_url` | 站点招聘入口页（校招首页）。**不要带筛选参数**——筛选条件由 `profile.yaml` 的 `job_seeking` 表达，agent 自己去页面上找；编进 URL 会静默过滤掉整类岗位（实测 87 条 vs 去掉后 134 条） |
| `max_pages` | 每个分类桶最多翻几页 |

> m1 有出厂默认而 m2/w3 没有，判据是**"它有没有每次都一样的参数"**：m2 每次的岗位都不同，w3 发的是当前所有已批准回复。白名单在 `dashboard/server.py::_DEFAULTABLE_WORKFLOWS`。

### `data/profile.yaml` — Layer 2 用户画像

搜索筛选字段（喂给 `services/boss_search_url.py` 拼搜索 URL）：
`keywords` / `cities` / `experience` / `degree` / `salary` / `job_types` / `financing` / `districts` / `position_types` / `industries` / `boss_online`。
另有 `prompt_injection`（用户自定义 prompt 注入，替代旧的 `extra_notes`）：一个字典，`global` 是系统层（注入进评分/意图/回复全部 3 条工作 prompt），`score_job`/`analyze_intent`/`generate_reply` 是任务层（各自只注入进同名 prompt）。全部可选，空/缺省 = 不注入。渲染在 `PromptManager.render()` 出口统一追加一个划界的"求职者本人补充指令"块——全局注入必须在此处而非塞进 `system.md`，因为 `generate_reply` 不吃 system prompt。

> 注意：`profile.yaml` **不含** `score_threshold`（那是 Layer 3 运行旋钮）、也**不需要** `name`（投递的打招呼语由 Boss 平台自动发送，全流程不消费 name）。

---

## 四、"本次运行" vs "设为默认"

前端两种操作，语义不同，**绝不隐式互相污染**：

- **本次运行临时调参**：值只随这一次请求走（API body），**不落盘**；下次回到默认。
- **「设为默认」按钮**：调用 `save_user_default(workflow, updates, data_dir)`，把值写入 `data/user_settings.yaml`（部分覆盖，只写改过的键）。

`user_settings.yaml` **懒创建**：用户没点过"设为默认"时该文件不存在，系统直接用 `config.yaml` 出厂值。

---

## 五、给维护者：如何加一个新运行参数

1. 在 `config.yaml` 的 `w1:` 或 `w2:` 节加出厂默认值（带注释）。
2. 在对应 runner（`run_w1`/`run_w2`）和 pipeline 的 `W1Config`/`W2Config` 加该字段并真正消费它。
3. 触发入口（`main.py` 的 CLI、`dashboard/server.py` 的 `_run_*_workflow`）已统一走 `resolve_params`，通常无需改——除非该参数要支持本次 override，则在 `trigger_*` 把 `body.get("新键")` 放进 overrides。
4. 加测试，跑 `pytest`。

> 教训：加字段前先 grep 它的消费方。本项目重构后曾残留大量"配置里有、代码没读"的死字段（见下），看到 `'X' is required` 之类报错先查根因，别猜着填值绕过。

---

## 五点五、身份事实：三层模型之外的第四类数据（已知空缺，不是失误）

**上面的三层模型只覆盖「系统怎么跑」「我想要什么职位」「这一次跑多大力度」，不覆盖「我是谁」。**
身份事实（姓名 / 电话 / 邮箱 / 性别 / 出生日期 / 证件类型…）**目前没有归属层**，于是每个需要它的模块就近自己存了一份：

| 存在哪 | 存了什么 | 谁为它而存 |
|--------|----------|-----------|
| `data/info_pool.yaml` → `basic_info` | 姓名 / 电话 / 邮箱 / 城市 / 学历 / 目标岗位 | 简历系统（生成简历抬头） |
| `data/personal_info/identity.yaml` | 性别 / 出生日期 / 证件国家 / 证件类型（**刻意不存证件号码**） | 多站点 Layer 1（自动填网申表单） |

`services/../multisite/personal_info_loader.py` 负责把这两处拼成一份扁平 dict 给填表用；姓名/电话/邮箱的**唯一真源是 info_pool**（去重取舍见 `DECISION.md`）。

### ⚠️ 两处同名不同义（"感觉混乱"的直接来源，都不是重复存储）

| 字段 | 在 `profile.yaml` 里 | 在 `info_pool.basic_info` 里 |
|------|---------------------|------------------------------|
| `degree` / `cities`·`city` | **筛选条件**：我愿意投的学历档 `["本科","硕士"]`、想去的城市 | **身份事实**：我的学历 `"硕士"`、我人在哪 |

两个概念恰好共用了一个词。**刻意没有改名**——`profile.yaml` 的字段名直接喂 `services/boss_search_url.py` 拼 Boss 搜索 URL，改名要连带改搜索链路。知道这件事即可，别把它当 bug 去"修"。

> 什么时候该把身份事实正式抽成第四层：出现**第三个**消费它的模块时（比如需要学校/专业/绩点的场景）。届时应连同快照/回滚机制一起做。详见 `DECISION.md`「身份事实与求职偏好没有归属层」。

---

## 六、本次重构清理的死字段（审计记录）

| 字段 | 原因 |
|------|------|
| `apply.aggressive_resume` | 全代码零引用 |
| `apply.generate_resume` | 对应工具已删除 |
| `job_search`（整节） | `keywords/cities` 与 profile 重复、`limit_per_run` 被 `max_cards` 取代 |
| `schedule`（整节） | `scheduler.py` 已删；定时改由 server 独立的 `schedule.yaml` 管 |
| `browser.headless` | 下放到 `w1`/`w2` 各自 |
| `profile.name` | 投递不使用（Boss 招呼全自动），原必填校验是残留 |
| `profile.scale` | `build_search_url` 不处理 |
| `run_w2(max_conversations=)` 断链 | 原收下却没传给 pipeline，现已修复生效 |

### 已知遗留（后续处理）

- `services/onboarding.py` 仍把 `score_threshold`/`scale`/`job_type`（单数）写进 profile，且文件内中文已被 GBK 工具链损坏，待单独修复。
- `agent_workflows.py` 是停用的 Chat Agent 遗留，读旧结构，随 chat 迁移再清理。
- `daily_limit` 仅用于 stats 显示，pipeline 未实现真正限流。
- 前端若消费 `/api/config/system`，注意其返回已从 `apply/schedule/browser` 改为 `w1/w2`，需同步适配。
