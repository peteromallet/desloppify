## Codex Overlay

Codex uses isolated tasks/worktrees for independent review passes.

1. Run subjective review tasks in a fresh worktree/thread (or a separate Codex cloud task).
2. Keep reviewer input scoped to `.desloppify/review_packet_blind.json` plus referenced source files.
3. Do not use prior score history, narrative summaries, or issue labels while scoring.
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
