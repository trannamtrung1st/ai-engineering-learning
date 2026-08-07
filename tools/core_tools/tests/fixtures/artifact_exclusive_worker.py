"""Spawn-safe workers for exclusive artifact creation concurrency tests."""

from __future__ import annotations


def exclusive_create_worker(
    artifact_path: str,
    payload: bytes,
    result_queue,
    barrier,
) -> None:
    from pathlib import Path

    from core_tools.persistence import exclusive_create_bytes

    barrier.wait()
    path = Path(artifact_path)
    try:
        exclusive_create_bytes(path, payload)
        result_queue.put("ok")
    except FileExistsError:
        result_queue.put("conflict")
