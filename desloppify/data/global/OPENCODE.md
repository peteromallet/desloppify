## OpenCode Overlay

When installed (via `desloppify update-skill opencode`), OpenCode automatically loads this skill for code quality, technical debt, and health score questions.

### Review workflow

Use the native `--runner opencode` for automated batch reviews:

```
desloppify review --run-batches --runner opencode --parallel --scan-after-import
```

This spawns OpenCode subprocesses (`opencode run --format json`) for each batch, extracts results from the NDJSON stream, merges them, and imports as trusted assessments — identical pipeline to the Codex runner but using OpenCode as the execution engine.

#### Warm server mode (optional, recommended for parallel runs)

Start a persistent OpenCode server to avoid MCP cold-start overhead per batch:

```
opencode serve --port 4096 &
export DESLOPPIFY_OPENCODE_ATTACH=http://localhost:4096
desloppify review --run-batches --runner opencode --parallel --scan-after-import
```

When `DESLOPPIFY_OPENCODE_ATTACH` is set, each batch subprocess attaches to the running server via `--attach <url>` instead of spawning a fresh instance.

#### Preparing a review manually

1. **Prepare**: `desloppify review --prepare` — writes `query.json` and `.desloppify/review_packet_blind.json`.
2. **Run batches**: `desloppify review --run-batches --runner opencode --parallel --scan-after-import`

The runner handles batch splitting, prompt generation, parallel execution, retry/stall detection, result extraction, merge, and trusted import automatically.

<!-- desloppify-overlay: opencode -->
<!-- desloppify-end -->
