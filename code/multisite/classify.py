"""岗位分类：批量、纯判断、可测。

**不走 ReAct 循环**是刻意的（spec §2.1 同理）：它不需要"看一眼再决定下一步"，
输入是文本、输出是标签。做成普通 LLM 调用换来的是**可单测 + 可 eval**。

**解析复用 `services/llm_parser.safe_parse_json_array`**（修复轮 1 收敛）：
这里的输出天然是一个数组（`[{"index":...}]`，按 index 对齐是硬要求，见下）。
`safe_parse_json` 认死了顶层是 JSON 对象，套用不了；`bucket_plan.py` 的输出
同样是数组，原本两边各写了一份逻辑相同、docstring 已经开始漂移的私有实现，
现已收敛进 `llm_parser.safe_parse_json_array`——那份三层解析（围栏提取 →
json.loads → json_repair 兜底）现在只有一份，见 `_parse_response`。

**prompt 默认走 `PromptManager`，不直接读文件**（修复轮 2 / FIX-2）：以前这里
是 `_PROMPT_PATH.read_text()`，绕开了用户在设置页保存进 `data/prompts_override/`
的覆盖版——用户改了 prompt、保存成功、页面显示"已修改"，但运行时用的还是 git
里的默认值，接线是断的。`PromptManager().load(name)` 才会去看覆盖层。

**`classify_jobs` 是 `async def`**（修复轮 1）：调用方 `multisite/harvest.py` 的
`harvest_page` 本身是 `async def`，且跑在 LangGraph 已有的事件循环里；这里如果
用 `asyncio.run()` 自己另起一个循环，会在集成时直接炸
`RuntimeError: asyncio.run() cannot be called from a running event loop`。
multisite 这一层从浏览器工具到 `run_agent` 全是 async，分类是网络调用，跟着
统一成 async 而不是靠 `model.invoke()` 同步接口绕过——后者会在 async 管线里
插一个阻塞调用，只是「眼下没有并发」才不出问题，是把正确性寄托在环境假设上。
"""
import re

from multisite.agent_runtime import build_model
from services.exceptions import LLMParseError
from services.llm_parser import safe_parse_json_array
from services.prompt_manager import PromptManager

_PROMPT_NAME = "layer1_classify_jobs"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# golden_examples 没传（调用方没有 tracker，或者库里确实没有已确认的历史纠正）
# 时的占位文案——不是"这个模块不接历史纠正样例"，那句话已经不成立了（FIX-4：
# golden examples 现在由 scan_buckets 节点从 preferences.render_golden_examples
# 取出来传进来，见 `golden_examples` 入参）。
_NO_GOLDEN_EXAMPLES = "（本次未提供历史纠正样例）"

# LLM 没给出干净标题时的兜底长度。**绝不能是整行原文**：`harvest_page` 传进来
# 的 `title` 其实是整张卡片拼接文本（标题+标签+地点+部门缩写……），长度没有上限，
# 一路透传会变成 `pending_jobs.title`，还会喂给 `resume_matcher.pick_for_job`
# 的关键词匹配（标题权重 3）——谁匹配到什么完全不可控，等于让一段抓取噪声悄悄
# 决定发出去的是哪一份简历（Ruling 10 之后新发现的两条生产路径，见模块内两处
# "FIX-5" 注释）。截断到一个较短的长度而不是清空成空串：Checkpoint 1 审批页
# 至少还能让人认出大概是哪个岗位，比一片空白更可用。
_TITLE_FALLBACK_MAX_CHARS = 60


def _safe_title_fallback(raw_title: str) -> str:
    return (raw_title or "").strip()[:_TITLE_FALLBACK_MAX_CHARS]


async def classify_jobs(
    items: list[dict],
    quotas: dict,
    *,
    model=None,
    prompt_text: str | None = None,
    golden_examples: str | None = None,
) -> list[dict]:
    """给每条岗位打一个类别标签，**顺带抽取干净的标题和公司名**。

    入参每项至少 `{title, jd, site_category}`——但这里的 `title` 未必是干净的
    标题，harvest_page（多站点抓取）传进来的其实是一整行卡片文本（标题+标签+
    地点混在一起）。模型本来就要读这段文本才能分类，顺手把标题和公司名择出来
    是免费的（修复轮 1：设计稿 §3.7 的原意，Task 4/6 首版漏接了这一步——`title`
    当时被当成输入字段直接透传，harvest 抓不到干净标题，落库的 `pending_jobs.title`
    变成了两百字的长文本，直接影响 Checkpoint 1 审批页可读性和
    `resume_matcher.pick_for_job` 的关键词匹配）。

    出参每项在原字段基础上加 `{category, why}`；`title`/`company` **只要模型
    在这一条的响应里给出对应字段就用模型的**（哪怕是空串——"读不出公司名"是
    合法答案，不是缺陷）。模型没给这个字段（key 缺失），或者这条 index 整个
    没被模型回答，**都退回一段截断过的原文，绝不是原样透传的整行卡片文本**
    （FIX-5：修复轮 1 只堵住了"模型给了空串"这条路径，这两条仍然会让
    `title` 变成无长度上限的整行原文，一路落进 `pending_jobs.title` 并影响
    `resume_matcher.pick_for_job` 选中哪份简历，见 `_safe_title_fallback`）。

    `golden_examples`：人工确认过的历史归类纠正（`preferences.render_golden_examples`
    的产出），不传或传空串时退回 `_NO_GOLDEN_EXAMPLES` 占位文案。

    空输入直接返回空列表，**不调模型**——没有岗位就没有要判断的东西，调一次
    空 prompt 只是白花钱。
    """
    if not items:
        return []

    if model is None:
        model = build_model()
    if prompt_text is None:
        # 覆盖层优先——见模块 docstring 的 FIX-2 说明。不能直接 `Path.read_text()`。
        prompt_text = PromptManager().load(_PROMPT_NAME)

    prompt = _render_prompt(prompt_text, items, quotas, golden_examples)

    response = await model.ainvoke(prompt)
    raw_results = _parse_response(response.content)

    by_index: dict[int, dict] = {}
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if isinstance(index, int):
            by_index[index] = entry

    out = []
    for i, item in enumerate(items):
        merged = dict(item)
        entry = by_index.get(i)
        if entry is None:
            # LLM 没回这一条——按 index 对齐，缺的就是空，绝不能让后面的
            # 答案错位顶上来（那会给岗位安错标签，结果却看起来完全正常）。
            # title 同样不能保留原样透传：`item["title"]` 是整行卡片原文，
            # 无长度上限（FIX-5，见函数 docstring）。
            merged["category"] = ""
            merged["why"] = ""
            merged["title"] = _safe_title_fallback(item.get("title", ""))
        else:
            category = entry.get("category") or ""
            why = entry.get("why") or ""
            if category in quotas:
                merged["category"] = category
                merged["why"] = why
            else:
                # 类别必须来自配额表，否则配额形同虚设。不丢弃 LLM 报的名字——
                # 写进 why 留痕，这是调 prompt 时最好的线索。
                merged["category"] = ""
                merged["why"] = f"LLM 报的类别「{category}」不在配额表里。{why}".strip()
            # title/company：**按 key 是否存在判断**，不是按值是否为真。模型显式
            # 给了空串（"读不出公司名"）要如实覆盖。**绝不因为模型给的 title 是
            # 空串就倒退回原始整行文本**（修复轮 1 的守门测试测这一条）；这个 key
            # 压根没出现在响应里时也不再"保留原样透传"——那个原样就是整行原文，
            # 同样要走截断兜底（FIX-5）。
            if "title" in entry:
                merged["title"] = entry.get("title") or ""
            else:
                merged["title"] = _safe_title_fallback(item.get("title", ""))
            if "company" in entry:
                merged["company"] = entry.get("company") or ""
        out.append(merged)
    return out


def _render_prompt(
    template: str, items: list[dict], quotas: dict, golden_examples: str | None
) -> str:
    quota_table = "、".join(f"{name} {count} 个" for name, count in quotas.items()) or "（未配置）"
    jobs_block = "\n\n".join(
        f"### [{i}] {item.get('title', '')}\n"
        f"站点分类：{item.get('site_category', '') or '（无）'}\n"
        f"职责：{item.get('jd', '') or '（无）'}"
        for i, item in enumerate(items)
    )

    text = template
    for key, value in {
        "quota_table": quota_table,
        "golden_examples": (golden_examples or "").strip() or _NO_GOLDEN_EXAMPLES,
        "jobs": jobs_block,
    }.items():
        text = text.replace("{{" + key + "}}", value)

    remaining = _PLACEHOLDER_RE.findall(text)
    if remaining:
        raise ValueError(f"prompt 模板占位符未替换：{remaining}")
    return text


def _parse_response(text: str) -> list:
    """整段回不成 JSON 数组是失败，抛 `ValueError`——静默返回空列表会让上层
    把它当成"这一页没有符合的岗位"。"""
    try:
        return safe_parse_json_array(text)
    except LLMParseError as exc:
        raise ValueError(f"LLM 回复无法解析为 JSON 数组：{text[:200]!r}") from exc
