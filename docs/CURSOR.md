## Cursor Overlay

Cursor supports native subagents via `.cursor/agents/` definitions. Use them
for context-isolated subjective reviews.

### Parallel review

Split dimensions across subagents so each reviewer scores independently.
Define a reviewer agent in `.cursor/agents/desloppify-reviewer.md`:

```markdown
---
name: desloppify-reviewer
description: Scores subjective codebase quality dimensions for desloppify
tools:
  - read
  - search
---

You are a code quality reviewer. You will be given a codebase path, a set of
dimensions to score, and what each dimension means. Read the code, score each
dimension 0-100 from evidence only, and return JSON in the required format.
Do not anchor to target thresholds. When evidence is mixed, score lower and
explain uncertainty.
```

Workflow:
1. Read `dimension_prompts` from `query.json` for dimension definitions.
2. Launch multiple reviewer subagents, each with a subset of dimensions.
3. Each agent writes its output to a separate file.
4. Merge assessments (average where dimensions overlap) and findings.
5. `desloppify review --import findings.json`

### Review integrity

1. Do not use prior chat context, score history, or target-threshold anchoring while scoring.
2. Score from evidence only; when evidence is mixed, score lower and explain uncertainty.
3. Return machine-readable JSON only for review imports:

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

<!-- desloppify-update: { curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/docs/SKILL.md; printf '\n\n'; curl -fsSL https://raw.githubusercontent.com/peteromallet/desloppify/main/docs/CURSOR.md; } > .cursor/rules/desloppify.md -->
