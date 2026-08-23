# Prepared packages and Sub-TDP internals

**Audience:** maintainers of prepare/execute and parent/child TDP units.

Operator procedures: [prepared execution](../workflows/prepared-and-sub-tdp.md). Integrity rationale: [prepared-execution integrity](../decisions/prepared-execution-integrity.md). Authoritative parent state: `production.json` → `sub_tdps` (journaled commits). Do not hand-edit.

## Package

`tdp prepare` writes an immutable directory whose entry point is **`manifest.json`**. The manifest carries parent and unit plan snapshots, digests, dependency graph, embedded execution config, and inherited plan approval.

Package IDs are store IDs confined under `.execution_packages/`. The run store rejects a second package with the same `package_id` and a different digest. `--replace` replaces the output directory on disk; it does not make IDs mutable inside the store.

`tdp execute --manifest` must point at that filename. Semantic config loads from the package. Optional `--config` / `--set` at execute time are limited to observability, notifications, and run-store location. Before creating prepared runs, execution validation compares live `config_contract`, `config_execution`, input/output-goal, and context-spec digests to the package context block.

Child package bindings are immutable after execution starts (retrofit only while `plan_validated` with no batches/sessions). Prepared children load the assigned subtree and inherited context; they do **not** enter planning.

## Lineage and accepted results

Child runs bind semantic dependencies as digest-verified wrappers:

- `accepted_result` / `accepted_result_digest`
- `upstream_contract_digest`
- `workspace_baseline_accepted_results`

Accepted-result attestations are **content-bound**: `workspace_changes` (latest live-batch capture per path), baseline/final context snapshot digests, and batch delivery (`batches[].result.outputs`, `contributions`). Bare `output_refs` path lists never authorize.

Wrapper delivery is revalidated per child; workspace bytes are checked once against the merged baseline map (not per historical wrapper). Parent resume, whole-output-review entry, production completion, child create, and baseline closure re-load child production and require the stored attestation to match a live `accepted_result_record` re-derivation. Live output digest must match `run.digests.output`. Terminal children are revalidated before reuse. Accepted-child delivery requires `completed` / `output_validated` / `accepted`.

## Baseline and upstream

`--upstream UNIT=RUN_ID` is the semantic `depends_on` map for direct `--unit` execution. `--baseline RUN_ID` adds workspace changes from accepted siblings **without** creating a dependency.

Same-path overwrites require snapshot-lineage succession rooted at the package **initial context snapshot**. Composite multi-result `--baseline` joins merge workspace lineage from all baseline wrappers. Unrelated conflicting hashes fail closed. Guidance and skill drift are always rejected. Resource drift from the cumulative baseline is authorized only when current workspace sha256 matches the merged final write digest.

Attach requires parent `phase=sub_tdps` and `status=paused`, holds parent ownership for validate-and-commit, and accepts only a completed/accepted child with whole-output approval. Dependencies must already be attached with matching `accepted_result_digest` values. The child's embedded `unit_id` is authoritative.

## Synthesis and integration

When all children are accepted, the parent synthesizes child results (completion claim `status=integration_pending`, `goal_met=false`), then runs parent production (integration producer), then `submit-completion` with the goal met, then `whole_output_review`.

A permanently failed child fails the parent immediately (`sub_tdp_unit_permanently_failed`) — not a resumable `sub_tdp_child_failed` pause.

Related: [persistence](persistence.md), [config and snapshots](config-and-snapshots.md), [user CLI](../manual/cli.md).
