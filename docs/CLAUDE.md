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
5. Import findings — do NOT fix code before this step. Import creates tracked state
   entries that let desloppify correlate fixes to findings.
6. Fix imported findings via the core loop: `desloppify issues` → fix code →
   `desloppify resolve fixed "<id>"` → rescan.
7. Preferred local path (Codex runner): `desloppify review --run-batches --runner codex --parallel --scan-after-import`.
8. Claude/cloud path:
   - robust session flow (recommended): `desloppify review --external-start --external-runner claude`; use the generated `claude_launch_prompt.md` and `review_result.template.json`, then run the printed `desloppify review --external-submit --session-id <id> --import <file>` command
   - preflight validation (optional legacy): `desloppify review --validate-import findings.json --attested-external --attest "I validated this review was completed without awareness of overall score and is unbiased."`
   - durable scored import (legacy): `desloppify review --import findings.json --attested-external --attest "I validated this review was completed without awareness of overall score and is unbiased."`
   - findings-only fallback: `desloppify review --import findings.json`

### General subagent rules

1. Prefer delegating subjective review tasks to a project subagent in `.claude/agents/`.
2. If a skill-based reviewer is used, set `context: fork` so prior chat context does not leak into scoring.
3. For blind reviews, consume `.desloppify/review_packet_blind.json` instead of full `query.json`.
4. Score from evidence only; do not anchor scores to target thresholds like 95.
5. When evidence is mixed, score lower and explain uncertainty rather than rounding up.
6. Return machine-readable JSON only for review imports. For `--external-submit`, include `session` from the generated template:

```json
{
  "session": {
    "id": "<session_id_from_template>",
    "token": "<session_token_from_template>"
  },
  "assessments": {
    "naming_quality": 0,
    "error_consistency": 0,
    "abstraction_fit": 0,
    "logic_clarity": 0,
    "ai_generated_debt": 0
  },
  "findings": [
    {
      "dimension": "naming_quality",
      "identifier": "short_id",
      "summary": "one-line defect summary",
      "related_files": ["relative/path/to/file.py"],
      "evidence": ["specific code observation"],
      "suggestion": "concrete fix recommendation",
      "confidence": "high|medium|low"
    }
  ]
}
```
7. `findings` MUST match `query.system_prompt` exactly. Use `"findings": []` only when no defects are found.
8. Import is fail-closed by default: if any finding is invalid/skipped, `desloppify review --import` aborts unless `--allow-partial` is explicitly passed.
9. Assessment scores are auto-applied from trusted internal run-batches imports, or from Claude cloud session imports via `--external-start` + `--external-submit` (recommended). Legacy attested external import via `--attested-external` remains supported.
10. Manual override remains emergency-only: it cannot be combined with `--allow-partial`, and provisional manual scores expire on the next `scan` unless replaced by trusted internal or attested-external imports.

<!-- desloppify-overlay: claude -->
<!-- desloppify-end -->
