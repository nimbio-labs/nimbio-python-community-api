"""Server-Sent-Events plumbing shared by the sync and async stream consumers.

Only what the Nimbio stream emits is supported: ``id`` / ``event`` / ``data``
fields, ``:`` comment lines (heartbeats), and blank-line dispatch. The parser
is incremental — feed it lines, it returns a frame dict when one completes.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Union

from .models import StreamEvent, StreamReset

# The server heartbeats every ~25s; three missed beats means the connection is
# dead and the read should time out so the consumer can reconnect.
STREAM_READ_TIMEOUT = 90.0
RECONNECT_BACKOFF_BASE = 0.5   # seconds; doubles per consecutive failure
RECONNECT_BACKOFF_MAX = 30.0

STREAM_PATH = "/v1/events/stream"


def stream_params(events: Any = None,
                  last_event_id: Optional[str] = None) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if events:
        params["events"] = ",".join(events)
    if last_event_id:
        params["last_event_id"] = last_event_id
    return params


def backoff_delay(attempt: int) -> float:
    return min(RECONNECT_BACKOFF_MAX, RECONNECT_BACKOFF_BASE * (2 ** attempt))


class SSEParser:
    """Incremental SSE frame assembler."""

    def __init__(self) -> None:
        self._id: Optional[str] = None
        self._event: Optional[str] = None
        self._data_lines: list = []

    def feed(self, line: str) -> Optional[Dict[str, Any]]:
        """Feed one line (without its trailing newline). Returns the completed
        frame on a dispatching blank line, else None."""
        if line == "":
            if self._id is None and self._event is None and not self._data_lines:
                return None  # stray blank line (e.g. after a comment)
            frame = {
                "id": self._id,
                "event": self._event,
                "data": "\n".join(self._data_lines),
            }
            self._id = None
            self._event = None
            self._data_lines = []
            return frame
        if line.startswith(":"):
            return None  # comment / heartbeat
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "id":
            self._id = value
        elif field == "event":
            self._event = value
        elif field == "data":
            self._data_lines.append(value)
        return None


def frame_to_model(frame: Dict[str, Any]) -> Optional[Union[StreamEvent, StreamReset]]:
    """Convert a parsed frame into a model, or None for unusable frames."""
    event_type = frame.get("event")
    if event_type == "stream.reset":
        try:
            reason = json.loads(frame.get("data") or "{}").get("reason")
        except ValueError:
            reason = None
        return StreamReset(reason=reason)
    if not frame.get("id") or not event_type:
        return None
    try:
        data = json.loads(frame.get("data") or "{}")
    except ValueError:
        return None
    return StreamEvent(id=frame["id"], type=event_type,
                       data=data if isinstance(data, dict) else {})
