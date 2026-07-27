"""Wave identifiers for concurrent render generation groups."""

from __future__ import annotations

from top_down_planning.models import RenderManifestItem


def assign_wave_ids(items: list[RenderManifestItem]) -> list[str]:
    if not items:
        return []
    return [_wave_id(item.wave, item.generation_group) for item in items]


def _wave_id(wave: int, generation_group: int) -> str:
    return f"render-wave-{wave:03d}-group-{generation_group:03d}"
