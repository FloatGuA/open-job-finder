# 前端设计守则（Frontend Doctrine）

> 与后端分层守则（`CLAUDE.md` / `docs/configuration.md`）对称的前端基准。
> 逐个 navigator 重构时，以本文档为共同标准。最后更新：2026-06-21。

技术栈：React 18 + Vite + TypeScript + Tailwind CSS v3。构建产物落 `dashboard/static/`。

---

## 一、分层（与后端 pipeline→tools→services 对称）

| 层 | 目录 | 职责 | 铁律 |
|----|------|------|------|
| **1. API 契约** | `src/api/index.ts` | 唯一对后端发 HTTP 的地方，全部带类型 | 组件/页面**禁止**直接 `fetch`/`requestJson`——一律走 `API.*`（= 后端"禁止 tool 层直接 SQL，走 tracker"）|
| **2. 共享状态 / 流** | `src/context/`、`src/hooks/` | 跨页状态、SSE（`workflowRunning` / `progressEvents`）| 全局状态与 SSE 只在这层；单向数据流 |
| **3. 页面（navigator）** | `src/pages/`（一个 navigator 一个）| 路由级**编排**：取数 + 持页面态 + 组合组件 | 页面只编排、不画深层 UI |
| **4. 组件** | `src/components/`（`ui/` 基元 + 业务组件）| 可复用**呈现**：收 props、渲染、回调冒泡 | 组件尽量"哑"；容器逻辑薄 |
| **5. 基元 / 设计令牌** | `src/components/ui/`、Tailwind tokens | 纯 UI 基元（Card/Button/SectionHeader）、配色/间距令牌 | 视觉常量集中，不散落硬编码 |

数据流向：`API`（取数）→ `context/hooks`（共享态）→ `pages`（编排）→ `components`（渲染）→ 用户事件向上冒泡回 `pages`。

---

## 二、贯穿性铁律（前端版 fail-fast / 约定优先）

1. **CJK 一律 `\uXXXX`**（已知坑，必守）。裸中文会被 Windows GBK 工具链 + Prettier 静默损坏。JSX 文本节点用 `{'\uXXXX'}`，JSX 属性也用表达式 `label={'\uXXXX'}`（双引号串不走转义）。新增中文后用 PowerShell 字节级转，验证 non-ASCII=0。
2. **类型从 `api/index.ts` 流出**——前后端契约的单一来源。后端改 schema，先改这里的类型，`tsc --noEmit` 立刻抓出所有断点（靠这个发现过 limit/days 没接、字段名对不上）。
3. **诚实状态**：running / done / error / 降级 如实显示，绝不伪造成功（= 后端 fail-fast；W1 幻影投递就是反例——UI 显示"成功"但实际没发）。
4. **死字段即删**：UI 上能调但后端不消费的参数，删掉而非留着误导（已删 limit / generate_resume）。
5. **性能即体验**：长列表截断、高频事件批处理（SSE 已改 200ms 批刷 + LiveLog 截 80 行）。
6. **约定优先于个人偏好**：沿用既有 Tailwind 令牌、命名、组件风格；不为风格重排无关代码。

---

## 三、UX / 视觉原则

1. **信息层级**：概览 → 下钻细节（WorkflowTrack 的 scope×step×tool 层级树是范式）。
2. **一致性 > 花样**：同类操作同一种交互、同一套基元。
3. **即时反馈**：每个异步操作有 loading / 成功 / 失败 三态。
4. **克制美学**：留白、克制配色、统一令牌；少即是多。沿用 Apple 设计令牌（`bg.page=#000000` 等深色基调）。
5. **消除冗余**：同一能力不在两个 navigator 各实现一遍（当前 reply 审批 / LLM 配置 / session 登录都有重复，重构时收敛）。

> 落地高设计质量界面时使用本环境的 **`frontend-design` skill**（产出不像 AI 套模板的生产级 UI）作为视觉标准。

---

## 四、设计令牌（现状速查）

Tailwind 自定义令牌（见 `tailwind.config`）：
- 背景：`bg-page`(#000) / `bg-card` / `bg-card2` / `bg-hover`
- 文本：`text-1`（主）/ `text-2`（次）/ `text-3`（弱）
- 品牌：`brand`(#0071e3) / `brand-hover` / `brand-dim`
- 语义色：emerald(成功) / amber(警告/待验证) / rose(错误) / sky(信息事件)
- 圆角卡片：`rounded-2xl bg-bg-card p-5/p-6 shadow-card`
- 区块小标题：`text-[10px] font-medium tracking-widest text-text-3 uppercase`

> 上述重复模式已抽成 `src/components/ui/` 基元（Card / SectionHeader / Button），新页面优先用基元。

### 文字色 vs 装饰色的硬分界（对比度契约）

**铁律：颜色令牌分两类，不可混用。**

| 类别 | 令牌 | 用途 | 对比度契约（深底/卡片上）|
|------|------|------|------|
| **文字色** | `text-1` / `text-2` / `text-3` | 渲染任何**承载信息**的字（含时间戳、时长、描述、计数、版本号这类"弱信息"）| **每一档都必须可读**：最弱的 `text-3` 也要 ≥ 4.5:1 |
| **装饰色** | 边框/网格/分隔线/禁用占位用的极淡灰（如 `rgba(255,255,255,0.05~0.12)`、`border-subtle`）| **只用于非文字元素** | 无下限（本就该淡）|

**这条原则的由来（2026-06-13 踩坑）**：控制台重构时把颜色按"视觉弱化程度"线性往下排，最弱那档（`#48484a`）跌破可读线（~1.9:1），却仍被拿去渲染时间戳/时长/描述 → 大量信息文字看不清。

**复发防护**：
1. 任何字（哪怕最弱）一律 ≥ `text-3`。**禁止**把装饰灰（`#48484a` 一类、低于 3:1 的色）用于文字。
2. 装饰灰只能出现在 `border` / `background` / 网格线 / 禁用态，绝不出现在 `color:`（文字）上。
3. 新增灰度令牌时先问：它是给字用还是给装饰用？给字 → 验证对比度 ≥ 4.5:1；给装饰 → 命名上与文字色区隔（如 `deco`/`hairline`），从命名上杜绝误用。
4. 自检：把"看不清的字"贴到对比度检查器，< 4.5:1 即为 bug，不是"风格弱化"。

---

## 五、调试辅助：组件名标签（DevLabel）

面向"对前端不熟"的协作场景：给界面每个主要区块挂上它对应的 **React 组件/区域名**，让反馈能精确指认（"`InstanceDetail` 这块太挤"），而不是描述位置。

**组件**：`src/components/dev/DevLabel.tsx` —— 半透明蓝色 pill，`pointer-events-none`（绝不挡下层操作）。两种用法：

| 用法 | 适用 |
|------|------|
| `<DevLabel name="X" />` | 内联 pill，跟在区块**已有标题**旁（首选，随布局流动、不重叠）|
| `<DevLabel name="X" float />` | 浮层，贴在 `relative` 父级**右上角**，用于没有标题文字的区块 |

**全局开关**：Topbar 的「标签 ON/OFF」按钮一键切换全站显隐，状态存 `localStorage('ojf_dev_labels')`，默认 ON。开关由 `src/hooks/useDevLabels.ts`（模块级 store + `useSyncExternalStore`，无需 Provider）驱动，关闭时 `DevLabel` 直接 `return null`。

**约定**：
1. **新增有意义的区块/卡片/可复用组件时，顺手挂一个 `DevLabel`**，`name` 用 PascalCase 的 React 组件名或区域名（与代码里的组件一致，便于双向定位）。
2. 优先内联（贴标题）；`float` 仅用于无标题区块，且确认右上角不压住按钮/角标。
3. `name` 一律用 **ASCII 英文**（组件名本就是英文）——顺带规避 CJK 转义负担。
4. 复用组件被多处使用时（如 Settings 的 `Card`、`WorkflowScheduleSection`），给它加一个可选 `dev` prop 透传名字，而不是在组件内写死单一名字。
5. 它是**调试/沟通辅助**，不是产品功能——不要让任何业务逻辑依赖它；默认 ON 只是方便协作期，随时可关。
