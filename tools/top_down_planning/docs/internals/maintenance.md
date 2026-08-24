# Extension and maintenance

**Audience:** maintainers changing TDP safely.

Layer map: [system context](../architecture/system-context.md). Install: [manual install](../manual/install.md) and package README Development.

## Import boundaries

| Rule | Test / note |
| --- | --- |
| `domain` must not import `cli`, `config`, `persistence`, `orchestrator`, or `core_tools` | `tests/unit/test_layer_boundaries.py` |
| Orchestrator must not import `rich` or `core_tools.observability.console` | `tests/unit/test_import_boundary.py` |
| Shared primitives | `core_tools` (providers, merge, atomic IO, observability, schema) |
| Product rules | TDP domain + orchestrator + agent_tool + product config schema |

Put new **behavior** in the layer that owns the invariant. Do not add semantic CLI flags that mirror config leaves (YAML + `--set` only). Presentation flags wire through `invocation.py`. New config paths: `DEFAULT_CONFIG`, `ALLOWED_OVERRIDE_PATHS`, `schema_docs.py`, and resume allowlists when needed.

New `stop.code` values must exist in the lifecycle model and resume validators **before** orchestration emits them.

## Prompts and skills

Role `protocol_instructions` are Jinja templates under `src/top_down_planning/prompts/templates/` (plus `prompts/contexts.py` flags). Do not inline protocol strings in orchestrator session modules. Templates ship in the installed package (`jinja2` is a runtime dependency).

Packaged agent skills live under `src/top_down_planning/bundled_skills/tdp-agent/` and inject when `agent_context.bundled_skills` is true. Project skills are extra paths (`SKILL.md` file or directory).

## Tests

From `tools/top_down_planning` (docs links and known contracts: `python scripts/check_docs.py` or `pytest tests/unit/test_docs_quality.py`):

```bash
python -m pytest                  # parallel unit tests (excludes integration and packaging)
python -m pytest -m integration   # stub-provider e2e; no live Cursor
python -m pytest -m packaging     # installed-artifact smoke against a wheelhouse
```

Unit tests use `StubProvider.script_turn()`, in-process `run_cli()`, and fakes — not live Cursor, desktop notifications, or full-system PID scans (autouse stubs in `tests/conftest.py`). Lifecycle tests assert canonical run state, exact-N limits, and `CommitSpec` fault injection. See `.cursor/skills/tools-dev/SKILL.md` and `.cursor/skills/tdd/SKILL.md` in this repo.

## Packaging

Supported install is **monorepo editable**: `core_tools` then `top_down_planning` from `tools/top_down_planning` (`file:../core_tools`). This is not a portable published wheel. A built wheel is for **CI packaging verification** (templates, skills, imports). `TDP_PACKAGING_WHEELHOUSE` + `pytest -m packaging`.

## Safe change workflow

1. Write a failing unit test from the expected durable outcome (status, stop, revision, events).
2. Implement the smallest domain/orchestrator/persistence change; keep transition + event in one `CommitSpec`.
3. Reload canonical run before outer failure handling; do not overwrite an operational pause.
4. Update `tdp agent schema` / examples / `schema_docs` when request contracts change.
5. Update docs under `tools/top_down_planning/docs/**` when operator or agent behavior changes; do not treat proposal-section comments in source as unpublished-spec license.

Related: [persistence](persistence.md), [security](security.md), [package README](../../README.md).
