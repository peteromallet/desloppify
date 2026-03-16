## Cursor Overlay

Cursor supports native subagents via `.cursor/agents/` definitions. Use them
for context-isolated subjective reviews.

### Review workflow

Define a reviewer agent in `.cursor/agents/desloppify-reviewer.md`:

```markdown
---
name: desloppify-reviewer
description: Scores subjective codebase quality dimensions for desloppify
tools:
  - read
  - search
---
```

Use the prompt from the "Reviewer agent prompt" section above.

Launch multiple reviewer subagents, each with a subset of dimensions.
Each agent writes its output to `results/batch-N.raw.txt` (matching the batch index).
Merge assessments (average where dimensions overlap) and findings, then import.

<!-- desloppify-overlay: cursor -->
<!-- desloppify-end -->
