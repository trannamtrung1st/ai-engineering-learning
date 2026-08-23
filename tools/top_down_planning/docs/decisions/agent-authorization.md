# Decision: agent-tool authorization

**Status:** verified current behavior.

**Evidence:** `tdp agent readme` (Session roles and authorization); `tests/unit/test_capability_security.py` (hash not secret; wrong session denied; revoke on phase leave; planner cannot use reviewer authority); `tests/unit/test_capability_token_file.py`; `tests/unit/test_capability_binding.py` (generation change revokes; stale generation denied); `tests/unit/test_reviewer_capability_stream_rebind.py` (one live reviewer capability across stream drain; reissue only when the exported token is gone). Packaged `tdp-agent` skill: do not pass `--role`.

Operator/agent how-to: [agent CLI](../agents/cli.md). Internals: [security](../internals/security.md).

## Binding choice

Mutating `tdp agent` commands are authorized by an orchestrator-issued **session capability**, not by a self-declared CLI role.

- Token is read from `TDP_CAPABILITY_TOKEN_FILE` at invocation time.
- Checks include run phase, allowed operations, bound provider session, and (for reviewers) the review loop.
- Persisted capability records store `secret_hash`, plus `session_instance_id` and `generation` — not the plaintext token.
- Tokens are revoked when the turn, loop, or phase ends; `generation` change revokes prior capabilities.

`--request` paths must resolve inside `agent-requests/`. `TDP_RUN_ID` must match `--run` when capability context is active.

## Verified consequences

- `capability_denied` means the token file is missing, revoked, unbound, or the session/phase/role does not match — retry without caching capability state in the shell.
- A planner cannot replay a reviewer token from disk.
- Reviewer sessions bind the token **then** deliver the review package before `review respond`.
- Stream-event handling reuses the live exported capability token; it must not mint a new token per streamed event (`test_reviewer_turn_drain_does_not_mint_capability_per_stream_event`). Reissue only when the exported token file is gone.
- This is orthogonal to production snapshot evidence authorization (workspace `outputs` vs skill/guidance drift).

## Not claimed

This record does not invent prior auth designs (for example a `--role` flag as a historical alternative). The current protocol simply forbids `--role` and binds authority to the session.

Related: [session bindings](session-bindings.md), [protocol](../agents/protocol.md).
