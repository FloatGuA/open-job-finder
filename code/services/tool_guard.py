"""
Tool guards: validate permissions before executing side-effect operations.
All tools with side effects must pass their guard before execution.
"""
from dataclasses import dataclass


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""

    @staticmethod
    def OK() -> "GuardResult":
        return GuardResult(ok=True)

    @staticmethod
    def BLOCKED(reason: str) -> "GuardResult":
        return GuardResult(ok=False, reason=reason)


class ToolGuard:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def check_apply(self, state) -> GuardResult:
        if not state.awaiting_confirmation:
            return GuardResult.BLOCKED("请先确认配置后再执行")
        limit = self.orchestrator.daily_limit
        today_count = self.orchestrator.tracker.count_today()
        if today_count >= limit:
            return GuardResult.BLOCKED(f"今日投递已达上限 {limit} 个（已投 {today_count} 个）")
        rate_limiter = getattr(self.orchestrator, "rate_limiter", None)
        if rate_limiter is not None and hasattr(rate_limiter, "is_exceeded"):
            if rate_limiter.is_exceeded():
                return GuardResult.BLOCKED("已超过频率限制，请稍后再试")
        return GuardResult.OK()

    def check_responses(self, state) -> GuardResult:
        if not state.awaiting_confirmation:
            return GuardResult.BLOCKED("请先确认配置后再执行")
        return GuardResult.OK()

    def check_remember(self, fact: str) -> GuardResult:
        if not fact or not fact.strip():
            return GuardResult.BLOCKED("没有可记录的内容")
        return GuardResult.OK()
