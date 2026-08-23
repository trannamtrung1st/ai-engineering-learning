# TDP agent documentation hub

**Docs home:** [Top Down Planning documentation](../README.md)

Navigation for **runtime TDP agents** (planner, producer, reviewer) inside provider sessions. Host IDE planning modes are not part of this protocol. For operator CLI and install, see the [operator manual](../manual/README.md) and the [package README](../../README.md).

## Start here

1. `tdp agent help` — command cheat sheet
2. `tdp agent readme` — full agent protocol (authorization, workflow, run store)
3. Packaged role skills — auto-injected into `agent_context.skills` on every session (`agent_context.bundled_skills`, default true): shared protocol plus planner, producer, or reviewer guide
4. `tdp agent schema <name>` / `tdp agent example <name>` — exact request shapes
5. Shared rules in this set: [protocol](protocol.md) (request files, revision safety, completion signals)
6. Contracts and auth: [agent CLI](cli.md); errors: [agent troubleshooting](troubleshooting.md)

Then open the page for your role. Exact request JSON/YAML is always from `tdp agent schema` / `tdp agent example`, not from memory.

| Role | Page |
| --- | --- |
| Shared rules | [Protocol](protocol.md) — request files, revision safety, completion signals |
| Planner | [Planner protocol](planner.md) |
| Producer | [Producer protocol](producer.md) |
| Reviewer / owner | [Reviewer protocol](reviewer.md) |
| Commands and auth | [Agent CLI, schemas, and authorization](cli.md) |
| Errors | [Agent troubleshooting](troubleshooting.md) |

Role `protocol_instructions` in planner, producer, and reviewer manifests are rendered Markdown from package-owned Jinja templates. Follow those instructions and `tool_instructions` in the session package. Example config: [examples/top-down-planning.yaml](../../examples/top-down-planning.yaml). Set `agent_context.bundled_skills: false` only when you want to disable packaged skills. Add extra project skills under `agent_context.*.skills`.

Concepts used below ([plan tree](../concepts/plan-tree.md), [quality loop](../concepts/quality-loop.md), [lifecycle terms](../concepts/lifecycle-terms.md), [roles](../concepts/roles.md)) are defined once in the concepts section.

## Discover schemas and examples

```bash
tdp agent schema
tdp agent example
tdp agent schema production-apply
tdp agent example batch-result
```

Published mutating-request schemas and the contract table are on [agent CLI](cli.md#published-schemas-and-examples). Role command tables are on the planner, producer, and reviewer pages so they are not dropped during rehoming.
