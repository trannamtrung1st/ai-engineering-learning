# Page ownership and naming conventions

**Audience:** document authors and reviewers of this documentation set.

**Purpose:** bind filenames, section jobs, and later authoring items so detailed pages fill this skeleton instead of inventing a parallel tree.

**Owned topics:** information architecture, page-ownership map, naming conventions, and which plan item fills each page.

This map is the skeleton contract (`item-915608fb4a15`). Later items expand the owned pages listed here; they do not add a second tree. Final landing integration and verification evidence belong to `item-971d08d48ab3`.

This file is authoring machinery. It is not part of the public operator/agent landing navigation.

## Naming conventions

- Section folders use plural audience or topic names: `concepts`, `workflows`, `manual`, `agents`, `architecture`, `internals`, `decisions`.
- Each folder’s `README.md` is the section index (audience, purpose, owned topics, links to pages).
- Leaf pages use kebab-case filenames that name the topic, not the plan item id.
- One canonical home per topic. Other pages link; they do not restate long explanations.
- Repository-relative Markdown links. Intended path references must resolve from `tools/top_down_planning/docs/`.
- Troubleshooting for operators lives under `manual/`. Runtime-agent errors live under `agents/`. Those are not a top-level landing section.
- Do not treat internal Python module names as a stable user-facing API unless the page is explicitly maintainer internals.

## Plan item fill list

| Plan item | Title | Pages this item fills |
| --- | --- | --- |
| `item-915608fb4a15` | Establish documentation information architecture and navigable skeleton | This map, the landing structure in [README.md](../README.md), section indexes, and purpose-bearing stubs. Copies the pre-landing hub body onto [agents/README.md](../agents/README.md). |
| `item-8def987b747e` | Author orientation and concept pages | [concepts/](../concepts/README.md) |
| `item-241464709d32` | Author end-to-end and operational workflow pages | [workflows/](../workflows/README.md) |
| `item-2aae0166bcec` | Author user and operator reference manual | [manual/](../manual/README.md) |
| `item-1049a037a1f6` | Author runtime-agent protocol and agent CLI documentation | [agents/](../agents/README.md) (filled start-here hub and nested protocol, role, CLI, and troubleshooting pages) |
| `item-3ad5312398e9` | Author architecture pages for layers, orchestration, domain, and sessions | [architecture/](../architecture/README.md) |
| `item-c4319df6b665` | Author technical internals for config, persistence, reviews, packages, security, and maintenance | [internals/](../internals/README.md) |
| `item-20599adcf3e0` | Author design-decision records from repository evidence | [decisions/](../decisions/README.md) |
| `item-971d08d48ab3` | Integrate navigation and verify documentation completeness | Landing TOC polish in [README.md](../README.md), cross-links, terminology sweep, and [QUALITY-CHECKS.md](../QUALITY-CHECKS.md) |

## Page map

### Root

| Page | Audience job | Filled by |
| --- | --- | --- |
| [README.md](../README.md) | Multi-audience landing and table of contents | Skeleton in `item-915608fb4a15`; TOC, stitched paths, and verification links in `item-971d08d48ab3` |
| [PAGE-OWNERSHIP.md](PAGE-OWNERSHIP.md) | Authoring contract for this tree | `item-915608fb4a15` |
| [QUALITY-CHECKS.md](../QUALITY-CHECKS.md) | How to run the checked-in docs checker | Filled in `item-971d08d48ab3` |

### Concepts (`item-8def987b747e`)

| Page | Owned topics |
| --- | --- |
| [concepts/README.md](../concepts/README.md) | Section index |
| [concepts/overview.md](../concepts/overview.md) | What TDP is, problem, use cases, non-goals |
| [concepts/plan-tree.md](../concepts/plan-tree.md) | Plan tree, item contracts, aggregation, dependencies, readiness |
| [concepts/quality-loop.md](../concepts/quality-loop.md) | Production batches, evidence, completion claims, validation, review, final quality outcomes |
| [concepts/lifecycle-terms.md](../concepts/lifecycle-terms.md) | Run status, lifecycle phase, mandatory review stage, plan/output revisions, recoverable versus terminal states |
| [concepts/roles.md](../concepts/roles.md) | Planner, producer, reviewer, operator, and orchestration-engine responsibilities |

### Workflows (`item-241464709d32`)

| Page | Owned topics |
| --- | --- |
| [workflows/README.md](../workflows/README.md) | Section index |
| [workflows/first-run.md](../workflows/first-run.md) | First successful `tdp` run using `cursor`; links to install/setup rather than duplicating it |
| [workflows/lifecycle.md](../workflows/lifecycle.md) | Input and output goal through plan, review, validation, production, output review, and acceptance |
| [workflows/operations.md](../workflows/operations.md) | Staged planning (`--until`), status/inspect/validate, pause and resume, configuration drift; links to manual recovery |
| [workflows/prepared-and-sub-tdp.md](../workflows/prepared-and-sub-tdp.md) | `prepare`/`execute`, parent/child Sub-TDPs, dependency and baseline handling, attach, parent resumption |
| [workflows/agent-sessions.md](../workflows/agent-sessions.md) | Operator-visible planning, production, amendments, focused and whole reviews, completion signals (not a replacement for agent protocol pages) |

### Operator manual (`item-2aae0166bcec`)

| Page | Owned topics |
| --- | --- |
| [manual/README.md](../manual/README.md) | Section index |
| [manual/install.md](../manual/install.md) | Canonical prerequisites, installation, provider setup, minimal working config |
| [manual/cli.md](../manual/cli.md) | User CLI: `run`, `prepare`, `execute`, `resume`, `status`, `inspect`, `validate`, `doctor`, `sub-tdp attach` |
| [manual/configuration.md](../manual/configuration.md) | Configuration by responsibility: precedence, paths, contracts, overlays, models, exclusions, reviews, limits, observability, notifications, provider, runtime paths, execution mode |
| [manual/run-store.md](../manual/run-store.md) | Run-store outputs and inspection without hand-editing orchestrator state |
| [manual/observability.md](../manual/observability.md) | Logging, stream JSON, transcripts, notifications |
| [manual/troubleshooting.md](../manual/troubleshooting.md) | Cancellation, concurrency, common errors, diagnosis, safe recovery |

### Runtime agents (`item-1049a037a1f6`)

[agents/README.md](../agents/README.md) is the filled runtime-agent start-here hub. Nested pages hold shared protocol, role command tables, agent CLI/schemas, and agent troubleshooting.

| Page | Owned topics |
| --- | --- |
| [agents/README.md](../agents/README.md) | Runtime-agent start-here hub, role index, and links to protocol, CLI, and troubleshooting |
| [agents/protocol.md](../agents/protocol.md) | Shared protocol, request files, revision safety, completion signals |
| [agents/planner.md](../agents/planner.md) | Planner workflow and plan-mutation contracts |
| [agents/producer.md](../agents/producer.md) | Producer batches, evidence, completion, amendments, blockers |
| [agents/reviewer.md](../agents/reviewer.md) | Reviewer respond, owner record-actions, focused and whole reviews |
| [agents/cli.md](../agents/cli.md) | `tdp agent` discoverability, commands, published schemas/examples, authorization, capability tokens |
| [agents/troubleshooting.md](../agents/troubleshooting.md) | Agent-facing error table and recovery hints |

### Architecture (`item-3ad5312398e9`)

| Page | Owned topics |
| --- | --- |
| [architecture/README.md](../architecture/README.md) | Section index |
| [architecture/system-context.md](../architecture/system-context.md) | System context, component/layer responsibilities, `top_down_planning` versus `core_tools` |
| [architecture/lifecycle.md](../architecture/lifecycle.md) | Lifecycle and state-transition architecture, orchestration phases, review stages, ownership, atomic transitions, outcome resolution |
| [architecture/domain.md](../architecture/domain.md) | Domain model and invariants for plans, dependencies, production, evidence, reviews, dispositions, acceptance |
| [architecture/sessions.md](../architecture/sessions.md) | Agent session architecture, effective context, provider binding/replacement, activity boundaries, process cleanup |

### Internals and maintenance (`item-c4319df6b665`)

| Page | Owned topics |
| --- | --- |
| [internals/README.md](../internals/README.md) | Section index |
| [internals/config-and-snapshots.md](../internals/config-and-snapshots.md) | Configuration resolution, contract/execution/context digests, workspace snapshots, drift rules, path containment |
| [internals/persistence.md](../internals/persistence.md) | Persistence layout, revisions/CAS, journaling, atomic commits, crash recovery, inspection surfaces |
| [internals/reviews.md](../internals/reviews.md) | Focused reviews, mandatory whole-plan/whole-output gates, finding families, audit passes, verification, scope review, loop limits |
| [internals/packages-and-sub-tdp.md](../internals/packages-and-sub-tdp.md) | Prepared-package and Sub-TDP internals, integrity/lineage, upstream contracts, accepted-result attestations, synthesis |
| [internals/security.md](../internals/security.md) | Capability authorization, redaction, secrets, workspace containment, ownership locks, cancellation, stale processes, platform limits |
| [internals/maintenance.md](../internals/maintenance.md) | Import boundaries, where behavior belongs, prompt/template ownership, tests, packaging, safe change workflow |

### Design decisions (`item-20599adcf3e0`)

| Page | Owned topics |
| --- | --- |
| [decisions/README.md](../decisions/README.md) | Decision-log index |
| [decisions/lifecycle-stop-states.md](../decisions/lifecycle-stop-states.md) | Lifecycle stop states |
| [decisions/split-config-digests.md](../decisions/split-config-digests.md) | Split configuration digests and drift policy |
| [decisions/session-bindings.md](../decisions/session-bindings.md) | Replaceable session bindings and recovery manifests |
| [decisions/run-ownership.md](../decisions/run-ownership.md) | Run ownership and concurrency |
| [decisions/agent-authorization.md](../decisions/agent-authorization.md) | Agent-tool authorization |
| [decisions/prepared-execution-integrity.md](../decisions/prepared-execution-integrity.md) | Prepared-execution integrity |

## Coverage notes

These groupings keep architecture, operator workflows, agent protocol, internals, and decisions separately reviewable. Topics that appear in more than one audience journey still have one canonical page:

- Install/setup truth: `manual/install.md` (first-run links here)
- Recovery/diagnosis truth: `manual/troubleshooting.md` (workflow operations links here)
- Lifecycle vocabulary: `concepts/lifecycle-terms.md` (architecture and workflows link here)
- Agent protocol and schemas: `agents/` (operator-visible session flow links here)
- Enduring rationale: `decisions/` (architecture and internals link here rather than restating motivation)
