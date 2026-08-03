from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class AppStatus(str, Enum):
    # FOUND is the in-memory "discovered, pre-apply" default for Job/ApplicationRecord;
    # it never lands in the applications table (W1 persists rows as APPLIED). The
    # persisted lifecycle is APPLIED → INTERVIEWING → OFFER / REJECTED (+ REJECTED→APPLIED
    # revival). SCORED/CHATTING were removed (never produced in the live flow).
    FOUND        = "FOUND"
    APPLIED      = "APPLIED"
    INTERVIEWING = "INTERVIEWING"
    OFFER        = "OFFER"
    REJECTED     = "REJECTED"


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    city: str
    salary: str
    url: str
    jd_text: str
    source_keyword: str
    discovered_at: str   # ISO8601
    hr_name: str = ""
    status: str = AppStatus.FOUND.value


@dataclass
class ScoreResult:
    job_id: str
    score: int                       # 0-100
    decision: str                    # "apply" | "skip"
    reason: str
    resume_patch: dict               # {"summary": str, "highlights": list}
    raw_response: str
    provider_used: str


@dataclass
class CriticResult:
    job_id: str
    verdict: str                     # "approve" | "reject"
    reason: str
    raw_response: str
    provider_used: str


@dataclass
class ApplicationRecord:
    job_id: str
    title: str
    company: str
    url: str = ""
    status: str = AppStatus.FOUND.value
    hr_name: Optional[str] = None
    city: Optional[str] = None
    salary: Optional[str] = None
    score: Optional[int] = None
    applied_at: Optional[str] = None
    created_at: str = ""


@dataclass
class StatusUpdate:
    job_id: str
    company: str
    new_status: str
    message: str
    updated_at: str
    chat_url: str = ""
    is_ad_push: bool = False


@dataclass
class HRConversation:
    conv_id: str               # sha256(hr_name|company|hr_title)[:12]
    hr_name: str
    company: str
    stage: str = "new"         # new|active|resume_sent|interview|offer|closed
    job_id: Optional[str] = None
    boss_conv_id: str = ""
    intent: Optional[str] = None
    reply_status: Optional[str] = None   # null|pending|approved
    reply_text: Optional[str] = None     # working reply; cleared after send
    last_msg_preview: str = ""           # DOM preview for dirty-check
    hr_title: str = ""                   # HR's own job title (e.g. 人力资源岗)
    wechat_dismissed: bool = False       # user dismissed the go-add-WeChat reminder
    last_msg_ts: int = 0                 # getGeekFriendList.lastTS (ms); scan-time last-message time
    last_analyzed_ts: int = 0            # last message ts we SUCCESSFULLY analyzed up to (dirty watermark)
    resume_status: Optional[str] = None  # null|queued — manual "queue a resume" intent; W3 delivers then clears
    # v2.18: W2 按岗位选出的「该发哪一份简历」（只选不写，Agent 不生成内容）
    matched_resume: str = ""
    matched_resume_reason: str = ""
    created_at: str = ""


@dataclass
class ChatScanResult:
    total_convs: int
    unread_count: int
    needs_sync: List[dict]     # [{conv_id, hr_name, company, last_msg_preview, item_idx, reason}]


class W1Action(str, Enum):
    FULL_PIPELINE = "full_pipeline"   # 未处理，走全流程（fetch → score → apply）
    APPLY_ONLY    = "apply_only"      # SCORED+decision=apply，跳过评分直接打招呼
    SKIP          = "skip"            # 已完成或已拒绝，不处理


class CardSignal(str, Enum):
    APPLIED = "applied"   # 已投递，继续搜索
    SKIPPED = "skipped"   # 已跳过，继续搜索
    STOP    = "stop"      # 停止搜索，browser 立即退出循环
