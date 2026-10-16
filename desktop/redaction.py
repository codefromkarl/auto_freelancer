"""In-memory log redaction; logging must never re-enter a locked OS vault."""

import re
import threading

_values = set()
_guard = threading.Lock()


def remember(value):
    if isinstance(value, str) and value:
        with _guard:
            _values.add(value)
    return value


def redact(message):
    with _guard:
        values = tuple(_values)
    for value in values:
        message = message.replace(value, "[REDACTED]")
        if len(value) >= 10:
            message = re.sub(
                re.escape(value[:8]) + r"[A-Za-z0-9_*.-]*", "[REDACTED]", message
            )
    return message
