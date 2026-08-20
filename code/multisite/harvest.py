"""抓一页岗位：切行 → 逐行取 URL 和 JD → 批量分类 → 落袋。

**为什么必须是代码而不是 agent 自己做**：一页 10 个岗位，每个都要「点开→读 URL→
读 JD→关掉」。交给 agent 就是 40 次工具调用、40 个 ReAct 轮次；60 步预算只够一页半。
代码做完这些只占 agent 的**一次**工具调用。分工（spec §5）：agent 决定去哪个桶、
勾哪个框、还要不要继续；代码承担「把这一页 N 条抓下来」；分类是 LLM，但批量、
不占 ReAct 轮次。

**不碰 tracker**：落库是节点的事（Task 6），这里只负责抓和分类，`sink` 是调用方
传入的 list，`known_urls` 是调用方传入的去重集合。
"""
from multisite.executors import job_url_offline, job_url_online, split_rows
from multisite.site_manual import SiteManual


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
            url, jd = got
        else:
            url = job_url_offline(row, snapshot_text, manual)
            if url is None:
                url_failed += 1
                continue
            jd = ""

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
