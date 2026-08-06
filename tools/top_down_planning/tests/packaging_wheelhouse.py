"""Offline wheelhouse resolution for packaging integration smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "TDP_PACKAGING_WHEELHOUSE"
_REQUIRED_PRODUCT_WHEEL_PREFIXES = ("core_tools", "top_down_planning")


class PackagingWheelhouseError(RuntimeError):
    """Raised when the packaging wheelhouse environment is missing or invalid."""


def resolve_packaging_wheelhouse(env_var: str = _ENV_VAR) -> Path:
    """Return the pre-built offline wheelhouse path from the environment."""

    configured = os.environ.get(env_var)
    if not configured:
        raise PackagingWheelhouseError(
            f"{env_var} is required. "
            "Run scripts/build_packaging_wheelhouse.py before packaging integration tests."
        )

    wheelhouse = Path(configured).expanduser().resolve()
    if not wheelhouse.is_dir():
        if wheelhouse.exists():
            raise PackagingWheelhouseError(f"{env_var} is not a directory: {wheelhouse}")
        raise PackagingWheelhouseError(f"{env_var} does not exist: {wheelhouse}")

    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise PackagingWheelhouseError(f"{env_var} has no wheels: {wheelhouse}")

    wheel_names = {wheel.name for wheel in wheels}
    missing_products = [
        prefix
        for prefix in _REQUIRED_PRODUCT_WHEEL_PREFIXES
        if not any(name.startswith(prefix) for name in wheel_names)
    ]
    if missing_products:
        raise PackagingWheelhouseError(
            f"{env_var} is missing product wheels "
            f"({', '.join(missing_products)}): {wheelhouse}"
        )

    return wheelhouse
