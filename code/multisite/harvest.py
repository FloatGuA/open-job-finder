"""抓一页岗位：切行 → 逐行取 URL 和 JD → 批量分类 → 落袋。

**为什么必须是代码而不是 agent 自己做**：一页 10 个岗位，每个都要「点开→读 URL→
读 JD→关掉」。交给 agent 就是 40 次工具调用、40 个 ReAct 轮次；60 步预算只够一页半。
代码做完这些只占 agent 的**一次**工具调用。分工（spec §5）：agent 决定去哪个桶、
勾哪个框、还要不要继续；代码承担「把这一页 N 条抓下来」；分类是 LLM，但批量、
不占 ReAct 轮次。

**不碰 tracker**：落库是节点的事（Task 6），这里只负责抓和分类，`sink` 是调用方
传入的 list，`known_urls` 是调用方传入的去重集合。
"""
from multisite.executors import (job_url_offline, job_url_online,
                                 snapshot_to_text, split_rows)
from multisite.site_manual import SiteManual

# 详情页 a11y 快照全文可能有 75-120KB（真实列表页 fixture 是 8.5KB/10 行，详情页
# 比列表行密得多）；`classify_jobs` 把一整页所有条目的 jd **拼进同一个 prompt**，
# 撑爆 deepseek-chat 64k 上下文 → classify 抛 → 整页被丢弃（found=0，看起来像
# "这个站没有岗位"，其实是自己的截断没做）。
#
# **必须在这里（harvest 边界）截，不能挪到 classify 里**：分类只是这份 jd 的一个
# 消费方，`pending.append(...)` 之后同一个 jd 还会经 `sink.extend(classified)`
# 落进 pending_jobs 表——如果只在 classify 的 prompt 拼接处截断，落库的 jd 依然
# 是全文，库里会堆一堆帯 uid 属性的原始 a11y 标记，且换一个消费方（比如以后加的
# eval/审批页）又得重新面对同一个撑爆问题。
#
# 2-3KB 是量级估计，不是精确调过的值：15 条候选 × 2KB ≈ 30KB，加上 prompt 里
# quota_table/golden_examples/说明文字，仍然远低于 64k 上下文；截断点选在
# "字符数"而不是"token 数"，因为这里没有现成的 tokenizer，字符数是可以不依赖
# 任何库、立刻算出来的近似量。
_JD_MAX_CHARS = 3000


async def harvest_page(
    snapshot_text: str,
    tools,
    manual: SiteManual,
    *,
    bucket: str,
    classify,
    sink: list,
    known_urls: set,
    limit: int,
) -> dict:
    """抓当前列表页快照上的岗位，批量分类，成功后追加进 `sink`。

    五个计数各自对应一种互不相同、不能被合并的"这一页什么都没抓到"原因：
    `rows`（这一页本来就没岗位）、`skipped_known`（都抓过了）、`url_failed`
    （取 URL 失败）、`truncated`（到 limit 停了）。少了任何一个都会让这四种
    情况在日志里长得一模一样。
    """
    rows = split_rows(snapshot_text, manual)

    truncated = len(rows) > limit
    rows = rows[:limit]

    collected = 0
    skipped_known = 0
    url_failed = 0
    pending = []

    for row in rows:
        if manual.job_url_source == "new_tab_on_click":
            got = await job_url_online(row, tools, manual)
            if got is None:
                url_failed += 1
                continue
            url, detail = got
            # **先转可读正文再截断**：`detail` 是 a11y 快照转储，`uid=` / 角色名 /
            # `url=` 这些标记占掉大半篇幅。顺序反了的话，按标记算的 3000 字里
            # 转换完可能只剩一千出头的正文——而且两个消费方（Checkpoint 1 审批页、
            # 分类 prompt）都是拿转换后的文本用，没有谁需要原始快照。
            jd = snapshot_to_text(detail)[:_JD_MAX_CHARS]
        else:
            url = job_url_offline(row, snapshot_text, manual)
            if url is None:
                url_failed += 1
                continue
            # 这条路取不到详情页快照（`link_in_row` 类站点，真机是 bambulab）。
            # `row.text` 已经是这个站手边能拿到的最好的 JD 替代——容器模式下
            # 整个卡片就是一个 link 节点，标题/地点/类型/JD 摘要全挤在它的
            # accessible name 里（见 `_split_rows_container_per_row` 的
            # docstring），而这段文本此刻已经在被当成分类 prompt 的 `title`
            # 用（layer1_agent 把 `text` 映射成 `title`）——过去只用了一半，
            # `jd` 被留成空串，落库和 Checkpoint 1 审批页看到的都是"这个岗位
            # 没有 JD"，而分类规则「职责里出现 xx 就归类」压根没有 jd 可读。
            # 同一个 `_JD_MAX_CHARS` 上限，不另开一个：见文件顶部的注释——
            # 截断必须在 harvest 边界做一次，落库和分类 prompt 才不会各自
            # 面对一份没截断的原文。
            jd = row.text[:_JD_MAX_CHARS]

        # 只有取回 URL 之后才知道是不是已收录过——判断顺序必须在取 URL 之后。
        if url in known_urls:
            skipped_known += 1
            continue

        pending.append({"url": url, "jd": jd, "bucket": bucket, "text": row.text})
        collected += 1

    # 分类在循环之后一次性批量调用——这是「不占 ReAct 轮次」的关键。
    # 抛异常就让它抛（fail fast），但必须在写 sink 之前：先攒 pending，
    # 分类成功后才 sink.extend(...)，半页结果落袋会让下次去重误判成「已收录」。
    classified = await classify(pending) if pending else []
    sink.extend(classified)

    return {
        "rows": len(rows),
        "collected": collected,
        "skipped_known": skipped_known,
        "url_failed": url_failed,
        "truncated": truncated,
    }
