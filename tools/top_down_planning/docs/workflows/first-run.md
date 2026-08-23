# First run

**Audience:** newcomers completing one successful TDP run.

Use the `cursor` provider. The `stub` provider is test-only and is not this walkthrough. Prerequisites, Cursor CLI, Python extras, working directory, provider setup, and the canonical minimal config are on [install and setup](../manual/install.md) — complete that page first.

## 1. Confirm install

From the repository root, `tdp --help` and `tdp agent help` should work. The example config already sets `runtime.runs_dir` and `provider.name: cursor`. Details: [install](../manual/install.md#minimal-working-config).

## 2. Start a run

Launch from the repository root (process cwd is the path-resolution root). A bare `tdp run` defaults to `--until plan` and **stops after planning construction**, not after production:

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml
```

That is the same as `--until plan`. Progress logs go to **stderr**. The structured command payload is on **stdout**. Watch for `[run:start]` and `[session:start]` lines. What those sessions do is summarized in [agent sessions](agent-sessions.md).

Later milestones on the same axis (not more conservative stops):

```bash
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until validated
tdp run --config tools/top_down_planning/examples/top-down-planning.yaml --until completed
```

`--until` values: [user CLI](../manual/cli.md). Staging and resume: [operations](operations.md).

## 3. Inspect the run

Copy the run id from the command payload or stderr.

```bash
tdp status --run <run-id> --config tools/top_down_planning/examples/top-down-planning.yaml
tdp inspect --run <run-id> --view active --config tools/top_down_planning/examples/top-down-planning.yaml
```

You should see a `status` (`running`, `paused`, `completed`, or `failed`) and a `phase`. Those are different axes — [lifecycle terms](../concepts/lifecycle-terms.md).

## 4. Continue production or resume

A default `tdp run` (`--until plan`) has not entered production. Continue with a later `--until` on resume (or pass `--until completed` on the original `tdp run` if you want the full path in one invocation):

```bash
tdp resume --run <run-id> --until completed --config tools/top_down_planning/examples/top-down-planning.yaml
```

`--until validated` is an intermediate milestone after planning construction and before production. Omit `--until` on **resume** to advance **one** orchestrator step. Flag catalog: [user CLI](../manual/cli.md). If resume refuses config or a limit is exhausted, [operations](operations.md) and [troubleshooting](../manual/troubleshooting.md).

## 5. Interpret the result

| What you see | Meaning |
| --- | --- |
| `status=completed` and `outcome=accepted` | Success. The [quality loop](../concepts/quality-loop.md) invariant held. |
| `status=completed` and `outcome=rejected` or `blocked` | Finished without accepting. Read validation/review, not a crash. |
| `status=paused` | Recoverable. Read `stop.code` and [troubleshooting](../manual/troubleshooting.md). |
| `status=failed` | Invariant stop. Failed runs cannot be resumed. |

Do not hand-edit the run store. Inspection commands: [run store](../manual/run-store.md).

Next: the [full lifecycle](lifecycle.md), or [prepared execution](prepared-and-sub-tdp.md) if you need parent/child packages.
