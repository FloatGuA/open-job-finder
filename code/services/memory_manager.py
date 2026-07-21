"""
Memory manager: handles short-term (session) and long-term (persistent) memory.

Short-term: data/memory/sessions/YYYY-MM-DD_HH-MM-SS.json
  - Full conversation history for the current session
  - Auto-compressed when recent > MAX_RECENT messages

Long-term: data/memory/long_term.yaml
  - User preferences, constraints, context facts
  - Only written on explicit user request ("记住 xxx")
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

MEMORY_DIR = Path("data/memory")
LONG_TERM_PATH = MEMORY_DIR / "long_term.yaml"
SESSIONS_DIR = MEMORY_DIR / "sessions"
MAX_RECENT = 20
COMPRESS_BATCH = 10
VALID_CATEGORIES = {"preferences", "constraints", "context"}


class MemoryManager:
    def load_long_term(self) -> str:
        """Return long-term memory as a formatted text block for system prompt injection."""
        if not LONG_TERM_PATH.exists():
            return ""
        try:
            with LONG_TERM_PATH.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return ""

        lines = []
        for category in ("preferences", "constraints", "context"):
            entries = data.get(category, [])
            if entries:
                lines.append(f"[{category}]")
                for e in entries:
                    lines.append(f"  - {e.get('fact', '')}")
        if "history_summary" in data:
            lines.append("[history]")
            for h in data["history_summary"][-3:]:  # last 3 days
                lines.append(f"  - {h.get('date', '')}: {h.get('summary', '')}")
        return "\n".join(lines)

    def save_long_term(self, fact: str, category: str) -> None:
        """Append a new fact to long-term memory. Only call on explicit user request."""
        if not fact:
            return
        if category not in VALID_CATEGORIES:
            category = "context"

        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if LONG_TERM_PATH.exists():
            with LONG_TERM_PATH.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        entry = {
            "fact": fact,
            "added_at": datetime.now().strftime("%Y-%m-%d"),
            "source": "user_stated",
        }
        data.setdefault(category, []).append(entry)

        with LONG_TERM_PATH.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def new_session(self) -> dict:
        """Create a new empty session object."""
        session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return {
            "session_id": session_id,
            "started_at": datetime.now().isoformat(),
            "summary": "",
            "recent": [],
        }

    def load_today_session(self) -> dict | None:
        """Load the most recent session from today, or return None."""
        if not SESSIONS_DIR.exists():
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        matches = sorted(SESSIONS_DIR.glob(f"{today}_*.json"), reverse=True)
        if not matches:
            return None
        try:
            with matches[0].open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def append_message(self, session: dict, role: str, content: Any) -> None:
        """Append a message to session recent history, compressing if needed."""
        session["recent"].append({"role": role, "content": content})
        if len(session["recent"]) > MAX_RECENT:
            self._compress(session)

    def _compress(self, session: dict, ollama_client=None) -> None:
        """Compress oldest COMPRESS_BATCH messages into summary."""
        batch = session["recent"][:COMPRESS_BATCH]
        session["recent"] = session["recent"][COMPRESS_BATCH:]

        # Build text summary of the batch
        lines = []
        for msg in batch:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)
            lines.append(f"{role}: {content}")
        batch_text = "\n".join(lines)

        if session["summary"]:
            session["summary"] += "\n" + batch_text
        else:
            session["summary"] = batch_text

    def save_session(self, session: dict) -> None:
        """Persist session to disk."""
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSIONS_DIR / f"{session['session_id']}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

    def get_context_messages(self, session: dict) -> list[dict]:
        """Return messages list for Ollama (OpenAI format), with summary prepended."""
        messages = []
        if session.get("summary"):
            messages.append({
                "role": "assistant",
                "content": f"[之前的对话摘要]\n{session['summary']}",
            })
        for msg in session["recent"]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)
            messages.append({"role": role, "content": str(content)})
        return messages
