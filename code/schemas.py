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
class PendingApplication:
    """Layer 2 (人工审批) record for the multi-site apply architecture. `fields` is a
    JSON-serializable list of {field_id, label, kind, candidate_value}; kind is one of
    demographic/open_question/government_id. government_id fields never carry a
    candidate_value -- Layer 1 only flags them, the reviewer fills them by hand."""
    id: Optional[int]
    site_name: str
    job_title: str
    fields: list             # [{field_id, label, kind, candidate_value}]
    company: str = ""
    job_url: str = ""
    status: str = "pending"  # pending|approved|rejected
    reason: Optional[str] = None
    created_at: str = ""
    decided_at: Optional[str] = None


@dataclass
class PendingJob:
    """Checkpoint 1 记录：选岗 agent 找到的一个候选岗位，等人工审批。

    这是四层架构里**第一个**人工确认点（第二个是 PendingApplication 的字段审批）。
    拆成两个 checkpoint 的理由：选错岗和填错字段是两类完全不同的错误，混在一条
    记录里审，人就得同时判断"这岗位该不该投"和"这些值填得对不对"，前者一旦判错
    后者审得再仔细也没用。

    **`category` 与 `category_agent` 是两列，不是冗余**：`category_agent` 是选岗
    agent 最初自报的类别、永不覆写；`category` 是当前值（人改过就是人改的）。只留
    一列的话，人一改，"agent 原本报的是什么"当场蒸发——而两列不等的行正好是一批
    带标注的纠错样本。配额是按类别算的，而类别只能由 agent 自报（只有它看过页面），
    所以它归错类就能占掉别的类的额度；人工纠正是这条链上唯一的纠错点。
    """
    id: Optional[int]
    site_name: str
    url: str
    title: str = ""
    company: str = ""
    category: str = ""        # 当前类别（人可改）
    category_agent: str = ""  # agent 最初自报，永不覆写
    why: str = ""             # 一句话说明对上了哪几条条件
    status: str = "pending"   # pending|approved|rejected
    reason: Optional[str] = None
    found_at: str = ""
    decided_at: Optional[str] = None
    # 审批人确认"这条纠正是对的，拿去教 agent"。跟"顺手改了个类别"刻意分开：
    # 随手一改不见得是标准案例，只有确认过的才够格进 prompt。
    is_golden: bool = False


@dataclass
class SiteLimit:
    """某个站点对"一个人最多能投几个岗位"的限制，由选岗 agent 在浏览时顺带发现。

    **`status` 是三态，不是"limit 为空就代表没限制"**。这是本类存在的全部理由：
    如果只存一个数字，`None` 会同时意味着"这个站不限量"和"我们没找到相关说明"，
    页面上就会显示成"无限制"，然后人放心批准十个——而真实上限可能是 3。
    找不到就是 unknown，必须跟 no_limit 分开显示。

    `evidence` 存页面原文，不是 agent 的转述："agent 说上限是 3"和"页面上写着
    「校招每人最多投递 3 个岗位」"是两回事，前者没法核对。

    `applied_count` 是机会性的（很多站会把"已投递 1/3"跟上限写在一起）：-1 表示
    没看到。它会随时间变化，看到的那一刻起就在过期，只作参考不作依据。
    """
    site_name: str
    status: str = "unknown"          # unknown | no_limit | limited
    max_applications: Optional[int] = None   # 只在 status='limited' 时有意义
    applied_count: int = -1          # -1 = 没看到
    evidence: str = ""               # 页面原文
    seen_at: str = ""


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
