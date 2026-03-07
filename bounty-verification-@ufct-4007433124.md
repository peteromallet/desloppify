# Bounty Verification: S189 @ufct

**Submission:** `make_unused_issues` omits line number from issue ID, enabling silent overwrites

## Problem (in our own words)

`make_unused_issues` in `issue_factories.py` constructs issue IDs as `unused::{file}::{name}` using only the identifier name, not its line number. When two unused identifiers share the same name in the same file (e.g., variable `x` assigned-but-unused in two separate functions), they produce identical IDs. Since state is `dict[issue_id, issue]`, the second silently overwrites the first — one finding disappears with no warning. The line number is available in `e["line"]` but is only stored in `detail`, not used in the ID. Other detectors (treesitter empty_catch, unreachable_code, unused_import) correctly embed the line number in the ID for uniqueness.

## Evidence

- `issue_factories.py:22-31` (at 6eb2065): `make_issue("unused", e["file"], e["name"], ...)` — name only, no line
- `filtering.py:173`: `issue_id = f"{detector}::{rfile}::{name}"` — ID construction confirms no line
- `merge_issues.py:164-165`: `existing[issue_id] = dict(issue)` — dict keyed by ID, duplicates overwrite
- `phases.py:36`: `f"empty_catch::{e['line']}"` — treesitter correctly embeds line number
- `phases.py:104-107`: `f"unused_import::{e['line']}"` — treesitter unused imports also embeds line
- `unused.py:65-70`: ruff detector produces entries with `line` field from `location.row`

## Fix

Add `e["line"]` to the name parameter in `make_unused_issues`: `make_issue("unused", e["file"], f"{e['name']}::{e['line']}", ...)`. This matches the pattern used by treesitter phases.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | YES | Inconsistent ID construction causes silent data loss in the state dict |
| **Is this at least somewhat significant?** | YES | Affects a core detection pipeline; findings silently disappear with no error signal |

**Final verdict:** YES

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 6/10 |
| Originality | 7/10 |
| Core Impact | 5/10 |
| Overall | 6/10 |

## Summary

The submission correctly identifies a real bug: `make_unused_issues` omits the line number from the issue ID, causing silent overwrites when the same identifier name appears unused multiple times in one file. The inconsistency with treesitter phases (which embed line numbers) is well-documented. Practical impact is moderate since it requires same-named identifiers in the same file, but it's a genuine data-loss bug in a core pipeline with no error or deduplication signal.

## Why Desloppify Missed This

- **What should catch:** A consistency checker or linter verifying that all `make_issue` callers include sufficient uniqueness guarantees in the name/ID segment
- **Why not caught:** The bug only manifests with specific input conditions (same name, same file); normal testing wouldn't exercise this path unless specifically constructing duplicate-name test cases
- **What could catch:** A unit test that feeds two entries with the same name but different lines in the same file into `make_unused_issues` and verifies both survive in the state dict

## Verdict Files

- [Verdict JSON](https://github.com/xliry/desloppify/blob/task-522-lota-1/bounty-verdicts/%40ufct-4007433124.json)
- [Verdict Report](https://github.com/xliry/desloppify/blob/task-522-lota-1/bounty-verification-%40ufct-4007433124.md)

Generated with [Lota](https://github.com/xliry/lota)
