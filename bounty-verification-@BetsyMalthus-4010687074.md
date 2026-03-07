# Bounty Verification: S231 @BetsyMalthus — Over-fragmented CLI parser modules

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4010687074
**Snapshot commit:** 6eb2065

## Claims Verified

### 1. CLI parsing logic split into "multiple small files"
**FACTUALLY INCORRECT.** The files at snapshot are:
- `parser.py` — 144 lines (top-level parser, imports subcommand builders)
- `parser_groups.py` — 285 lines (scan, status, tree, show, next, suppress, exclude)
- `parser_groups_admin.py` — 179 lines (detect, move, zone, config, autofix, viz, dev, langs, update-skill)
- `parser_groups_admin_review.py` — 298 lines (review command with 5 argument groups)
- `parser_groups_plan_impl.py` — 385 lines (plan command with 10+ subcommands)

Total: ~1,291 lines across 5 files. These are substantial modules, not "small files."

### 2. Split organized by "permission level" (admin/review/plan_impl)
**MISCHARACTERIZED.** The split is by command complexity and size:
- `parser_groups_admin_review.py` contains only the `review` command — it has 5 argument groups (core, external review, batch execution, trust, post-processing) totaling 298 lines. This single command warrants its own file.
- `parser_groups_plan_impl.py` contains only the `plan` command — it has 10+ subcommands (queue, reorder, skip, resolve, cluster, triage, commit-log) totaling 385 lines.
- The split is driven by command complexity, not by an artificial permission hierarchy.

### 3. "Understanding requires jumping between multiple files"
**OVERSTATED.** The import chain is `parser.py` → `parser_groups.py` → `parser_groups_admin.py` → `parser_groups_admin_review.py`. There is one re-export chain that could be cleaner, but each file is self-contained for its command group. The review parser is entirely in one file; the plan parser is entirely in one file.

### 4. "Simple changes may involve multiple files"
**NOT DEMONSTRATED.** Adding a new argument to `review` requires editing only `parser_groups_admin_review.py`. Adding a new plan subcommand requires editing only `parser_groups_plan_impl.py`. Adding a new top-level command requires `parser_groups.py` (or `parser_groups_admin.py`) and `parser.py` — the same 2-file change that any modular design requires.

### 5. Root cause: "over-engineering" / premature optimization
**DISAGREE.** Combining all files would produce a ~1,100-line monolith with 18 command parsers, 10+ plan subcommands, and 5 review argument groups. The current split is a reasonable response to genuine complexity.

## Duplicate Check
- **S200** (@XxSnake) raised "over-fragmentation" of planning/runner files — rejected as NO with similar reasoning.
- **S157** (@devnull37) covers a related but distinct concern (CLI command metadata split across registry.py and parser.py without sync enforcement) — accepted as YES_WITH_CAVEATS.
- **S232** (@lbbcym) explicitly references and agrees with S231 — would be a duplicate if S231 were accepted.

## Assessment
The submission mischaracterizes substantial modules (179-385 lines) as "small files" and claims the split follows "permission levels" when it actually follows command complexity. No concrete bug, maintenance incident, or actual developer friction is demonstrated. Combining would create a monolith that is itself an anti-pattern. This is a style preference presented as an engineering flaw.

The re-export chain (`parser_groups` → `parser_groups_admin` → `parser_groups_admin_review`) is a minor code smell, but it's a cosmetic issue, not a significant engineering problem.
