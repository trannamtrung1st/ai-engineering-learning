"""Persist prepared packages inside the run store for resume/attach durability."""

from __future__ import annotations

import shutil
from pathlib import Path

from top_down_planning.package.loader import ExecutionPackageLoader, LoadedExecutionPackage


def package_store_dir(store_root: Path, package_id: str) -> Path:
    return (store_root / ".execution_packages" / package_id).resolve()


def persist_package_in_store(
    store_root: Path,
    package: LoadedExecutionPackage,
) -> Path:
    """
    Copy the loaded package under ``<runs-root>/.execution_packages/<package_id>/``.

    Returns the persisted ``manifest.json`` path. Idempotent when the target
    already contains the same package_id and package_digest.
    """

    package_id = str(package.manifest.get("package_id") or "").strip()
    package_digest = str(package.manifest.get("package_digest") or "").strip()
    if not package_id or not package_digest:
        raise ValueError("package_id and package_digest are required to persist a package")

    source_dir = package.manifest_path.parent.resolve()
    target_dir = package_store_dir(store_root, package_id)
    target_manifest = target_dir / "manifest.json"

    if target_manifest.is_file():
        loaded = ExecutionPackageLoader().load(target_dir, verify_workspace=False)
        if (
            str(loaded.manifest.get("package_id") or "") == package_id
            and str(loaded.manifest.get("package_digest") or "") == package_digest
        ):
            return target_manifest

    if source_dir == target_dir:
        return target_manifest

    staging = target_dir.parent / f".staging-{package_id}"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source_dir, staging)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    staging.rename(target_dir)
    return target_manifest


__all__ = ["package_store_dir", "persist_package_in_store"]
