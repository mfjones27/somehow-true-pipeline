"""Pick a human-readable failure line out of a pipeline log."""
from __future__ import annotations

import re

_ERROR_LINE = re.compile(r"^(?:ERROR:\s*)(.+)$")
_NAMED = re.compile(
    r"^(?:(?:\w+\.)*?(?:Error|Exception|Failure|RuntimeError|SystemExit)):\s*(.+)$"
)


def extract_failure(log: str) -> str:
    lines = [line.strip() for line in (log or "").splitlines() if line.strip()]
    if not lines:
        return "The job failed with no log output."

    for line in reversed(lines):
        match = _ERROR_LINE.match(line)
        if match:
            return match.group(1)[:500]

    traceback_exc = ""
    in_trace = False
    for line in lines:
        if line.startswith("Traceback (most recent call last)"):
            in_trace = True
            traceback_exc = ""
            continue
        if in_trace and not line.startswith("File ") and "Error" in line:
            traceback_exc = line
    if traceback_exc:
        return traceback_exc[:500]

    for line in reversed(lines):
        match = _NAMED.match(line)
        if match:
            return line[:500]
        if "FAILED" in line and "Pipeline FAILED" not in line:
            return line[:500]
    last = lines[-1]
    if last.startswith("Pipeline FAILED"):
        return last[:500]
    return last[:500]
