# S320 Verification: @vu1n — --runner CLI only accepts 'codex'

## Claims & Evidence

### Claim 1: --runner CLI arg only accepts 'codex' in parser_groups_admin_review.py
**VERIFIED**
- `parser_groups_admin_review.py:118-119`: `choices=["codex"]`, `default="codex"`
- `batch/scope.py:17-23`: `validate_runner()` raises `CommandError` for any non-codex value

### Claim 2: prepare.py displays workflow options for multiple runners
**VERIFIED**
- `prepare.py:121-155` prints 5 workflow paths:
  1. Codex (automated `--run-batches --runner codex`)
  2. Claude / other agent (`--dry-run` → manual subagent)
  3. Cloud/external (`--external-start --external-runner claude`)
  4. Issues-only fallback (`--import issues.json`)
  5. Emergency manual override

### Claim 3: runner_process.py:24-44 builds codex-specific CLI
**VERIFIED**
- `runner_process.py:24-44`: `codex_batch_command()` builds `["codex", "exec", "--ephemeral", ...]`
- Only codex binary invocation; no abstraction for other runners

### Claim 4: orchestrator.py:243-259 hardcodes run_codex_batch_fn
**VERIFIED**
- `orchestrator.py:243-259`: Lambda wraps `run_codex_batch()` with `CodexBatchRunnerDeps`
- Named `run_codex_batch_fn` — codex-specific by design

### Claim 5: execution.py:418 retrieves runner but only codex works
**VERIFIED**
- `execution.py:418`: `runner = getattr(args, "runner", "codex")`
- `execution.py:419`: `validate_runner(runner, ...)` — rejects non-codex

## Significance Assessment

**Intentional phased rollout, not a bug.** The codebase explicitly provides:

1. `--dry-run` mode (`execution.py:504-557`) generates prompts without running codex,
   allowing any runner to be used manually. The prepare output documents this as
   "Option 2: Claude / other agent".
2. `--external-runner claude` (`parser_groups_admin_review.py:97-101`) handles
   external review sessions with a separate path.
3. `--import-run` re-imports results from any runner's output directory.
4. The `choices=["codex"]` constraint is honest — it only restricts the automated
   `--run-batches` path, not the broader review workflow.

The multi-runner prepare output is aspirational documentation for the dry-run
workflow, not a broken promise. Users who want Claude or other runners use
`--dry-run` and get fully functional prompt/result scaffolding.

## Verdict

**PARTIALLY VERIFIED** — All code references are accurate. The asymmetry between
the `--runner` flag (codex-only) and the prepare output (multi-runner guidance) is
real but by design. The `--dry-run` + `--import-run` path provides a complete
workaround for non-codex runners. Low significance as a design issue.

| Metric | Score |
|--------|-------|
| Sig    | 3     |
| Orig   | 3     |
| Core   | 1     |
| Overall| 2     |
