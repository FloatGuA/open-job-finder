# m1 / m2 / m3 三张图拆分 —— 边界与覆盖检查（2026-08-18）

> 状态：**方案待用户确认，未实现**。
> 起因：用户实测三层可视化后指出「m1/m2/Layer3 很晕，边界不清，感觉混在一起」。
> 核代码后确认：**不是 UI 说不清，是它本来就混在一起**。

## 1. 现状的三处混乱（已核实）

### 1.1 m1 与 m2 是同一张图，靠一个布尔量分叉

```python
def build_graph(tools, ..., select_only: bool = False):
    stages = [ensure_ready, find_jobs, write_pending_jobs]
    if not select_only:
        stages += [open_application, scan_and_classify_fields, write_pending_application]
```

m2 的形状被定义成「m1 的形状 + 3」。连 `stage_names` 都是 `STAGE_ORDER[:3]` 切出来的——
那个切片把「m2 = m1 加三站」这个假设写进了代码。

### 1.2 m2 里有两个幽灵节点

m2 由 `pending_job_id` 触发 → 解析成 `job_url` → 于是：

| 节点 | 名字承诺的 | m2 里实际做的 |
|------|-----------|--------------|
| `find_jobs` | 浏览站点、按偏好选岗 | 走 `if state.get("job_url")` 分支，把调用方给的**那一个**岗位包成 `FoundJob` 原样返回 |
| `write_pending_jobs` | 把候选岗位落库 | 那个 url 早在库里 → `add_pending_job` 返回 None → 空操作 |

第 2 层可视化如实画了图，所以 m2 显示 6 站、其中 2 站是幽灵。
**可视化没制造混乱，它只是把本来就有的混乱显影了。**

### 1.3 两套坐标系混着讲

| 词 | 是什么 |
|----|--------|
| Layer 1/2/3/4 | **职责分层**（设计文档）：识别判断 / 人工审批 / 分派执行 / 验证 |
| m1 / m2 | **运行单元**（可调度的 workflow） |

不是一一对应：**m1 和 m2 都属于 Layer 1**（所以代码同在 `layer1_agent.py`）；
Layer 2 不是 workflow，是人在页面上点；Layer 3 才是第三个 workflow。
「m1 / m2 / Layer 3」这个说法本身就在混两套坐标系。

### 1.4 最要命的一条：**m2 根本不填表**

`open_application`（开表单+传简历）→ `scan_and_classify_fields`（扫空字段+分类）
→ `write_pending_application`（落库待审批）。**一个字段都没往表单里填。**
它是**勘察**，不是填写。UI 上却叫「多站点填表」。

---

## 2. 提议的三张图

```
m1  选岗       START → ensure_ready → find_jobs → write_pending_jobs → END
    ↓ Checkpoint 1（人：这些岗该投吗）        产出 pending_jobs
m2  勘察表单   START → ensure_ready → open_application → scan_and_classify_fields
                     → write_pending_application → END
    ↓ Checkpoint 2（人：这些值对吗）          产出 pending_applications
m3  填写提交   START → ensure_ready → open_application → fill_fields → submit
                     → capture_proof → END
                                                产出 已提交 + 存证截图
```

**三张图各自完整，没有前缀/后缀关系。** `STAGE_ORDER[:3]` 这种切片写法作废。

**节点函数一个都不复制**：`ensure_ready` 三张图都用、`open_application` m2 和 m3 都用，
都是同一个函数被各自 `add_node` 一次。拆的是**接线**，不是实现。
反过来说，现在 `find_jobs` 里那个 `if job_url` 分支才是「一个函数硬扛两种职责」，
拆完它就不需要存在了。

| | 对外副作用 | 触发方式 |
|---|---|---|
| m1 | **零**（只浏览） | 控制台，给入口页 URL |
| m2 | **上传简历到企业系统**（未提交） | Checkpoint 1 站点条的「开始填表」 |
| m3 | **真实提交** | Checkpoint 2 批准之后（触发方式待定，见 §5） |

---

## 3. 解耦检查：三个交接点

### 交接 1（m1 → m2）：`pending_jobs` 行 ✅ 够用

m2 需要 url / title / company / site_name，全在行里。m2 从 URL 重新开始，
不依赖 m1 的浏览器状态、不依赖 m1 的进程还活着。**完全解耦。**

### 交接 2（m2 → m3）：`pending_applications` 行 ⚠️ **四个缺口**

#### 缺口 A（最重要）：表单状态不跨 run 存活

**证据**（2026-08-17 真机）：
- m2 跑完时的快照：`姓名 value="张三"`、简历已附（`ojf_resume_30568.pdf 上次上传: ...`）、
  `学校名称 value="甲大学"` —— 这些都是**站点解析上传的简历后自动回填的**。
- 我随后单独导航到**同一个 URL**：表单**完全是空的**——没有简历、没有任何值。

**后果**：m3 重新打开表单拿到的是空表，**必须重新上传简历**，才能让站点重新自动回填
那些 m2 当时看到「已填」的字段。

**推论**：`open_application` 必然出现在 m3 的图里。这正是用户直觉说的「m3 跟 m2 做一样的事」——
它不是冗余，是**表单状态不可携带**逼出来的物理约束。

#### 缺口 B：m2 只记录「空字段」，而 m3 面对的是空表

m2 记的是「当时还空着的字段」。m3 重新传简历后若站点自动回填不完全一致
（换了简历版本、站点解析逻辑变了），会出现 **m2 没记录、m3 也没值** 的字段 → 提交被站点拒。

两个选择：
- **b1（倾向）**：m3 重新扫一遍空字段，跟已批准的值比对。有已批准值就填；
  **出现 m2 没见过的空字段就中止，退回 Checkpoint 2**——不猜，也不让机器决定。
- b2：m2 记录**全部**字段（含已填的和它们当时的值），m3 逐个核对。存储更重，
  且「多出来的字段」仍然需要人看，b2 并不能省掉那次人工。

#### 缺口 C：`role` 没有落库

`ScannedElement.role`（textbox / combobox / radio / checkbox）在 `record_application` 里被丢掉，
`fields` 只存 field_id / label / kind / candidate_value / candidates / required。
m3 要知道「怎么填」（打字 / 点开选 / 点一下）必须有控件类型。

**不必补存储**——m3 会重新截图，可以从新快照重新拿 role。但**要明确写成 m3 的职责**，
否则会有人以为 `fields` 里有。

#### 缺口 D：提交现在被硬拦，且理由写死在错误信息里

`safe_tools.make_guarded_click` 对任何「提交/下一步」类标签直接 REFUSE：

> `REFUSED: 拒绝点击 uid=...（标签 ...）——这看起来是提交/下一步类操作。本阶段只负责识别，提交属于人工审批之后的阶段。`

m3 必须能提交 → 守法策略要按图分。

**提议：不给 m3 解除守法。** 而是给 m3 一个**只允许提交一次的显式代码动作**
（`submit` 节点直接调用，不经 agent 的 `click`）。agent 在 m3 里**仍然**拿不到能提交的 click。
这样「提交」永远是代码决定、不是模型决定，符合项目的 models judge / code decides，
也保住了设计文档那条「提交动作永远要求 Layer 2 的 go 信号」。

### 交接 3（m3 → 外部）：提交 + 存证 ⚠️ 见 §4.2

---

## 4. 覆盖检查：需要但三张图都还没覆盖的

### 4.1 `site_limits` 写了从来没人读 ❗

`record_site_limit` 把「27届秋招（研发类）最多可以投递 2 次」这类真实约束写进了 `site_limits`
表——**全仓库没有任何消费方**（只有 tracker 的建表/迁移和写入路径引用它）。

**m3 提交前必须查它**，否则会超投。这是 m3 落地时的硬需求，不是可选优化。

### 4.2 「提交了但没存证」必须能跟「没提交」区分开 ❗

m3 的 `submit` 成功、`capture_proof` 失败，是一个必须能识别的中间态。
两者混同的后果是**重复提交**——本项目在 W1/W2 上已经因为「动作做没做 ≠ 结果发生没发生」
栽过（`upload_resume_file` 点完确定就报 ok、W3 的 verify 假阳性）。

→ m3 的状态机至少要有 `submitting` / `submitted_unverified` / `submitted` 三格，
且 `submitted` 只能由「回站点看到已投递证据」置位。

### 4.3 `pending_jobs` 缺「已投递」终态

现在 pending_jobs 只有 pending / approved / rejected。m3 落地后必须有终态，
否则无法防止同一个岗位被反复投。（用户此前说「先不管」，但 m3 落地时它就是阻塞项。）

### 4.4 m2 失败后的重试语义

m2 失败 → `pending_jobs` 停在 approved → `_jobs_awaiting_fill` 仍把它算进去 →
再点「开始填表」会重跑。行为可接受，但**要写进文档**，否则会被当成 bug。

---

## 5. 已拍板（2026-08-18 用户确认）

### 5.1 m2 改名「勘察表单」

UI、workflow 标题、文档一律用「勘察表单」。`m2` 这个 id 不变（改 id 会牵动队列、
run_id、日志历史）。

### 5.2 缺口 B 选 **b1**：m3 重扫，多出来的字段中止退回

m3 重新扫一遍空字段，跟已批准的值比对：
- 有已批准值 → 填
- **出现 m2 没见过的空字段 → 中止本条，退回 Checkpoint 2**，不猜、不让机器决定

> 这跟 W3 的**新鲜度闸**是同一个模式：W3 发送前发现末条已是我方消息就作废、
> 退回 W2 重新分析，绝不盲发。m3 发现表单跟批准时不一致就退回，同理。
> 两处共享的原则是：**已批准的值只对「批准时看到的那个页面」有效**。

### 5.3 m3 由人再点一次，**照 W3 的装填队列模式**

用户原话：「切记不是批准之后就直接触发 m3，而是跟 W3 一样装填队列，
等着人手动点击发送再原子发送。」

```
Checkpoint 2 批准  →  只写状态（approved），不入队
                       ↓
              「开始提交 N」按钮（人点）
                       ↓
              m3 run：逐条**原子**提交
```

- **批准 ≠ 触发**。跟 v2.25.1「批准与填表解耦」同一个理由，而 m3 的后果更不可逆。
- **原子**：一条申请的「开表单 → 重传简历 → 重扫 → 比对 → 填 → 提交 → 抓存证 → 落终态」
  是一个不可分的单元；中途任一步失败，这一条整体回到可重试状态，不留半提交。
- **加载失败 ≠ 零条待提交**（照抄 W3 `get_approved_replies` 的纪律）：
  读不出已批准列表要让 run 失败，不能当成"没有要提交的"而静默跳过。

---

## 6. 明确不在本次范围

- ④ 名额过早填满 + W1 评分 + 站点/种类/分数三级呈现（见 `PROGRESS.md`，重构后做）
- ⑤ 前端调名额阈值（同上）
- Layer 4 验证层
- adapter（按站点写死的交互优化）
