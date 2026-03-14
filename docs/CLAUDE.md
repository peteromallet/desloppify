## Claude Code Overlay

Use Claude subagents for subjective scoring work. **Do not use `--runner codex`** — use Claude subagents exclusively.

Install it with `desloppify update-skill claude`. The native Claude target is `~/.claude/skills/desloppify/SKILL.md`. Use `--scope project` only if you intentionally need the legacy repo-local compatibility install.

### Review workflow

Run `desloppify review --prepare` first to generate review data, then use Claude subagents:

1. **Prepare**: `desloppify review --prepare` — writes `query.json` and `.desloppify/review_packet_blind.json`.
2. **Launch subagents**: Split the review across N parallel Claude subagents (one message, multiple Task calls). Each agent reviews a subset of dimensions.
3. **Merge & import**: Merge agent outputs, then `desloppify review --import merged.json --manual-override --attest "Claude subagents ran blind reviews against review_packet_blind.json" --scan-after-import`.

#### How to split dimensions across subagents

- Read `dimension_prompts` from `query.json` for dimensions with definitions and seed files.
- Read `.desloppify/review_packet_blind.json` for the blind packet (no score targets, no anchoring data).
- Group dimensions into 3-4 batches by theme (e.g., architecture, code quality, testing, conventions).
- Launch one Task agent per batch with `subagent_type: "general-purpose"`. Each agent gets:
  - The codebase path and list of dimensions to score
  - The blind packet path to read
  - Instruction to score from code evidence only, not from targets
- Each agent writes output to a separate file. Merge assessments (average overlapping dimension scores) and concatenate findings.

### Subagent rules

1. Each agent must be context-isolated — do not pass conversation history or score targets.
2. Agents must consume `.desloppify/review_packet_blind.json` (not full `query.json`) to avoid score anchoring.

### Triage workflow

Orchestrate triage with per-stage subagents:
1. `desloppify plan triage --run-stages --runner claude` — prints orchestrator instructions
2. For each stage (observe → reflect → organize → enrich):
   - Get prompt: `desloppify plan triage --stage-prompt <stage>`
   - Launch a subagent with that prompt
   - Verify: `desloppify plan triage` (check dashboard)
   - Confirm: `desloppify plan triage --confirm <stage> --attestation "..."`
3. Complete: `desloppify plan triage --complete --strategy "..." --attestation "..."`

<!-- desloppify-overlay: claude -->
<!-- desloppify-end -->
