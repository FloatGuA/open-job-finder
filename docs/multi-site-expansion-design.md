# 多站点扩展设计方案（草案，未实现）

> 状态：**设计讨论阶段，未落地任何代码**。本文档是 2026-08-10~08-12 多次对话的产出，用于对齐方向。核心运行时架构（识别/审批/分派/验证四层）2026-08-12 定稿，动手前需要按文中"建议的下一步"验证关键假设。

## 背景

现有系统只服务 Boss 直聘一个站点，`services/boss_search_url.py`、`tools/browser/w1|w2/*`、`browser_context.py` 里的 XHR 拦截逻辑全是 Boss 专属。想把"搜索→打分→投递"这条能力扩展到其他招聘网站，同时不重写打分逻辑、简历子系统、审批队列、Dashboard、tracker schema——这些本来就跟 Boss 解耦。

## 范围声明

**这次要做的：** 投递流程（对应现有 W1）的多站点适配，含"表单字段由 LLM 结合 JD 填写、人工确认后再提交"的能力。

**明确不做，及原因：**
- **应届生网（yingjiesheng.com）的会话追踪（对应 W2/W3）**：实测验证，"先聊聊"/"和HR聊聊"（无论详情页还是个人中心投递反馈列表）在 PC 网页上 100% 弹出 App 下载引导，**没有网页内嵌 IM**，产品层面锁死，不是技术难度问题。见下方"案例：应届生网侦察结果"。
- **Android 模拟器路线（用来够到 App 内 IM）**：技术可行（Appium/uiautomator2），但等于重建整个浏览器层（DrissionPage 的 API 在原生 UI 自动化里完全不适用），且大厂 App 的反模拟器检测大概率比网页版更严，投入产出比不划算。已否决，不在本方案范围内。
- **"自动测评"（笔试自动答题）**：调研发现牛客网自己在重点打击这类行为（反作弊系统检测虚拟机/多屏/远程控制，抓到会标记作弊并通报企业）。这类工具本质是代替用户完成筛选考核，不是效率工具，不做，也不协助寻找同类工具。

## 核心思路：四层运行时架构

不是"每个网站写一套独立代码"，也不是"完全交给 agent 现场发挥点哪里"，是把**判断**和**执行**分开，各自用最合适的机制——这是 2026-08-12 一次讨论（从"要不要用 LangGraph+Chrome MCP+DeepSeek 做通用 agent"出发）收敛出的结论，取舍详见 `DECISION.md`。

```
Layer 1 识别/判断（agent：LangGraph + Chrome MCP + DeepSeek，允许出错）
  → 输入已登录会话的站点 URL + 目标岗位描述，站内定位到具体岗位详情页并进入投递表单
    （对应下方 JobSiteAdapter 契约里的 build_search_url / extract_job_cards / fetch_jd）
  → 扫描表单字段，分类为 demographic / open_question / government_id（见下方 FieldSpec）
  → demographic 字段查 personal_info 存储生成候选值；open_question 字段由 LLM 结合 JD 生成候选值
  → government_id 字段只标记，不生成值、不触碰
  → 写入 pending_application 记录

Layer 2 人工审批（Dashboard，目前不存在，需新建）
  → 人看 Layer 1 提出的候选值，可编辑/批准
  → government_id 字段由人亲自填
  → 点"批准" = 显式 go 信号，此前任何一层都不能自行触发提交

Layer 3 分派（纯代码，不是 agent，不做判断）
  → 查 adapter_registry 有没有登记这个网站的确定性 adapter
      有 → CodeExecutor 执行（写死的选择器/点击序列，快、稳、可预测）
      没有 → AgentExecutor 执行（agent 驱动，但只负责把 Layer 2 已批准的值真正落到页面上，不再判断填什么）
  → 两条执行路径共享同一组安全边界，在分派之前统一过滤/校验，不在每条执行路径里各自实现一次：
      · government_id 字段永远不出现在派给任一 executor 的写入指令里
      · 提交动作永远要求 Layer 2 的 go 信号，两个 executor 都不能自行决定"够了可以提交"

Layer 4 验证
  → verify_apply_success 独立于 apply() 的返回值判定（历史教训：动作做没做 ≠ 结果发生没发生，见 PITFALLS.md）
```

**为什么 AgentExecutor 可以碰真实提交、不违反项目"models judge, code decides"的原则**：Layer 1 的 agent 允许犯错——错了会在 Layer 2 被人工审批挡住，不会流到真实世界。AgentExecutor 虽然也是 agent 驱动，但它消费的是**已经被人批准过的值**，不再判断"该填什么"，只负责"把这个值点/打进页面"这个操作动作——真正有真实后果的判断（投不投、填什么身份信息）已经被前置到 Layer 1+2 并经过人工确认，AgentExecutor 剩下的只是操作层面的不确定性（会不会点错元素），跟会被真实后果放大的判断错误不是一回事。

## Adapter：可选的执行优化，不是强制项

**demographic 字段的值解析（"姓名"→"余佩其"）本来就是通用的，从设计上就不属于 adapter**——它是 Layer 1 查 `personal_info` 存储得到的，跟目标网站是谁无关，只写一份，不随网站数量增长（牛客网申助手"字段名映射库"的调研已验证这个划分是对的，见下）。

真正因网站而异、需要写 adapter 的，只是"怎么把这个值操作到页面上"这类交互细节——选择器、点击顺序、日期选择器的精度（华为要精确到日，Hytera/Moka 只到年月）、分步表单要不要逐节保存。而 Layer 3 的 AgentExecutor 本身就能通用处理这类交互（现场读页面、找元素、操作，跟本次 recon 会话里 Claude 操作 Hytera 表单是同一套机制），**不需要提前认识这个网站**。所以 adapter 不是每个网站的必需品，是"这个网站会被反复投递、值得为它投入写死代码换取更快更稳（不用每次都过一遍模型推理去现场找元素）"时才做的可选优化——大多数网站可以永远停留在 AgentExecutor 这条通用路径上，一份 adapter 代码都不写。这也大幅缓解了下方风险清单里"维护成本随站点数量线性增长"那条——增长速度取决于**愿意为多少网站单独投入优化**，不取决于网站总数。

### 能力清单（写 adapter 时才用得上，多数网站用不到）

| 能力 | 是否必需 | 说明 |
|---|---|---|
| `build_search_url` / 搜索 | 必需 | URL 参数化（Boss、应届生都是）还是要交互点击，决定实现方式 |
| `extract_job_cards` | 必需 | 列表页抓卡片，含分页 |
| `fetch_jd` | 必需 | 详情页/面板取 JD 正文 |
| `check_duplicate` | 必需 | 该站点有没有"已投过"的可见信号（Boss 是 `already_chatting` 按钮态） |
| `detect_form_fields` | 可选 | 返回空列表 = 单击即投（Boss、应届生都是这种）；非空 = 需要过字段填写流程 |
| `apply` | 必需 | 提交投递动作本身 |
| `verify_apply_success` | 必需，**独立于 apply() 的返回值** | 历史教训（见 PITFALLS.md）：动作做没做 ≠ 结果发生没发生，必须有独立校验 |
| `supports_messaging` + `list_conversations`/`read_messages`/`send_message` | 可选，整体开关 | 该站点没有站内 IM 就整组不实现，W2/W3 对该站点直接不启用 |

### 草拟的方法签名

落地时建议放在 `protocols.py` 或新增 `tools/browser/site_adapter.py`：

```python
class JobSiteAdapter(Protocol):
    site_name: str
    supports_messaging: bool  # 决定 W2/W3 是否对该站点可用

    def build_search_url(self, profile: Profile) -> str: ...
    def extract_job_cards(self, page) -> list[JobCard]: ...
    def check_duplicate(self, job: JobCard) -> bool: ...
    def fetch_jd(self, job: JobCard) -> str: ...
    def detect_form_fields(self, job: JobCard) -> list[FieldSpec]: ...
    def apply(self, job: JobCard, filled_fields: dict) -> ApplyResult: ...
    def verify_apply_success(self, job: JobCard) -> bool: ...

    # supports_messaging=True 才需要实现
    def list_conversations(self) -> list[Conversation]: ...
    def read_messages(self, conv: Conversation) -> list[Message]: ...
    def send_message(self, conv: Conversation, text: str) -> bool: ...
```

```python
@dataclass
class FieldSpec:
    field_id: str
    label: str
    kind: Literal["demographic", "open_question", "government_id"]
    demographic_key: str | None  # kind=demographic 时对应 personal_info/basic.yaml 或 identity.yaml 的哪个字段
```

`FieldSpec.kind` 的区分来自调研牛客网申助手的技术实现得到的结论（见下）。

**`government_id`（身份证/护照等政府证件号码）是硬约束，不是分类判断**：识别到这类字段直接标记为 `pending_manual_input`，永远不进入"人口学字段规则填"的自动填充路径——即使字段值本身就存在本地存储里。这不是能力问题，是产品安全边界；取舍见 `DECISION.md`"政府证件号码类字段写入 adapter 契约作为硬约束"。

## Recon 阶段：怎么填这份契约

用 Claude Code + `claude-in-chrome` 对新站点做**一次性、人在场核实**的侦察，不是运行时组件。产出一份"能力矩阵报告"，覆盖固定检查清单：

1. 搜索机制：URL 参数化 vs 交互式
2. 列表页/详情页选择器，分页方式
3. 投递机制：单击 vs 多字段表单 vs 跳转第三方 ATS（跳转外部系统的，大概率超出自动化范围，标注跳过）
4. **投递成功的判定信号**（历史最难的部分，recon 只能给"候选信号"，不能当结论，必须真机反复验证——Boss 当年也是改了好几版才稳定）
5. 有没有站内 IM，网页端是否可达（不能只看有没有聊天入口，要实际点进去确认不是导流到 App）
6. 反自动化信号：**DrissionPage 是否被目标站点检测**，这条不能靠人工浏览判断，要单独拿 DrissionPage 实例真测
7. 去重/幂等信号是否存在

## 表单字段填写：分两类处理（历史结论，已并入上方 Layer 1 描述）

调研牛客网申助手（Edge 扩展，`macoagnpgdmmcpnkpmiplpfompjkfdbe`）后确认，它的技术实现是"预解析表单结构 + 建字段名映射库"（school/university/graduateSchool 同义词归一化），纯规则匹配，不涉及 LLM，且是闭源商业产品、用户手动触发、无编程接口——**不可直接复用**，但验证了一个划分是对的：

| 字段类型 | 处理方式 | 对应原则 |
|---|---|---|
| 人口学字段（姓名/学校/电话/学历） | 规则映射，读 `personal_info` 存储，不用 LLM | 确定性数据转换归代码（CLAUDE.md #9） |
| 开放问题字段（期望薪资/自我评价/筛选题） | LLM 结合 JD 生成候选值 | 只在需要真判断的地方用 LLM |

`装填→待发→人工批准→再执行` 这套流程（同简历发送/回复发送的模式）现已展开为上方"核心思路：四层运行时架构"里的 Layer 1→2→3→4，此处不再重复步骤列表。

## 新增能力：轻量二分类打分模式

跟现有 5 维度加权评分器**并存，不替代**（`DECISION.md` 已明确记录过"结构化维度评分优于 LLM 整体判断"的教训，不重走回头路）。定位：新站点还没做完整 JD 结构化抽取时的降级/冷启动选项。

- 输入：用户 profile + 用户自己写的 task prompt（自然语言描述想要什么工作）+ JD
- 输出：布尔（投/不投），无维度拆解
- 实现：新增 `tools/llm/score_job_simple.py`，实现跟现有评分器同一个"打分"能力契约，按站点/按用户选择用哪个,不改动现有评分器

## 案例：应届生网侦察结果（作为 recon 报告的范例）

- 域名归属：`q.yingjiesheng.com` 是前程无忧(51job)旗下产品，非独立平台
- 搜索：`jobs/search/?jobarea=xxx&keyword=xxx`，URL 参数化，结果服务端渲染纯文本，可翻页（实测到 50 页）
- 投递：详情页"立即申请"按钮点击后真实提交，返回"投递成功"提示，按钮变"已申请"——单击即投，无表单字段
- IM：**不可用**。"先聊聊"（详情页）、"和HR聊聊"（个人中心投递反馈列表）两个入口，点击后均弹出 App 下载引导，无网页内嵌聊天界面
- 折中信号：个人中心"投递反馈"页面有粗粒度状态追踪（已投递/已查看/HR对你感兴趣/不合适），网页端可读，可以做"知道 HR 有没有理你"但读不到内容、发不了消息的弱化版监控
- 反自动化：**未测试**。以上探索用的是 `claude-in-chrome`（挂在真实 Chrome 上），不是 DrissionPage，两者的自动化特征不同，不能直接套用这次探索的结论去判断 DrissionPage 是否会被检测

## 案例：华为侦察结果（真机走到简历解析页，未提交）

- 登录：走独立 Uniportal 求职账号，跟企业内部账号体系无关（风险量级远低于 Apple 那种绑定式登录，见 `DECISION.md`）。
- **投递前置关卡**：申请流程里有一道"隐私声明"，**必须滚动到页面底部才能点击继续**，不是简单弹窗确认——adapter 若要自动化这一步，需要模拟滚动到底而非只是点"同意"按钮。其他网站大概率也有类似模式，recon 时要专门检查。
- **简历解析不稳定**：同一份 PDF，第一次上传直接返回"简历解析失败"，不做任何改动原样重新上传就成功了。说明"解析是否成功"这类判定不能只测一次就下结论，需要重试逻辑（类似 Boss 投递成功判定当年也是改了好几版才稳定）。
- **解析结果——成功字段 vs 缺口字段**：用一份真实 PDF 简历（FlowCV 模板）测试，解析成功填入了姓名、邮箱、自我评价（整段文字直接抓取）；**性别、证件签发国家/地区、证件类型+号码、出生日期、联系电话全部留空**——这些恰好是简历文本里本来就不包含、或格式对不上的身份类字段，跟"人口学字段规则填"的设计假设吻合：解析补不上的缺口，规律上就是这几类。
- **分步向导会硬卡住**：表单是 wizard 形式（基本信息 → 教育经历 → 工作经历 → 其他信息），必须先把当前分区的必填项填完并点保存，才能进入下一分区——左侧导航点了没反应。意味着"解析后仍为空的必填字段"不是可以留到最后回填的软缺口，是**卡住整条链路的硬缺口**，adapter 设计里 `detect_form_fields` 识别出的缺口字段必须在进入下一步之前处理掉。

## 案例：Hytera/海能达侦察结果（Moka 平台，真机打开表单，未提交）

- 入口：不是自己在官网搜到的岗位，是一个**带身份 token 的定向邀请链接**（`app.mokahr.com/su/{code}` → 跳转到 `invite-resume/{base64 token}`，token 解出来是 `{时间戳, 企业标识, 若干数字 ID}`）。这类链接通常来自 HR 主动邀请候选人更新资料，不是公开投递入口。
- **关键发现：Moka 是跨企业共享的中心化 ATS，不是每家企业各自一套简历**。打开链接时，姓名/邮箱/教育背景（学校、专业、学历、就读时间）**已经预填**——候选人档案挂在 Moka 平台账号上，不是挂在 Hytera 这一家企业下。这跟华为"每家企业各自从零开始解析简历"的模式**根本不同**：同样用 Moka 的其他企业，大概率复用同一份候选人档案，adapter 遇到 Moka 域名（`app.mokahr.com`）时应该按"共享档案 ATS"而不是"逐家孤立 ATS"设计交互流程——具体是"先检测已有字段再只填缺口"还是"整份档案当只读参考"，需要在真正实现前另外确认。
- **日期选择器只精确到年月**：出生日期字段用自定义日期选择器（先选年代 → 年 → 月），选完只产出"2001-03"，**没有"日"这一级**，跟华为要求完整日期的字段粒度不同——adapter 若要做通用日期填充逻辑，不能假设所有网站要的日期精度一致。
- **证件号码**：跟华为一样是必填字段，同样落进 `government_id` 这个硬约束分类，全程未触碰。
- **后续补充（同日）**：会话后段在用户明确要求下把这份表单填完并由用户本人提交，补出了完整字段清单——教育经历分区每条都要求"是否为最高学历"（多条经历要循环判断，不是只填一次）、"成绩专业排名"（下拉：前5%/前10%/前30%/前50%/其他）、"英语能力"（CET-4/6、TEM-4/8、TOEFL、IELTS、以上均未通过、其他）这类需要用户真实学业数据的字段，均由用户本人提供数值、Claude 只负责操作，证件号码全程未触碰、由用户自己填写后提交。

## 风险与开放问题

1. **反自动化未验证，且这次验证不了**：本轮所有 recon（应届生网、华为、Hytera）都用 `claude-in-chrome`（挂在真实 Chrome 上，行为特征接近真人），不代表 AgentExecutor 未来实际使用的自动化技术（大概率是 Chrome MCP / DrissionPage 之类）不会被目标站点识别——这是动手写 AgentExecutor 前第一件要单独确认的事。
2. **"投递成功"判定仍需真机迭代**：recon 报告给的信号只是候选，不是结论；Boss 这条逻辑历史上改过多版才稳定，新站点大概率要重复这个过程。
3. **Boss 的 `tools/browser/w1/*` 跟这套新架构是什么关系，尚未确认**：Boss 直聘要不要收编进 Layer 1-4 模型（比如让 AgentExecutor 也能处理 Boss，还是 Boss 保持现有独立实现不动），是需要单独讨论的问题，本文档未覆盖。
4. **Layer 2 的审批队列 + Dashboard UI 目前完全不存在**：`pending_application` 这类记录、以及对应的人工审批界面，是这套架构里唯一必须先建的基础设施（不像 adapter 那样可选）——没有它，Layer 1 识别出的候选值没有地方落地审批，整条链路走不通。
5. **两套 executor 共享的安全边界代码是单点关键路径**：government_id 过滤、提交前置 go 信号这两条，如果未来有代码绕过 Layer 3 的分派直接调用某个 executor，保护就失效——需要专门的测试守门，不能只靠"设计上说好了"。

## 建议的下一步

不建议一次性把四层架构全部搭起来。建议按风险从高到低排序，逐项单独验证：

1. **反自动化验证**：用目标自动化技术（不是 `claude-in-chrome`）测试候选站点是否有拦截——这是最大的未知数，决定了 AgentExecutor 这条路线是否可行。
2. **Layer 2 审批队列最小实现**：`pending_application` 表 + 一个极简 Dashboard 页面（哪怕只有字段值展示 + 批准按钮），先把"人工确认"这个闸建起来——它是整个架构里唯一不可绕过的必建项。
3. **端到端最小验证（一个站点，不写 adapter，全走 AgentExecutor）**：验证 Layer 1 识别 + Layer 2 审批 + Layer 3 AgentExecutor 执行 + Layer 4 验证成功信号 这条链路能不能真的跑通一次真实投递。
4. 这一趟做完，再评估要不要为高频网站投入写第一份 adapter（CodeExecutor 路径），以及要不要把 Boss 直聘也收编进这套架构。

现在直接建四层通用框架，属于"还没打过一次仗就先建兵工厂"——不符合项目一贯的 simplicity first 原则。
