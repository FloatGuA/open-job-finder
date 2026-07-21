import re


def extract_job_id(url: str) -> str:
    if not url:
        return ""
    cleaned = url.split("?", 1)[0].rstrip("/")
    match = re.search(r"/job_detail/([^/.]+)", cleaned)
    if match:
        return match.group(1)
    if "conversationId=" in url:
        return ""
    tail = cleaned.rsplit("/", 1)[-1]
    return tail.replace(".html", "")


def extract_company_id(url: str) -> str:
    """Extract Boss 公司加密id from a /gongsi/{id}.html link.

    Unlike the per-job encryptJobId, the company encrypt id is stable (company-level),
    so it's a reliable component of the content-dedup fingerprint. Strips the query and
    the `~~`/`~` padding Boss appends.
    """
    if not url:
        return ""
    cleaned = url.split("?", 1)[0].rstrip("/")
    match = re.search(r"/gongsi/([^/.]+)", cleaned)
    if match:
        return match.group(1).rstrip("~")
    return ""


def extract_city(job_info: str) -> str:
    if not job_info:
        return ""
    for separator in ("路", "|", "/", " "):
        parts = [part.strip() for part in job_info.split(separator) if part.strip()]
        if parts:
            return parts[0]
    return job_info.strip()
