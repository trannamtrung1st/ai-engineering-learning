"""Persist prepared packages inside the run store for resume/attach durability."""

from __future__ import annotations

import fcntl
import shutil
import uuid
from pathlib import Path

from top_down_planning.package.loader import (
    ExecutionPackageError,
    ExecutionPackageLoader,
    LoadedExecutionPackage,
)


def package_store_dir(store_root: Path, package_id: str) -> Path:
    return (store_root / ".execution_packages" / package_id).resolve()


def persist_package_in_store(
    store_root: Path,
    package: LoadedExecutionPackage,
) -> Path:
    """
    Copy the loaded package under ``<runs-root>/.execution_packages/<package_id>/``.

    Returns the persisted ``manifest.json`` path. Idempotent when the target
    already contains the same package_id and package_digest. Rejects collision
    when the same package_id exists with a different digest. Rejects replacement
    when the same package_id exists with a different digest.
    """

    package_id = str(package.manifest.get("package_id") or "").strip()
    package_digest = str(package.manifest.get("package_digest") or "").strip()
    if not package_id or not package_digest:
        raise ValueError("package_id and package_digest are required to persist a package")

    source_dir = package.manifest_path.parent.resolve()
    target_dir = package_store_dir(store_root, package_id)
    target_manifest = target_dir / "manifest.json"
    lock_path = target_dir.parent / f".{package_id}.lock"

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if target_manifest.is_file():
                loaded = ExecutionPackageLoader().load(target_dir, verify_workspace=False)
                existing_id = str(loaded.manifest.get("package_id") or "")
                existing_digest = str(loaded.manifest.get("package_digest") or "")
                if existing_id == package_id and existing_digest == package_digest:
                    return target_manifest
                if existing_id == package_id and existing_digest != package_digest:
                    raise ExecutionPackageError(
                        f"package_id {package_id!r} already persisted with digest "
                        f"{existing_digest}; refusing to replace with {package_digest}",
                        code="package_id_collision",
                    )

            if source_dir == target_dir:
                return target_manifest

            staging = target_dir.parent / f".staging-{package_id}-{uuid.uuid4().hex[:8]}"
            backup: Path | None = None
            try:
                if staging.exists():
                    shutil.rmtree(staging)
                shutil.copytree(source_dir, staging)
                ExecutionPackageLoader().load(staging, verify_workspace=False)
                if target_dir.exists():
                    backup = target_dir.parent / f".backup-{package_id}-{uuid.uuid4().hex[:8]}"
                    target_dir.rename(backup)
                staging.rename(target_dir)
                if backup is not None and backup.exists():
                    shutil.rmtree(backup)
                return target_manifest
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                if backup is not None and backup.exists() and not target_dir.exists():
                    backup.rename(target_dir)
                raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


__all__ = ["package_store_dir", "persist_package_in_store"]
