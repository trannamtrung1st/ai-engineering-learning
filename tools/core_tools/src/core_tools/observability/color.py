"""Terminal color mode resolution."""

from __future__ import annotations

import os
import sys
from typing import Any, Literal

ColorMode = Literal["auto", "always", "never"]


def resolve_color_mode(
    *,
    color: ColorMode = "auto",
    stream: Any | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    """Return True when colorized output should be enabled."""

    if color == "never":
        return False
    if color == "always":
        return True

    env = environ if environ is not None else os.environ
    if env.get("NO_COLOR"):
        return False
    if env.get("TERM", "").lower() == "dumb":
        return False

    target = stream if stream is not None else sys.stderr
    isatty = getattr(target, "isatty", None)
    return bool(isatty and isatty())
