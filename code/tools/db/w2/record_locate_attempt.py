from tools.base import BaseTool, ToolResult


class RecordLocateAttempt(BaseTool):
    """Track W3's consecutive search-locate misses for a conversation and give up
    after `threshold` failures.

    A conversation can vanish from Boss's chat list (the user rejected/removed it
    manually) while an approved reply still points at it. W3's search-locate then
    fails every run forever. This tool counts consecutive misses: locating resets
    the count to 0; each miss increments it, and once it reaches the threshold the
    reply is dismissed (reply_status -> 'dismissed', a status get_approved_replies
    excludes) so W3 stops retrying an unreachable conversation.
    """

    name = "record_locate_attempt"
    description = "Count W3 locate misses per conversation; dismiss the reply after N consecutive failures."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id": {"type": "string"},
            "located": {"type": "boolean"},
            "threshold": {"type": "integer"},
        },
        "required": ["conv_id", "located"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_id: str, located: bool, threshold: int = 3) -> ToolResult:
        with self._db.conn:
            if located:
                self._db.conn.execute(
                    "UPDATE hr_conversations SET locate_fail_count = 0 WHERE conv_id = ?",
                    (conv_id,),
                )
                return ToolResult(ok=True, data={"count": 0, "given_up": False})

            self._db.conn.execute(
                "UPDATE hr_conversations SET locate_fail_count = COALESCE(locate_fail_count, 0) + 1 WHERE conv_id = ?",
                (conv_id,),
            )
            row = self._db.conn.execute(
                "SELECT locate_fail_count FROM hr_conversations WHERE conv_id = ?",
                (conv_id,),
            ).fetchone()
            count = int(row[0]) if row and row[0] is not None else 0
            given_up = count >= threshold
            if given_up:
                # Only dismiss a still-queued reply; leave already-terminal states alone.
                self._db.conn.execute(
                    """
                    UPDATE hr_conversations
                    SET reply_status = 'dismissed', reply_text = ''
                    WHERE conv_id = ? AND reply_status IN ('approved', 'revision')
                    """,
                    (conv_id,),
                )
        return ToolResult(ok=True, data={"count": count, "given_up": given_up})
