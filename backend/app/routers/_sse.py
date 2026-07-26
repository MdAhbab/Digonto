"""Shared Server-Sent-Events formatting, used by ask.py, me.py, and vault.py.

Not one of the eleven router modules named in the build brief; kept separate
only so the exact `"event: name\\ndata: json\\n\\n"` wire format and the
standard SSE headers are written once instead of copy-pasted three times.
"""

from __future__ import annotations

import json
from typing import Any

# Every SSE response in this API sets these so a reverse proxy (nginx,
# Caddy) does not buffer the stream or time it out early.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def format_sse(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    """Render one SSE frame. `data` is always a JSON object, per every event
    payload shape in docs/api_contract.md sections 5 and 12."""
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def sse_comment(text: str = "keepalive") -> str:
    """A comment line: ignored by the EventSource client, but enough traffic
    to keep an idle proxy from closing the connection (requirement: a
    heartbeat every 15 seconds on GET /stream)."""
    return f": {text}\n\n"
