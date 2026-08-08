"""Build a local wheelhouse for offline packaging smoke tests.

Requires runtime and build dependencies to be importable or wheelable from the
active environment (CI installs editable dev packages before invoking this script).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_paths() -> tuple[Path, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    core_tools_root = project_root.parent / "core_tools"
    repo_root = project_root.parent.parent
    return repo_root, project_root, core_tools_root


def build_packaging_wheelhouse(destination: Path) -> Path:
    """Populate ``destination`` with product wheels and transitive runtime/build deps."""

    destination.mkdir(parents=True, exist_ok=True)
    _, project_root, core_tools_root = _repo_paths()

    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(destination), str(core_tools_root)],
        check=True,
        stdout=sys.stderr,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(destination), str(project_root)],
        check=True,
        stdout=sys.stderr,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "build",
            "hatchling",
            "editables",
            "pytest",
            "jinja2",
            "pathspec",
            "rich",
            "-w",
            str(destination),
        ],
        check=True,
        stdout=sys.stderr,
    )
    return destination.resolve()


def _default_wheelhouse_destination() -> Path:
    _, project_root, _ = _repo_paths()
    return project_root / "temp" / "tdp-packaging-wheelhouse"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination",
        type=Path,
        nargs="?",
        default=None,
        help="Wheelhouse directory (default: <package>/temp/tdp-packaging-wheelhouse)",
    )
    args = parser.parse_args(argv)
    destination = args.destination or _default_wheelhouse_destination()
    wheelhouse = build_packaging_wheelhouse(destination)
    print(wheelhouse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
