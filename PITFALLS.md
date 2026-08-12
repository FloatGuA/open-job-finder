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
**注意**：编辑器的自动转义也只覆盖 JSX 文本节点，JS 对象字面量/常量/JSX 属性串都不转。

## 用 Edit 工具直接写 \uXXXX 会被 JSON 解码回中文

**现象**：明明写的是 `\uXXXX`，落盘却是裸中文，于是又踩上面那两个坑。
**真因**：Edit 的参数走 JSON，`\uXXXX` 在解析时就被解码了。
**正确做法**：用脚本文件把内容转成 ASCII 再落盘，然后校验 `nonascii == 0`。
**已第三次踩到**，固化为 `esc_any.py`。

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
