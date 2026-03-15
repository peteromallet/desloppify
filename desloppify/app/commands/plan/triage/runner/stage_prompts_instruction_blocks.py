"""Per-stage instruction text blocks for triage prompts."""

from __future__ import annotations

from desloppify.engine._plan.policy.execution_constraints import render_constraints

from .stage_prompts_instruction_shared import (
    PromptMode,
    observe_example_report_quality,
    observe_false_positive_guidance,
    observe_structured_template,
)


def _observe_instructions(mode: PromptMode = "self_record") -> str:
    tail = """\
When done, run:
```
desloppify plan triage --stage observe --report "<your analysis with structured assessments>"
```
"""
    if mode == "output_only":
        tail = """\
When done, write a plain-text observe report with structured assessments per issue.
The orchestrator records and confirms the stage.
"""
    return f"""\
## OBSERVE Stage Instructions

Your task: verify every open review issue against the actual source code.

{observe_false_positive_guidance()}

Do NOT analyze themes, strategy, or relationships between issues. That's the next stage (reflect).
Just verify: is each issue real?

**CRITICAL: You must cite specific issue IDs (hash prefixes like [abcd1234]) in your report.**
The confirmation gate requires citing at least 10% of issues (or 5, whichever is smaller).

**USE SUBAGENTS to parallelize this work.** Launch parallel subagents — one per dimension
group — to investigate concurrently. Each subagent MUST:
- Open and read the actual source file for EVERY assigned issue
- Verify specific claims: count the actual casts, props, returns, line count
- Check if the suggested fix already exists (common false positive)
- Report a clear verdict per issue: genuine / false positive / exaggerated / over-engineering / not-worth-it

Example subagent split for 90 issues across 17 dimensions:
- Subagent 1: architecture + organization (cross_module_architecture, package_organization, high_level_elegance)
- Subagent 2: abstraction + design (abstraction_fitness, design_coherence, mid_level_elegance)
- Subagent 3: duplicates + contracts (contract_coherence, api_surface_coherence, low_level_elegance)
- Subagent 4: migrations + debt + conventions (incomplete_migration, ai_generated_debt, convention_outlier, naming_quality)
- Subagent 5: type safety + errors + tests (type_safety, error_consistency, test_strategy, initialization_coupling, dependency_health)

### Structured Assessment Template

**Your report MUST include a structured assessment for EVERY issue.** Copy and fill out this
template for each issue:

{observe_structured_template()}

**Example:**
```
- hash: 34580232
  verdict: false-positive
  verdict_reasoning: Uses branded string union KnownTaskType with ~25 literals in src/types/database.ts line 50. The issue describes code that doesn't exist.
  files_read: [src/types/database.ts]
  recommendation: No action needed — issue is inaccurate

- hash: b634fc71
  verdict: genuine
  verdict_reasoning: Confirmed 65 properties at lines 217-282. Mixes pane lifecycle, filters, gallery data, interaction, and navigation.
  files_read: [src/shared/components/GenerationsPane/hooks/useGenerationsPaneController.ts]
  recommendation: Decompose into focused sub-hooks
```

{observe_example_report_quality()}

**Validation checks (all blocking):**
- Every entry must have a recognized `verdict` keyword
- Every entry must have non-empty `verdict_reasoning`
- Every entry must have non-empty `files_read` list
- Every entry must have non-empty `recommendation`

- Template fields left empty or with placeholder text

{tail}
"""


def _reflect_instructions(mode: PromptMode = "self_record") -> str:
    tail = """\
When done, run:
```
desloppify plan triage --stage reflect --report "<your strategy with cluster blueprint>" --attestation "<80+ chars mentioning dimensions or recurring patterns>"
```
"""
    if mode == "output_only":
        tail = """\
When done, write a plain-text reflect report with a concrete cluster blueprint.
The orchestrator records and confirms the stage.
"""
    return f"""\
## REFLECT Stage Instructions

Your task: using the verdicts from observe, design the cluster structure.

**A strategy is NOT a restatement of observe.** Observe says "here's what I found." Reflect
says "here's what we should DO about it, and here's what we should NOT do, and here's WHY."

**The Structured Observe Assessments table (provided below) is your primary input.** It contains
a per-issue verdict (genuine/false-positive/exaggerated/over-engineering/not-worth-it) with reasoning. Use
these verdicts as authoritative — do not second-guess observe unless you have specific evidence.

**Important: Issues with verdict `false-positive` or `exaggerated` have already been auto-skipped
by observe confirmation.** They are NOT in your issue set and do NOT need ledger entries.

For issues with verdict `over-engineering` or `not-worth-it`: observe flagged these as
questionable, but YOU decide. If you agree they're not worth fixing, skip them. If you disagree
and think the fix has value, cluster them. These are judgment calls, not factual determinations.

### What you must do:

1. **Filter:** which issues are genuine (from the observe assessments table)?
2. **Map:** for each genuine issue, what file/directory does it touch?
3. **Group:** which issues share files or directories? These become clusters.
4. **Skip:** which issues should be skipped? Apply YAGNI: if the fix is more complex than the
   problem, skip it. Valid skip reasons:
   - "the fix would add a 50-line abstraction to save 3 lines of duplication"
   - "the current code is clear and simple despite being theoretically suboptimal"
   - "observe verdict: not-worth-it — the improvement is marginal"
   - "fixing this requires touching 8 files for a naming consistency issue nobody notices"
   Invalid: "low priority" (everything is low priority compared to something)
5. **Order:** which clusters depend on others? What's the execution sequence?
6. **Check recurring patterns** — compare current issues against resolved history. If the same
   dimension keeps producing issues, that's a root cause that needs addressing, not just
   another round of fixes.
7. **Consider mechanical backlog** — the backlog section shows auto-clusters
   (pre-grouped detector findings) and unclustered items. For each auto-cluster:
   - **promote**: name it in a `## Backlog Decisions` section. Prefer clusters with
     `[autofix: ...]` hints because they are lower-risk.
   - **skip**: explicitly skip with a reason (e.g., "mostly test noise", "low value").
   - **supersede**: absorb the underlying work into a review cluster when the same files
     or root cause already belong together.
   You MUST make an explicit decision for every auto-cluster. Include a `## Backlog Decisions`
   section listing each auto-cluster with: promote, skip (with reason), or supersede.
   For unclustered items: promote individually or group related ones into a manual cluster.
   Mechanical items are NOT part of the Coverage Ledger — that ledger remains review-issues only.
8. **Account for every issue exactly once** — every open issue hash must appear in exactly one
   cluster line or one skip line. Do not drop hashes, and do not repeat a hash in multiple
   clusters or in both a cluster and a skip.

### Your report MUST include both a coverage ledger and a concrete cluster blueprint

This blueprint is what the organize stage will execute. Be specific:
```
## Coverage Ledger
- a5996373 -> cluster "travel-structure-contract-unification"
- fb113678 -> skip "false-positive-current-code"

## Cluster Blueprint
Cluster "media-lightbox-hooks" (all in src/domains/media-lightbox/)
Cluster "task-typing" (both touch src/types/database.ts)

## Backlog Decisions
- auto/unused-imports -> promote (overlaps with the files in cluster "task-typing")
- auto/dead-code -> skip "mostly test noise, low value"
- auto/type-assertions -> supersede "absorbed into cluster task-typing"

## Skip Decisions
Skip "false-positive-current-code" (false positive per observe)
```

### Hard accounting rule

- Start your report with a `## Coverage Ledger` section.
- In that section, mention each issue hash **once and only once** on its own ledger line.
- Do **not** mention issue hashes again in cluster rationale paragraphs, recurring-pattern notes,
  or ordering explanations. After the ledger, refer to clusters by name.
- Before finishing, do a self-check: the ledger must cover all open issue hashes exactly once.

### What a LAZY reflect looks like (will be rejected):
- Restating observe findings in slightly different words
- "We should prioritize high-impact items and defer low-priority ones"
- A bulleted list of dimensions without any strategic thinking
- Ignoring recurring patterns
- No `## Coverage Ledger`
- No cluster blueprint (just vague grouping ideas)
- Missing or duplicated issue hashes

### What a GOOD reflect looks like:
- "50% false positive rate. Of 34 issues, 17 are genuine. 10 of those are batch-scriptable
  convention fixes (zero risk, 30 min) — cluster 'convention-batch'. The remaining 7 split into
  3 clusters by file proximity: 'media-lightbox-hooks' (issues X,Y,Z — all in src/domains/media-lightbox/),
  'timeline-cleanup' (issues A,B,C — touching Timeline components), 'task-typing' (issues D,E).
  Skip: issue W (false positive), issue V (over-engineering), issue U (not-worth-it:
  adds ErrorBoundary wrapper around 3 components that already handle errors inline —
  technically cleaner but doubles the JSX nesting depth for no behavioral change).
  design_coherence recurs (2 resolved, 5 open) but only 1 of the 5 actually warrants work."

{tail}
"""


def _organize_instructions(mode: PromptMode = "self_record") -> str:
    intro = (
        "The reflect report contains a specific plan: which clusters to create, which issues go\n"
        "where, what to skip. The reflect report included above is authoritative. Do not go\n"
        "search old triage runs for a different blueprint unless you find a concrete mismatch.\n"
        "Build it using the CLI. If something doesn't work as planned\n"
        "(issue hash doesn't match, file proximity doesn't hold), adjust and document why."
    )
    process_block = """\
2. **False-positive and exaggerated issues have already been auto-skipped** by observe confirmation.
   You do NOT need to skip them manually. If reflect skipped additional issues (over-engineering/not-worth-it),
   skip those now:
   ```
   desloppify plan skip --permanent <pattern> --note "<reason from reflect>" --attest "I have reviewed this triage skip against the code and I am not gaming the score by suppressing a real defect."
   ```
3. Create clusters as specified in the blueprint:
   `desloppify plan cluster create <name> --description "..."`
4. Add issues: `desloppify plan cluster add <name> <patterns...>`
5. Execute ALL backlog decisions from the reflect stage's `## Backlog Decisions` section:
   - **promote**: `desloppify plan promote auto/<cluster-name>`
   - **skip**: no CLI action needed — the cluster stays in backlog, skip is documented
   - **supersede**: absorb into the named review cluster (already handled by clustering above)
   - With placement: `desloppify plan promote <pattern> before -t <target>`
6. Add steps that consolidate: one step per file or logical change, NOT one step per issue
7. Set `--effort` on each step individually (trivial/small/medium/large)
8. Set `--depends-on` when clusters touch overlapping files
"""
    tail = """\
When done, run:
```
desloppify plan triage --stage organize --report "<summary of priorities and organization>" --attestation "<80+ chars mentioning cluster names or the organized work>"
```
"""
    if mode == "output_only":
        intro = (
            "The reflect report contains a specific plan: which clusters to create, which issues go\n"
            "where, what to skip. The reflect report included above is authoritative. Do not go\n"
            "search old triage runs for a different blueprint unless you find a concrete mismatch.\n"
            "Translate that plan into a precise organize report. If something\n"
            "doesn't work as planned (issue hash doesn't match, file proximity doesn't hold), adjust\n"
            "and document why."
        )
        process_block = """\
2. **False-positive and exaggerated issues have already been auto-skipped** by observe confirmation.
   If reflect skipped additional issues (over-engineering/not-worth-it), include those skip decisions.
3. Define the clusters exactly as they should be created.
4. Assign every kept issue to a cluster.
5. Execute ALL backlog decisions from reflect's `## Backlog Decisions` section (promote/skip/supersede).
6. Consolidate steps: one step per file or logical change, NOT one step per issue.
7. Assign an effort level to each planned step (trivial/small/medium/large).
8. Call out cross-cluster dependencies when clusters touch overlapping files.
"""
        tail = """\
When done, write a plain-text organize report that names the clusters, their issue membership,
their consolidated steps, and any skip/dependency decisions. The orchestrator records the stage.
"""
    return f"""\
## ORGANIZE Stage Instructions

Your task: execute the cluster blueprint from the reflect stage.

{intro}

This stage should be largely mechanical. If you find yourself making major strategic
decisions, something went wrong in reflect — the strategy should already be decided.

### Process

1. Review the reflect report's cluster blueprint AND the observe assessments table (both provided below)
{process_block}

### Quality gates (the confirmation will check these)

Before recording, verify:
- [ ] Every issue that reflect marked as skip has been skipped (false-positive/exaggerated are already auto-skipped)
- [ ] No cluster where the total fix effort exceeds the problem severity (KISS: prefer
      simple code with a known smell over complex code with a hidden abstraction)
- [ ] Every cluster name describes an area or specific change, not a problem type
- [ ] No cluster has issues from 5+ unrelated directories (theme-group smell)
- [ ] Step count < issue count (consolidation happened)
- [ ] Every skip has a specific per-issue reason (not "low priority")
- [ ] Overlapping clusters have --depends-on set
- [ ] Cluster descriptions describe the WORK, not the PROBLEMS

Every review issue must end up in a cluster OR be skipped.

{tail}
"""


def _enrich_instructions(mode: PromptMode = "self_record") -> str:
    subagent_block = """\
**USE SUBAGENTS — one per cluster.** Each subagent MUST:

1. Run `desloppify plan cluster show <name>` to get steps, members, and reviewer suggestions
2. For deeper analysis, run `desloppify show <issue-id> --no-budget` to see full evidence
3. **Read the actual source file for every step** — not just the issue description.
   The issue says what's wrong; you need to see the code to say what to DO.
4. Write detail that includes: the file path, the specific location (line range or
   function name), and the exact change to make
5. Set effort based on the ACTUAL complexity you see in the code, not a guess
"""
    tail = """\
When done, run:
```
desloppify plan triage --stage enrich --report "<enrichment summary>" --attestation "<80+ chars mentioning cluster names or the executor-ready work>"
```
"""
    if mode == "output_only":
        subagent_block = """\
**USE SUBAGENTS — one per cluster.** Each subagent MUST:

1. Inspect the cluster definition provided in the prompt context
2. **Read the actual source file for every step** — not just the issue description.
   The issue says what's wrong; you need to see the code to say what to DO.
3. Write detail that includes: the file path, the specific location (line range or
   function name), and the exact change to make
4. Set effort based on the ACTUAL complexity you see in the code, not a guess
"""
        tail = """\
When done, write a plain-text enrichment report describing the corrected step details,
effort tags, and issue refs for each cluster. The orchestrator records the stage.
"""
    return f"""\
## ENRICH Stage Instructions

Your task: make EVERY step executor-ready. The test: could a developer who has never seen
this codebase read your step detail and make the change without asking a single question?

If the answer is "they'd need to figure out which file" or "they'd need to understand the
context" — your step is not ready. Be specific enough that the work is mechanical.
Use the organize report included above as the authoritative cluster plan; do not re-derive
strategy from old triage runs unless you find a concrete mismatch you need to explain.

### Requirements (ALL BLOCKING — confirmation will reject if not met)

1. Every step MUST have `--detail` with 80+ chars INCLUDING at least one file path (src/... or supabase/...)
2. Every step MUST have `--issue-refs` linking it to specific review issue hash(es)
3. Every step MUST have `--effort` tag (trivial/small/medium/large) — set INDIVIDUALLY, not bulk
4. File paths in detail MUST exist on disk (validator checks this)
5. No step may reference a skipped/wontfixed issue in its issue_refs

### How to enrich

{subagent_block}

### Common lazy patterns to avoid

**Copying the issue description as step detail.** The issue says "useGenerationsPaneController
returns 60+ values mixing concerns." That's a PROBLEM description. The step detail should say
"In src/shared/components/GenerationsPane/hooks/useGenerationsPaneController.ts (283 lines),
extract lines 45-89 (filter state: activeFilter, setActiveFilter, filterOptions, applyFilter)
into a new useGenerationFilters hook. The controller imports and spreads the sub-hook's return."

**Vague action verbs.** "Refactor", "clean up", "improve", "fix" are not actions.
"Extract lines 45-89 into useGenerationFilters", "delete lines 12-18", "rename the file
from X to Y and update the 3 imports in A.tsx, B.tsx, C.tsx" are actions.

**Guessing file paths.** If you write `src/shared/lib/jsonNarrowing.ts` and it doesn't exist,
confirmation will block. READ the file system. Only reference files you've verified exist.

**Bulk effort tags.** Don't mark everything "small". A file rename with 2 imports is "trivial".
Decomposing a 400-line hook into 3 sub-hooks is "medium" or "large". Think about each one.

**Over-engineering the fix.** KISS: the fix should be simpler than the problem. If you're
adding interfaces, registries, factory methods, or configuration to fix a code smell, the
cure is worse than the disease. Prefer: delete code > inline code > extract a function >
add an abstraction. If the simplest fix is "delete these 10 lines," say that — don't
propose a refactoring framework.

### Examples

**GOOD step detail:**
```
--detail "In src/shared/hooks/billing/useAutoTopup.ts lines 118-129, add onMutate handler
to capture previous queryClient state before optimistic update. In onError callback, restore
previous state and change showToast from false to true."
--issue-refs 79baeebf --effort small
```

**BAD step detail (will be rejected):**
```
--detail "Fix silent error swallowing"  # No file, no location, no action
--detail "Decompose god-hooks"  # What file? What hooks? Into what?
--detail "Address the issues identified in the observe stage"  # This says nothing
```

### Do NOT mark steps as done

Use `--update-step N` to add detail, effort, and issue-refs.
Do NOT use `--done-step` — steps are only marked done when actual code changes are made.

### File path rules

Only reference files that exist RIGHT NOW. Do not reference files that a step will create
(e.g., a new shared module) or rename targets (the new filename after a rename). Reference
the current source file and describe what will change. The path validator will block
confirmation if paths don't exist on disk.

{tail}
"""


def _sense_check_instructions(mode: PromptMode = "self_record") -> str:
    content_fix_block = (
        'Fix with: `desloppify plan cluster update <name> --update-step N --detail "..." --effort <tag>`'
    )
    structure_fix_block = """\
Fix with: `desloppify plan cluster update <name> --depends-on <other>`
Fix with: `desloppify plan cluster update <name> --add-step "..." --detail "..." --effort trivial --issue-refs <hash>`
"""
    value_commands = """\
Use these commands aggressively:
- `desloppify next --count 100` to inspect the current execution queue
- `desloppify plan cluster show <name>` to inspect cluster members and steps
- `desloppify show <issue-id-or-hash> --no-budget` to re-read the underlying finding
- `desloppify plan cluster update <name> --description "..." --update-step N --detail "..." --effort small`
- `desloppify plan skip --permanent <pattern> --note "<why>" --attest "I have reviewed this triage skip against the code and I am not gaming the score by suppressing a real defect."`
- `desloppify plan cluster delete <name>` if you skipped everything it contained
"""
    tail = """\
When done, run:
```
desloppify plan triage --stage sense-check --report "<findings summary>"
```
"""
    if mode == "output_only":
        content_fix_block = (
            "Report the exact step corrections that need to be made; the orchestrator will apply them."
        )
        structure_fix_block = (
            "Report the exact dependency additions or cascade steps that need to be made; "
            "the orchestrator will apply them.\n"
        )
        value_commands = (
            "State the exact queue items to keep, tighten, or skip, plus any cluster-step "
            "updates or deletions needed. The orchestrator will apply them."
        )
        tail = """\
When done, write a plain-text sense-check report with concrete content, structure, and value findings.
The orchestrator records and confirms the stage.
"""
    investigation_hint = (
        "Use `desloppify show <issue-hash> --no-budget` to verify step details "
        "match the original reviewer analysis.\n\n"
        if mode == "self_record"
        else ""
    )
    constraints = render_constraints(header="   Also flag steps that:", bullet="   - ")
    return f"""\
## SENSE-CHECK Stage Instructions

This stage is handled by three subagents. If you are being run as a
single-subprocess fallback, perform ALL three checks below.

Execution order: content batches (parallel) → structure batch → value batch (sequential).
Value runs last because it needs the corrected plan state from content and structure.

### Content Check (per cluster)
{investigation_hint}For EVERY step in every cluster, read the actual source file and verify:
1. OVER-ENGINEERING (check FIRST — if the fix fails this, skip the rest):
   Would this change make the codebase *worse*? Flag steps that:
   - Add abstractions, wrappers, or indirection for a one-time operation
   - Introduce unnecessary config/feature-flags/generalization
   - Make simple code harder to read for marginal benefit
   - Gold-plate beyond what the issue actually requires
   - Trade one smell for a worse one (e.g. fix duplication by adding a fragile base class)
   - Add more lines of code than they remove (net complexity increase)
{constraints}
   Remove or simplify over-engineered steps. If the whole cluster is net-negative,
   recommend removing it entirely — don't just flag it, say "skip this cluster."
2. STALENESS: Is the problem still present, or already fixed?
3. LINE NUMBERS: Does the code at the claimed lines match the step description?
4. NAMES: Do function/variable/type names in the step exist in the file?
5. COUNTS: Are counts ("update the 3 imports") accurate?
6. VAGUENESS: Could a developer with zero context execute this step?
7. EFFORT TAGS: Does the tag match actual scope?
8. DUPLICATES: Flag steps that duplicate work in another cluster.

{content_fix_block}

### Structure Check (global)
Build a file-touch graph and check:
1. SHARED FILES: Two clusters touching same file without --depends-on → add dependency
2. MISSING CASCADE: Rename/remove without importer updates → add cascade step
3. CIRCULAR DEPS: Flag cycles, don't add them

{structure_fix_block}

### Value Check (global — YAGNI/KISS pass)

Walk the CURRENT planned work item by item and make the final judgment about value.
Ask: does doing this make the codebase genuinely better? Beauty is a valid reason to keep work,
but not if it buys that beauty with new indirection, wrappers, abstraction layers, or confusion.

For EVERY live queue target, choose exactly one:
1. `keep` — clearly improves correctness, clarity, cohesion, simplicity, or elegance
2. `tighten` — worth doing, but the plan must be simplified or made more concrete first
3. `skip` — the fix would add churn, indirection, coordination, or abstraction for too little gain

What should usually be skipped:
- facade pruning that just spreads imports
- abstraction-for-abstraction's-sake
- tiny theoretical cleanups that make the code harder to follow
- fixes whose implementation is more complicated than the current code

What can still be worth keeping:
- simplifications that delete layers or reduce branching
- aesthetic cleanups that genuinely improve readability without adding machinery
- focused unifications that make naming or flow more coherent with less confusion

{value_commands}

Required process:
1. Re-read the actual code behind each queue target.
2. Apply the rubric above, not the raw issue title.
3. Tighten any keeper whose steps are too vague, too broad, or too complicated.
4. Permanently skip anything that fails the value test.
5. Delete dead clusters after skipping all their members.

Required report structure — include a Decision Ledger section:
```
## Decision Ledger
- cluster-or-id -> keep
- cluster-or-id -> tighten
- cluster-or-id -> skip
```

{tail}
"""


_STAGE_INSTRUCTIONS = {
    "observe": _observe_instructions,
    "reflect": _reflect_instructions,
    "organize": _organize_instructions,
    "enrich": _enrich_instructions,
    "sense-check": _sense_check_instructions,
}


__all__ = [
    "_STAGE_INSTRUCTIONS",
    "_enrich_instructions",
    "_observe_instructions",
    "_organize_instructions",
    "_reflect_instructions",
    "_sense_check_instructions",
]
