"""Verify Top Down Planning documentation links and known contracts.

Run from the package root::

    python scripts/check_docs.py
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from core_tools.config import load_yaml_config
from core_tools.persistence import load_yaml
from top_down_planning.config.defaults import DEFAULT_CONFIG
from top_down_planning.schema_docs import show_schema

AUTHORING_DIR_NAME = "authoring"
LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"^```")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FORBIDDEN_OK_PATTERNS = (
    re.compile(r"Continuation/resume success is `true` only for `completed`"),
    re.compile(r"Continuation success is `completed` \*\*and\*\* `accepted` only"),
    re.compile(r"Success for continuation/resume semantics is `completed`"),
    re.compile(r"`completed` plus `accepted` is the successful continuation result"),
    re.compile(r"continuation success \(`completed` \+ `accepted` only\)"),
    re.compile(r"Continuation/resume success is `completed` \*\*and\*\* `accepted` only"),
)
UNDIFFERENTIATED_RUNS_FALLBACK = re.compile(
    r"Precedence:\s*--runs-dir\s*>\s*\$TDP_RUNS_DIR\s*>\s*runtime\.runs_dir\s*>\s*\./runs",
    re.IGNORECASE,
)
PLAN_ITEM_RE = re.compile(r"item-[0-9a-f]{8,}", re.IGNORECASE)
USER_CLI_COMMANDS = (
    "run",
    "prepare",
    "execute",
    "resume",
    "status",
    "inspect",
    "validate",
    "doctor",
    "sub-tdp",
    "agent",
)
FIRST_RUN_CONFIG_REL = Path("examples") / "first-run" / "config.yaml"
CANONICAL_EXAMPLE_REL = Path("examples") / "top-down-planning.yaml"
FIRST_RUN_ARTIFACT = "greeting.txt"


def package_root_from_script() -> Path:
    return Path(__file__).resolve().parent.parent


def docs_root(package_root: Path) -> Path:
    return package_root / "docs"


def iter_markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def is_authoring_page(docs: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(docs.resolve())
    except ValueError:
        return False
    return relative.parts[:1] == (AUTHORING_DIR_NAME,)


def github_slug(heading: str) -> str:
    text = heading.strip()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*_`~\[\]()]+", "", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text


def heading_slugs(markdown: str) -> set[str]:
    counts: dict[str, int] = defaultdict(int)
    slugs: set[str] = set()
    in_fence = False
    for line in markdown.splitlines():
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match is None:
            continue
        base = github_slug(match.group(2))
        if not base:
            continue
        seen = counts[base]
        counts[base] += 1
        slugs.add(base if seen == 0 else f"{base}-{seen}")
    return slugs


def iter_markdown_targets(markdown: str) -> list[str]:
    stripped = HTML_COMMENT_RE.sub("", markdown)
    in_fence = False
    targets: list[str] = []
    for line in stripped.splitlines():
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for raw in LINK_RE.findall(line):
            target = raw.strip().strip("<>").split()[0] if raw.strip() else ""
            if target:
                targets.append(target)
    return targets


def _split_href(href: str) -> tuple[str, str | None]:
    path, _, fragment = href.partition("#")
    return path, (fragment or None)


def check_markdown_links(docs: Path) -> list[str]:
    errors: list[str] = []
    for path in iter_markdown_files(docs):
        text = path.read_text(encoding="utf-8")
        slugs_cache: dict[Path, set[str]] = {}
        for href in iter_markdown_targets(text):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, fragment = _split_href(href)
            if not file_part:
                target_file = path
            else:
                target_file = (path.parent / file_part).resolve()
            if not target_file.exists():
                rel = path.relative_to(docs)
                errors.append(f"{rel}: broken link {href!r}")
                continue
            if fragment is None:
                continue
            if target_file.suffix.lower() != ".md":
                continue
            cached = slugs_cache.get(target_file)
            if cached is None:
                cached = heading_slugs(target_file.read_text(encoding="utf-8"))
                slugs_cache[target_file] = cached
            if fragment not in cached:
                rel = path.relative_to(docs)
                errors.append(f"{rel}: missing heading fragment {href!r}")
    return errors


def public_markdown_pages(docs: Path) -> list[Path]:
    return [path for path in iter_markdown_files(docs) if not is_authoring_page(docs, path)]


def check_landing_coverage(docs: Path) -> list[str]:
    landing = docs / "README.md"
    if not landing.is_file():
        return [f"missing landing page {landing}"]
    linked: set[Path] = set()
    for href in iter_markdown_targets(landing.read_text(encoding="utf-8")):
        if href.startswith(("http://", "https://", "mailto:")):
            continue
        file_part, _fragment = _split_href(href)
        if not file_part:
            continue
        target = (landing.parent / file_part).resolve()
        try:
            target.relative_to(docs.resolve())
        except ValueError:
            continue
        if target.suffix.lower() == ".md" and target.is_file():
            linked.add(target)
    errors: list[str] = []
    for page in public_markdown_pages(docs):
        if page.resolve() == landing.resolve():
            continue
        if page.resolve() not in linked:
            errors.append(
                f"landing does not link public page {page.relative_to(docs)}"
            )
    return errors


def check_example_runs_dir_comment(example_text: str) -> list[str]:
    if UNDIFFERENTIATED_RUNS_FALLBACK.search(example_text):
        return [
            "example YAML uses a single runs-dir precedence line that implies "
            "./runs for every command"
        ]
    lowered = example_text.lower()
    creating_ok = (
        "run, prepare, execute" in lowered
        and ("no ./runs fallback" in lowered or "does not fall back" in lowered)
    )
    lookup_ok = (
        "resume" in lowered
        and "status" in lowered
        and "./runs" in lowered
    )
    if creating_ok and lookup_ok:
        return []
    return [
        "example YAML must distinguish creating commands (no ./runs fallback) "
        "from lookup/resume-style commands (./runs allowed)"
    ]


def check_continuation_ok_docs(docs: Path) -> list[str]:
    errors: list[str] = []
    required = {
        docs / "concepts" / "lifecycle-terms.md": (
            "continuation-command success",
            "terminal quality success",
            "target_reached",
        ),
        docs / "concepts" / "quality-loop.md": (
            "continuation-command success",
            "terminal quality success",
        ),
        docs / "workflows" / "lifecycle.md": (
            "continuation-command success",
            "terminal quality success",
        ),
        docs / "workflows" / "operations.md": (
            "ok=true",
            "status=running",
            "target_reached",
        ),
    }
    for path, snippets in required.items():
        if not path.is_file():
            errors.append(f"missing {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_OK_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"{path.relative_to(docs)}: obsolete exclusive completed+accepted ok rule"
                )
                break
        lowered = text.lower()
        for snippet in snippets:
            if snippet.lower() not in lowered:
                errors.append(
                    f"{path.relative_to(docs)}: missing required wording {snippet!r}"
                )
    extra_pages = [
        docs / "architecture" / "lifecycle.md",
        docs / "concepts" / "roles.md",
        docs / "decisions" / "lifecycle-stop-states.md",
    ]
    for path in extra_pages:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_OK_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"{path.relative_to(docs)}: obsolete exclusive completed+accepted ok rule"
                )
                break
    return errors


def check_first_run_safety(package_root: Path) -> list[str]:
    errors: list[str] = []
    config_path = package_root / FIRST_RUN_CONFIG_REL
    if not config_path.is_file():
        return [f"missing first-run config {FIRST_RUN_CONFIG_REL}"]
    parsed = load_yaml(config_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return ["first-run config is not a mapping"]
    workspace = str((parsed.get("project") or {}).get("workspace") or "")
    if workspace in {"", "."}:
        errors.append("first-run config must not use project.workspace: .")
    expected_prefix = "tools/top_down_planning/examples/first-run/"
    if not workspace.startswith(expected_prefix):
        errors.append(
            "first-run project.workspace must stay under examples/first-run/"
        )
    walkthrough = package_root / "docs" / "workflows" / "first-run.md"
    text = walkthrough.read_text(encoding="utf-8")
    config_ref = FIRST_RUN_CONFIG_REL.as_posix()
    if config_ref not in text:
        errors.append(f"first-run walkthrough must use {config_ref}")
    if FIRST_RUN_ARTIFACT not in text:
        errors.append(f"first-run walkthrough must name artifact {FIRST_RUN_ARTIFACT}")
    if "examples/top-down-planning.yaml --until completed" in text:
        errors.append(
            "first-run walkthrough must not drive production with the canonical repo-root workspace"
        )
    return errors


def check_known_defaults(package_root: Path) -> list[str]:
    errors: list[str] = []
    expected_idle = DEFAULT_CONFIG["limits"]["provider"]["turn_idle_timeout_seconds"]
    example = (package_root / CANONICAL_EXAMPLE_REL).read_text(encoding="utf-8")
    needle = f"turn_idle_timeout_seconds: {int(expected_idle)}"
    if needle not in example and f"turn_idle_timeout_seconds: {expected_idle}" not in example:
        errors.append(
            f"{CANONICAL_EXAMPLE_REL}: idle timeout must match DEFAULT_CONFIG ({expected_idle})"
        )
    errors.extend(check_example_runs_dir_comment(example))
    schema = show_schema("config")
    properties = schema.get("properties") or {}
    loaded = load_yaml_config(package_root / CANONICAL_EXAMPLE_REL)
    extra = [key for key in loaded if key not in properties]
    if extra:
        errors.append(f"{CANONICAL_EXAMPLE_REL}: keys not in config schema: {extra}")
    return errors


def check_cli_docs(package_root: Path) -> list[str]:
    cli_md = (package_root / "docs" / "manual" / "cli.md").read_text(encoding="utf-8")
    errors: list[str] = []
    for command in USER_CLI_COMMANDS:
        if command not in cli_md:
            errors.append(f"manual/cli.md missing documented command {command!r}")
    landing = (package_root / "docs" / "README.md").read_text(encoding="utf-8")
    if "PAGE-OWNERSHIP.md" in landing:
        errors.append("landing must not link authoring PAGE-OWNERSHIP.md")
    for path in public_markdown_pages(docs_root(package_root)):
        text = path.read_text(encoding="utf-8")
        if PLAN_ITEM_RE.search(text):
            errors.append(
                f"{path.relative_to(docs_root(package_root))}: public docs must not embed plan-item ids"
            )
    return errors


def check_all(package_root: Path | None = None) -> list[str]:
    root = package_root or package_root_from_script()
    docs = docs_root(root)
    errors: list[str] = []
    errors.extend(check_markdown_links(docs))
    errors.extend(check_landing_coverage(docs))
    errors.extend(check_continuation_ok_docs(docs))
    errors.extend(check_first_run_safety(root))
    errors.extend(check_known_defaults(root))
    errors.extend(check_cli_docs(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=package_root_from_script(),
        help="top_down_planning package root (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    errors = check_all(args.package_root.resolve())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("docs quality checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
