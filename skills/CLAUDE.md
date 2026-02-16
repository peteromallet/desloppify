## Claude Code Overlay

Use Claude subagents for subjective scoring work that should be context-isolated.

1. Prefer delegating subjective review tasks to a project subagent in `.claude/agents/`.
2. If a skill-based reviewer is used, set `context: fork` so prior chat context does not leak into scoring.
3. For blind reviews, consume `.desloppify/review_packet_blind.json` instead of full `query.json`.
4. Return machine-readable JSON only for review imports:

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
