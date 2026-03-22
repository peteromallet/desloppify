## VS Code Copilot Overlay

VS Code Copilot supports native subagents via `.github/agents/` definitions.
Use them for context-isolated subjective reviews.

### Review workflow

Define a reviewer in `.github/agents/desloppify-reviewer.md`:

```yaml
---
name: desloppify-reviewer
tools: ['read', 'search']
---
```

Use the prompt from the "Reviewer agent prompt" section above.

Define an orchestrator in `.github/agents/desloppify-review-orchestrator.md`:

```yaml
---
name: desloppify-review-orchestrator
tools: ['agent', 'read', 'search']
agents: ['desloppify-reviewer']
---
```

Split dimensions across `desloppify-reviewer` calls (Copilot runs them concurrently), merge assessments and findings, then import.

<!-- desloppify-overlay: copilot -->
<!-- desloppify-end -->
