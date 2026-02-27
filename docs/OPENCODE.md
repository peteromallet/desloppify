## OpenCode Overlay

When installed (via `desloppify update-skill opencode`), OpenCode automatically loads this skill for code quality, technical debt, and health score questions.

### Subjective review

1. **Preferred**: `desloppify review --run-batches --runner codex --parallel --scan-after-import`.
2. **Manual path**: `desloppify review --prepare` → delegate to subagent for isolated scoring → `desloppify review --import findings.json`.
3. Import first, fix after — import creates tracked state for correlation.

<!-- desloppify-overlay: opencode -->
<!-- desloppify-end -->
