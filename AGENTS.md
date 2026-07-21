# AGENTS.md — Claude Code & Codex 协作约定

## 我们是谁

**Claude Code** 负责：架构决策、任务规划、代码审查、bug 定位、直接修复高风险或编码敏感问题。
**Codex** 负责：按任务规范批量实现功能、系统性代码变更、重复性修复。

两者平等协作，共同维护代码库质量。做了对方需要知道的事，就往 COLLAB.md 写一条。

---

## 编码约定

### 首要规则：所有文件 I/O 必须显式指定 UTF-8

这是根本约束。编码损坏的根源是在 Windows GBK 环境下，未指定编码的文件操作会以系统默认编码（GBK）读写，导致 UTF-8 中文字符被静默损坏且难以批量恢复。

**读和写都要指定，缺一不可——只约束写不够，读错了写再对也没用。**

```python
# Python — 读写都要加 encoding
open(file, encoding='utf-8')
open(file, 'w', encoding='utf-8')
```

或者在执行环境设置环境变量，强制 Python 全局 UTF-8 模式（Python 3.7+）：

```bash
PYTHONUTF8=1
```

### 次要防线：JS / HTML / CSS 中的 CJK 字符用 `\uXXXX`

在首要规则之上的额外保险。即使 I/O 已经正确，管道中其他工具也可能出问题；`\uXXXX` 是纯 ASCII，对任何工具链均安全。

- 例：`'搜索'` → `'\u641C\u7D22'`，`'完成'` → `'\u5B8C\u6210'`
- 改动 JS 文件后必须自检：`node --check <file>`，无语法错误才算完成

---

## 文件改动纪律

- 只改任务明确涉及的文件；不"顺手"重构未被要求的代码
- 整文件重写是高风险操作——除非任务明确要求，优先做 targeted edit（保留上下文更安全）
- 改动前先查 COLLAB.md，确认对方近期是否动过同一文件

---

## 错误处理约定（Tool 错误契约）

- **系统/意外错误**（DB 失败、编程 bug 等"不该发生"的）→ **raise**，不在 tool 内 try/except 吞掉。`ToolRegistry.call()` 会在 except 里先记 `failed` 日志再 re-raise——失败进 tool trace，且 fail-fast 不吞。
- **预期内、调用方需分支处理的结果**（元素未找到、弹窗不存在、卡片不在）→ **return `ToolResult(ok=False)`**。
- **Step 责任**：对"会返回 ok=False"的调用必须检查 `.ok`，按语义分支或上报为 step 失败（发可见红色事件）；**不可直接读 `.data` 而忽略 ok=False**，否则把失败变成静默吃空数据。
- **"是否立刻终止"是独立决策**：控制流（跳过/继续/中止）与状态标签（successful/degraded/failed）互不绑架——流程选择跳过不代表这一步该记成成功。

---

## 自检清单

| 文件类型 | 改动后必跑 |
|----------|-----------|
| `.js` | `node --check <file>` |
| `.py` | `python -m py_compile <file>` |
| 任何含中文的文件 | 确认非 ASCII 字符处理符合上方编码约定 |

---

## 冲突处理

发现对方的改动有问题时：
1. 先在 COLLAB.md 记录（问题是什么、影响范围）
2. 再动手修改
3. 改完在 COLLAB.md 再追加一条说明——不静默覆盖
