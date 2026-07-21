"""Content fingerprint for W1 job dedup.

Boss 的 encryptJobId 会随搜索会话轮换——同一岗位重新刷到时 job_id 完全不同，导致
按 job_id 去重漏判、重复投递。内容指纹用「规范化标题 + 公司加密id + 规范化JD」的
SHA256 作为稳定身份：同一岗位原样重发 → JD 一字不差 → hash 相同；真不同的同名岗
（如大厂多个同名职位）→ JD 不同 → hash 不同，不会误合并。

规范化（去空白 + 小写）先行，避免读取时的空白/异步渲染抖动改变 hash。局限：Boss
改写了 JD 文案则 hash 变（只挡"一字不差重发"，挡不住"改写重发"）。
"""
import hashlib
import re

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Whitespace-insensitive, case-folded normalize for stable fingerprinting."""
    return _WS.sub("", (s or "")).lower()


def compute_content_hash(title: str, company_id: str, jd_text: str) -> str:
    """Stable content fingerprint of a job posting (hex sha256)."""
    basis = normalize_text(title) + "|" + (company_id or "").strip() + "|" + normalize_text(jd_text)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
