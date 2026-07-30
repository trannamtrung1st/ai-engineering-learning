# Core Tools (`core_tools`)

Cross-product infrastructure shared by agent orchestration tools in this monorepo.

## What belongs here

| Module | Contents |
| --- | --- |
| `core_tools.provider` | Provider protocol, stub/Cursor adapters, stream normalization, session references |
| `core_tools.config` | Deep merge, YAML config load, `--set` override parsing (generic; no product schema) |
| `core_tools.persistence` | Atomic file writes, content digests, minimal YAML helpers |

## What stays in product packages

Product packages (e.g. `top_down_planning`, a future todos tool) own:

- Domain models and business rules (plan trees, readiness, dispositions, outcomes)
- Orchestrator lifecycle (planning, review loops, amendment, production)
- Agent tool surfaces and product CLIs (`tdp`, etc.)
- Run-store layout, revision binding, and product config schemas (`DEFAULT_CONFIG`, allowed override paths)

## Consumers

- [`top_down_planning`](../top_down_planning) — top-down planning and production orchestration
- Future todos tool — will depend on `core_tools` instead of forking TDP internals

## Install

```bash
cd tools/core_tools
python -m pip install -e ".[dev]"
```

When working on a product package, install both packages (product `pyproject.toml` depends on `core-tools`):

```bash
python -m pip install -e tools/core_tools -e "tools/top_down_planning[dev]"
```

## Import boundary

`core_tools` must not import product packages. Product packages may import `core_tools` for shared infra only.
