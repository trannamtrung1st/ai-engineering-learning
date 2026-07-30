"""Shared multiline formatting helpers."""

from __future__ import annotations


def format_multiline_body(
    message: str,
    *,
    prefix_width: int,
    continuation_indent: int = 2,
) -> str:
    """Format *message* with continuation lines aligned under the body.

    The first line is returned without a prefix; callers attach the timestamp/tag
    prefix to the first line only.
    """

    lines = message.splitlines() or [""]
    if len(lines) == 1:
        return lines[0]

    first = lines[0]
    pad = " " * (prefix_width + continuation_indent)
    rest = "\n".join(f"{pad}{line}" if line else pad.rstrip() for line in lines[1:])
    return f"{first}\n{rest}"


def prefix_width(*, show_timestamps: bool, tag: str) -> int:
    """Compute rendered prefix width for continuation alignment."""

    ts_part = "[00:00:00] " if show_timestamps else ""
    return len(ts_part) + len(f"[{tag}] ")
