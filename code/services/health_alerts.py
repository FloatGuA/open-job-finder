"""「有东西坏了但没人发现」的信号，给 Dashboard 顶部横幅用。

这个系统的卖点是"不用盯着也能跑"，而 session 过期 / Boss 改版选择器失效 /
调度器不再触发，任何一个都可能**安静地跑好几天**——日志里全是记录，只是没人翻。

**渠道是 Dashboard**（用户 2026-08-22 定：别的都要接 MCP，更复杂）。
边界说清楚：它解决不了"三天没打开"，解决的是"打开了但没看出来有问题"。

**误报率决定它的存活率。** `precommit_pii_scan` 已经教过一次：误报 → 用户开始
无视 → 防线归零。所以这里的判据一律偏保守，宁可漏报——**没启用定时的
workflow 一律不报**（用户压根没打算让它自动跑）。

纯函数，不碰文件系统：调用方把日志读好传进来，测试因此不需要任何 mock。
"""
from datetime import datetime, timedelta
from typing import Optional

# 一次失败太常见（网络抖一下）。报它＝天天报＝没人看。
CONSECUTIVE_FAILURE_THRESHOLD = 2
STALE_DAYS = 2

_WF_LABEL = {"apply": "W1 投递", "check": "W2 检查回应", "reply": "W3 发送"}
# schedule.yaml 用 apply/check，schedule_log 里也是这两个名字。
_SCHEDULED = ("apply", "check")


def _parse(ts: Optional[str]) -> Optional[datetime]:
    """日志是追加写的文本，历史上出现过半截行。**告警是诊断工具，
    它自己因为一行坏数据就炸，恰恰是在最需要它的时候失灵。**"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _for_workflow(schedule_log: list, workflow: str) -> list:
    """该 workflow 的记录，按时间从旧到新。"""
    rows = [r for r in schedule_log if r.get("workflow") == workflow]
    return sorted(rows, key=lambda r: r.get("triggered_at") or "")


def _consecutive_failures(rows: list) -> int:
    """末尾连续失败几次。

    **`skipped` 直接跳过，不计数也不打断**：它是"今天撞了配额，没跑"——
    当成成功会掩盖真正的连续失败，当成失败会在正常限流时误报。
    """
    n = 0
    for r in reversed(rows):
        result = r.get("result")
        if result == "skipped":
            continue
        if result == "error":
            n += 1
            continue
        break
    return n


def _last_success(rows: list) -> Optional[datetime]:
    for r in reversed(rows):
        if r.get("result") == "success":
            t = _parse(r.get("triggered_at"))
            if t:
                return t
    return None


def detect_alerts(*, schedule_log: list, selfcheck_log: list, schedule: dict,
                  now: datetime, stale_days: int = STALE_DAYS) -> list:
    """返回 [{id, level, title, detail}]，没问题就是空列表。"""
    alerts: list = []

    for wf in _SCHEDULED:
        if not (schedule.get(wf) or {}).get("enabled"):
            continue          # 没开定时 = 没打算让它自动跑，报什么都是噪音
        label = _WF_LABEL.get(wf, wf)
        rows = _for_workflow(schedule_log, wf)

        fails = _consecutive_failures(rows)
        if fails >= CONSECUTIVE_FAILURE_THRESHOLD:
            last = rows[-1] if rows else {}
            alerts.append({
                "id": f"{wf}:consecutive_failures",
                "level": "error",
                "title": f"{label} 连续 {fails} 次失败",
                "detail": (last.get("summary") or "").strip()[:200]
                          or "最近几次定时运行都没跑成，日志页能看到每次卡在哪一步。",
            })

        # **这条最值钱**：不管失败长什么样，只问"上一次真的正常是什么时候"。
        # 调度器不再触发、每次都失败、session 过期，全都会落到这一条上。
        success_at = _last_success(rows)
        if success_at is None:
            alerts.append({
                "id": f"{wf}:stale",
                "level": "error",
                "title": f"{label} 从来没有成功跑过",
                "detail": "定时是开着的，但调度日志里一条成功记录都没有。",
            })
        elif now - success_at > timedelta(days=stale_days):
            days = (now - success_at).days
            alerts.append({
                "id": f"{wf}:stale",
                "level": "warn",
                "title": f"{label} 已经 {days} 天没有成功跑过",
                "detail": f"最后一次成功是 {success_at.strftime('%Y-%m-%d %H:%M')}。"
                          "定时开着却一直没有成功记录，通常是 session 过期或页面结构变了。",
            })

    checks = sorted([c for c in selfcheck_log if isinstance(c, dict)],
                    key=lambda c: c.get("started_at") or "")
    if checks and not checks[-1].get("ok"):
        bad = [s.get("label") or s.get("stage") or "?"
               for s in (checks[-1].get("stages") or []) if not s.get("ok")]
        alerts.append({
            "id": "selfcheck:failing",
            "level": "warn",
            "title": "最近一次自检没通过",
            "detail": ("未通过：" + "、".join(bad[:4])) if bad else "自检页有明细。",
        })

    return alerts
