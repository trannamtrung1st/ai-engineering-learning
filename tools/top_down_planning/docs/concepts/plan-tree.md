# Plan tree

**Audience:** operators and runtime agents who need the shared model of work items.

A TDP **plan** is a tree of **items** under a required root (`item-root`). The plan names the **output goal**, **input refs**, plan-level **scope** and **boundaries**, plus **constraints**, **assumptions**, **acceptance**, and **risks**. Each item is either `work` or `aggregate`.

The planner mutates the tree through `tdp agent plan apply`. Producers consume **work** leaves, not aggregates. Exact request shapes are on the [planner protocol](../agents/planner.md) pages.

## Item kinds

| Kind | Role in the tree |
| --- | --- |
| `work` | An executable leaf (or a node the producer may dispose). Ready-set membership and production batches apply to active `work` items. |
| `aggregate` | A grouping node. Aggregates are never in `ready_item_ids`. The producer cannot assign them a batch disposition. Their satisfaction is **derived** from descendant items (`derived_subtree`), not from an explicit production disposition. |

An aggregate with no descendants is a plan-validation issue (`aggregate_without_descendants`). `item-root` is an aggregate.

## Item contract

Each item carries a production contract. Item-owned fields are the item’s slice; **effective** fields merge plan-level guardrails first, then the item:

| Field | Meaning |
| --- | --- |
| `id`, `title`, `outcome` | Identity and the result this item is for |
| `kind` | `work` or `aggregate` |
| `scope.includes` / `scope.excludes` | Item-owned scope slice |
| `boundaries` | Item-owned constraints on how work may proceed |
| `effective_scope`, `effective_boundaries` | Union of plan-level then item-level lists (blanks skipped; case-insensitive duplicates dropped) |
| `acceptance` | Verifiable checks for this item |
| `risks` | Item-owned risks |
| `source_refs` | Inputs this item draws on |
| `depends_on` | Other item ids that must be satisfied before this item is ready |
| `parent_id`, `order_key`, `depth` | Tree placement (depth is persisted with the item) |

Item **scope and boundaries** are the item-owned slice. **`effective_*`** is the union with plan-level guardrails. Production and review treat the effective contract as the batch boundary.

`planning_status` is `open` (active), `superseded`, or `removed`. Only active (`open`) items participate in readiness and production applicability.

## Dependencies and readiness

`depends_on` names predecessor items. A `work` item is **ready** when it is active, applicable (not yet terminal), and every dependency is satisfied. Satisfaction is:

- **explicit** — a terminal production disposition on that `work` item
- **derived_subtree** — all relevant descendants of an aggregate are satisfied
- **blocked** — a `blocked` disposition or a review block on the dependency chain

Ready-set views also report `not_ready` with a reason such as `unsatisfied_dependency` or `review_blocked`. Cycles and unresolved subtrees surface as deadlock issues during plan validation.

Producers record one batch of ready `work` items at a time. See [quality loop](quality-loop.md) for dispositions and evidence.

## Planning budget

Soft planning limits (package defaults) bound tree growth:

- `planning.max_depth` default `4`
- `planning.max_expansion_per_item` default `7`

These are planning-construction limits, not run-status values. Changing them is an operator configuration concern; see [configuration](../manual/configuration.md).

Related: [quality loop](quality-loop.md), [roles](roles.md), [domain model](../architecture/domain.md).
