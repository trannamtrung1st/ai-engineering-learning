# Decision: prepared-execution integrity

**Status:** verified current behavior.

**Evidence:** `package/execution_validation.py`; `tests/unit/test_sub_tdp_content_bound_baseline.py` (`workspace_changes` sha256 bind; reject when bytes differ; **`output_refs` do not authorize**; conflicting hashes fail closed; ordered same-path overwrite composes); package README (Prepared Sub-TDP execution); `tdp execute` / `tdp sub-tdp attach` help.

Operator procedures: [prepared execution](../workflows/prepared-and-sub-tdp.md). Internals: [packages and Sub-TDPs](../internals/packages-and-sub-tdp.md).

## Binding choice

Prepared packages and child deliveries are **content-bound**. A path list of output refs is not enough to authorize workspace baseline or parent synthesis.

- Package `package_id` + digest is immutable in the store (duplicate id with different digest rejected).
- Execute-time semantic config must match package context digests (`config_contract`, `config_execution`, input/output-goal, context-spec) before runs are created.
- Accepted-result attestations include `workspace_changes` (sha256 per path from live-batch capture), snapshot digests, and batch delivery. Re-derivation must match the live `accepted_result_record`. Live `run.digests.output` must match.
- `--upstream` is the semantic dependency map. `--baseline` contributes workspace lineage without becoming `depends_on`. Same-path overwrites require snapshot-lineage succession from the package **initial context snapshot**. Unrelated conflicting hashes fail closed.
- Guidance and skill drift are always rejected on these paths.

## Verified consequences

- Attach requires parent `phase=sub_tdps` and `status=paused`, and a child that is `completed` / `output_validated` / `accepted` with whole-output approval.
- A permanently failed child fails the parent (`sub_tdp_unit_permanently_failed`) rather than leaving the parent `running`.
- Hand-editing `production.json` → `sub_tdps` is not an integrity mechanism; orchestration commits go through `RunStore.commit`.

## Not claimed

This record does not invent a date for content-bound attestations or discarded designs (for example “path lists used to suffice”). Tests show path-only `output_refs` are insufficient **now**.

Related: [split config digests](split-config-digests.md), [run ownership](run-ownership.md).
