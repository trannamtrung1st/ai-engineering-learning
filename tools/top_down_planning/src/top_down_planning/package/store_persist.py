"""Persist prepared packages inside the run store for resume/attach durability."""

from __future__ import annotations

import fcntl
import shutil
import uuid
from pathlib import Path

from core_tools.persistence import PersistenceError

from top_down_planning.package.loader import (
    ExecutionPackageError,
    ExecutionPackageLoader,
    LoadedExecutionPackage,
)
from top_down_planning.persistence.path_ids import validate_store_id


def _validated_package_id(package_id: str) -> str:
    try:
        return validate_store_id(str(package_id or ""), label="package_id")
    except PersistenceError as exc:
        raise ExecutionPackageError(str(exc), code="package_id_invalid") from exc


def package_store_dir(store_root: Path, package_id: str) -> Path:
    validated = _validated_package_id(package_id)
    package_root = (Path(store_root) / ".execution_packages").resolve()
    target = (package_root / validated).resolve()
    try:
        target.relative_to(package_root)
    except ValueError as exc:
        raise ExecutionPackageError(
            f"package_id escapes execution package root: {package_id!r}",
            code="package_id_path_escape",
        ) from exc
    return target


def _contained_under(package_root: Path, candidate: Path, *, label: str) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as exc:
        raise ExecutionPackageError(
            f"{label} escapes execution package root: {candidate}",
            code="package_id_path_escape",
        ) from exc
    return resolved


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

    package_id = _validated_package_id(str(package.manifest.get("package_id") or ""))
    package_digest = str(package.manifest.get("package_digest") or "").strip()
    if not package_digest:
        raise ValueError("package_id and package_digest are required to persist a package")

    source_dir = package.manifest_path.parent.resolve()
    package_root = (Path(store_root) / ".execution_packages").resolve()
    target_dir = package_store_dir(store_root, package_id)
    target_manifest = target_dir / "manifest.json"
    lock_path = _contained_under(
        package_root,
        package_root / f".{package_id}.lock",
        label="package lock",
    )

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

            staging = _contained_under(
                package_root,
                package_root / f".staging-{package_id}-{uuid.uuid4().hex[:8]}",
                label="package staging",
            )
            backup: Path | None = None
            try:
                if staging.exists():
                    shutil.rmtree(staging)
                shutil.copytree(source_dir, staging)
                ExecutionPackageLoader().load(staging, verify_workspace=False)
                if target_dir.exists():
                    backup = _contained_under(
                        package_root,
                        package_root / f".backup-{package_id}-{uuid.uuid4().hex[:8]}",
                        label="package backup",
                    )
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


def assert_manifest_path_in_store(
    store_root: Path,
    manifest_path: Path,
    *,
    package_id: str | None = None,
) -> Path:
    """Require ``manifest_path`` to live under ``.execution_packages/`` (optionally under package_id)."""

    package_root = (Path(store_root) / ".execution_packages").resolve()
    resolved = Path(manifest_path).resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as exc:
        raise ExecutionPackageError(
            f"manifest_path escapes execution package root: {manifest_path}",
            code="package_id_path_escape",
        ) from exc
    if package_id:
        expected_dir = package_store_dir(store_root, package_id)
        try:
            resolved.relative_to(expected_dir)
        except ValueError as exc:
            raise ExecutionPackageError(
                f"manifest_path is outside package {package_id!r}: {manifest_path}",
                code="package_id_path_escape",
            ) from exc
    return resolved


__all__ = ["assert_manifest_path_in_store", "package_store_dir", "persist_package_in_store"]
