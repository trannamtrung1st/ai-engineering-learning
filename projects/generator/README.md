# Portable Spec Generator

Turn a single **initial idea** into a full spec package (BRD, technical, UI/UX, AI harness) using a Ralph-style stepped loop with verification gates.

## Fresh repo (portable)

Copy only these into a new repository:

```
generator/
docs/initial-idea.md
```

Then run from the generator directory:

```bash
cd generator
npm run gen:loop
```

Or:

```bash
cd generator
GEN_APPLY=1 ./scripts/generate.sh --apply
```

To target a repo when the generator lives outside it:

```bash
GEN_REPO_ROOT=/path/to/target-repo GEN_APPLY=1 ./scripts/generate.sh --apply
```

## Prerequisites

- [Cursor CLI](https://cursor.com/docs/cli): `agent login`
- `jq`, `curl`, `rsync`, `node`

## Commands

Run from `generator/`:

| Command | Description |
|---|---|
| `npm run gen:loop` | Full autonomous loop until `GEN_COMPLETE` |
| `npm run gen:once` | Single step |
| `npm run gen:verify` | Check all steps passed |
| `./scripts/generate.sh --apply --once` | Single step (shell) |

The target repo's root `package.json` does **not** include generator scripts — only `aih:*` implementation harness commands.

## Environment

| Variable | Purpose |
|---|---|
| `GEN_APPLY=1` | Required to write `docs/` and `ai-harness/` |
| `GEN_REPO_ROOT` | Target repo root (default: parent of `generator/`) |
| `GEN_FORCE=1` | Overwrite existing harness backlog |
| `GEN_SKIP_AGENT=1` | Skip Cursor agent (testing) |
| `GEN_SKIP_REVIEW=1` | Skip optional AI doc review |
| `GEN_MODEL` | Override default model |
| `GEN_STREAM_AGENT=0` | Disable live stream-json agent output and use legacy text output |
| `GEN_AGENT_VERBOSE=0` | Hide stream adapter tool/session diagnostics |
| `GEN_AGENT_TIMEOUT_MS` | Override max wall-clock timeout for generator agents |
| `GEN_AGENT_IDLE_TIMEOUT_MS` | Override stream idle timeout for generator agents |
| `GEN_AGENT_SIGNAL_GRACE_MS` | Override grace period after completion signals |
| `GEN_AGENT_RESULT_GRACE_MS` | Override grace period after Cursor CLI result events |

## Output

After `GEN_COMPLETE`:

```
docs/product-meta.json  # Extracted product metadata (optional designSystem)
docs/brds/              # 10 BRD files
docs/technical/         # 14 technical specs
docs/ui-ux/             # 16 UI/UX specs (includes DESIGN.md)
ai-harness/             # Full Ralph harness (scripts + generated backlog)
package.json            # Root workspace with aih:* scripts only
```

Next: run the implementation harness from the repo root:

```bash
npm run aih:testgen:loop
npm run aih:loop
```

## Safety in existing repos

The generator **does not write** unless `GEN_APPLY=1`. It refuses to overwrite an existing `ai-harness/whole-app-backlog.json` unless `GEN_FORCE=1`.

Generated artifacts must not reference `generator/` — validators enforce this.

### `product-meta.json` — optional `designSystem`

```json
"designSystem": {
  "framework": "default",
  "sourceUrl": null
}
```

- **`default`** — bundled neutral `DESIGN.md` template (step `uiux-design-md`)
- **Custom framework** — set `sourceUrl` to a raw design-md URL (e.g. Notion from [awesome-design-md](https://github.com/VoltAgent/awesome-design-md)); doc-writer customizes the preamble in the same step

See [GENERATOR-DESIGN.md](./GENERATOR-DESIGN.md) for step index and architecture.
