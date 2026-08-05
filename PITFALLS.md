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
