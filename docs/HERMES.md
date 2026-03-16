## Hermes Agent Overlay

Hermes has built-in parallel subagent support via `delegate_task` (up to 3
concurrent children). Use `delegate_task(tasks=[...])` for subjective review
batches and per-stage triage support; avoid the older worktree-based guidance
here.

### Review workflow

1. Prepare review prompts and the blind packet:
   ```bash
   desloppify review --run-batches --dry-run
   ```
   This generates one prompt file per batch in
   `.desloppify/subagents/runs/<run-id>/prompts/` and prints the run directory.

2. Launch Hermes subagents in batches of 3 with `delegate_task(tasks=[...])`.
   Each subagent should:
   - read its prompt file at
     `.desloppify/subagents/runs/<run-id>/prompts/batch-N.md`
   - read `.desloppify/review_packet_blind.json`
   - inspect the repository from the prompt's dimension
   - write ONLY valid JSON to
     `.desloppify/subagents/runs/<run-id>/results/batch-N.raw.txt`

   Example task payload:
   ```json
   {
     "goal": "Review batch N. Read the prompt at .desloppify/subagents/runs/<run-id>/prompts/batch-N.md, follow it exactly, inspect the repository, and write ONLY valid JSON to .desloppify/subagents/runs/<run-id>/results/batch-N.raw.txt.",
     "context": "Repository root: <cwd>. Blind packet: .desloppify/review_packet_blind.json. The prompt file defines the required output schema. Do not edit repository source files. Only write the review result file.",
     "toolsets": ["terminal", "file"]
   }
   ```

   Repeat for batches 1-3, 4-6, 7-9, etc. Wait for each group of 3 to finish
   before launching the next group.

3. After all prompt files for that run have matching results, import them:
   ```bash
   desloppify review --import-run .desloppify/subagents/runs/<run-id> --scan-after-import
   ```

### Key constraints

- `delegate_task` supports at most 3 concurrent children at a time.
- Subagents do not inherit parent context; the prompt file and blind packet must
  provide everything needed.
- Subagents cannot call `delegate_task`, `clarify`, `memory`, or `send_message`.
- The importer expects `results/batch-N.raw.txt` files, not `.json` filenames.
- The blind packet intentionally omits score history to prevent anchoring bias.

### Triage workflow

Run triage stages sequentially. For each stage:

1. Get the stage prompt or use the command suggested by `desloppify next`.
2. If the stage benefits from parallel review work, use `delegate_task(tasks=[...])`
   in groups of 3; otherwise run the stage directly in the parent session.
3. Record the stage output with `desloppify plan triage --stage <stage> --report "..."`
   or the corresponding `--run-stages --runner ...` command when available.
4. Confirm with `desloppify plan triage --confirm <stage> --attestation "..."`.
5. Finish with `desloppify plan triage --complete --strategy "..." --attestation "..."`.

<!-- desloppify-overlay: hermes -->
<!-- desloppify-end -->
