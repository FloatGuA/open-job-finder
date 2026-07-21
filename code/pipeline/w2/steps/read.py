import time
from dataclasses import dataclass, field

from pipeline.base import StepOutput, StepStatus


@dataclass
class ReadStepOutput(StepOutput):
    messages: list = field(default_factory=list)
    new_message_count: int = 0


class ReadStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, conv_id: str) -> ReadStepOutput:
        start_ts = time.time()
        scope = {"conv_id": conv_id}
        self._reg.set_context("read", scope)

        read = self._reg.call("read_messages")
        if not read.ok:
            out = ReadStepOutput(status=StepStatus.FAILED, error=read.error)
            self._log_step(scope, out, start_ts, {})
            return out

        messages = read.data.get("messages", [])
        write = self._reg.call("write_hr_messages", conv_id=conv_id, messages=messages)
        inserted = write.data.get("inserted_count", 0) if write.ok else 0

        out = ReadStepOutput(
            status=StepStatus.SUCCESSFUL,
            messages=messages,
            new_message_count=inserted,
        )
        self._log_step(scope, out, start_ts, {"message_count": len(messages), "new_message_count": inserted})
        return out

    def _log_step(self, scope, out, start_ts, data):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        logger.log_step(
            step="read",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data=data,
            error=out.error,
        )
