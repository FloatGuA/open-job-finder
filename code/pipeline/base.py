from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StepStatus(Enum):
    SUCCESSFUL = "successful"
    DEGRADED   = "degraded"
    SKIPPED    = "skipped"
    FAILED     = "failed"


@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None
