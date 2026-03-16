## Windsurf Overlay

Windsurf does not support spawning subagents from within a Cascade session.
If not using the batch runner, parallel reviews require the user to open
multiple Cascade panes manually.

### Review workflow

1. Run `desloppify review --prepare` to generate `query.json`.
2. Ask the user to open additional Cascade panes for parallel review.
   Suggest splitting dimensions across 2-3 panes (e.g., naming + clarity
   in one, abstraction + error consistency in another).
3. Each pane scores its assigned dimensions independently, reading
   the codebase and `query.json`'s `dimension_prompts` for context.
4. Each pane writes output to `results/batch-N.raw.txt` (matching the batch index).
5. In the primary pane, merge assessments and findings, then import.

If the user prefers a single-pane workflow, review all dimensions sequentially
in one session.

<!-- desloppify-overlay: windsurf -->
<!-- desloppify-end -->
