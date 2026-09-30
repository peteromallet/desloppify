## Codex Overlay

This is the canonical Codex overlay used by the README install command.

1. Prefer first-class batch runs: `desloppify review --run-batches --runner codex --parallel --scan-after-import`.
2. The command writes immutable packet snapshots under `.desloppify/review_packets/holistic_packet_*.json`; use those for reproducible retries.
3. Keep reviewer input scoped to the immutable packet and the source files named in each batch.
4. If a batch fails, retry only that slice with `desloppify review --run-batches --packet <packet.json> --only-batches <idxs>`.
5. Manual override is safety-scoped: you cannot combine it with `--allow-partial`, and provisional manual scores expire on the next `scan` unless replaced by trusted internal or attested-external imports.

To replay completed slices from an interrupted or partly failed run, use
`desloppify review --import-run <run-dir> --only-batches <idxs>`. Indexes are
1-based in the immutable packet after multi-dimension batches are split, and
must belong to that run's recorded selection. Replay validates every selected
result and requires an assessment for every dimension in that slice, including
non-default dimensions. Without a filter, replay requires the entire recorded
run selection. Retry failed slices separately from the same immutable packet;
keep the packet, run summary and raw results unchanged.

### Subagent policy

Do not ask Codex review or triage prompts to spawn their own child agents. The supported Codex path is the first-class batch runner above: it already isolates packet slices, supports parallel subprocess execution, preserves retry artifacts, and keeps execution guardrails outside the model prompt. Revisit this only after Codex exposes a stable non-interactive subagent contract that can cap concurrency, preserve blind-packet isolation, and retry failed child tasks without increasing cost or weakening guardrails.

### Sandbox

Codex batch runs default to `-s workspace-write`. On hosts where that sandbox cannot run, such as WSL1 systems without the needed Linux namespace support, set `DESLOPPIFY_CODEX_SANDBOX=danger-full-access` in an externally sandboxed environment before running review batches. Supported values are `read-only`, `workspace-write`, and `danger-full-access`; invalid values fall back to `workspace-write`.

### Triage workflow

Prefer automated triage: `desloppify plan triage --run-stages --runner codex`

Options: `--only-stages observe,reflect` (subset), `--dry-run` (prompts only), `--stage-timeout-seconds N` (per-stage).

Run artifacts go to `.desloppify/triage_runs/<timestamp>/` — each run gets its own directory with `run.log` (live timestamped events), `run_summary.json`, per-stage `prompts/`, `output/`, and `logs/`. Check `run.log` to diagnose stalls or failures. Re-running resumes from the last confirmed stage.

If automated triage stalls, check `run.log` for the last event, then use `desloppify plan triage --stage-prompt <stage>` to get the full prompt with gate rules.

<!-- desloppify-overlay: codex -->
<!-- desloppify-end -->
