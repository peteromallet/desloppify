## GitHub Copilot Overlay

### Copilot CLI

Install a personal skill shared across projects with `desloppify setup --interface copilot`.
This writes `~/.copilot/skills/desloppify/SKILL.md` in the home directory of the
environment running Desloppify, including Linux/WSL. Run `/skills reload` in an
existing Copilot CLI session after installation.

For a project-local installation, run `desloppify update-skill copilot` from the
project root (or set `DESLOPPIFY_ROOT` explicitly). This updates
`.github/copilot-instructions.md`, which Copilot CLI also reads.

Use context-isolated subagents for subjective review when available. Otherwise,
follow the manual review workflow in the base skill. The agent definitions below
are specific to VS Code.

### VS Code

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
