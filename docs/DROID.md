## Droid Overlay

Droid skills are installed at `.factory/skills/desloppify/SKILL.md`. Droid
automatically discovers and invokes skills based on the task context,
or you can invoke directly with `/desloppify`.

### Subagents

Droid supports custom droids (subagents) for parallel work. Use the `worker`
droid for delegating independent tasks — it inherits the project's tool
configuration and is ideal for parallel smell detection, file analysis,
or cross-cutting refactoring work.

### Review workflow

1. Run `desloppify review --prepare` to generate `query.json` and
   `.desloppify/review_packet_blind.json`.
2. Split dimensions into 3-4 batches by theme.
3. For each batch, launch a worker subagent:
   ```
   Task("worker", "review batch 1",
     prompt="Score these dimensions: <list>. Read .desloppify/review_packet_blind.json. Score from code evidence only. Write results to review_batch_1.json.")
   ```
4. Merge assessments (average overlapping scores) and concatenate findings.
5. Import: `desloppify review --import merged.json --manual-override --attest "Worker subagents ran blind reviews" --scan-after-import`.

Each worker must consume `.desloppify/review_packet_blind.json` (not full
`query.json`) to avoid score anchoring.

### Triage workflow

1. For each stage (observe → reflect → organize → enrich):
   - Get prompt: `desloppify plan triage --stage-prompt <stage>`
   - Launch worker with that prompt.
   - Confirm: `desloppify plan triage --confirm <stage> --attestation "..."`
2. Complete: `desloppify plan triage --complete --strategy "..." --attestation "..."`

<!-- desloppify-overlay: droid -->
<!-- desloppify-end -->
