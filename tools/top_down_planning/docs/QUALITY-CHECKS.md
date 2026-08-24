# Documentation quality checks

**Audience:** document authors and reviewers verifying this documentation set.

**Purpose:** point at the reusable checker that keeps docs navigable and aligned with current public CLI, schema, and example behavior.

Do not treat this page as frozen evidence (file counts, link counts, or one-time plan-item ids). Re-run the checker after documentation or default changes.

## How to run

From `tools/top_down_planning`:

```bash
python scripts/check_docs.py
pytest tests/unit/test_docs_quality.py
```

The checker lives at [scripts/check_docs.py](../scripts/check_docs.py). It covers:

- Internal Markdown links and heading fragments under `docs/`
- Landing-page coverage of **public** pages (`docs/authoring/` is excluded from that requirement)
- Continuation `ok` / `target_reached` wording on the canonical lifecycle pages
- First-run disposable workspace and known output artifact
- Canonical example YAML: two-class run-store precedence, config schema keys, and known defaults such as `limits.provider.turn_idle_timeout_seconds`
- User CLI command names on [manual/cli.md](manual/cli.md)
- No plan-item ids in public docs; landing does not link authoring page-ownership

Authoring bookkeeping (plan-item fill lists) lives under [authoring/PAGE-OWNERSHIP.md](authoring/PAGE-OWNERSHIP.md), not on the public landing.

Landing: [README.md](README.md).
