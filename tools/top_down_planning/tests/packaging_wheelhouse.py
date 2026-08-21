"""Offline wheelhouse resolution for packaging integration smoke tests."""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from pathlib import Path

_ENV_VAR = "TDP_PACKAGING_WHEELHOUSE"
_REQUIRED_PRODUCT_WHEEL_PREFIXES = ("core_tools", "top_down_planning")
_BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_packaging_wheelhouse.py"


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


def _load_build_packaging_wheelhouse() -> Callable[[Path], Path]:
    spec = importlib.util.spec_from_file_location(
        "tdp_build_packaging_wheelhouse",
        _BUILD_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise PackagingWheelhouseError(f"cannot load {_BUILD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_packaging_wheelhouse


def _default_build(destination: Path) -> Path:
    return _load_build_packaging_wheelhouse()(destination)


def ensure_packaging_wheelhouse(
    *,
    env_var: str = _ENV_VAR,
    destination: Path | None = None,
    build: Callable[[Path], Path] | None = None,
) -> Path:
    """Return a valid wheelhouse, building one when the env var is unset.

    Used by packaging smoke so ``python -m pytest -o addopts='' tests`` is
    self-contained on a clean checkout. ``resolve_packaging_wheelhouse()``
    stays strict and does not build.
    """

    if os.environ.get(env_var):
        return resolve_packaging_wheelhouse(env_var)

    target = destination or Path(__file__).resolve().parents[1] / "temp" / "tdp-packaging-wheelhouse"
    builder = build or _default_build
    built = Path(builder(target)).expanduser().resolve()
    os.environ[env_var] = str(built)
    return resolve_packaging_wheelhouse(env_var)
