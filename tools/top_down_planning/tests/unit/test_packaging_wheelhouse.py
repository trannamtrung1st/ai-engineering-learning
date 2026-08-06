"""Unit tests for offline packaging wheelhouse resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.packaging_wheelhouse import PackagingWheelhouseError, resolve_packaging_wheelhouse


def _write_product_wheels(directory: Path) -> None:
    (directory / "core_tools-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (directory / "top_down_planning-0.1.0-py3-none-any.whl").write_bytes(b"wheel")


def test_resolve_packaging_wheelhouse_requires_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TDP_PACKAGING_WHEELHOUSE", raising=False)

    with pytest.raises(PackagingWheelhouseError, match="TDP_PACKAGING_WHEELHOUSE is required"):
        resolve_packaging_wheelhouse()


def test_resolve_packaging_wheelhouse_rejects_nonexistent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-wheelhouse"
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(missing))

    with pytest.raises(PackagingWheelhouseError, match="does not exist"):
        resolve_packaging_wheelhouse()


def test_resolve_packaging_wheelhouse_rejects_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "not-a-directory.whl"
    file_path.write_bytes(b"wheel")
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(file_path))

    with pytest.raises(PackagingWheelhouseError, match="is not a directory"):
        resolve_packaging_wheelhouse()


def test_resolve_packaging_wheelhouse_rejects_empty_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty-wheelhouse"
    empty.mkdir()
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(empty))

    with pytest.raises(PackagingWheelhouseError, match="has no wheels"):
        resolve_packaging_wheelhouse()


def test_resolve_packaging_wheelhouse_rejects_missing_product_wheels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    partial = tmp_path / "partial-wheelhouse"
    partial.mkdir()
    (partial / "jinja2-3.1.6-py3-none-any.whl").write_bytes(b"wheel")
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(partial))

    with pytest.raises(PackagingWheelhouseError, match="missing product wheels"):
        resolve_packaging_wheelhouse()


def test_resolve_packaging_wheelhouse_accepts_valid_wheelhouse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _write_product_wheels(wheelhouse)
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(wheelhouse))

    resolved = resolve_packaging_wheelhouse()

    assert resolved == wheelhouse.resolve()
    assert os.environ["TDP_PACKAGING_WHEELHOUSE"] == str(wheelhouse)


def test_resolve_packaging_wheelhouse_does_not_launch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _write_product_wheels(wheelhouse)
    monkeypatch.setenv("TDP_PACKAGING_WHEELHOUSE", str(wheelhouse))

    def _forbidden_subprocess(*_args, **_kwargs):
        raise AssertionError("resolve_packaging_wheelhouse must not launch subprocesses")

    monkeypatch.setattr("subprocess.run", _forbidden_subprocess)
    monkeypatch.setattr("subprocess.Popen", _forbidden_subprocess)

    resolved = resolve_packaging_wheelhouse()

    assert resolved == wheelhouse.resolve()
