"""Text templates for scan reporting output."""

from __future__ import annotations

from textwrap import dedent


def build_workflow_guide(attest_example: str) -> str:
    """Render the scan workflow guide with current attestation text."""
    return dedent(
        f"""
        ## Workflow Guide

        Work the two loops: **outer** (scan → score → at target? → rescan) and
        **inner** (plan → fix next → update plan → repeat until plan clear).

        1. **Follow `next`**: `desloppify next` — the single source of truth for what to work on.
           It respects the plan, surfaces auto-clustered batches, and tells you exactly what to do.
        2. **Fix & resolve**: Fix the issue, then:
           `desloppify plan done "<id>" --note "<what you did>" --confirm`
           Or with explicit attestation: `--attest "{attest_example}"`
        3. **Plan strategically**: `desloppify plan` — reorder, cluster related issues, defer low-value work.
           Think about sequencing: what unblocks the most? What cascades? What can be batched?
        4. **Run auto-fixers** (if available): `desloppify fix <fixer> --dry-run` to preview, then apply.
        5. **Rescan**: `desloppify scan --path <path>` — verify improvements, catch cascading effects.
        6. **Subjective review**: `desloppify review --run-batches --runner codex --parallel --scan-after-import`
           (or `review --prepare` → review → import for manual path).
        7. **Check progress**: `desloppify status` — dimension scores dashboard.

        ### Decision Guide
        - **Tackle**: T1/T2 (high impact), auto-fixable, security findings
        - **Consider skipping**: T4 low-confidence, test/config zone findings (lower impact)
        - **Wontfix**: Intentional patterns, false positives →
          `desloppify plan skip --permanent "<id>" --note "<why>" --attest "{attest_example}"`
        - **Batch wontfix**: Multiple intentional patterns →
          `desloppify plan skip --permanent "<detector>::*::<category>" --note "<why>" --attest "{attest_example}"`

        ### Understanding Scores
        - **Overall**: 40% mechanical + 60% subjective. Lenient — wontfix doesn't count against you.
        - **Objective**: Mechanical detectors only (no subjective review component).
        - **Strict**: Same as overall, but wontfix items count as open. THIS IS YOUR NORTH STAR.
        - **Verified**: Like strict, but only credits fixes the scanner has confirmed.
        - Wontfix is not free — every wontfix widens the overall↔strict gap.
        - Re-reviewing subjective dimensions can LOWER scores if the reviewer finds issues.

        ### Understanding Dimensions
        - **Mechanical** (File health, Code quality, etc.): Fix code → rescan
        - **Subjective** (Naming quality, Logic clarity, etc.): Address review findings → re-review
        """
    ).strip()


__all__ = ["build_workflow_guide"]
