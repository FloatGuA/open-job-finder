"""Listing + deletion of on-disk artifacts that accumulate real HR/company PII and
are never auto-cleaned: failed-run JSONL logs (logs/runs/) and W1 apply-failure
screenshots (data/apply_failures/). precommit_pii_scan.py only guards what goes
into git; it has no reach here -- these files live only on disk and grow without
bound on a long-running unattended machine.

Sibling to run_log_reader.py (also reads run JSONL) but that module is explicitly
read-only by its own docstring; deletion is kept in a separate module rather than
expanding that one's stated scope.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services import run_log_reader

# Run statuses that mean "this run did not complete cleanly" -- the set of things
# worth surfacing for manual review/cleanup. Successful runs are left alone: they
# still have ongoing debugging/regression value (see docs/audit-remediation-log.md).
_FAILURE_STATUSES = {"failed", "error", "aborted", "stopped"}

# capture_screenshot.py names files "{run_id}_{job_id}_{YYYYMMDD_HHMMSS}.png". Both
# run_id and job_id can themselves contain underscores/digits, so the only reliably
# parseable part is the trailing timestamp -- everything before it is shown as-is
# rather than guessing at an internal split that could misattribute a job_id.
_SCREENSHOT_TS_RE = re.compile(r"^(?P<label>.+)_(?P<ts>\d{8}_\d{6})\.png$")


def list_failed_run_logs(runs_dir: Path) -> list[dict[str, Any]]:
    """Run JSONL logs whose last recorded status is a failure (see
    _FAILURE_STATUSES). Reuses run_log_reader.summarize_run_file for the status/
    started_at parsing -- one source of truth for "what does this run's last event
    say" instead of a second JSONL reader here."""
    items: list[dict[str, Any]] = []
    for path in run_log_reader.iter_run_files(runs_dir):
        summary = run_log_reader.summarize_run_file(path)
        if summary is None or summary["status"] not in _FAILURE_STATUSES:
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        items.append({**summary, "size_bytes": size_bytes})
    items.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return items


def list_apply_failure_screenshots(apply_failures_dir: Path) -> list[dict[str, Any]]:
    if not apply_failures_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in apply_failures_dir.glob("*.png"):
        m = _SCREENSHOT_TS_RE.match(path.name)
        label = m.group("label") if m else path.stem
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append({
            "filename": path.name,
            "label": label,
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _safe_delete(directory: Path, filename: str, suffix: str) -> bool:
    # Same path-traversal guard as the existing /api/apply-failure/{name} serve
    # endpoint: bare filename only, correct extension, no separators/"..".
    if "/" in filename or "\\" in filename or ".." in filename or not filename.endswith(suffix):
        return False
    path = directory / filename
    if not path.exists():
        return False
    path.unlink()
    return True


def delete_run_log(runs_dir: Path, filename: str) -> bool:
    return _safe_delete(runs_dir, filename, ".jsonl")


def delete_screenshot(apply_failures_dir: Path, filename: str) -> bool:
    return _safe_delete(apply_failures_dir, filename, ".png")
