# 简历信息池语义检索设计（2026-08-17）

> 状态：已与用户对齐，**仅设计，未实现**。
> 相关：`DECISION.md`「简历信息池语义检索：为未来 Copywriter agent 打基础」、`PROGRESS.md`。
> 动机备注：这次设计的起点是充实"Agent 开发工程师"方向的简历（用户原话："先写设计稿然后加到简历里，实现滞后一点也没关系"），不是当前业务的紧急需求。这不影响设计本身的质量要求，但影响了后面几处"现在就做 vs 以后再做"的取舍——凡是不影响这次设计能不能成立的分支，一律按 YAGNI 收窄。

## 1. 要解决什么

`data/info_pool.yaml`（简历信息池，求职者全部素材的主库）现在只有一种消费方式：**整份塞进 LLM 上下文**（生成/组合简历时）。这在池子小的时候没问题，但池子只会越攒越大（多次上传、多份简历素材汇总）。

正在规划中的**网申"开放问题"字段生成能力**（`DECISION.md`「网申表单字段：人口学字段规则填，开放问题字段 LLM 填 + 人工审批」这条已经拍板但未实现的缺口）需要的不是整份池子，而是"跟这条 JD/这个问题最相关的 2-3 段经历"——这是检索问题，不是"塞更多上下文"能解决的。

**这次只设计检索能力本身**：给定一段查询文本（未来是 JD 片段或开放问题原文），从信息池里返回最相关的 top-k 个 block。**不设计消费方**（Copywriter agent 的角色划分、如何接入 LangGraph、和 Filler 节点如何交接结构化数据）——那是另一个独立的设计，等这个能力先落地验证过再说。

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ services/pool_retriever.py（新增）                            │
│   retrieve(query: str, top_k=5) -> list[RetrievedBlock]      │
│     1. load_pool() 读 info_pool.yaml（复用现有 info_pool.py）  │
│     2. 展开所有 block → 拼接"分区名 + title+time+bullets       │
│        +summary"成一段文本 → 算 content_fingerprint            │
│     3. 查 data/info_pool_embeddings.json 缓存：                │
│        命中 → 直接用；未命中 → 调 tools/llm/embed_text 补算    │
│        并写回缓存（顺带清掉缓存里不再出现的旧指纹）             │
│     4. query 本身现算 embedding（不缓存，每次都不同）           │
│     5. 全量 block 向量做 cosine 相似度，取 top_k               │
└─────────────────────────────────────────────────────────────┘
        ↑ 调用                              ↑ 调用
┌───────────────────────┐      ┌────────────────────────────────┐
│ tools/llm/embed_text.py│      │ scripts/eval/run_retrieval_eval │
│（新增，单个外部调用）    │      │（新增，走真实 retrieve() 签名）  │
│ 调 OpenAI embedding API │      │ 读人工标注金标集算 Recall@k/MRR │
│ ToolResult 契约         │      │                                  │
└───────────────────────┘      └────────────────────────────────┘
```

**排序算法用暴力 cosine 相似度，不引入 faiss/chroma 等向量库**——池子只有几十个 block，暴力算全量相似度是毫秒级的，专门的向量库在这个规模下是过度设计。

## 3. 数据流

**查询侧（每次 `retrieve()` 调用）**：

```
retrieve(query, top_k)
  → load_pool() 展开全部 block（含分区名前缀，帮助区分同关键词不同分区的 block）
  → 对每个 block 算 content_fingerprint
  → 缓存命中的直接取向量；未命中的批量调 embed_text 补算
  → 写回缓存文件，清理缓存里不再存在于当前池子的旧指纹
  → embed_text([query]) 现算 query 向量（不缓存）
  → 全量 block 向量与 query 向量算 cosine 相似度，排序取 top_k
  → 返回 [{block, section, score}, ...]
```

**空池子 / 无 block**：返回空列表，**不是错误**——这是用户还没建池子的正常状态。

## 4. 组件细节

### `tools/llm/embed_text.py`

```python
def embed_text(texts: list[str]) -> ToolResult:
    """批量调 OpenAI text-embedding-3-small，返回 texts 对应顺序的向量列表。"""
```

- 单次操作，跟 `tools/llm/score_job.py`、`analyze_intent.py` 同样的 `ToolResult` 契约，经 `registry.call` 自动 trace/SSE。
- **Fail fast，不做静默兜底**：`OPENAI_API_KEY` 缺失、网络失败、API 报错，一律直接抛错，不返回零向量或空结果假装成功。理由：这是检索基建的下游依赖，静默返回"查不到"会让上游（未来的 Copywriter）误判成"没有相关经历"而不是"检索坏了"，两种情况的应对完全不同，必须让错误在这一层就暴露。

### `data/info_pool_embeddings.json`（缓存文件，随 `data/` 整体 gitignore）

```json
{
  "<content_fingerprint>": {
    "vector": [0.01, -0.02, ...],
    "model": "text-embedding-3-small",
    "dim": 1536,
    "cached_at": "2026-08-17T12:00:00"
  }
}
```

- key 用 block 内容的 `content_fingerprint`（复用 `info_pool.py` 已有的指纹算法思路：`sha256(内容 JSON) 前 12 位`），**不用 block 的位置/标题**做 key——block 改了内容，指纹变了，自动触发重算；block 内容没变，即使挪了分区顺序也还能命中缓存。
- 每次 `retrieve()` 顺带清理：缓存里存在、但当前池子里已经没有任何 block 对应这个指纹的条目，直接删除。避免池子反复编辑后缓存文件无限增长。

### `services/pool_retriever.py`

```python
def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """返回 [{block, section, score}], 按 score 降序，最多 top_k 条。"""
```

- 纯业务编排：加载池子、维护缓存、算相似度、排序截断。除了缓存文件的读写，无其他状态副作用。
- 和 `resume_matcher.py`（按岗位选"该发哪份简历"）职责不同、不合并：一个是在**已组合好的多份简历之间选一份**（确定性关键词匹配，`DECISION.md` 已拍板不用 LLM/向量，保可解释性），一个是在**池子内部的碎片素材里找相关片段**（语义检索问题）。两者解决的问题类型不同，合并会让文件同时承担两种不相关的判断逻辑。

## 5. Eval Harness

**现在就建**（用户明确要求，即使还没有真实消费方校准"检索准不准"）——沿用项目已有的 LLM eval 方法论（`scripts/eval/` 下意图分类 eval 立的三条硬约束，这次原样复用）：

1. 金标 PII 只落 `data/eval/`（gitignore 保护），不进 git
2. eval 忠实生产调用签名——跑的是真实 `pool_retriever.retrieve()`，不是重新实现一遍算法
3. ground truth 必须人标，不用 LLM 自我评判

**组件**：

- `scripts/eval/export_retrieval_golden.py`：从当前 `info_pool.yaml` 抽取 block 列表，人工写"查询文本 → 期望命中的 block 标题"映射，导出 `data/eval/retrieval_golden.jsonl`
- `scripts/eval/run_retrieval_eval.py`：加载金标，对每条查询跑真实 `retrieve()`，算 **Recall@k**（期望的 block 有没有出现在 top-k 里）和 **MRR**（期望的 block 排第几，取倒数再平均），输出报告

**不设强制通过阈值**——跟意图 eval 阶段1一样，先跑起来看数字，样本量（预计 10-20 条，池子本身就这个规模）不足以支撑一个有统计意义的阈值判断，硬卡一条线是假精确。

## 6. 测试计划

- `tests/test_pool_retriever.py`：mock `embed_text` 工具，测缓存命中 / 未命中触发补算 / 旧指纹清理 / 空池边界 / 排序正确性
- `tests/test_embed_text.py`：mock OpenAI 调用，测 `ToolResult` 契约的成功/失败路径（key 缺失、API 报错都要抛错）
- eval harness **不进 pytest 门禁**——依赖人工标注的金标数据，跟当前意图 eval 的现状一致（是评测工具，不是回归测试）

## 7. 明确不做的事（本次范围之外）

- Copywriter agent 本身（角色定义、LangGraph 接入点、和 Filler 节点的交接协议）——留给下一次设计
- `resume_matcher.py` 的向量相似度 tie-break 信号——是另一条独立的候选方案（见 `DECISION.md` 讨论），本次不动
- 给 `DECISION.md`/`PITFALLS.md` 做检索的自举工具——用户未表态是否要做，本次不包含
- 知识图谱（跨 Boss 直聘 W1/W2/W3 与多站点 Layer1-4 两套数据孤岛的关联推理）——动机不够强，本次不做
