"""把 chrome-devtools-mcp 的原始工具包装成 Layer 1 能安全交给 agent 的版本。

**为什么必须有这个模块**：Layer 1 改成 agent 自主导航之后，安全边界的守法变了。
旧版是"代码写死点哪个 uid"，agent 根本没有决定点什么的余地；改成 agent 循环后
`click` 变成一个它可以任意调用的工具，而投递页上"提交/下一步"就是一个普通按钮
——**同一个工具既能点「申请」也能点「提交」**。

四层架构里提交属于 Layer 3（且必须在 Layer 2 人工审批之后），Layer 1 越界点一次
就是对真实企业投出一份没人审过的申请，不可撤销。所以守法从"工具集里没有提交
能力"换成"**点击工具自己拒绝点提交类元素**"——仍然是代码强制，不是 prompt 叮嘱
（DECISION.md 反复记过：安全边界靠不给能力，不靠指令约束）。

拒绝时返回的是**一段给 agent 看的错误文本**而不是抛异常：agent 需要知道"这条路
被挡住了、换个方式"，抛异常会直接终止整个 run，把可恢复的情况变成硬失败。
"""
import re
from typing import Callable, Optional

from langchain_core.tools import BaseTool, StructuredTool

# 会把表单**发出去**的终局动作。命中即拒绝点击。
#
# 这个表里刻意只放终局短语，不放「申请」「投递」「apply」这类**入口**词——入口
# 按钮必须放行，否则 Layer 1 连表单都进不去。所以：
#   「申请职位」「立即申请」「Apply Now」 → 不命中，放行（入口）
#   「确认投递」「立即投递」「提交」       → 命中，拒绝（终局）
# 注意 "apply now" 之类**不能**加进来：英文招聘站上它通常就是入口按钮。
_SUBMIT_KEYWORDS = (
    "提交", "submit",
    "下一步", "next step",
    "确认投递", "立即投递", "投递简历", "确认提交", "确认申请",
    "完成投递", "保存并提交", "send application",
)

_SNAPSHOT_LINE_RE = re.compile(r'uid=(?P<uid>\S+)\s+(?P<role>\w+)(?:\s+"(?P<name>[^"]*)")?')


def looks_like_submit(label: str) -> bool:
    """label 是否是"会把表单发出去"的终局动作。"""
    lowered = (label or "").strip().lower()
    if not lowered:
        return False
    return any(k.lower() in lowered for k in _SUBMIT_KEYWORDS)


def label_for_uid(snapshot_text: str, uid: str) -> Optional[str]:
    """从 a11y 快照里取某个 uid 的可读名字。

    取不到返回 None——**注意区分「取不到」和「空字符串」**：前者意味着我们无法
    判断这次点击安全与否（该 uid 不在这张快照里），后者意味着这个元素确实没有
    accessible name。两者在 make_guarded_click 里都是放行，但原因不同，不要合并。
    """
    for line in snapshot_text.splitlines():
        m = _SNAPSHOT_LINE_RE.search(line)
        if m and m.group("uid") == uid:
            return (m.group("name") or "").strip()
    return None


def make_guarded_click(
    click_tool: BaseTool,
    snapshot_provider: Callable[[], str],
) -> BaseTool:
    """包一层「拒绝提交类点击」的 click，工具名仍叫 click（对 agent 透明）。

    `snapshot_provider` 是个同步可调用对象，返回**最近一次** a11y 快照文本（由
    layer1_agent 维护）。刻意不在这里自己重新截图：截图昂贵，而且守法要校验的是
    "agent 看到并据此决定点击的那张快照"——拿一张更新的快照去校验基于旧快照做出
    的决定，uid 可能已经对不上号了。

    **取不到 label 时放行（fail-open），这是刻意的取舍**：a11y 快照里大量可交互
    元素压根没有 accessible name（PITFALLS 记过这条坑，上传按钮和三个必填
    combobox 都是），fail-closed 会让 agent 寸步难行、连表单都进不去。真正的兜底
    是四层架构本身——Layer 1 的产出是一条 `pending_applications` 待审批记录，不是
    任何对外动作。这个取舍必须显式写在这里，别哪天有人"顺手改成更安全的
    fail-closed"却不知道它会把整个 Layer 1 卡死。
    """

    async def _guarded(uid: str, dblClick: bool = False) -> str:
        label = label_for_uid(snapshot_provider(), uid)
        if label is not None and looks_like_submit(label):
            return (
                f"REFUSED: 拒绝点击 uid={uid}（标签 {label!r}）——这看起来是提交/下一步类操作。"
                "本阶段只负责识别，提交属于人工审批之后的阶段。"
                "不要再尝试点击这个元素；完成当前页面的信息收集后就结束。"
            )
        return await click_tool.ainvoke({"uid": uid, "dblClick": dblClick})

    return StructuredTool.from_function(
        coroutine=_guarded,
        name="click",
        description=(
            "点击页面上的一个元素，用 take_snapshot 返回的 uid 定位。"
            "提交/下一步类按钮会被拒绝——本阶段只做信息识别，不提交任何表单。"
        ),
    )


def _result_text(result) -> str:
    """把工具返回值摊平成文本。

    MCP 工具返回的是 content block 列表；字符串只是"单块文本"的简写。
    chrome-devtools-mcp 把执行错误**当正常内容返回**（isError=False），所以错误就
    躺在这些 block 里，只 try/except 是抓不到的——真机日志里 29 次点击失败没有一次
    是异常。
    """
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(b.get("text", "") for b in result if isinstance(b, dict))
    return str(result)


def looks_like_tool_error(result) -> bool:
    """这次调用是不是失败了。

    **只认开头的 `Error`，不做全文包含匹配。** 快照和页面正文里出现 "Error" 是常事
    （404 页面、报错文案），全文匹配会在一个完全正常的页面上把 `take_snapshot` 判成
    连续失败并锁死——那等于把 agent 的眼睛挖掉，比它原本的循环严重得多。
    """
    return _result_text(result).lstrip().startswith("Error")


def make_repeat_failure_guard(tool: BaseTool, limit: int = 2) -> BaseTool:
    """连续用**同一组参数**调同一个工具失败 `limit` 次后，后续同样的调用不再执行。

    **为什么必须是代码而不是 prompt**：2026-08-18 真机（m1 首次跑 join.qq.com），
    agent 对同一个点不动的 uid 连点 29 次，中间夹着 30 次重新截图，四分钟烧光步数、
    一个岗位都没找到。它的 think 里写着"让我重新截图拿最新的 uid"然后照样点回旧 uid
    ——不是提示不到位，是它看不见自己的循环。而"这次调用跟上次是不是同一个"是纯比对，
    不需要判断力（models judge / code decides）。

    **成功即清零**：连续失败才叫循环。失败一次、成功一次、再失败不是循环，拦它是误伤。
    这条同时保证了参数天然相同的高频工具（`take_snapshot({})`，真机那轮调了 30 次）
    只要在正常工作就永远不会被拦。

    异常**照抛不误**，只是顺带记一笔——包装层不处理异常（fail fast），吞掉它会把
    "浏览器崩了"变成"工具安静地返回了一句话"。
    """
    import json

    failures: dict = {}
    last_error: dict = {}

    def _key(kwargs: dict) -> str:
        return json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)

    async def _guarded(**kwargs):
        key = _key(kwargs)
        if failures.get(key, 0) >= limit:
            return (
                f"BLOCKED: 你已经用完全相同的参数调用 {tool.name} 失败 {failures[key]} 次，"
                f"这次没有执行。\n参数：{key}\n最后一次的错误：{last_error.get(key, '')}\n"
                "不要再用这组参数重试——重复同一个动作不会有不同结果。换个办法："
                "换一个 uid、先滚动或等待让它变成可交互、改用别的工具，或者干脆换一条路走。"
            )
        try:
            result = await tool.ainvoke(kwargs)
        except Exception as exc:
            failures[key] = failures.get(key, 0) + 1
            last_error[key] = str(exc)
            raise
        if looks_like_tool_error(result):
            failures[key] = failures.get(key, 0) + 1
            last_error[key] = _result_text(result)
        else:
            failures[key] = 0
        return result

    return StructuredTool.from_function(
        coroutine=_guarded,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )
