"""Layer 1 的 agent 循环运行时：模型绑定 + 上下文控制。

**这个模块存在的唯一理由是上下文**。Layer 1 的工具返回的是 a11y 快照——单张
几十 KB，而 DeepSeek 的上下文只有 64k tokens。一个自主导航的 agent 跑十几步就会
把上下文塞满然后崩掉，这在改成 agent 驱动之前就被预见并写进了 DECISION.md
（"DeepSeek 在长程浏览器循环上的上下文与稳定性风险是真实且已预见的"）。所以：

1. `_trim_tool_outputs` 作为 `pre_model_hook`，只保留**最近一张**完整快照，更早
   的快照工具结果替换成一行占位。**为什么可以这么砍**：浏览器状态是当前页面，
   历史快照描述的是已经不存在的页面状态，对下一步决策没有价值——留着它们既费
   token 又容易让模型拿旧 uid 去点已经不存在的元素。
2. `MAX_STEPS` 兜住无限循环：agent 找不到路时会反复截图重试，没有硬上限就会一直
   烧到上下文爆掉为止。

刻意**不复用**项目自己的 `ModelRouter`：LangGraph 要的是 LangChain 原生
`BaseChatModel`，而 ModelRouter 返回的是纯文本 + provider 名。这是本模块（连同
layer1_agent）游离于项目 LLM 路由之外的原因，取舍已记在 DECISION.md。
"""
import os
from typing import Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# agent 的输出里什么字符都可能有（真机撞到过 ✅）。追踪是纯日志，**没有资格中断
# 业务流程**——用 safe_print 而不是 print，见 services/console_utf8 的模块说明。
from services.console_utf8 import safe_print

# 一次 agent 循环最多允许的模型轮次。超过就当这一步失败——比让它烧穿上下文再
# 报一个看不懂的错要好定位得多。
#
# 24 → 40（v2.23.0）：配额上线后选岗任务变长了。2026-08-14 真机跑用 43 步找齐
# 12 个岗位（开发 5/5、产品 3/3、运营 3/3 全部记满），效率没问题，但六个类别里
# AI NATIVE 0/3、游戏 0/2、测试 1/2 还差着就被上限砍断了——**它不是在兜圈子，
# 是活儿本来就没干完**。上一版 24 是给"只找 5 个岗位"定的，那个前提已经不在了。
#
# 40 → 60（同日，第四次真机跑）：分桶扫描上线后要覆盖站点的多个顶层分类桶
# （拓竹是 研发类 / 非研发类），每个桶各翻到底。第四次跑在第二个桶的第 4 页
# 步数用完。上下文不是瓶颈——pre_model_hook 只保留最近一张快照，轮次多了也不涨。
MAX_STEPS = 60

# LangGraph 的 `create_react_agent` 在步数快用完时**不抛异常**：它往 messages 里塞
# 这条固定文案然后"正常"返回。我们原本 `except GraphRecursionError` 的兜底因此
# 一次都没触发过——run 静默地半途而废，日志里跟正常收尾长得一模一样
# （2026-08-14 第四次真机跑才发现，此前三次的"主动收尾"结论都得打问号）。
# 这是耦合 LangGraph 内部文案的检测，升级版本时要复查；但静默截断比这点耦合危险得多。
_STEP_LIMIT_SENTINEL = "Sorry, need more steps to process this request."

# 单条工具结果保留的字符上限（只作用于被判定为"陈旧"的那些）。
_STALE_TOOL_PLACEHOLDER = "[已省略：这是较早的页面快照，页面此后已经变化，不要再用它里面的 uid]"

# 快照类工具的名字——只有这些的历史结果值得砍，`fill` 之类的返回值本来就短。
_BULKY_TOOLS = {"take_snapshot", "navigate_page", "wait_for", "click"}


def build_model(temperature: float = 0.0) -> ChatOpenAI:
    """DeepSeek。api_key 从环境读（scripts/run_layer1.py 会先 load_dotenv）。

    刻意不给默认值：缺 key 就应该在这里以 KeyError 直接炸掉，而不是带着空 key
    走到第一次网络调用才报一个 401（fail fast，见全局开发原则）。
    """
    return ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        temperature=temperature,
    )


def trim_stale_snapshots(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """只保留最近一条大块工具结果的完整内容，更早的替换成占位说明。

    纯函数、无副作用，单独抽出来是为了能直接单测——agent 循环本身要真浏览器 +
    真 LLM 才跑得起来，如果上下文裁剪逻辑埋在里面就永远测不到。
    """
    out: list[BaseMessage] = []
    kept_recent = False
    # 从后往前走：第一次遇到的大块工具结果是"最近的"，保留；再往前的都砍掉。
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name in _BULKY_TOOLS:
            if not kept_recent:
                kept_recent = True
                out.append(msg)
            else:
                out.append(
                    ToolMessage(
                        content=_STALE_TOOL_PLACEHOLDER,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                )
            continue
        out.append(msg)
    out.reverse()
    return out


def _pre_model_hook(state: dict) -> dict:
    """LangGraph 在每次调模型前会调它。返回 `llm_input_messages` 表示"这次调用
    用这些消息"，**不会**改写图里持久化的 messages——历史仍然完整，只是不喂给
    模型。这点很重要：如果直接改 messages，后面想回看 agent 到底看到过什么就没
    有了。"""
    return {"llm_input_messages": trim_stale_snapshots(state["messages"])}


def build_agent(tools: Sequence[BaseTool], prompt: str, response_format=None):
    """组装一个受控的 ReAct agent。

    response_format 传 pydantic 模型时，LangGraph 会在 agent 结束后额外跑一次
    结构化输出，结果放在 state["structured_response"]——这样调用方拿到的是类型
    化的结果，而不是从自由文本里正则抠。
    """
    return create_react_agent(
        model=build_model(),
        tools=list(tools),
        prompt=prompt,
        pre_model_hook=_pre_model_hook,
        response_format=response_format,
    )


def _trace(msg: BaseMessage, step: int) -> None:
    """把 agent 的每一步打到 stdout。

    **不是可选的调试便利，是这条路线的必需品**：agent 自主导航失败时的现象是
    "跑了很久然后报 GraphRecursionError"，异常本身完全不说明它在哪兜圈子。第一次
    真机跑就撞上了——226 行日志里除了 MCP 噪音和 traceback 什么都没有，无从判断
    是没找到筛选器、还是快照读不懂、还是在两个页面之间来回跳。
    """
    if isinstance(msg, AIMessage):
        for call in (msg.tool_calls or []):
            args = {k: str(v)[:120] for k, v in (call.get("args") or {}).items()}
            safe_print(f"  [{step:02d}] -> {call.get('name')}({args})", flush=True)
        text = msg.content if isinstance(msg.content, str) else ""
        if text.strip():
            safe_print(f"  [{step:02d}] 说: {text.strip()[:300]}", flush=True)
    elif isinstance(msg, ToolMessage):
        body = msg.content if isinstance(msg.content, str) else str(msg.content)
        first = body.strip().splitlines()[0] if body.strip() else "(空)"
        safe_print(f"  [{step:02d}] <- {msg.name}: {len(body)} 字符 | {first[:160]}", flush=True)


async def run_agent(agent, user_message: str, max_steps: int = MAX_STEPS, trace: bool = True) -> dict:
    """跑一次 agent 循环并返回最终 state。

    `recursion_limit` 是 LangGraph 对图 superstep 数的硬上限，而**一次模型轮次是
    三跳不是两跳**：`pre_model_hook → agent → tools`。`pre_model_hook` 是
    `create_react_agent` 真的往图里加的一个节点（chat_agent_executor.py:796-798），
    不是回调——我们用它做上下文裁剪，等于每轮多一跳。

    这里原本乘的是 2，于是 `MAX_STEPS=60` 实际只买到约 41 轮，**这个常量的名字
    一直在骗人**（2026-08-14 逐行读 LangGraph 源码时发现）。改成乘 3。

    另外注意：真正先触发的**不是**这个硬上限，而是 `create_react_agent` 内建的
    软着陆——`remaining_steps < 2 且模型还想调工具`时它直接返回一句固定文案
    （见 `_STEP_LIMIT_SENTINEL`）。所以下面那个 GraphRecursionError 基本不会抛，
    判断"跑完没跑完"必须用 `hit_step_limit()`。
    """
    config = {"recursion_limit": max_steps * 3 + 4}
    payload = {"messages": [{"role": "user", "content": user_message}]}
    if not trace:
        return await agent.ainvoke(payload, config=config)

    final: dict = {}
    step = 0
    async for chunk in agent.astream(payload, config=config, stream_mode="values"):
        final = chunk
        msgs = chunk.get("messages") or []
        # 只打新出现的那些，避免每轮把整段历史重打一遍。
        while step < len(msgs):
            _trace(msgs[step], step)
            step += 1
    if hit_step_limit(final):
        # 大声说出来。这条路径是"没干完"，不是"干完了"，而两者的返回值一模一样。
        safe_print(f"  [!!] agent 步数耗尽（MAX_STEPS={max_steps}），任务未完成就返回了。"
                   f"结果是部分的。", flush=True)
    return final


def hit_step_limit(state: dict) -> bool:
    """这次 agent 循环是不是因为步数耗尽才停的。

    **区分"干完了"和"没干完"**：两者的 state 长得一样（都是正常返回、最后一条是
    AI 文本消息），只有文案不同。不检测的话，"扫完所有桶"和"扫到一半没步数了"
    在日志里完全无法区分——第四次真机跑就是这么把一次半途而废读成了主动收尾。
    """
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage):
            return isinstance(msg.content, str) and _STEP_LIMIT_SENTINEL in msg.content
    return False


def last_text(state: dict) -> str:
    """从 agent 最终 state 里取最后一条 AI 文本消息（没有结构化输出时用）。"""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""
