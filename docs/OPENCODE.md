## OpenCode Overlay

Use the desloppify skill for codebase health scanning and technical debt tracking.

### Running Commands

Execute desloppify commands via the Bash tool:

```bash
desloppify scan --path .
desloppify status
desloppify next --count 5
desloppify show <pattern>
desloppify fix <fixer>
desloppify resolve fixed "<id>"
```

### Skill Integration

When this skill is installed (via `desloppify update-skill opencode`), OpenCode will automatically load the desloppify skill and use it when you ask about:
- Code quality issues
- Technical debt
- Health scores
- What to fix next
- Creating a cleanup plan

### Core Workflow

1. `desloppify scan --path .` — run scan, follow INSTRUCTIONS FOR AGENTS
2. Fix recommended issues
3. `desloppify resolve fixed "<id>"`
4. Rescan to verify

### Subjective Reviews

For subjective scoring, use OpenCode's subagent system:
1. Read `dimension_prompts` from `query.json`
2. Delegate to subagent for isolated scoring
3. Import findings: `desloppify review --import findings.json`
4. Fix via core loop

<!-- desloppify-overlay: opencode -->
<!-- desloppify-end -->
