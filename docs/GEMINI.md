## Gemini CLI Overlay

Gemini CLI has experimental subagent support, but subagents currently run
sequentially (not in parallel). Review dimensions one at a time.

### Setup

Enable subagents in Gemini CLI settings:
```json
{
  "experimental": {
    "enableAgents": true
  }
}
```

Optionally define a reviewer agent in `.gemini/agents/desloppify-reviewer.md`:

```yaml
---
name: desloppify-reviewer
description: Scores subjective codebase quality dimensions for desloppify
kind: local
tools:
  - read_file
  - search_code
temperature: 0.2
max_turns: 10
---

You are a code quality reviewer. You will be given a codebase path, a set of
dimensions to score, and what each dimension means. Read the code, score each
dimension 0-100 from evidence only, and return JSON in the required format.
Do not anchor to target thresholds. When evidence is mixed, score lower and
explain uncertainty.
```

### Review workflow

1. Run `desloppify review --prepare` to generate `query.json`.
2. Invoke the reviewer agent for each group of dimensions sequentially.
   Even without parallelism, isolating dimensions across separate agent
   invocations prevents score bleed between concerns.
3. Merge assessments and findings, then `desloppify review --import findings.json`.

When Gemini CLI adds parallel subagent execution, split dimensions across
concurrent agent calls instead.

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
