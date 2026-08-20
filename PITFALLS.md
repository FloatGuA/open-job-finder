# OpenJobFinder — Pitfalls

> **地雷清单**：不知道这些，会以完全合理的方式踩上去。
>
> 准入判据只有一条——**不知道这件事的人，会以完全合理的方式踩上去**。
> 重点在"完全合理"：如果正确做法是显然的、或报错信息已说清楚，那不是坑，是普通 bug。
> 尤其收**静默失败**——报错的问题会自己暴露，静默的不会。
>
> **纪律**：同类坑踩第二次，回去改原条目并补上"为什么第一次没防住"，不要新增第二条。
> 能变成测试的优先变成测试，然后在此记一行"已由 xxx 守门"。
>
> 相关：为什么这么选 → `DECISION.md`；做到哪了 → `PROGRESS.md`。

---

## 从 TECHNICAL.md 迁入（2026-08-05）

- **DrissionPage 4.1.x 键盘 API**：`ChromiumElement` 和 `ChromiumPage` 均无 `.key` 属性，调用会直接抛 `AttributeError`。唯一正确键盘操作入口是 `page.actions.key_down('Enter').key_up('Enter')`（`Actions` 类，通过 `page.actions` 获取）。
- **`update_hr_analysis` CASE 保护范围**：`CASE WHEN reply_status IN ('approved','revision') THEN reply_status ELSE ?` 若不包含 `'sent'` 和 `'dismissed'`，W2 AnalyzeStep 触发 LLM 再分析时会把已发送（sent）或已忽略（dismissed）的状态覆写回 pending，导致同一条回复被重复发送。保护列表必须包含所有"终态"：`('approved','revision','sent','dismissed')`。

- **ClaudeCLIProvider prompt injection 拒绝**：`claude -p` 运行在 Claude Code 的 print-mode 下，用户消息中以 "You are a..." 开头的角色声明（含通过 `System: ...` 拼接的 system 内容）会触发 Claude Code 的 prompt-injection 拒绝，返回中文警告文本，不执行任务。正确做法：忽略 system 参数，仅发 prompt；prompt 模板应足够自包含（不依赖外部 system 角色定义）。

- **claude -p 输出编码（Windows）**：subprocess 用 `text=True, encoding="utf-8"` 时，Windows 上 Claude CLI 的中文响应会被 GBK 误解码为乱码。正确做法：用 bytes 模式读取 stdout，手动 `.decode("utf-8", errors="replace")`，并在 env 中设置 `PYTHONUTF8=1`。

---

## 从 CLAUDE.md 迁入（2026-08-05）

## 改配置/字段前不查消费方，会照着报错猜着填值绕过

**现象**：看到 `'X' is required` 之类报错，顺手填个值让它过去。
**真因**：本项目重构后残留大量死字段/断链配置，很多校验本身就是残留。
**正确做法**：先 grep X 被谁**读**、被谁**写**，再决定是补值还是删校验。
**教训实例**：曾因 `ProfileLoader` 要求 `name` 报错就去填值绕过，实际投递根本不用 name，是残留校验。

## 登录态不在 session.json，判断是否登录只有一个权威

**现象**：查 `data/session.json` 判断登录状态，得到错误结论。
**真因**：登录态在 `data/browser_profile/`（DrissionPage 的 Chrome user-data 目录）；`session.json` 是废弃占位。
**正确做法**：判断 session 是否有效，唯一权威是跑 `VerifySessionStep`（访问 `geek/recommend` 读 `window._PAGE.name`）。
**判据**：任何"检查登录"的新代码，如果没有走 `VerifySessionStep`，就是错的。

## React TSX/TS 里的裸中文会被静默损坏

**现象**：写进去是中文，构建出来是乱码；且损坏后每个字符变成 2-3 个乱码字符，字节长度变了，sed/replace 难以精确定位恢复。
**真因**：Windows GBK 工具链 + Prettier format-on-save 双重因素。
**正确做法**：JS/HTML/TSX 中 CJK 一律写 `\uXXXX`（纯 ASCII，对任何编码工具链都安全）。JSX 文本节点用 `{'\uXXXX'}`，JS 字符串字面量直接转义。
**已发生两次编码损坏事故。**

## JSX 属性的双引号字符串不处理 \uXXXX 转义

**现象**：`label="\u4e2d\u6587"` 在页面上渲染成字面量 `\u4e2d\u6587`，而不是中文。
**真因**：JSX 属性双引号串是 **JSX 语法层**，不走 JS 字符串转义；esbuild 只对 JSX **文本节点**处理转义，属性字符串不处理。
**正确做法**：改为 JS 表达式 —— `label={'\uXXXX'}`。
**受影响属性**：`label=`、`title=`、`aria-label=`、`placeholder=`。

**判据是"这段文字会不会被渲染出去"，不是"文件里有没有中文"**（2026-08-16 补）：
仓库里的 `.ts/.tsx` **注释**大量是裸中文且一直如此——转义了就没人读得懂，那是反效果。
要转的是**会进到界面上的字符串字面量**（提示文案、按钮文字、错误信息）。写一个新
模块时按"文件里不许有中文"去自查会得出错误结论（本次就误判了一次 `api/index.ts`），
按"哪些字符串会被渲染"去查才对。
**注意**：编辑器的自动转义也只覆盖 JSX 文本节点，JS 对象字面量/常量/JSX 属性串都不转。

## 用 Edit 工具直接写 \uXXXX 会被 JSON 解码回中文

**现象**：明明写的是 `\uXXXX`，落盘却是裸中文，于是又踩上面那两个坑。
**真因**：Edit 的参数走 JSON，`\uXXXX` 在解析时就被解码了。
**正确做法**：用脚本文件把内容转成 ASCII 再落盘，然后校验 `nonascii == 0`。
**已第三次踩到**，固化为 `esc_any.py`。

## 生成 \uXXXX 的脚本里手敲十六进制码位，敲错了肉眼看不出来

**复现**：写一个转 ASCII 的脚本（正确做法，见上一条），但脚本里的映射表直接手打
`"児底"` 这样的十六进制转义（凭记忆现算码位），而不是先写真实中文字面量
再用 `ord()` 机械换算。2026-08-20 就这样把"兜底"的"兜"打成了 `児`（另一个
生僻字 児），正确码位其实是 `兜`。
**现象**：脚本正常跑完、`nonascii == 0` 校验也通过（校验只管"是不是纯 ASCII"，
不管"这段 ASCII 解码回去对不对"）；生成的 `\uXXXX` 文本里两个码位都合法，肉眼扫
一遍完全看不出哪个错了——不报错、不违和，静默地把错字发布上线。
**真因**：`\uXXXX` 手工换算本质是人肉查码表，人会记错，而这一步没有任何机制校验
"我想要的字"和"我敲出来的码位"是同一个字。
**正确做法**：转义脚本的输入永远是**真实中文字面量**（正常打字，不手算十六进制），
让脚本用 `ord()`/`chr()` 做码位转换；写完用 Read 工具把脚本文件本身读回来做一遍
视觉复核（脚本是纯 UTF-8 源码，Read 显示不受 Bash 控制台 GBK 编码影响）。要复用
别处已出现过的词，从已确认正确的 UTF-8 源文件里按锚点用 python 提取码位，不要凭
记忆重敲。
**判据**：转义脚本的映射表里如果直接出现十六进制数字字面量（而不是中文字符本
身），就是危险信号——正确的脚本里不应该有任何手打的 `\uXXXX`。
**状态**：仍有效（无自动化守门；`nonascii == 0` 只能挡住裸中文残留，挡不住码位敲
错）。
**首次**：2026-08-20

---

> **与项目记忆的关系**：用户级 `MEMORY.md` 的 Known Pitfalls 是**每次会话自动加载的高频索引**，
> 本文件是**全集与权威原文**。两者定位不同、有意并存：索引要短才进得了上下文，全集要全才查得到。
> 新坑先进本文件；只有高频、影响每次动手的，才另外在 MEMORY.md 留一行索引。

---

## 2026-08-06 新增

## PowerShell here-string 里独立的 ` / ` 会被拆成单独参数传给原生命令

**现象**：`git commit -m @'...'@` 报 `fatal: /: '/' is outside repository`，提交没发生。
**更危险的是**：紧跟其后的 `git push` 会输出 **"Everything up-to-date"**——看起来像成功，
实际是因为压根没产生新提交。只看最后一行输出会以为活干完了。
**真因**：PowerShell 向原生 exe 传参时会对字符串做自己的一套切分，消息正文里两侧带空格的
独立 `/`（如"302 行 / 全项目"）被当成一个独立参数交给 git，git 把它当 pathspec。
反引号、`@`、`-` 开头的片段也有类似风险。
**正确做法**：**含中文或标点的提交信息一律写进文件，用 `git commit -F <file>`。**
不要试图靠转义救 here-string——这条路每次都要重新试错。
**判据**：提交后**必须看 `git log --oneline -1` 确认 HEAD 变了**，不能只看 push 的输出。

## 验证前端改动前必须比对 bundle hash，否则会读到没导航完的旧页面

**现象**：改了前端、build 绿了、页面也刷新了，但 DOM 里还是旧的 class / 旧的文案。
**真因（两层）**：① `location.reload()` 返回后立刻跑 JS，打在的是**还没导航完的旧文档**上；
② 更隐蔽的一层——页面若有未保存编辑，`beforeunload` 会弹「离开站点？」**把刷新拦下**，
而 `location.reload()` 依然正常返回，从外面看不出任何异常。
**正确做法**：验证前先比对 bundle hash——盘上的用
`grep -ao 'index-[A-Za-z0-9_-]*\.js' dashboard/static/index.html`，
页面里的用 `[...document.scripts]`，**不一致就别测**。
有未保存编辑时**开新标签页验证，绝不 force 导航丢掉用户的编辑**。
**判据**：一次改动后两次测量结果完全相同（连像素都没变），先怀疑没刷新，而不是改动没生效。

## 改 server.py 新增端点后，--reload 常常不触发，表现为端点 404

**现象**：新端点返回 404，前端静默拿到空数据，看起来像前端 bug。
**真因（两种，表现完全一样，得分开排查）**：
① WatchFiles 对新增路由的重载不可靠；运行中的进程还是旧的。
② **进程压根没带 `--reload` 启动**——`/api/dev/restart`（Topbar「重启后端」按钮同款）只是
`Path(__file__).touch()`，前提是进程本身在跑 `uvicorn --reload` 监听文件变化；如果当初是用不带
`--reload` 的命令起的（例如手工敲的 `python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765`，
少了文档里的 `--reload`），touch 文件不会有任何效果，反复重试也只会一直 404。
**正确做法**：新增端点后直接 curl 一下确认，404 先用 `/api/dev/restart`（或 Topbar 按钮）触发一次热重载，
等几秒再 curl；**如果还是 404，别死等，去查真实进程命令行**——
`netstat -ano | grep :8765` 拿到 PID，再
`powershell -Command "Get-CimInstance Win32_Process -Filter 'ProcessId=<PID>' | Select CommandLine"`，
看命令行里有没有 `--reload`。没有就必须手动 kill 该 PID、按 CLAUDE.md「启动方式」里的完整命令
（带 `--reload`）重新起一个。
**重启前必须先查 `/api/workflow/status`**——真跑 W1/W2 对真实 HR 不可撤销，`running` 非空先问用户。
**连带坑**：杀进程后端口可能仍被占（孤儿 worker / socket 未释放），
`Get-NetTCPConnection` 会显示一个**已经不存在的 PID**。重试一次即可，别急着换端口。
**判据**：`/api/dev/restart` 触发后等了 5 秒以上仍 404，且反复 touch 也没用——说明不是「重载慢」，
该去查进程命令行了，别在原地反复 curl。

---

## 2026-08-09 新增

## 引入「实时过滤渲染列表」后，原始拉取数组的 `.length` 会散落在别处继续被用

**现象**：Chat.tsx「待审批」tab 里，单条批准/驳回后左侧列表条数正确减少，但「一键拒绝全部」按钮和确认框上的计数没变——按钮上写的是拉取时的总数，不是当前真实待处理数。
**真因**：`updateConversation` 只就地改字段（如 `reply_status`），从不从 `conversations` 数组里移除项，所以原始数组长度只在重新拉取时才变；页面早先为了修同类 bug（2026-07-28，「W2 待审批列表没有实时更新」）引入了 `tabScoped = conversations.filter(matchesTabFilter)` 作为渲染用的实时过滤列表，但那次只把**列表渲染**换过去了，同一页面上其他直接写 `conversations.length` 的地方（按钮文案、确认框文案、显隐条件）没有一起排查，漏网了三处。
**正确做法**：一旦某页面存在「原始拉取数组 vs 实时过滤视图」的分裂（如 `conversations` vs `tabScoped`），修的时候要 **grep 整个组件里该原始数组的所有 `.length`/`.map`/直接引用**，不能只改列表渲染那一处——凡是给用户看的计数/文案，一律要用过滤后的那个变量。
**判据**：只要页面里同时存在两个语义不同的同源数组（一个"拉取时的"、一个"当前视图的"），任何显示数字的地方都要问一遍"这个数字该跟着哪个变"。

## 在 git worktree 里跑本项目，`data/` 和 `node_modules/` 都不存在——依赖它们的功能会「看起来坏了」

**现象**：两种表现，第二种是静默的。① `npm run build` 直接报 `vitest 不是内部或外部命令`——看着像 npm 装坏了。② 在 worktree 里起 dashboard，读 `data/` 的页面全是空的：面试准备页显示"还没有面试卡片"，简历/信息池同理。**没有任何报错**，看起来就是数据丢了或功能有 bug。
**真因**：worktree 是仓库的独立工作目录，只有 **git 跟踪的文件**会出现在里面。`node_modules/`（未跟踪）和 `data/`（gitignore 的运行时数据：`jobs.db`、`browser_profile/`、`info_pool.yaml`、`interview_prep.yaml`、`resumes/`）全都只存在于主仓，worktree 里那个目录压根没有。后端 loader 又普遍按「文件不存在返回空结构」设计（这本身是对的，页面要能提示怎么建），于是缺文件和"内容为空"表现完全一致。
**正确做法**：worktree 里只做**代码**改动，跑 `pytest` 和 `npm run build`（首次需在 worktree 内 `npm install` 装一份自己的 `node_modules`）。凡是要**看真实数据**的验证，回主仓做——把 worktree 的改动合并过去再验，或临时从主仓拷一份数据文件进 worktree（用完删掉，别让它留下来混淆）。gitignore 的数据文件本来就该直接在主仓改，它不参与合并。
**判据**：在 worktree 里遇到「某个页面/功能空空如也但代码看着没问题」，先 `ls code/data/` ——目录不在就是这条，不是 bug。

---

## 2026-08-13 新增（Layer 1：LangGraph + chrome-devtools-mcp + DeepSeek 真机验证）

## `MultiServerMCPClient.get_tools()` 每次工具调用各开一个新 session，不是持续同一个浏览器

**现象**：`navigate_page` 导航到目标网址后，紧接着 `take_snapshot()` 拿到的是全新一个空白浏览器实例的 `about:blank`，好像刚才的导航根本没发生。日志里 chrome-devtools-mcp 的启动横幅反复打印多次（每次工具调用一次）。
**真因**：`client.get_tools(server_name=...)` 是个便捷方法，返回的每个工具各自绑定一次性的短生命周期 session——不是一个持续会话贯穿全程。每次 `.ainvoke()` 都在背后重新起一个 chrome-devtools-mcp 子进程 + 全新浏览器，前一次调用做的操作（导航）对这次调用的浏览器毫无意义。
**正确做法**：用 `client.session(server_name)` 作为 async context manager 开一个持续 session，`langchain_mcp_adapters.tools.load_mcp_tools(session)` 把这一个 session 绑定的工具集传给整条 LangGraph 图（或整次自动化流程）复用。全程只应该看到一次 chrome-devtools-mcp 启动横幅。
**判据**：启动横幅打印次数 > 1，或者"刚导航过的页面"取快照却是空白/初始状态，先怀疑这个，不要先怀疑导航本身失败了。

## `langchain_mcp_adapters` 工具调用结果不保证是字符串，可能是内容块列表

**现象**：`AttributeError: 'list' object has no attribute 'lower'`（或 `.strip()`/`.splitlines()` 等字符串方法炸掉），明明工具文档说返回的是文本。
**真因**：`.ainvoke()` 的返回值单个文本内容块时是 `str`，多个内容块时是 `list[{"type":"text","text":...}, ...]`——由底层 MCP 结果的内容块数量决定，调用方不能假设是哪种。
**正确做法**：写一个统一的文本提取函数，先判断类型（`isinstance(x, str)` / `isinstance(x, list)`），list 就拼接所有 `type=="text"` 块的 `text`，任何直接消费工具返回值当字符串用之前都先过这个函数。

## `navigate_page` 只保证导航完成，不保证 SPA 客户端渲染完成

**现象**：跟上面 session 隔离那条表现几乎一样（拿到空壳页面），但这次即使 session 是持续的、正确的同一个浏览器，紧跟导航之后立刻截图仍然可能是空的。
**真因**：`navigate_page` 完成的是浏览器层面的页面加载事件，不是 JS 框架（React/Vue 等）客户端渲染完成的信号，两者之间有真实的时间差。
**正确做法**：导航后不要只截一次图就下结论，轮询（间隔 1 秒左右）直到快照不再是空壳（比如判断行数/是否只有根节点），设一个合理的总超时。
**判据**：跟"session 隔离"那条的区别——如果 session 已经确认是持续同一个（横幅只打印一次），还是拿到空壳，就是这条时序问题，不是 session 问题。

## a11y 快照里的可交互元素可能完全没有 accessible name，按标签关键词匹配会静默漏掉整个字段

**现象**：真机验证一个投递表单，"学校名称""学历""来源渠道"三个必填下拉框完全没有出现在扫描结果里——不报错，就是这些字段像不存在一样。
**真因**：这些控件在 DOM/无障碍树里没有 `aria-label`/关联 `<label>` 等任何可读名称（常见于自定义下拉组件、文件上传输入框），任何"按元素自己的文字标签去匹配"的定位策略对这类元素天然无解，会直接跳过，且没有任何报错信号——是纯粹的静默漏字段。
**正确做法**：给"按标签匹配"策略加一个兜底——匹配不到自己名字的元素，回退取快照里离它最近的、有文字内容的前置"地标"行（一般是紧邻的说明文字/上一个问题的标题）作为它的语义标签，而不是直接丢弃。
**判据**：扫描表单字段的结果数量，跟人工用眼睛数页面上"看起来必填"的项数对不上，先怀疑这个，而不是怀疑分类逻辑判断错了。

## chrome-devtools-mcp 的单选题（radio group）快照没有 radiogroup 包裹节点，朴素按行解析会把一个问题拆成 N 个假字段

**现象**：一个"推荐方式"单选题（选项：无/内推/大使推荐）在解析结果里变成三个各自独立、语义错误的"字段"。
**真因**：问题标题和各选项在快照文本里是**平铺的同级行**，没有类似 `radiogroup` 的父节点把它们关联起来；而且已选中的选项，状态是行尾一个裸的 `checked` 词（不是 `value="..."` 这种属性形式），跟 textbox 判断"是否已有值"的方式完全不同，直接套用会漏判。
**正确做法**：把连续出现的 radio 行按"离它们最近的非 radio 文字地标"聚合成一个逻辑问题；任意一个选项带 `checked` 就整题跳过（已经有答案，不需要处理），不要按选项数量产出字段。
**已由 `tests/test_layer1_agent.py::TestParseEmptyInputElements` 系列用例守门**（`test_already_selected_radio_group_is_excluded` / `test_unchecked_radio_group_surfaces_as_one_field`）。

## DeepSeek 的 API 不支持 LangChain `with_structured_output()` 的默认结构化输出策略

**现象**：`openai.BadRequestError: Error code: 400 - {'error': {'message': 'This response_format type is unavailable now', 'type': 'invalid_request_error'...}}`。
**真因**：`with_structured_output()` 不显式指定 `method` 时，会尝试较新的 OpenAI `json_schema` response_format，DeepSeek 的 chat completions 端点不支持这个模式（虽然文档上支持 function calling）。
**正确做法**：显式传 `method="function_calling"`——这是 DeepSeek 明确支持的、更通用的结构化输出方式，其他 OpenAI-compatible 第三方端点遇到同类报错也应优先试这个。

## Python 脚本被 Bash 工具重定向到文件 + 后台跑时，`print()` 可能完全不出现在日志里

**现象**：后台跑的脚本看起来"卡住了"，反复 `tail` 日志文件内容长时间不变，但进程其实还活着（CPU 使用率低但不是 0），也没报错——像是无声挂起。
**真因**：标准输出连到文件（不是真实终端）时 Python 默认走全缓冲，不是行缓冲，`print()` 的内容可能一直留在内存缓冲区，直到缓冲区写满或进程退出才真正落盘，这段时间外部看日志文件完全看不出脚本的真实进度。
**正确做法**：调试阶段用 `python -u`（无缓冲）跑，或者压根不依赖 print 做实时可观测性——关键中间状态（比如失败时的页面快照）应该主动落盘到一个随时能读的文件，而不是指望 stdout。
**判据**：日志文件长时间原地不动，但对应进程还在（用 `tasklist`/`Get-CimInstance Win32_Process` 查 CPU 时间是不是在涨），先怀疑缓冲，不要先怀疑脚本挂了就去杀进程重跑。

## 需要人工介入（如手动登录）的自动化脚本不能用阻塞的 `input()` 等——如果它是被 Claude Code 的 Bash 工具后台拉起的

**现象**：脚本弹出一个真实浏览器窗口等用户操作，用户能看到窗口、能在窗口里点击/输入，但脚本本身像是永远卡在原地，用户没有任何办法让它"继续"。
**真因**：这个子进程的 stdin 没有连接到用户能敲键盘的地方——用户看到的是浏览器窗口（一个独立进程），不是运行脚本的那个终端会话；阻塞在 `input()` 上等的是后者的输入，没人能提供。
**正确做法**：需要人工完成某个动作（登录等）时，改成轮询检测该动作是否已完成（比如定期重新截图，检查登录态特征是否消失），不要求任何人对着运行脚本的进程本身输入任何东西。

## 后端进程"网络层面活着、进程管理层面够不着"，反复杀进程重启也没用（比"--reload 不触发"更深一层）

**现象**：改完 `server.py`、按标准流程（先查 `/api/workflow/status` 确认无 run 在跑，再杀进程重启）重启后端，接口响应还是旧代码的行为——新加的返回字段完全不出现。反复"杀进程→重启→测试"好几轮都没用，比 `--reload` 不触发那条坑更顽固。
**真因（两层，叠在一起才会看着像"怎么杀都杀不掉"）**：① `netstat` 能看到端口上一个真实、活跃、有正常 ESTABLISHED 连接（含浏览器标签页连过去的连接）的进程在服务请求；但 `Get-Process`/`Get-CimInstance`/`taskkill` 全都说"这个进程不存在"。直接用 Python `os.kill(pid, signal.SIGTERM)` 去杀，报的是 `[WinError 5] 拒绝访问`——不是"进程不存在"的错误。**"拒绝访问" 和 "进程不存在" 是两种完全不同的信号**：前者说明操作系统层面这个进程真实存在，只是当前工具调用所在的会话/权限边界够不着它，不是它真的死了（怀疑与 Bash 工具每次调用可能处于不同进程组/会话隔离边界有关，尤其是很早之前用 `nohup ... & disown` 启动、已经脱离当次 shell 的后台进程）。② 更隐蔽的是：中途尝试"重新起一个新进程"时，新进程其实从头到尾没能绑定成功——`uvicorn` 日志里有 `[Errno 10048] 通常每个套接字地址只允许使用一次`（端口被占用），绑定失败后自己退出了；但因为是后台起的，没人盯着这行日志，表面看着像是"启动成功"，实际上全程还是那个杀不掉的旧进程在原地继续服务所有请求——这就是为什么"重启"之后还是旧代码行为。
**正确做法**：①重启后端后不能只看返回状态码/是否 200，必须实际验证新代码带来的具体行为差异（比如新加的返回字段是否真的出现）；②反复重启都不见效时，去检查"新起的进程"自己的 stdout/stderr 日志里有没有 bind 失败的报错，不要无脑重试同一套杀进程流程；③`Get-Process`/`taskkill` 说进程不存在但 `netstat` 显示它在正常服务流量时，用 `os.kill` 测一下区分"拒绝访问"还是"进程不存在"；④确实杀不掉时，换一个端口另起一个全新实例是最快能把"代码本身对不对"和"旧进程能不能杀掉"两件事解耦验证的办法——代码验证过没问题后，"怎么真正杀掉旧进程"这件事交给用户在他们自己权限更高的终端/任务管理器里处理（重启电脑是最彻底的兜底）。
**判据**：`os.kill` 报 `Access Denied`（而不是"进程不存在"），同时 `netstat` 显示该端口有正常 ESTABLISHED 流量——这个组合就是这条坑，别继续在原地重试同一套杀进程手法。

## 一次重启就能让 W1/W2 全线瘫痪：Windows 保留端口段吃掉 9222，而报错指向的是"浏览器"

**现象**（2026-08-13 真实发生，W1/W2 连续多次触发全失败）：`schedule_log.jsonl` 里 apply/check 全部 `result: error`，`summary` 是 DrissionPage 的

```
浏览器连接失败。地址: 127.0.0.1:9222
提示: 1、用户文件夹没有和已打开的浏览器冲突 2、如为无界面系统，请添加'--headless=new' ...
```

每次固定 32 秒超时。8-09 的冒烟还全绿，中间没有任何相关代码改动。

**为什么极易误诊**：DrissionPage 这段提示把人往"浏览器/用户文件夹冲突"引，于是自然会去杀残留 Chrome、删 LOCK、怀疑 Chrome 自动升级（本机确实 8-12 升到了 151）。**这些全是错的方向**，而且每一步都会"看起来有点道理"：
- 杀光所有占用 profile 的 Chrome 之后**依然复现** → 排除残留进程/锁文件；
- 换全新干净 profile、换 `--headless=new`/`old`/有头三种模式**全都复现**；
- 换 Edge 151、换 Playwright 自带的 Chromium 145 **也全都复现** → 这一步很容易得出"Chromium 上游把 TCP 远程调试禁了"的错误结论。**实际上是我随手挑的验证端口 9231/9241/9251/9261/9271 全都落在同一个保留段里**，属于用错误的实验证实了错误的假设。

**真因**：Chrome 自己的 stderr（`--enable-logging=stderr --v=1`）才给出唯一有效信号：

```
ERROR:net\socket\tcp_socket_win.cc:530] bind() returned an error: (0x271D)
ERROR:content\browser\devtools\devtools_http_handler.cc:311] Cannot start http server for devtools.
```

`0x271D` = `WSAEACCES(10013)`，是**操作系统拒绝 bind**。Windows 的 Hyper-V/WinNAT 会在**每次开机时动态保留若干 TCP 端口段**，落在段内的 bind 一律失败：

```
netsh interface ipv4 show excludedportrange protocol=tcp
      9211        9310       ← 9222 在里面
```

**而 Chrome 遇到这个错不会退出**——它照常把浏览器跑起来，只是没有调试端口，于是 DrissionPage 干等到超时。**"进程活着"因此完全不能作为"启动成功"的证据**：判据是 profile 目录里有没有生成 `DevToolsActivePort` 文件，以及 `curl http://127.0.0.1:<port>/json/version` 通不通。

**关键性质：保留段每次重启都会挪。** 这意味着 ①故障来得毫无预兆，不需要任何代码或 Chrome 变更，重启一次就可能中招；②**任何硬编码端口都不是安全的**，包括换一个"看起来没人用"的数字。

**正确做法**：启动前用 `socket.bind()` 探一个本机真能绑上的端口（普通 bind 复现的正是 Chrome 即将做的那次检查，保留段会自然被过滤掉），已实现为 `services/browser_context.py::pick_debug_port()`，`open_browser` 与 `resume_tailor.render_html_to_pdf` 共用这一份——**端口选择只能有一份实现**，否则就是"同一外部契约散多处必漂移"的又一例（`render_html_to_pdf` 原本硬编码 9920，纯属运气好没落进保留段）。

**故障窗口（用证据钉准，别凭感觉说"多久没发现"）**：最后一次真正跑完的 run 是 **8-12 23:00**（check，352s）→ **8-13 12:56 重启**（`(Get-CimInstance Win32_OperatingSystem).LastBootUpTime`，保留端口段就是在这一刻重新分配的）→ **8-13 15:19 第一次失败**，也正是重启后第一次真跑。**故障是重启那一刻产生的，2 小时 23 分后被首次触发**——不是"停摆了好几天"。冒烟自 8-09 起就没再跑（`schedule.yaml` 的 `selfcheck.enabled: false`）是另一件事，两者不要混成一句话说。

## `schedule_log.jsonl` 里 71% 的 "success" 是幻影，判据是 `duration_seconds > 0`

**现象**：想回答"这个功能上一次真的正常是什么时候"，翻 `schedule_log.jsonl` 会看到密密麻麻的 `result: "success"`，于是得出"一直好好的"的错误结论。

**真相**：2631 条记录里 **1883 条是 `duration_seconds: 0` 且 `summary: "ok"` 的 `trigger_type: manual`**，它们**没有对应的 run 日志**——即 `logs/runs/` 里根本没有那次运行的记录，pipeline 压根没跑。交叉验证很干净：8-13 当天 `logs/runs/` 有 11 条 run 记录，而 `schedule_log` 当天 `duration>0` 的条目也正好 11 条，**1:1 对上**；剩下那些 dur=0 的 success 一条都对不上。

**为什么会误导人**：真跑和空转写进的是**同一个日志、同一个 `result` 字段**，只有 `duration_seconds` 能区分。真实的 W1/W2 跑一次是几十秒到几百秒（`round(time.monotonic() - start_time)`），**不可能是 0**；而且这些幻影条目经常成对出现在同一秒（`apply` 和 `check` 同一时刻各一条），真跑绝无可能。

**判据**：读这个日志找"上次真的成功"，**必须先过滤 `duration_seconds > 0`**，或者直接去 `logs/runs/`（注意是**仓库根**的 `logs/runs/`，不是 `code/logs/runs/`——`run_diagnostics.RUNS_DIR` 用的是 `parent.parent.parent`）交叉验证。

**注意**：`logs/runs/` 才是 run 的权威数据源（[[regression-diagnostics]] 已记"JSONL 是完整数据源"），`schedule_log` 只是触发流水账，两者定位不同——问题在于它没有把"接受了请求"和"真的跑完了"区分开。

## 浏览器 agent 不肯收尾：症状是 GraphRecursionError，真因是"答案只能最后一次性给出"

**现象**（2026-08-14 Layer 1 自主选岗真机跑，连撞两次）：agent 在招聘站上正确地点了「深圳」「产品」「研发」「日常实习」几个筛选器，每次截图后都说"让我分析当前页面的岗位"，然后**又去点下一个筛选器**，一路撞到 `GraphRecursionError: Recursion limit of 52 reached`。

**为什么容易误诊成 prompt 不够严**：第一反应是加约束。加了"最多点 N 次筛选器"之后，它确实不碰筛选器了——**改成在翻页上打转**：2→3→4→2→4→2……，每次仍然说"让我分析当前页面的岗位"然后翻页。**换个地方犯同一个错，说明不是预算不够。**

**真因**：结构问题不是措辞问题。当"答案必须在最后一次性输出"时，模型永远可以认为"我还没看够"，于是每一轮都选择继续探索而不是收尾——尤其是能力较弱的模型（这里是 DeepSeek）。约束只是把打转的位置从一个维度挪到另一个维度。

**正确做法**：**把结果收集外置成一个工具**（`record_job`），让 agent 边看边记，而不是憋到最后。三个收益：①每记一条就有一次明确的进展信号，收尾变成自然行为；②即使最后仍然超限，已记录的部分**不再全丢**（在 `find_jobs` 里 catch `GraphRecursionError` 并采用已记录结果）；③不必把所有候选一直留在上下文里，正好避开小上下文模型最吃不消的用法。改完当次真机就干净收尾（EXIT=0，6 个岗位全部经独立抓页面核对无误）。

**顺带两条**：
- **agent 循环必须自带逐步追踪**，否则失败时只有一个 `GraphRecursionError`，完全不说明它在哪兜圈子。第一次真机跑的 226 行日志里除了 MCP 噪音和 traceback 什么都没有。追踪实现在 `agent_runtime.run_agent`（用 `astream` 逐条打工具调用与结果长度）。
- **Windows 上 stdout 重定向到文件默认走 GBK**，追踪里的中文岗位名会被写成不可逆的替换字符，日志等于白打。`scripts/run_layer1.py` 启动时强制 `sys.stdout.reconfigure(encoding="utf-8")`。

## 2026-08-16 新增（m1/m2 接线检查）

## 后端加一个 workflow 而前端 `WorkflowId` 没跟着加，队列页会让**整个 SPA 白屏**

**现象**：批准一个 Checkpoint 1 岗位之后，打开「队列」页整页空白——不是那一块不显示，是整个 Dashboard 没了，控制台一句 `Cannot read properties of undefined (reading 'color')`。

**真因**：`Queue.tsx` 的 `WF_META` 是 `Record<WorkflowId, …>`，而 `WorkflowId` 只写了 `'w1' | 'w2' | 'w3'`。后端的 `VALID_WORKFLOWS` 早在 v2.24.0 就加了 `m1`/`m2`，队列快照原样把它们发给前端，`WF_META['m2']` 于是是 `undefined`。**项目前端没有 ErrorBoundary**，React 18 遇到渲染期异常会卸载整棵树——所以一个查表失败的后果是全站白屏，不是局部空白。

**为什么容易漏**：`workflow_queue.py` 顶部那条"加新 workflow **必须同时改三处**"的清单本身**漏了第四处**（前端类型）。照着清单做也会踩。而 tsc 只保证 `Record<WorkflowId, …>` 的键齐全，**保证不了 `WorkflowId` 本身没漏后端的某个 workflow**——漏掉的恰恰是这一层。

**触发路径一点都不冷门**：Checkpoint 1 一批准就自动入队 `m2`（`server.py::_enqueue_fill_jobs`），之后任何人打开队列页都会撞上。

**已由 `tests/test_multisite_wiring.py::TestWorkflowIdContract` 守门**：它读 `api/index.ts`、把 `WorkflowId` 联合类型解析出来跟后端 `VALID_WORKFLOWS` 比。这是个跨语言契约，两边各写一份必然漂移——判据同「同一外部契约散多处必漂移」。

## 一个开关跨了进程边界，起点打印它、终点不读它，中间没有任何报错

**现象**：`python scripts/run_layer1.py --search-url ... --category 开发:5 --max-pages 3` 跑完，日志明明白白打了一行「本站生效名额: {'开发': 5}」，实际跑的却是 `profile.yaml` 的默认名额和默认 8 页。

**真因**：默认路径（不加 `--direct`）是把任务**排进 Dashboard 队列**由另一个进程执行的。`_enqueue_via_dashboard(args, resume_path, quotas)` 收下了 `quotas` 参数**却从不放进请求 body**，队列侧的 `_run_multisite_select` 也不读 `max_pages`——两头都"看起来接住了"，中间那一段静默断掉。函数签名里那个用不到的参数是唯一的痕迹，而它长得完全像正常代码。

**为什么特别坑**：那行打印发生在**排队之前的本进程**里，它打印的是"我算出来的名额"，不是"实际生效的名额"。看着像验证过了。

**判据**：**一个参数只要跨了进程/队列边界，验证它生效必须在终点做**——看接收方拿到的值，或者在终点打日志。起点的打印在这类缺陷里恰好总是对的。

**已由 `tests/test_multisite_wiring.py::TestSelectPassthrough` 守门**（断言 run_layer1 实际收到的 kwargs）。

## 追踪日志的一句 `print` 能打死整条 run —— 而且只在某一个入口炸

**现象**（2026-08-16 首次从 Dashboard 触发 m1）：agent 正常跑了十几步、已经 `record_job` 记下 8 个岗位，然后整条 run 失败，**库里一条都没有**。

**真因**：agent 说了一句带 ✅ 的话，`agent_runtime._trace` 的 `print` 在 GBK 的 stdout 上抛 `UnicodeEncodeError`，异常从 LangGraph 节点里冒出去打死了 `find_jobs`——于是下游的 `write_pending_jobs` **从来没执行**，内存里那 8 条记录随异常一起蒸发。

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'
  agent_runtime.py:134  print(f"  [{step:02d}] 说: {text}")
  During task with name 'find_jobs'
```

**为什么以前从没撞到**：`scripts/run_layer1.py` 开头一直有 `sys.stdout.reconfigure(encoding="utf-8")`，而**从 Dashboard 跑走的是 uvicorn 进程，拿不到那一行**。同一件事两份实现、其中一份漏了——CLI 那条路径被保护着，新加的控制台入口没有。

**判据（比这个具体 bug 更值钱）**：**任何"进程级"的设置——stdout 编码、locale、信号处理、warnings 过滤——如果只写在某一个入口脚本里，换个入口就静默失效。** 加新入口时要专门问一遍："老入口在 main 之前做了哪些进程级设置？" 这类设置不会在代码里表现为被调用的函数，grep 调用方是找不到它们的。

**两道修复**（都做了，v2.24.8）：
1. 收敛进程级编码修复到 `services/console_utf8.force_utf8_stdout()`，CLI 与 uvicorn 两个入口共用同一份。
2. **日志不该有杀死流程的权力**：agent 追踪改用 `safe_print`（写不出去就退化成 backslashreplace，绝不抛）。第 1 条修好之后第 2 条仍然必要——换个终端、换个重定向目标，照样可能有写不出去的字符。

**这次能查出来是因为**观测层刚接上：run 日志里明明白白是 `find_jobs failed` + 那句报错 + `run_end failed`。在此之前同样的失败只会表现为"跑了几分钟，库里啥也没有"。

## 简历列表和导出存档是两个互不相干的列表，于是没人知道哪一份"真的能发出去"

**现象**（2026-08-16）：m2 连投三个岗位都"成功"了，传的却是一份**比简历最后修改还早 10 分钟**导出的 PDF——内容是旧的，全程没有任何提示。

**真因**：多站点投递只能用**已导出的 PDF**（后端不渲染，A4 排版的唯一实现在前端 `resumeHtml.ts`），而界面上：
- 「已保存简历」列表显示 slug / 名字 / 目标岗位 / 激活状态
- 「最近生成」列表显示导出的文件名

**两个列表之间没有任何连线**。于是"这份简历有没有 PDF""那份 PDF 是不是比简历还旧"这两个决定能不能发出去的事实，在界面上根本不存在。而 m2 当时的选法是 `latest_export_path()`——"最近导出的那份"，一个**跟岗位毫无关系的时间属性**。

**判据**：**「有没有文件」和「能不能用」是两件事。** 只要一份产物是从别处生成、又要被自动流程消费的，就必须显式表达"它是否仍然对应当前的源"。这里的具体形式是三态：
- `ready`   有 PDF，且不早于简历最后修改
- `stale`   有 PDF，但简历之后改过——**发出去的是旧内容**
- `missing` 从没导出过

只判断"有没有文件"会把 `stale` 报成可用，那正是这次踩的。

**顺带一个同源问题**：存档文件名原本只带简历名字，而真实数据里有两份都叫「游戏岗版」——一旦两份都导出就再也分不清谁是谁。现已改为 `{ts}_{slug}_{name}.pdf`；老存档按名字兜底匹配，但**名字重复时直接放弃**（宁可报"没有"让人重导一次，也不要猜错一份发进企业系统）。

**已由 `tests/test_resume_pdf_status.py`（7 例）与 `tests/test_m2_resume_gate.py`（5 例）守门。**

---

## 2026-08-17 新增（Checkpoint 2 表单截图）

## `fullPage: true` 拍出来仍然只有视口那么高——因为在滚的不是文档

**现象**：Checkpoint 2 的表单截图三张尺寸一模一样（1209×1269），内容在「邮箱」处齐刷刷截断，
审批人要核对的「学校名称」「起止时间」一个都看不见。代码里 `fullPage=True` 明明传了。

**真因**：`fullPage` 量的是 `max(documentElement.scrollHeight, body.scrollHeight)`
（chrome-devtools-mcp → Puppeteer → CDP 都是这个口径）。而这个站把整张表单放进了一个
内部滚动容器（`section.atsx-layout`，`overflow-y:auto`，clientHeight 1269 / scrollHeight 2403），
`body` 被写死 `height:1269px` ——**文档本身不滚动，所以"整页"就等于视口**。参数是对的，
量的对象不对。SPA 里 `html,body{height:100%;overflow:hidden}` + 内层 scroller 是极常见布局，
所以这不是某个站的怪癖。

**为什么骗了这么久**：截图看起来完全正常——顶部是页头、底部是「提交简历」按钮栏（`position:fixed`
的悬浮条正好停在视口底部），一张"到底了"的完整页面。没人会去数它高多少。

**判据**：同一份代码对**不同页面**拍出**完全相同的像素高度**＝它拍的是视口，不是内容。
一行 `evaluate_script` 就能定死：`documentElement.scrollHeight` 是否等于 `window.innerHeight`。

**正确做法**：截图前临时注入样式，把 `html,body` 和**所有真正在滚的容器**
（判据是 `overflowY ∈ {auto,scroll,overlay}` 且 `scrollHeight > clientHeight`，
**不是**写死某个 class 名）解成 `height:auto;overflow:visible`，让文档自己变长，再 `fullPage`；
`finally` 里一定还原。顺带把 `position:fixed` 改 `absolute`——否则整页截图里那种悬浮条会停在
原视口底部，正好压掉一整行字段（真机确认它盖住了「您从哪些渠道了解到该岗位招聘信息？」）。

**连带的判据**：解锁失败就**别拍**。半截图比没有截图更糟——审批人看到一张图会以为
"表单就这些字段"，而真正要核对的正好在被裁掉的下半页。已由
`tests/test_form_screenshot.py::TestNoMisleadingHalfShot` 守门。

---

## 2026-08-17 新增（Checkpoint 2 字段扫描）

## 说明文字比字段名更靠近输入框，于是它成了字段名

**现象**：审批页上出现一个叫「最多可选 2 个城市」的字段；而真正的字段「意向城市」不见了，
连它的必填星号也一起丢了（被记成选填，于是连值都不会生成）。

**真因**：a11y 树是平的，字段名 → `*` → 说明文字 → 输入框。取"离输入框最近的那行文字"当字段名，
拿到的必然是说明。**已有的那道闸卡的是长度**（>12 字且不是问句 = 说明文字），
而这行只有 9 个字，光明正大地走过去了。

**判据不是长度，是位置**：星号之后、输入框之前的文字是说明。所以星号一落下就上闩，
闩住期间不再接受新地标，输入框来了才解闩（顺带把必填标记一起吃掉——那个星号是它的，
漏给下一个字段的表现是「一个选填项被标成必填」）。

**唯一能压过闩的是"这行后面紧跟星号"**——那是字段名最硬的信号。没有这条例外，
「手机号码 `*` +86 138-… 邮箱 `*` 输入框」这种版式会翻车：手机号是纯展示、没有输入框，
闩永远等不到解，于是「邮箱」被闩住，输入框最后认领到的是手机号那一段。
守门测试 `test_field_scan_quality.py::TestDisplayOnlyFieldDoesNotSwallowTheNextLabel`。

## 「这个节点没有 value」≠「这个字段没填」

**现象**：整张表单其实早就被简历解析填好了，系统却报了 5 个"空字段"，
其中「学校名称」「起止时间」页面上明明有值。LLM 对着它们编了两句填写说明当答案
（「请填写您的学校名称（例如：…）」），而这些值如果真被填回表单，覆盖掉的是正确内容。

**真因**：复合控件的值不在被扫描的那个节点上。两种形态，都在同一张表单上：

| 控件 | 值在哪 | 被扫描的节点长什么样 |
|------|--------|---------------------|
| 下拉框 | **子节点**：缩进更深的 `textbox value="甲大学"` | 外壳 `combobox` 自己没有 value |
| 日期 | **兄弟节点**：平铺的 `StaticText "2019" "-" "09"` | `textbox`（永远是空的） |

**日期控件的两种状态正好能分开**：填好了是数字碎片（`2019`/`09`），没填是格式占位符（`YYYY`/`MM`）。
所以"自上一个地标以来见过纯数字碎片"＝后面那个无名输入框已经有值。

**判据**：扫描表单空字段时，"这一行没有 value" 是最弱的证据。至少要再看两处——
**子树里有没有 value**、**前面有没有平铺着已选好的值**。

## LLM 分类的 taxonomy 缺一档时，兜底桶的动作会被当成"正确答案"

**现象**：真机跑出来的五个字段 **kind 全是 `open_question`**，包括「学校名称」这种纯事实字段。

**真因**：kind 只有 `demographic | open_question | government_id` 三档，而 demographic 的判据是
"能在 personal_info 里找到 key"——那里只有 5 个 key。于是凡不在这 5 个里的事实性字段
（学校、城市、日期、公司名）全部按排除法掉进 `open_question`，
而 `open_question` 的指令是**"生成一段候选文本"**。机器不是想编，是没别的地方可去。

**判据：兜底那一档的动作是什么？** 如果是"生成/猜测"，那这套 taxonomy 就是在结构上鼓励编造，
调 prompt 没用——得补桶（这里加了 `unknown_fact`：事实性字段但资料里没有 → 留空请人填）。
补桶是 prompt 的事，兜底是代码的事：`_enforce_no_invented_values` 保证只有 `open_question`
带得出生成的值，prompt 不听话的那一次值也漏不出去。

## 「重启后端」按钮在没带 `--reload` 起的进程上静默失效，还回报成功

**现象**：点 Dashboard 的「重启后端」，界面无报错、按钮转一圈就好了，但后端跑的还是旧代码。
表现出来是「新加的端点 404」「改的逻辑没生效」，而这两个症状跟"代码写错了"长得一模一样。
2026-08-17 撞到时，`/api/multisite/stages` 一直 404，一度让人怀疑新代码有问题；
实际是监听 8765 的进程**七小时前**起的，从没换过。

**真因**：`/api/dev/restart` 的全部实现是 `Path(__file__).touch()` —— 它靠 **uvicorn 的
`--reload` 监听文件变化**来完成重启。进程不是用 `--reload` 起的时候，touch 就是纯粹的
无操作；而端点**照样返回 `{"status": "restarting"}`**。一个确信无疑的成功响应，对应一件
没发生的事。

**怎么确认后端到底是哪一版**：不要看进程在不在、也不要看按钮转没转，**问它要一个只有新代码
才有的东西**：

```bash
curl -s http://localhost:8765/api/<某个新加的端点>     # 404 = 旧代码
```

再看进程的真实身份（创建时间 + 启动命令里有没有 `--reload`）：

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen | Select OwningProcess
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Select ProcessId, CreationDate, CommandLine
```

**正确做法**：起后端一律带 `--reload`，否则那个按钮是装饰品：

```bash
cd code && python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload
```

**判据（比这个具体案例更值钱的那一句）**：**一个"执行动作"的端点，如果它的成功响应不依赖
动作真的发生，那它迟早会骗人。** `dev_restart` 返回的是"我已经 touch 了文件"，而调用方
以为读到的是"后端已经重启了"。同类反例见 PITFALLS 里 `upload_resume_file` 那条
（点完确定就报 ok、不验证送达）和 `schedule_log.jsonl` 那条（"接受了请求"与"真的跑完了"
混成同一个 success）。

**遗留**：这个按钮目前既不检测自己有没有生效，也不告诉调用方"我依赖 --reload"。
要修的话，最小改法是让它回报**它实际做了什么**（touched file）而不是**它希望发生什么**
（restarting），并在响应里带上进程启动时间，让前端能对比出"重启到底有没有发生"。

## 补丁脚本里的 `\b` 会静默变成退格符（`\s` 会警告，`\b` 不会）

**现象**：用补丁脚本往 `.py` 里写一条正则 `r"^.*\bRootWebArea\b.*$"`，落盘后**永远匹配不上**。
`grep` 出来看着像「只是少了 `\b`」——因为退格符在终端里把前一个字符吃掉了，肉眼分辨不出来。

**真因**：补丁脚本里那段内容写在**非 raw** 的三引号串里。Python 对无效转义（如 `\s`）只发
`SyntaxWarning` 并原样保留，所以 `\s` 侥幸活了下来；但 **`\b` 是合法转义（退格，0x08）**，
它一声不吭地变成了一个真正的控制字符。写进文件的是 `^.*\x08RootWebArea\x08.*$`。

**为什么特别难查**：
- 没有任何警告（`\s` 那几行反而报了 SyntaxWarning，把注意力引到了错误的方向）
- `grep` / 终端输出里退格是不可见的，还会吞掉前一个字符
- 测试只表现为「匹配不上」，看起来像正则写错了逻辑

**判据**：补丁脚本写出来的代码「看起来完全对但行为不对」时，先查有没有**不可见控制字符**：

```python
print(repr(pattern))              # repr 会把 \x08 显示出来
chr(8) in text or chr(12) in text # 退格 / 换页
```

**正确做法**：补丁脚本里承载代码内容的字符串**一律用 raw 或双写反斜杠**
（`r'''...'''` / `\b`）。同一族的老坑：`'\u%04x'` 写在 heredoc / `python -c` 里会被当转义
（已踩三次），所以含 `\n` / `\u` / 中文的补丁脚本一律写成独立 `.py` 文件再执行——
但**写成文件还不够，文件里那个字符串也得是 raw**。

---

## 2026-08-19 新增（m1 首次跑新站点 join.qq.com）

## `--reload` 进程确实带了 `--reload`，改的模块照样不生效，而且**没有任何 404 之类的迹象**

**现象**：改完 `multisite/safe_tools.py` + `multisite/observability.py`，直接跑 m1，
跑出来的行为跟改之前一模一样。

**与上一条 `--reload` 坑的区别（别混为一谈）**：
- 上一条改的是 `server.py` **新增端点**，症状是 404——**有信号**，一 curl 就知道。
- 这一条改的是被 server 间接 import 的**普通模块**，函数签名没变、端点照常 200。
  症状是「跑出来的行为还是旧的」，而旧行为本身也是合法输出，**没有任何东西会报错**。
  比 404 危险得多：会让人以为「修了但没用」，转而去改一个根本没上场的实现。

**判据（唯一可靠的一条）**：比对 **worker 进程的启动时间** 和 **你改的文件的 mtime**。

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Select-Object ProcessId, ParentProcessId, CreationDate,
    @{n='Cmd';e={$_.CommandLine.Substring(0,[Math]::Min(70,$_.CommandLine.Length))}} |
  Format-Table -AutoSize
Get-Item <改过的文件> | Select-Object LastWriteTime
```

worker 的 `CreationDate` 早于文件 `LastWriteTime` = **没重载**，无论命令行里有没有 `--reload`。

注意**按 `CommandLine -like '*uvicorn*'` 过滤只会捞到 reloader 父进程**，真正跑代码的 worker
是它的子进程，命令行长这样：`python -c "from multiprocessing.spawn import spawn_main..."`。
只看父进程会得出「进程是新的」的错误结论——父进程本来就不重启。

**正确做法**：真机跑之前先做这一次比对（一次 m1 要四分钟，不值得赌）。没重载就
kill 掉**父子两个** PID 重起；kill 前必须先查 `/api/workflow/status`。

## agent 会把同一个失败动作原样重复到步数耗尽，而它的「思考」全程看起来很正常

**真机（2026-08-18，m1 首次跑 join.qq.com）**：要勾「2027校园招聘」筛选项，
`click({"uid":"8_30"})` 返回
`Error: Failed to interact with the element ... did not become interactive within the configured timeout`。
它于是重新截图、再点**同一个** uid、再失败……**连续 29 次完全一样**，四分钟烧光 60 步预算，
`find_jobs` 报 partial、found=0，一个岗位都没找到。61 次工具调用里 **59 次是废动作**
（29 次失败 click + 30 次 take_snapshot 严格交替）。

**为什么读日志时容易被骗过去**：它的 think 每一轮都写得很像样，甚至有自省——
"Let me take a fresh snapshot to get current uids"——然后照样点回旧 uid。
**逐条读单轮记录完全看不出问题，只有把整段并排看才看得出是同一个循环。**

**判据**：run 日志里对 `(工具名, 参数)` 做频次统计，出现两位数的就是循环：

```python
calls = Counter((c["name"], json.dumps(c["args"], sort_keys=True))
                for r in agent_records for c in r.get("calls") or [])
```

**修法（v2.27.0）**：`safe_tools.make_repeat_failure_guard` —— 同一工具 + 同一组参数
**连续**失败 2 次后，第 3 次不执行，返回一段告诉它「换个办法」的文本。
在 `build_agent_toolset` 里逐个工具包上（循环是 agent 的行为模式，不是 click 的属性）。
两条不能省的边界：**成功即清零**（否则误伤正常重试），**只认开头的 `Error`**
（页面正文里出现 "Error" 是常事，全文匹配会把 `take_snapshot` 锁死 = 挖掉 agent 的眼睛）。

## 阶段修好了如实报告，**整轮 run 还在替它圆谎**

同一轮日志里：`step find_jobs partial {"truncated": true}` 紧跟着 `run_end done`。

阶段级 `partial` 是上一版刚修的（步数耗尽不许报 successful），但 `run_scope` 收尾
写死了 `done`。而**人先看到的恰恰是 run 那一行**——运行列表、诊断器、第 1 层全链视图
读的都是它。一个绿色的 `done` 会让人根本不去展开看里面那个黄色的阶段。

**普遍判据**：修「子层级不许谎报」时，**顺着往上问一层：父层级的状态是从哪来的？**
如果父层级是写死的常量，那这个修就只做了一半。整轮的状态不能比它最差的那一步更乐观。

## 「点击成功 + 页面一字未变」= 多半开在新标签页里，不是点击没生效

**现象**：`click` 返回 `Successfully clicked on the element`，紧接着 `take_snapshot`
拿到的快照与点击前**完全相同**（字符数都一样）。看起来像点空了。

**真因**：站点用 `window.open` 打开详情页——**新页面在第二个标签页里**，
而 `take_snapshot` 只返回**当前选中的那一页**。真机（join.qq.com，2026-08-19）：

```
点 uid=1_71 'AI全栈工程师'  →  Successfully clicked on the element
## Pages
1: 岗位投递 | 腾讯校招 (https://join.qq.com/post.html) [selected]
2: 岗位详情 | 腾讯校招 (https://join.qq.com/post_detail.html?postid=1282707398326592512)
```

**为什么这个坑特别毒**：它同时骗过人和 agent。人看日志会得出「这个站的卡片点不动 /
没有链接」的结论（我就下过这个结论并写进了文档，被用户手点一次直接推翻）；
agent 则完全收不到任何反馈信号，于是原地重试 → 死循环。

**判据**：`navigate_page` 的返回**带 `## Pages` 清单**，`take_snapshot` 不带。
怀疑开了新标签页时，调一次 `navigate_page` 或 `list_pages` 就能看见。

**连带**：`list_pages` / `select_page` / `close_page` 当时不在 Layer 1 白名单里
（v2.27.0 已加）。**加工具前先确认它不可能提交表单**——这三个不碰
`make_guarded_click` 守的那条线，`evaluate_script` / `fill` / `press_key` 仍然一个不给。

**更一般的一条**：判断「某个站点结构上支持不支持某种操作」时，**只看 a11y 快照会漏**。
快照是 agent 的视野，不是站点的全部——940 个岗位在快照里全是 `StaticText`、没有一个
link 节点，但每张卡片点进去都有独立 URL。**「不在表示里」不等于「不存在」。**

## 上下文裁剪按「工具名」判，会把错误反馈整段删掉——表现是 agent 死循环，看着像模型太笨

**真机（2026-08-19，join.qq.com，连着三轮 found=0）**：agent 对同一个 uid 连点 29 次。
我先后判成「筛选器点不动」「站点结构不支持」「deepseek-chat 能力不行」，**三个都错**。

**真因在我们自己的代码里**。`agent_runtime.trim_stale_snapshots` 为省 token 把历史大块
工具输出换成占位符，判据是 `msg.name in _BULKY_TOOLS`，而那个集合里**含 `click`**；
同时 `kept_recent` 是**一个全局开关**，只保留最近的那一条 bulky 消息。

agent 的实际节奏是「点击 → 截图 → 点击 → 截图」，做决定时最近的 bulky 消息**永远是快照**，
于是**每一条点击结果都被换成了占位符**：

| 模型实际收到 | 本该收到 |
|---|---|
| `[已省略：较早的页面快照，页面此后已经变化…]` | `Error: ... did not become interactive` |
| 同上 | `BLOCKED: 你已经用同样的参数失败 2 次…` |

**它从来没看见过自己失败过。** 每轮醒来只有 system prompt + 自己过去的分析 + 一张全新快照
+ 一堆「较早的快照」。从它的视角它压根没试过 → 重新推导 → 同样的结论 → 再点一次。
**循环是完全理性的**，换任何模型都一样。占位符那句「页面此后已经变化」还在主动误导：
页面一字未变，它被连骗 28 次。

**为什么单测没拦住**：旧 fixture 用 `"SNAPSHOT-1"` 这种十来个字符的桩当快照，
**在一个真实世界里不存在的输入上做断言**。真机快照 6613 字符、点击返回 114/206 —— 差一个
数量级，而这个数量级差正是判据该用的东西。

**修法**：判据改成**输出大小**（>2000 字符），删掉 `_BULKY_TOOLS`。
该砍的性质是「这段输出很大且描述的是已经过时的页面」，不是「它出自哪个工具」。
按名字判还有维护陷阱：工具面一变就得同步改那个集合，而**漏改不会有任何报错**。

**修完的对照（同一个站、同一个模型、只改了这一处）**：

| | 修前 | 修后 |
|---|---|---|
| agent 轮次 | 122（步数耗尽） | 35（自己收尾） |
| 同参数重复调用 | 28–29 次 | **0** |
| 筛选器 | 一个都没点动 | **生效，岗位 940 → 243** |

**通用判据**：agent 在原地重复同一个动作时，先问 **「它到底看不看得见上一次的结果？」**
把喂给模型的消息真的打印出来看一眼，再谈模型能力。**任何「为省 token 而删东西」的机制
都要先回答：删掉的里面有没有反馈信号。**

---

## 2026-08-19 新增（计划 A 的 SDD 执行中挖出）

## 用「玩具桩」写的单测，会把真实世界唯一会出错的形态测没了

**现象**：一个函数的单测五条全绿、任务级评审也通过，但拿**真实数据**跑一遍立刻错。

**真机（2026-08-19）**：`job_url_offline` 的 `link_in_row` 分支从快照开头一路扫到锚点，
取"最近见到的带 url 的 link"。它的单测用了一份 **3 行的假快照**，里面唯一的链接恰好就是
那一行自己的链接，所以永远取对。而真实快照里锚点之前**永远**有导航栏和页脚链接——
最终评审拿仓库自带的真实 fixture 一跑：**10 个岗位行全部返回同一个页脚链接
`join.qq.com/about.html`**。

**更毒的是下游**：轻校验的判据③「取 URL 的方式仍然成立」只看 `startswith("http")`，
而 `about.html` 以 http 开头 → 校验返回 `(True, '手册仍然成立')`。**一份取 URL 方式完全
错误的手册会被判绿**，然后抓回 10 条指向同一个页面的岗位记录，去重后还会把 9 个岗位吃掉。

**判据**：同一个模块里，**一部分函数用真实数据测、另一部分用玩具桩测**，就是这个坑的温床。
玩具桩测出来的"绿"只覆盖了你想象中的形状。

**正确做法**：凡是解析**外部系统输出**（HTML/a11y 快照/API 响应/日志）的函数，
单测必须至少有一条用**真实尺寸、真实结构**的样本。同一族函数不要一半真一半假。
（同族老坑：上下文裁剪的单测拿 `"SNAPSHOT-1"`（10 字符）当快照，让一个把点击结果整段
删掉的 bug 溜过了单测——见本文件「上下文裁剪按工具名判」那条。）

## 「拿集合做基准做差集」的逻辑，在基准解析失败时会静默反转

**现象**：一个"找出新出现的东西"的函数，在上游返回错误时会把**所有已存在的东西**都认成新的。

**真机（2026-08-19）**：`job_url_online` 点开岗位卡片后要找出"新开的那一页"：

```python
before = {url for ... in _parse_pages(await list_pages())}   # 基准
after  = _parse_pages(await list_pages())
fresh  = [(idx, url) for idx, url, _ in after if url not in before]
idx, url = fresh[0]
await close_page(pageIdx=idx)
```

`list_pages` 返回的若不是可解析的页面列表（**而 chrome-devtools-mcp 把执行错误当正常内容
返回，`isError=False`**——本仓库 `safe_tools.py` 的注释早就写死了这个事实），
`before` 就是**空集** → `after` 里每一页都算 fresh → `fresh[0]` 正是索引 0 的**列表页** →
**把列表页 URL 当成岗位 URL 返回，并且把列表页关掉**（后续每个岗位全部失败）。

**判据**：任何 `新 = 全集 - 基准` 的写法，问一句：**基准为空时会发生什么？**
如果答案是"全集都被当成新的"，而基准又来自一个可能失败的外部调用，那就是这个坑。

**正确做法**：
- 基准为空时 **fail fast**（本例：页面数永远 ≥ 1，空集只可能是工具出错）
- 用**稳定标识**（索引/ID）而不是内容（URL/文本）做差集——内容可能重复，也可能因解析失败而缺失
- 上游已经给了更可靠的信号就用它（本例 `_parse_pages` 一直在解析 `[selected]` 标记，
  **但三个调用位上一次都没读过**）

## 闭集枚举里混进「声明了但会炸」的取值，一定会被写进 prompt

`row_split` 的闭集含 `container_per_row`，`from_dict` 接受它，但执行器一碰就
`NotImplementedError`。

**为什么危险**：让 LLM 填结构化字段时，prompt 几乎一定会把**枚举的全部取值**列给它挑。
挑中未实现的那个 = 运行中途崩溃，而且绕开了「所有执行器都不匹配 → 诚实报搞不定」
这个专门设计的出口。

**判据**：**闭集的全部意义是「过了校验就代表代码能执行它」。** 做不到这一点的取值不该在闭集里。

**正确做法**：设计空间（`ROW_SPLITS`）与已实现集（`IMPLEMENTED_ROW_SPLITS`）分开，
入口校验按后者拒绝，错误信息写明"还没有对应的执行器"。两个常量放在一起互相指向，
避免实现了却忘了放开。
