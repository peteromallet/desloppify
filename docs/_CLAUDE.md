## Claude Code Overlay

Use Claude subagents for subjective scoring work that should be context-isolated.

### Subjective review

1. **Preferred**: `desloppify review --run-batches --runner codex --parallel --scan-after-import` — does everything in one command.
2. **Claude cloud path**: `desloppify review --external-start --external-runner claude` → use generated `claude_launch_prompt.md` + `review_result.template.json` → run printed `desloppify review --external-submit --session-id <id> --import <file>`.
3. **Manual path**: split dimensions across N subagents (one message, multiple Task calls), merge outputs, then `desloppify review --import findings.json`.

For the manual path:
- Read `dimension_prompts` from `query.json` for dimension definitions.
- Give each agent the codebase path, dimensions, and output format. Let agents decide what to read.
- Each agent writes output to a separate file. Merge assessments (average overlaps) and findings.
- Import first, fix after — import creates tracked state for correlation.

### Subagent rules

1. Prefer delegating review tasks to a project subagent in `.claude/agents/`.
2. Set `context: fork` so prior chat context does not leak into scoring.
3. For blind reviews, consume `.desloppify/review_packet_blind.json` instead of full `query.json`.
4. Score from evidence only; do not anchor to target thresholds. When mixed, score lower.
5. Return machine-readable JSON matching the format in the base skill doc. For `--external-submit`, include `session` from the generated template.
6. `findings` MUST match `query.system_prompt` exactly. Use `"findings": []` when no defects found.
7. Import is fail-closed: invalid findings abort unless `--allow-partial` is passed.

<!-- desloppify-overlay: claude -->
<!-- desloppify-end -->
