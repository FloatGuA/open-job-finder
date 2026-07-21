# Pipeline Design Index

## 文件索引

| 文件 | 内容 |
|------|------|
| `w1_pipeline.md` | W1 搜索 + 投递 Pipeline 完整设计 |
| `w2_pipeline.md` | W2 会话检查 + 回复 Pipeline 完整设计 |
| `tools_catalog.md` | 所有 Tool 的输入输出定义 |
| `db_schema.md` | 数据库表结构设计 |

## 核心概念

**Tool**：原子 IO 操作，单一职责，JSON 输入/输出。
三类：BrowserTool / LLMTool / DBTool / BusinessLogicTool（纯函数）。

**Step**：Pipeline 中有意义的业务阶段。有 dataclass 输入/输出、独立错误边界（on_error 策略）、独立结构化日志。内部可串联调用多个 Tool。

**on_error 策略**：
- `ABORT_WORKFLOW`：终止整个 Pipeline
- `SKIP`：跳过当前处理单元（一张卡 / 一个会话），继续下一个
- `CONTINUE_DEGRADED`：记录错误，继续执行后续 Step

## 删减范围

以下 Tool 在此次重构中不实现：
- **CritiqueJob**：Critic 二次审核砍掉
- **GenerateResume**：简历定制生成砍掉
