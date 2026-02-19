## Claude Code Overlay

Use Claude subagents for subjective scoring work that should be context-isolated.

### Parallel review (required)

Always run reviews in parallel — one message with multiple Task calls. Split dimensions
across agents however makes sense. Give each agent the codebase path, the dimensions to
score, what those dimensions mean, and the output format. Let agents decide what to read.
Do NOT prescribe file lists or tell agents whether to zoom in or out.

Workflow:
1. Read `dimension_prompts` from `query.json` for dimension definitions.
2. Split dimensions across N agents, send all Task calls in one message.
3. Each agent writes its output to a separate file.
4. Merge assessments (average where dimensions overlap) and findings.
5. `desloppify review --import findings.json`

### General subagent rules

1. Prefer delegating subjective review tasks to a project subagent in `.claude/agents/`.
2. If a skill-based reviewer is used, set `context: fork` so prior chat context does not leak into scoring.
3. For blind reviews, consume `.desloppify/review_packet_blind.json` instead of full `query.json`.
4. Score from evidence only; do not anchor scores to target thresholds like 95.
5. When evidence is mixed, score lower and explain uncertainty rather than rounding up.
6. Return machine-readable JSON only for review imports:

```json
{
  "assessments": {
    "naming_quality": 0,
    "error_consistency": 0,
    "abstraction_fit": 0,
    "logic_clarity": 0,
    "ai_generated_debt": 0
  },
  "findings": []
}
```
