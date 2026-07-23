# git-modifier

Local-only helpers under `temp/tools/` (gitignored). Run from anywhere inside
the repo; scripts resolve the git root automatically.

## distribute-commit-dates

Rewrites author and committer dates for commits on the **current branch** since
its merge-base with a base branch.

Each gap between consecutive commits is a **random** duration (configurable).
Scheduling options (direction, anchor, office hours, gaps, etc.) live in a YAML
config file you pass at runtime.

### Config

Create or edit a YAML config (see `temp/tools/distribute-commit-dates.config.yaml`
as an example). Pass it with `--config` (required). CLI flags override config
values.

### Usage

Preview:

```bash
python3 temp/tools/git-modifier/distribute-commit-dates.py --config <config.yaml>
```

Apply rewrite (creates `git-modifier-backup/<branch>-before-date-rewrite` first):

```bash
python3 temp/tools/git-modifier/distribute-commit-dates.py --config <config.yaml> --apply
```

Uses `git filter-branch` so merge commits are supported when `include_merges: true`.
Requires a clean index/worktree for **tracked** files (untracked `temp/` is OK).

Or set `apply: true` in the config file.

Reproducible gaps:

```bash
python3 temp/tools/git-modifier/distribute-commit-dates.py --config <config.yaml> --seed 42
```

Run from `apps/frontend` (paths above) or adjust paths relative to your cwd.

### Recovery

If `--apply` fails:

```bash
git reset --hard git-modifier-backup/<sanitized-branch>-before-date-rewrite
```

After a successful rewrite, force-push is required if the branch was already
pushed (`git push --force-with-lease`).
