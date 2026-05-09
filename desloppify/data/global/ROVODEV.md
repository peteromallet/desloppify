## Rovo Dev Overlay

Desloppify is installed as a Rovo Dev skill at `.rovodev/skills/desloppify/SKILL.md`. Rovo Dev discovers skills in both the user-level (`~/.rovodev/skills/`) and project-level (`.rovodev/skills/`) directories, and lazy-loads the skill body into context via the built-in `get_skill` tool when desloppify is invoked.

### Subagents

Rovo Dev supports parallel subagents via the `invoke_subagents` tool. The `General Purpose` subagent inherits all of the parent's tools and is ideal for context-isolated subjective review batches and per-stage triage work. Concurrency caps for `invoke_subagents` are set by Rovo Dev itself and may evolve over time — see the manual fallback section below for the current per-call limit.

### Review workflow

#### Native batch runner (recommended)

Use the first-class `--runner rovodev` for automated batch reviews:

```bash
desloppify review --run-batches --runner rovodev --parallel --scan-after-import
# Each batch is its own `acli rovodev` subprocess, so concurrency is bounded
# by `--max-parallel-batches` (default 3), NOT by Rovo Dev's in-process
# subagent limit. Bump it for faster wall-clock review on large packets:
#   --max-parallel-batches 6
```

This spawns `acli rovodev` subprocesses (one per batch), recovers the JSON payload from each agent's reply (or from the agent-written output file), merges them, and imports as trusted assessments — same end-to-end shape as the Codex / OpenCode runners (subprocess-per-batch → file-output → merge → trusted import), with the wire-level details adapted to `acli rovodev`'s prompt-instructed output mode.

Optional environment overrides:

- `DESLOPPIFY_ROVODEV_NO_YOLO=1` opts out of `--yolo` (the default). With `--yolo` enabled the agent can write the per-batch output file in non-interactive mode without permission prompts; turn it off only for interactive review work.
- `DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA='<schema or path>'` is forwarded as `--output-schema`, constraining the agent's reply to a JSON shape.
- `DESLOPPIFY_ROVODEV_EXTRA_ARGS="--config-override '{...}'"` is shell-split and appended verbatim before the prompt (useful for `--config-override`, `--restore`, `--worktree`, etc.).
- `DESLOPPIFY_ROVODEV_EXECUTABLE=acli` overrides the binary name (useful when `acli` is shipped under a different name in CI).

#### Manual subagent path

If you prefer to drive batches from inside an existing Rovo Dev session, use the manual subagent flow:

1. Prepare review prompts and the blind packet:
   ```bash
   desloppify review --run-batches --dry-run
   ```
   This generates one prompt file per batch in
   `.desloppify/subagents/runs/<run-id>/prompts/` and prints the run directory.

2. Note the run id printed by step 1 (e.g. `20260509_122030`). Replace
   `<run-id>` in the paths below with that real value before invoking —
   subagents do not share the parent's context, so passing the
   placeholder verbatim will leave them unable to find the prompt or
   know where to write their output.

3. Launch Rovo Dev subagents in groups (Rovo Dev currently caps
   `invoke_subagents` at 4 per call) using `invoke_subagents`,
   passing one task per batch. Each subagent should:
   - read its prompt file at
     `.desloppify/subagents/runs/<run-id>/prompts/batch-N.md`
   - read `.desloppify/review_packet_blind.json`
   - inspect the repository as instructed by the prompt's dimension list
   - write ONLY valid JSON to
     `.desloppify/subagents/runs/<run-id>/results/batch-N.raw.txt`

   Example invocation (with `<run-id>` already substituted):
   ```
   invoke_subagents(
     subagent_names=["General Purpose", "General Purpose", "General Purpose"],
     task_names=["review-batch-1", "review-batch-2", "review-batch-3"],
     task_descriptions=[
       "Review batch 1. Read .desloppify/subagents/runs/20260509_122030/prompts/batch-1.md, follow it exactly, inspect the repository, and write ONLY valid JSON to .desloppify/subagents/runs/20260509_122030/results/batch-1.raw.txt. Do not edit repository source files.",
       "Review batch 2. ...",
       "Review batch 3. ..."
     ],
   )
   ```

   Repeat the call in groups respecting Rovo Dev's per-call cap (e.g.
   batches 1-4, then 5-8, ...). Wait for each group to finish before
   launching the next.

4. After every prompt for the run has a matching result file, import them
   (using the same real run id):
   ```bash
   desloppify review --import-run .desloppify/subagents/runs/<run-id> --scan-after-import
   ```

### Key constraints

- `invoke_subagents` only applies to the manual fallback path; it does NOT
  cap the native `--runner rovodev` pipeline (each batch is its own
  subprocess, throttled by `--max-parallel-batches`).
- Per-call `invoke_subagents` concurrency is bounded by Rovo Dev itself
  (currently up to 4 subagents per call). Check `/help invoke_subagents`
  if you suspect the limit has changed.
- Subagents do not inherit parent conversation context — the prompt file and
  the blind packet must contain everything they need.
- Subagents must consume `.desloppify/review_packet_blind.json` (not full
  `query.json`) to avoid score anchoring.
- The importer expects `results/batch-N.raw.txt` files, not `.json` filenames.
- The blind packet intentionally omits score history to prevent anchoring bias.

### Triage workflow

#### Native triage runner (recommended)

Use the first-class `--runner rovodev` to drive the full staged triage
pipeline (strategize → observe → reflect → organize → enrich → sense-check
→ commit) via `acli rovodev` subprocesses:

```bash
desloppify plan triage --run-stages --runner rovodev
```

Useful flags:

- `--only-stages observe,reflect` runs a subset of stages.
- `--dry-run` prints prompts only.
- `--stage-timeout-seconds N` overrides the per-stage timeout.

Each stage's prompt, output, log, and run summary land under
`.desloppify/triage_runs/<timestamp>/`; rerunning resumes from the last
confirmed stage. The `runner` field in `run_summary.json` is set to
`"rovodev"` for provenance.

The same `DESLOPPIFY_ROVODEV_*` environment overrides documented for the
review runner above (`DESLOPPIFY_ROVODEV_NO_YOLO`,
`DESLOPPIFY_ROVODEV_OUTPUT_SCHEMA`, `DESLOPPIFY_ROVODEV_EXTRA_ARGS`,
`DESLOPPIFY_ROVODEV_EXECUTABLE`) apply to triage stages too.

#### Manual stage-prompt path

If you prefer to drive triage from inside an existing Rovo Dev session,
run each stage by hand:

1. Get the stage prompt: `desloppify plan triage --stage-prompt <stage>`
2. If the stage benefits from parallel review work, fan it out with
   `invoke_subagents` (in groups respecting Rovo Dev's per-call cap);
   otherwise run the stage directly in the parent session.
3. Confirm the stage: `desloppify plan triage --confirm <stage> --attestation "..."`
4. Complete: `desloppify plan triage --complete --strategy "..." --attestation "..."`

### Atlassian context

Rovo Dev ships with first-class Atlassian (Jira / Confluence / Bitbucket)
tooling. When triaging or planning desloppify work, you can pull related
Jira issues, design docs, or PR history via the built-in Atlassian MCP
toolset, or load the `full-context-mode` skill via the `/full-context`
slash command for guided organisational research — no extra setup
required.

<!-- desloppify-overlay: rovodev -->
<!-- desloppify-end -->
