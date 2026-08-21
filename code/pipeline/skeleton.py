"""W1/W2/W3 有哪些步骤，以及每一步是「整轮跑一次」还是「每个岗位/会话跑一次」。

**前端第 2 层那张图（空闲态骨架）的数据源。** 它原来是抄在前端的一份常量，
抄的东西会烂——2026-08-21 对着代码核了一遍：

    W3  前端只有 scan/locate/send/verify，代码里还有 freshness/detect/resume/upsert
    W2  代码里有 wechat 步，前端没有

而这种烂法**不会报错**：少登记一个步骤，那一步在空闲态就是不存在，跑起来才冒出来。
`tests/test_pipeline_skeleton.py` 现在双向盯着它——源码里 `set_context` 过的步骤
必须都在这儿，这儿声明的也必须在源码里有。

**只登记步骤，不登记每步会调哪些工具。** `send_pipeline.py` 一个文件里有 4 个
`set_context` 和 8 个 `_reg.call`，哪个工具属于哪一步靠静态分析分不出来，
而那种聪明本身就是新的脆弱点。前端改成**只显示实际观测到的工具**——
空闲态本来就不知道会调什么，装作知道比不显示更糟。

m1/m2 不在这里：它们的步骤是 LangGraph 图节点，由 `/api/multisite/stages` 从图定义
导出（内层 ReAct 循环里 agent 调什么工具每次都不同，**没有"预期步骤"这回事**）。
"""

# 顺序即前端渲染顺序：按一次 run 里实际发生的先后排。
STEPS = {
    "w1": ["navigate", "scan", "fetch_jd", "apply", "upsert"],
    "w2": ["scan", "navigate", "read", "analyze", "wechat", "resume", "finalize"],
    "w3": ["scan", "freshness", "locate", "send", "verify", "detect", "resume", "upsert"],
}

# run 级：整轮跑一次，在逐项循环之外（scope={}）。
RUN_STEPS = {
    "w1": ["navigate", "scan"],
    "w2": ["scan", "finalize"],
    "w3": ["scan"],
}

# 循环级：每个岗位（W1 的 CardPipeline）/ 每个会话（W2 ConversationPipeline、
# W3 SendReplyPipeline & SendResumePipeline）跑一次。
LOOP_STEPS = {
    "w1": ["fetch_jd", "apply", "upsert"],
    "w2": ["navigate", "read", "analyze", "wechat", "resume"],
    "w3": ["freshness", "locate", "send", "verify", "detect", "resume", "upsert"],
}
