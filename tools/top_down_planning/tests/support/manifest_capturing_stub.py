"""Stub provider that records reviewer session manifests for recovery regressions."""

from __future__ import annotations

import copy
from typing import Any

from core_tools.provider import StubProvider


class ManifestCapturingStubProvider(StubProvider):
    """Record manifests passed to ``start_reviewer_session``."""

    def __init__(self) -> None:
        super().__init__()
        self.reviewer_session_manifests: list[dict[str, Any]] = []

    def start_reviewer_session(
        self,
        manifest: dict[str, Any],
        *,
        model: str | None = None,
    ) -> str:
        self.reviewer_session_manifests.append(copy.deepcopy(manifest))
        return super().start_reviewer_session(manifest, model=model)
