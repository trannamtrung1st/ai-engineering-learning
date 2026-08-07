"""Atomic file writes for crash-safe persistence (proposal §18)."""

from __future__ import annotations

import errno
import json
import os
import uuid
from pathlib import Path
from typing import Any


def _write_fd_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short write while persisting bytes")
        offset += written


def exclusive_create_bytes(path: Path, data: bytes) -> None:
    """Create ``path`` with ``data``; fail if the file already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.create-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            _write_fd_all(fd, data)
        finally:
            os.close(fd)
        if tmp_path.read_bytes() != data:
            raise OSError("temporary artifact write incomplete")
        try:
            os.link(tmp_path, path)
        except FileExistsError as exc:
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(path)) from exc
        if path.read_bytes() != data:
            raise OSError("published artifact content mismatch")
    finally:
        tmp_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes via a temp file and atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_text_secure(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write text via a private temp file created with ``mode``, then atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    tmp_path = path.with_name(
        f".{path.name}.secure-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    try:
        fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        try:
            _write_fd_all(fd, data)
        finally:
            os.close(fd)
        if tmp_path.read_bytes() != data:
            raise OSError("temporary secure write incomplete")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)
