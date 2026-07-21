import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus

# HR's WeChat message renders asynchronously after we click 同意; poll a few times.
_RESCAN_ATTEMPTS = 4
_RESCAN_DELAY = 1.5  # seconds between re-reads


@dataclass
class WechatStepOutput(StepOutput):
    agreed: bool = False
    new_messages: int = 0


class WechatStep:
    """Auto-agree to an HR 'exchange WeChat' card on the currently-open conversation.

    Cheap and idempotent: it asks the browser to click 同意 on an active
    `.dialog-icon.weixin` card. If there is no such active card (no request, or
    already agreed), the tool is a no-op and this step is silent 'skipped'.

    On a successful agree, the HR *immediately* auto-sends a new message carrying
    their WeChat. The conversation's ReadStep already ran BEFORE this agree, so that
    new message would otherwise be missed until the next W2 run. We therefore re-scan
    the open conversation (with retry for async render) and persist via
    write_hr_messages -- the same "act, then re-read to confirm the result landed"
    pattern W3 uses for reply delivery. The frontend reads from the DB, so the new
    WeChat message + the reminder banner update on its next load.

    No stage change is made (decision: dedicated frontend reminder, not a stage
    transition, so real offers stay uncontaminated).
    """

    def __init__(self, registry):
        self._reg = registry

    def run(self, scope: dict = None) -> WechatStepOutput:
        start_ts = time.time()
        step_scope = scope or {}
        conv_id = step_scope.get("conv_id", "")
        self._reg.set_context("wechat", step_scope)

        res = self._reg.call("accept_wechat_card")
        agreed = bool(res.ok and res.data.get("clicked"))

        # Silent no-op on the common case (no WeChat card): don't clutter the run log
        # with a per-conversation "skipped" node (wechat isn't in the monitor skeleton,
        # so there is no pending "waiting" dot to resolve either).
        if not agreed:
            return WechatStepOutput(status=StepStatus.SKIPPED, agreed=False)

        new_messages = self._rescan_and_persist(conv_id)
        out = WechatStepOutput(status=StepStatus.SUCCESSFUL, agreed=True, new_messages=new_messages)
        self._log_step(
            step_scope, out, start_ts,
            f"已自动同意交换微信，重扫入库 {new_messages} 条新消息",
        )
        return out

    def _rescan_and_persist(self, conv_id: str) -> int:
        """Re-read the open conversation and persist, so HR's just-sent WeChat lands.

        Retries because the HR message renders asynchronously right after the agree.
        write_hr_messages is idempotent (UNIQUE(conv_id, sender, text)), so re-reading
        the same bubbles inserts nothing; the count reflects genuinely new messages.
        """
        if not conv_id:
            return 0
        for _ in range(_RESCAN_ATTEMPTS):
            time.sleep(_RESCAN_DELAY)
            read = self._reg.call("read_messages")
            if not read.ok:
                continue
            messages = read.data.get("messages", [])
            write = self._reg.call("write_hr_messages", conv_id=conv_id, messages=messages)
            inserted = write.data.get("inserted_count", 0) if write.ok else 0
            if inserted:
                return inserted
        return 0

    def _log_step(self, scope, out, start_ts, message):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        logger.log_step(
            step="wechat",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data={"agreed": out.agreed, "new_messages": out.new_messages},
            message=message,
            error=out.error,
        )
