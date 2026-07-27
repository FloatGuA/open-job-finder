from tools.base import BaseTool, ToolResult


class InvalidateStaleReply(BaseTool):
    """Void an approved reply W3 found stale at send time and reset the conversation
    for W2 re-analysis.

    Fires only from W3's pre-send freshness gate, when the open thread shows the
    conversation has moved on since approval (the last bubble is no longer the
    HR's). Rather than send an outdated draft to a real HR, we clear the draft +
    status and knock last_analyzed_ts back to 0 so filter_conversations re-selects
    the conversation and AnalyzeStep re-drafts into the approval queue only if a
    reply is still due. Thin shell: the single source of the SQL lives in
    tracker.invalidate_reply_for_reanalysis.
    """

    name = "invalidate_stale_reply"
    description = "Void a stale approved reply and reset the conversation for W2 re-analysis."
    input_schema = {
        "type": "object",
        "properties": {"conv_id": {"type": "string"}},
        "required": ["conv_id"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_id: str) -> ToolResult:
        return ToolResult(ok=True, data={"reset": self._db.invalidate_reply_for_reanalysis(conv_id)})
