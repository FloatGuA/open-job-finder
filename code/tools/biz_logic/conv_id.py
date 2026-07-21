import hashlib


def derive_conv_id(job_id: str, hr_name: str, company: str) -> str:
    """Stable conversation identity for hr_conversations.

    Hard-association key: prefer job_id (== Boss encryptJobId, the same string
    stored in applications.job_id), so a W1 application and its W2 conversation
    share one identity without depending on the fragile hr_name+company soft key.
    Fall back to the legacy sha256(hr_name|company) only when no job_id is
    available (rare — getGeekFriendList carried encryptJobId for 100/100 probed
    conversations — e.g. an orphan system conversation).
    """
    if job_id:
        return job_id
    return hashlib.sha256(f"{hr_name}|{company}".encode()).hexdigest()[:12]
