# git-modifier

Local Git helpers for rewriting commit timestamps on the current branch.

Run from anywhere inside a Git repository; the CLI resolves the repository root automatically.

## Requirements

- Python 3.11+
- Git

## Installation

```bash
cd tools/git_modifier
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

After installation: `git-modifier`, or `python -m git_modifier`.

## distribute-commit-dates

Rewrites author and committer dates for commits on the **current branch** since
its merge-base with a base branch.

Each gap between consecutive commits is a **random** duration (configurable).
Scheduling options (direction, anchor, office hours, gaps, etc.) live in a YAML
config file you pass at runtime.

### Config

Create or edit a YAML config (see `examples/distribute-commit-dates.config.yaml`).
Pass it with `--config` (required). CLI flags override config values.

### Usage

Preview:

```bash
git-modifier --config ./examples/distribute-commit-dates.config.yaml
```

Apply rewrite (creates `git-modifier-backup/<branch>-before-date-rewrite` first):

```bash
git-modifier --config ./examples/distribute-commit-dates.config.yaml --apply
```

Uses `git filter-branch` so merge commits are supported when `include_merges: true`.
Requires a clean index/worktree for **tracked** files.

Or set `apply: true` in the config file.

Reproducible gaps:

```bash
git-modifier --config ./examples/distribute-commit-dates.config.yaml --seed 42
```

### Recovery

If `--apply` fails:

```bash
git reset --hard git-modifier-backup/<sanitized-branch>-before-date-rewrite
```

After a successful rewrite, force-push is required if the branch was already
pushed (`git push --force-with-lease`).
