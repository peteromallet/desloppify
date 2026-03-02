## Claude Code Overlay

Use Claude subagents for subjective scoring work. **Do not use `--runner codex`** — use Claude subagents exclusively.

### Subjective review

Run `desloppify review --prepare` first to generate review data, then use Claude subagents:

1. **Prepare**: `desloppify review --prepare` — writes `query.json` and `.desloppify/review_packet_blind.json`.
2. **Launch subagents**: Split the review across N parallel Claude subagents (one message, multiple Task calls). Each agent reviews a subset of dimensions.
3. **Merge & import**: Merge agent outputs, then `desloppify review --import merged.json --manual-override --attest "Claude subagents ran blind reviews against review_packet_blind.json" --scan-after-import`.

#### How to split dimensions across subagents

- Read `dimension_prompts` from `query.json` — it lists all dimensions with their definitions and seed files.
- Read `.desloppify/review_packet_blind.json` for the blind packet (no score targets, no anchoring data).
- Group dimensions into 3-4 batches by theme (e.g., architecture, code quality, testing, conventions).
- Launch one Task agent per batch. Each agent gets:
  - The codebase path and list of dimensions to score
  - The blind packet path to read
  - The output JSON schema (assessments + findings)
  - Instruction to score from code evidence only, not from targets
- Each agent writes output to a separate file. Merge assessments (average overlapping dimension scores) and concatenate findings.
- Import first, fix after — import creates tracked state entries for correlation.

### Subagent rules

1. Use the Task tool with `subagent_type: "general-purpose"` for review agents.
2. Each agent must be context-isolated — do not pass conversation history or score targets.
3. Agents must consume `.desloppify/review_packet_blind.json` (not full `query.json`) to avoid score anchoring.
4. Score from evidence only; do not anchor to target thresholds. When mixed, score lower.
5. Return machine-readable JSON matching the format in the base skill doc.
6. `findings` MUST match the schema in the blind packet's `system_prompt`. Use `"findings": []` when no defects found.
7. Import is fail-closed: invalid findings abort unless `--allow-partial` is passed.

<!-- desloppify-overlay: claude -->
<!-- desloppify-end -->
