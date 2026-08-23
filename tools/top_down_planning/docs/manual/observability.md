# Observability and notifications

**Audience:** operators watching a live or completed run.

`tdp run` and `tdp resume` always stream progress logs to **stderr** (including with `--stream-json`). Final structured command payloads remain on **stdout**.

Presentation precedence: defaults → YAML → `--set` → explicit dedicated flag. Changing `observability.*` or `notifications.*` does not invalidate resume.

## Console logging

```bash
tdp run --config cfg.yaml --log-level verbose --color auto
tdp run --config cfg.yaml --log-format jsonl --no-color
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--color auto\|always\|never` | from config / `auto` | Color (`--no-color` ⇒ `never`) |
| `--log-level quiet\|normal\|verbose\|trace` | from config / `normal` | Stderr verbosity (does not change `--agent-transcript`) |
| `--log-format console\|jsonl` | from config / `console` | Human console vs JSONL on stderr |
| `--agent-text` / `--no-agent-text` | from config / on | Thinking/response text on stderr |
| `--timestamps` / `--no-timestamps` | from config / off | Optional timestamp prefix |
| `--max-message-length N` | from config / unlimited | Truncate console event messages |
| `--max-tool-summary-length N` | from config / unlimited | Truncate `[tool:start]` / `[tool:end]` summaries |

YAML keys live under `observability` (`log_level`, `log_format`, `color`, `show_agent_text`, `agent_transcript`, optional length caps).

Capability tokens and secrets are redacted at every log level in stderr, JSONL, transcripts, and desktop notifications. `--log-level` and `--no-agent-text` filter stderr only.

## Stream JSON

```bash
tdp run --config cfg.yaml --stream-json
```

Progress stays on stderr. The command payload is on stdout (pipe to `jq` if you want). With durable user cancel, stdout includes `"cancelled": true`. If the command is interrupted **without** taking run ownership, `"cancelled": false` and `"command_interrupted": true`. Details: [troubleshooting](troubleshooting.md#cancellation).

`validate`, `status`, `inspect`, `doctor`, `tdp agent *`, and `tdp resume --check` never send desktop notifications. They may still use `--stream-json` for structured stdout.

## Transcripts

```bash
tdp resume --run <run-id> --config cfg.yaml --agent-transcript
```

`--agent-transcript` persists a redacted provider transcript to `agent-transcript.jsonl` under the run directory. It is independent of `--log-level` / `--no-agent-text`. Default is off (from config).

## Notifications

Optional desktop alerts on blocking `tdp run` / `tdp resume`. Install extra `[notifications]` after `core_tools` ([install](install.md)). Without `notify-py`, notifications are silently skipped. `CI=true` and headless Linux environments are suppressed at send time.

```yaml
notifications:
  enabled: true
  terminal: true    # outcomes, pauses, failures
  phase: true       # major phase transitions
  progress: false   # per-batch / per-item (noisy)
```

```bash
tdp run --config cfg.yaml --set notifications.progress=true
tdp resume --run <run-id> --no-notify
```

`--no-notify` is a master disable for that invocation. Omitted `--no-notify` does not override YAML/`--set`.

`terminal` and `phase` default on; `progress` defaults off. Ctrl+C (`user_cancelled`) and partial `--until` milestones notify when `notifications.enabled` is true even if `terminal` is false. Default single-step `tdp resume` (no `--until`) does not emit `target_reached`.

Related: [user CLI](cli.md), [configuration](configuration.md), [run store](run-store.md).
