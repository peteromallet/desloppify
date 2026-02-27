## VS Code Copilot Overlay

VS Code Copilot supports native subagents via `.github/agents/` definitions.
Use them for context-isolated subjective reviews.

### Subjective review

1. **Preferred**: `desloppify review --run-batches --runner codex --parallel --scan-after-import`.
2. **Copilot/cloud path**: `desloppify review --external-start --external-runner claude` → use generated prompt/template → run printed `--external-submit` command.
3. **Manual path**: define a reviewer agent, split dimensions, merge, import.

For the manual path, define a reviewer in `.github/agents/desloppify-reviewer.md`:

```yaml
---
name: desloppify-reviewer
tools: ['read', 'search']
---
You are a code quality reviewer. You will be given a codebase path, a set of
dimensions to score, and what each dimension means. Read the code, score each
dimension 0-100 from evidence only, and return JSON in the required format.
Do not anchor to target thresholds. When evidence is mixed, score lower and
explain uncertainty.
```

And an orchestrator in `.github/agents/desloppify-review-orchestrator.md`:

```yaml
---
name: desloppify-review-orchestrator
tools: ['agent', 'read', 'search']
agents: ['desloppify-reviewer']
---
```

Split dimensions across `desloppify-reviewer` calls (Copilot runs them concurrently), merge assessments (average overlaps) and findings, then import.

### Review integrity

1. Do not use prior chat context, score history, or target-threshold anchoring while scoring.
2. Score from evidence only; when mixed, score lower and explain uncertainty.
3. Return JSON matching the format in the base skill doc. For `--external-submit`, include `session` from the generated template.
4. `findings` MUST match `query.system_prompt` exactly. Use `"findings": []` when no defects found.
5. Import is fail-closed: invalid findings abort unless `--allow-partial` is passed.

<!-- desloppify-overlay: copilot -->
<!-- desloppify-end -->
