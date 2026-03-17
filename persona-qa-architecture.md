# Persona-Based Browser QA: Architecture Investigation Report

**Date**: 2026-03-17
**Scope**: Native integration of persona-based browser QA into the Open Paws desloppify fork
**Investigator**: Gary (Claude Code agent)

---

## 1. Current State: What Desloppify's Core Assumes

### Issue/WorkItem Data Model

The central data structure is `WorkItem` (TypedDict in `engine/_state/schema_types_issues.py`). Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Format: `{detector}::{relative_file}::{name}` |
| `detector` | `str` | Which detector produced this |
| `work_item_kind` | `str` | One of: `mechanical_defect`, `review_defect`, `review_concern`, `assessment_request` |
| `origin` | `str` | One of: `scan`, `review_import`, `synthetic_task` |
| `file` | `str` | **Defaults to `""` if missing** — not strictly mandatory but deeply embedded |
| `tier` | `int` | 1-4, validated |
| `confidence` | `str` | `low`/`medium`/`high` |
| `summary` | `str` | Human-readable |
| `detail` | `dict` | Arbitrary detector-specific payload |
| `status` | `Status` | `open`/`fixed`/`wontfix`/`false_positive`/`auto_resolved`/`deferred`/`triaged_out` |
| `note` | `str \| None` | Resolution note |
| Various timestamps | `str` | `first_seen`, `last_seen`, `resolved_at` |

**Key finding: `file` is NOT hard-mandatory.** The `ensure_state_defaults` function sets `issue.setdefault("file", "")` — empty string is legal. The display code (`render.py:144-146`) already handles empty/dot file values gracefully:
```python
file_val = item.get("file", "")
if file_val and file_val != ".":
    print(f"  File: {file_val}")
```

**Issue ID format is the real constraint.** `make_issue()` constructs IDs as `{detector}::{rel_file}::{name}`. For URL-based findings, we can use the URL path as the "file" component: `persona_qa::/about::missing-alt-text`.

### How State/Scoring/Display Work

**State persistence**: `engine/_state/persistence.py` — `load_state()` / `save_state()` with file locking, backup/recovery, atomic writes. State lives in `.desloppify/state.json`. `save_state()` calls `_recompute_stats()` which recalculates all scores from the current issue set — no special handling needed to add new issue types.

**Scoring**: Two-pool system (25% mechanical / 75% subjective). New mechanical dimensions can be added at runtime via `register_scoring_policy()` which calls `_rebuild_derived()` to rebuild `DIMENSIONS` in-place. The `MECHANICAL_DIMENSION_WEIGHTS` dict is mutable and can receive new entries.

**Work queue**: `engine/_work_queue/core.py` — `build_work_queue()` takes `StateModel` and returns ranked items. The queue is rebuilt from state + plan on every invocation. All finding sources already coexist: mechanical, subjective/LLM review, triage items, workflow actions. No filtering by origin type.

**Display**: The `next` render pipeline (`app/commands/next/render.py`) handles items generically. File display is gracefully optional. The compact view shows `item.get('file', '')`. No hard crashes on missing/empty file.

**Resolution**: `engine/_state/resolution.py` — `resolve_issues()` matches by pattern (ID, glob, prefix, detector, path). Pattern matching in `_matches_pattern()` uses ID string matching and path matching. URL-based IDs would match by ID or detector pattern without issue.

### Work Item Kinds and Origins

The taxonomy in `engine/_state/issue_semantics.py` is fixed to 4 kinds and 3 origins. Persona QA findings most naturally map to `mechanical_defect` with `scan` origin, though we could add a new kind. The inference functions (`infer_work_item_kind`) fall through to `MECHANICAL_DEFECT` for unknown detector names, which means persona QA issues would work immediately without taxonomy changes.

### Hook/Event System

**There is no post-scan hook system.** The `engine/hook_registry.py` is strictly for language detector hooks (test coverage modules). There are no callbacks, events, or extension points for "after scan completes" or "before queue renders." This means persona QA cannot be triggered automatically after a scan — it must be a separate explicit command.

### Plugin System

Three discovery mechanisms exist, but all are designed for adding new *detectors* within the static analysis paradigm. The plugin system can register detector metadata and scoring policies at runtime, but cannot inject new CLI commands. A persona QA command requires modifying the command registry directly.

---

## 2. Architecture Analysis: Hard Blockers vs Soft Constraints

### Not Blockers (Soft / Already Handled)

1. **Empty `file` field** — already handled gracefully throughout display and resolution
2. **New scoring dimension** — `register_scoring_policy()` and `MECHANICAL_DIMENSION_WEIGHTS` mutation are designed for this
3. **Mixed finding sources in queue** — mechanical, review, synthetic, workflow items already coexist
4. **Pattern-based resolution** — works on ID strings, detector names, globs — no file-path assumption
5. **State persistence** — `save_state()` recomputes everything from the issue dict, no special handling needed
6. **Work item kinds** — unknown detectors default to `mechanical_defect`, works out of the box

### Requires New Code (Medium Effort)

1. **New CLI command** — must add to `app/commands/registry.py` and create `app/commands/persona_qa/`
2. **Issue ID format** — need a `make_browser_issue()` helper that uses URL paths instead of file paths
3. **Display adaptation** — the `next` render shows "File:" label; browser issues should show "URL:" or "Route:"
4. **Detector + scoring registration** — boilerplate but necessary
5. **Agent interaction model** — the browser navigation/evaluation loop is entirely new

### Requires Design Decision (Needs Sam's Input)

1. **How findings persist across scans** — **Verified safe.** `reconcile_plan_after_scan()` only touches plan-referenced IDs that are no longer alive. It never enumerates by detector. Persona QA findings persist untouched through scan cycles.
2. **Potentials calculation** — mechanical scoring uses `potentials` (denominator). For browser QA, what's the denominator? Routes tested? Assertions checked? Personas run?
3. **Rescan behavior** — should `desloppify persona-qa` re-test everything, or only re-test previously failing routes?

---

## 3. Recommended Architecture

### Command Design: `desloppify persona-qa`

A dedicated command, not a post-scan hook. Rationale:
- Browser QA requires a running server (fundamentally different from static analysis)
- Different timing, different CI stage, different failure modes
- Can run independently or alongside scan results
- The same agent running `desloppify next` would also run `desloppify persona-qa` — sequential, not nested

**Subcommands:**
```
desloppify persona-qa --url http://localhost:3000        # run all personas against URL
desloppify persona-qa --url http://localhost:3000 --persona donor  # run specific persona
desloppify persona-qa --status                           # show persona QA status
desloppify persona-qa --clear                            # clear all persona QA findings
```

### Entry Point Integration

Add to `app/commands/registry.py`:
```python
"persona-qa": cmd_persona_qa,
```

New package: `app/commands/persona_qa/` with:
- `cmd.py` — command handler
- `runner.py` — browser session orchestration
- `profiles.py` — persona profile loading/validation
- `findings.py` — issue creation from browser observations

### Persona Profile Config Format

Profiles live in `.desloppify/personas/` as YAML files.

**Example: `.desloppify/personas/new-supporter.yaml`**
```yaml
name: New Supporter
description: >
  First-time visitor who cares about animals but has never
  donated or volunteered. Using a mobile phone, moderate
  tech literacy. Looking for ways to help.

# Browser context
device: mobile
viewport: { width: 390, height: 844 }
user_agent: default  # or specific string

# What this persona tries to do (ordered)
scenarios:
  - name: Find ways to help
    start: /
    goal: >
      Navigate from homepage to find concrete actions I can take
      to help animals. I should be able to find volunteer or
      donation options within 3 clicks.
    check:
      - Can reach action page from homepage
      - Clear call-to-action visible without scrolling
      - Language is welcoming, not guilt-inducing

  - name: Learn about the organization
    start: /
    goal: >
      Understand what this organization does and whether I trust
      them with my money or time.
    check:
      - About page is findable from any page
      - Mission statement is clear and specific
      - No jargon that requires insider knowledge

  - name: Make a donation
    start: /donate
    goal: >
      Complete a donation. The process should feel safe and
      straightforward.
    check:
      - Form is accessible and labeled correctly
      - Amount options are reasonable
      - Security indicators visible
      - Confirmation is clear

# Accessibility requirements for this persona
accessibility:
  - All images have alt text
  - Focus order is logical
  - Color contrast meets WCAG AA
  - Forms have visible labels

# What counts as a failure
severity_mapping:
  blocker: high     # Cannot complete the scenario at all
  usability: medium # Can complete but experience is poor
  polish: low       # Minor issues that don't block the goal
```

**Design rationale:**
- `scenarios` are narrative, not scripted — the LLM agent decides how to navigate
- `check` items are human-readable assertions the agent evaluates
- `severity_mapping` maps to desloppify's confidence levels for scoring
- Non-engineers can write these by describing what a user would try to do
- No CSS selectors, no XPaths, no code — pure intent and expectations

### Agent-Browser Interaction Model

The agent (Claude) drives the browser via Playwright MCP (already available as a deferred tool in this environment). The flow:

```
1. Agent reads persona profile YAML
2. Agent launches browser via Playwright MCP → navigates to start URL
3. For each scenario:
   a. Agent takes snapshot of current page
   b. Agent reasons about the persona's goal and decides next action
   c. Agent performs action (click, fill, navigate)
   d. Agent evaluates check items against what it observes
   e. Agent records findings (pass/fail per check item, with evidence)
4. Agent runs accessibility checks (can use axe-core via browser evaluate)
5. Agent produces structured findings JSON
6. desloppify imports findings into state
```

**Key design choice**: The agent is NOT running a scripted test. It's behaving AS the persona, making navigation decisions based on what it sees, and evaluating the experience qualitatively. This is why an LLM agent is the right tool — it can make judgment calls about "is this welcoming?" or "would a first-time visitor find this?"

### Finding Format: Browser Issues Become WorkItems

```python
def make_browser_issue(
    persona: str,
    route: str,
    scenario: str,
    check: str,
    *,
    severity: str,  # "blocker" / "usability" / "polish"
    summary: str,
    evidence: str,
    screenshot_path: str | None = None,
) -> Issue:
    confidence_map = {"blocker": "high", "usability": "medium", "polish": "low"}
    confidence = confidence_map.get(severity, "medium")

    # Use route as the "file" equivalent
    safe_route = route.strip("/").replace("/", "_") or "root"
    issue_id = f"persona_qa::{persona}::{safe_route}::{_slug(check)}"

    return {
        "id": issue_id,
        "detector": "persona_qa",
        "file": route,  # URL route as file — display will need "Route:" label
        "tier": {"blocker": 2, "usability": 3, "polish": 3}[severity],
        "confidence": confidence,
        "summary": summary,
        "detail": {
            "persona": persona,
            "scenario": scenario,
            "check": check,
            "evidence": evidence,
            "severity": severity,
            "screenshot": screenshot_path,
            "route": route,
        },
        "status": "open",
        "note": None,
        "first_seen": utc_now(),
        "last_seen": utc_now(),
        "resolved_at": None,
        "reopen_count": 0,
    }
```

**ID structure**: `persona_qa::{persona_name}::{route_slug}::{check_slug}` — stable across runs, enables reconciliation.

### Scoring Model

Register as a new mechanical dimension:

```python
register_detector(DetectorMeta(
    name="persona_qa",
    display="Persona QA",
    dimension="persona qa",
    action_type="manual_fix",
    guidance="Fix browser-facing issues identified by persona-based testing",
    tier=3,
))

register_scoring_policy(DetectorScoringPolicy(
    detector="persona_qa",
    dimension="persona qa",
    tier=3,
    file_based=False,  # NOT file-based — unique scoring per issue
))

MECHANICAL_DIMENSION_WEIGHTS["persona qa"] = 1.0
```

**Potentials**: The denominator for scoring should be the total number of check items across all personas and scenarios. If 3 personas have 4 scenarios with 3 checks each = 36 potentials. Issues that fail reduce the dimension score proportionally.

### Resolution Flow

Persona QA findings flow through the existing resolution system:

```bash
# Agent fixes the frontend code
# Agent re-runs persona QA for affected routes
desloppify persona-qa --url http://localhost:3000 --persona new-supporter

# Findings that pass now get auto-resolved
# Remaining failures stay open
# Agent resolves manually if needed:
desloppify plan resolve persona_qa::new-supporter::donate::form-labels \
  --attest "Added aria-labels to all donation form fields" \
  --note "Fixed form accessibility"
```

**Scan reconciliation**: When `desloppify persona-qa` runs, it should:
1. Mark all existing `persona_qa` issues for the tested personas as candidates for auto-resolve
2. Re-evaluate all check items
3. Issues that now pass → status `auto_resolved`
4. Issues that still fail → update `last_seen`
5. New failures → create as `open`
6. Issues from untested personas → unchanged (not wiped)

This mirrors how `desloppify scan` reconciles mechanical findings.

### Integration with Existing State and Queue

Persona QA findings are stored in the same `state["work_items"]` dict as all other findings. They appear in `desloppify next` output, are ranked by the same impact algorithm, can be clustered, skipped, described, and resolved through the same plan commands.

The only display adaptation needed: when rendering an item where `detail.get("route")` exists, show "Route:" instead of "File:" in the `next` output. This is a ~5-line change in `app/commands/next/render.py`.

---

## 4. LLM Integration

### How the Agent Drives the Browser

The agent (Claude) already has Playwright MCP tools available. The persona QA command doesn't need to implement browser automation — it orchestrates the agent's use of existing tools.

**Command output format** (what `desloppify persona-qa` prints for the agent):

```
  PERSONA QA: new-supporter
  URL: http://localhost:3000
  Device: mobile (390x844)

  SCENARIO 1: Find ways to help
  Start: /
  Goal: Navigate from homepage to find concrete actions I can take
        to help animals within 3 clicks.

  CHECK ITEMS:
  1. Can reach action page from homepage
  2. Clear call-to-action visible without scrolling
  3. Language is welcoming, not guilt-inducing

  INSTRUCTIONS FOR AGENT:
  1. Open http://localhost:3000 in the browser with mobile viewport
  2. Act as this persona — navigate naturally toward the goal
  3. For each check item, evaluate pass/fail with evidence
  4. Take screenshots of any failures
  5. When done, report findings as JSON to:
     desloppify persona-qa --import findings.json
```

The agent then:
1. Uses `mcp__playwright__browser_navigate` to open the URL
2. Uses `mcp__playwright__browser_snapshot` to see the page
3. Makes navigation decisions based on what a "new supporter" would do
4. Evaluates check items qualitatively
5. Writes findings JSON
6. Imports via the `--import` subcommand

### Relation to Existing Review System

The subjective review system (`intelligence/review/`) prepares payloads but never calls an LLM directly. Persona QA follows the same pattern:
- `desloppify persona-qa --prepare` → outputs structured persona/scenario data
- Agent performs the testing
- `desloppify persona-qa --import findings.json` → imports results into state

This is architecturally parallel to `desloppify review --prepare` / `desloppify review --import`.

### Agent Context

The agent needs:
1. The persona profile (YAML, loaded and printed by the command)
2. The target URL
3. Playwright MCP tools (already available)
4. The import command format

The agent does NOT need:
- Source code knowledge (it's testing the running app, not the code)
- Previous scan results
- Scoring internals

---

## 5. Persona Profile Format: Design Details

### File Location and Discovery

```
.desloppify/
  personas/
    new-supporter.yaml
    monthly-donor.yaml
    volunteer.yaml
    screen-reader-user.yaml
    organization-admin.yaml
```

Profiles are discovered by globbing `.desloppify/personas/*.yaml`.

### Profile Schema

```yaml
# Required
name: string                    # Human-readable persona name
description: string             # Multi-sentence description of who this person is

# Optional browser context (defaults to desktop Chrome)
device: mobile | desktop        # Default: desktop
viewport:                       # Default: 1280x720
  width: int
  height: int
user_agent: string | "default"  # Default: "default"

# Required: at least one scenario
scenarios:
  - name: string                # Short scenario label
    start: string               # URL path (appended to base URL)
    goal: string                # Natural language: what this persona is trying to do
    max_steps: int              # Optional: max navigation steps before declaring failure (default: 10)
    check:                      # List of assertions (natural language)
      - string
      - string

# Optional: accessibility checks applied to every page visited
accessibility:
  - string                      # Natural language accessibility requirement

# Optional: custom severity mapping (defaults shown)
severity_mapping:
  blocker: high
  usability: medium
  polish: low

# Optional: pages to skip (e.g., login-required areas for anonymous persona)
skip_routes:
  - /admin/*
  - /dashboard/*
```

### Why Natural Language Over Scripted Tests

1. **Non-engineers can write profiles** — describe the persona and what they'd try to do
2. **LLM agents can interpret intent** — "find ways to help" doesn't need a specific click path
3. **Resilient to UI changes** — a button rename doesn't break the test
4. **Qualitative evaluation** — "language is welcoming, not guilt-inducing" can't be a CSS selector assertion
5. **Composable** — personas can be combined (e.g., "screen-reader user who is also a new supporter")

### Example: Advocacy-Specific Persona

```yaml
name: Skeptical Visitor
description: >
  Someone who landed on this site from a social media link. They eat meat,
  are mildly curious about animal welfare, but skeptical of "vegan propaganda."
  They'll leave immediately if they feel lectured at or judged.

device: mobile
viewport: { width: 390, height: 844 }

scenarios:
  - name: First impression
    start: /
    goal: >
      Decide within 30 seconds whether this site is worth my time.
      I'm looking for credible information, not emotional manipulation.
    check:
      - Homepage doesn't use guilt or shame tactics
      - Information feels factual and evidence-based
      - No graphic images above the fold
      - Clear what the organization does without jargon

  - name: Learn something new
    start: /learn
    goal: >
      Find one piece of information about animal agriculture that
      surprises me and feels trustworthy.
    check:
      - Content cites sources
      - Tone is informative, not preachy
      - Can navigate back to homepage easily
      - No guilt-trip pop-ups or overlays

accessibility:
  - Text is readable on mobile without zooming
  - Videos have captions
```

---

## 6. Implementation Phases

### Phase 1: Minimum Viable (Week 1-2)

**Goal**: `desloppify persona-qa` command that loads profiles, prints agent instructions, and imports findings.

1. Create `app/commands/persona_qa/` package:
   - `cmd.py` — CLI handler with `--url`, `--persona`, `--prepare`, `--import`, `--clear`, `--status` flags
   - `profiles.py` — YAML loading, validation, profile discovery
   - `findings.py` — `make_browser_issue()`, finding import/merge into state

2. Register detector and scoring:
   - Add `persona_qa` DetectorMeta to catalog
   - Register scoring policy and mechanical dimension weight
   - Wire into `app/commands/registry.py`

3. Add to command registry in `app/commands/registry.py`

4. Basic display: Show "Route:" instead of "File:" when `detail.route` exists (patch `render.py`)

**Deliverable**: Agent can run `desloppify persona-qa --prepare --url http://localhost:3000` to get persona instructions, manually test in browser, then `desloppify persona-qa --import findings.json` to merge findings into state. Findings appear in `desloppify next`.

### Phase 2: Agent Automation (Week 3-4)

**Goal**: Structured agent flow with prepare → test → import cycle.

1. `--prepare` output format that Playwright MCP agents can consume directly
2. Findings JSON schema with validation
3. Auto-reconciliation logic (auto-resolve findings that now pass)
4. Potentials tracking for accurate scoring denominators
5. `--status` showing per-persona pass/fail summary

**Deliverable**: Full scan-like cycle: `desloppify persona-qa --url ... → agent tests → desloppify persona-qa --import → findings in queue`.

### Phase 3: Skill Integration (Week 5-6)

**Goal**: Skill overlay that teaches agents the persona QA workflow.

1. Add persona QA section to SKILL.md overlay
2. Define the agent workflow: when to run persona QA, how to interpret results
3. Integration with the plan/triage cycle — persona QA findings can be clustered and prioritized
4. Screenshot capture and storage (`.desloppify/screenshots/`)

**Deliverable**: An agent running `desloppify next` that encounters a persona QA finding knows how to verify the fix by re-running the relevant scenario.

### Phase 4: Advanced Features (Ongoing)

- Persona composition (combine profiles for intersection testing)
- Regression mode (only re-test previously failing routes)
- CI integration (run persona QA in CI against preview deploys)
- Accessibility auto-checking via axe-core injection
- Multi-page session state (login → authenticated flows)
- Comparative testing (same scenario, different personas, different outcomes)

---

## 7. Design Decisions (Resolved)

All architectural decisions have been made. These are locked in for implementation.

### 1. Scan reconciliation: Persona QA findings survive `desloppify scan`

**Verified in code**: `reconcile_plan_after_scan()` in `engine/_plan/scan_issue_reconcile.py` only touches issues *referenced in the plan* that are no longer alive in state. It does not enumerate or filter by detector. Persona QA findings with detector `persona_qa` are completely invisible to scan reconciliation — they persist untouched. No changes needed.

### 2. Scoring weight: 1.0 (equal to other mechanical dimensions)

Start at `1.0`. Equal footing with code quality, duplication, etc. Adjustable later if experience shows it should carry more weight. Don't overthink this for v1.

### 3. Potentials model: Per-check-item (fine-grained)

Each check item in every scenario across all personas is one potential. If 3 personas × 4 scenarios × 3 checks = 36 potentials, and 4 checks fail, the dimension score is 32/36 ≈ 89%. Adding check items raises the bar — correct behavior. More checks = higher standards.

### 4. Origin field: `scan` (use existing value)

No new origin. `scan` works today with zero core changes. Adding `browser_qa` would require touching the `WORK_ITEM_ORIGINS` frozenset and every validation path. Revisit only if origin-based filtering becomes necessary.

### 5. Work item kind: `mechanical_defect` (use existing value)

No new kind. `mechanical_defect` works today. Unknown detectors already default to this in `infer_work_item_kind()`. Adding `browser_defect` would require touching `WORK_ITEM_KINDS` and kind-inference logic. Revisit only if triage needs to distinguish browser findings from code findings.

### 6. Profile authorship: Open Paws provides templates, orgs customize

Open Paws ships template personas for common types (new visitor, donor, activist, admin, screen-reader user). Client organizations customize by adding their own scenarios and adjusting descriptions. The natural-language format is the enabler — non-engineers can write and maintain profiles without understanding desloppify internals.

### 7. Base URL: CLI flag with config fallback

`--url` flag always wins. `.desloppify/config.yaml` provides a `persona_qa.base_url` default for CI environments. Both work. Config example:
```yaml
persona_qa:
  base_url: http://localhost:3000
```

### 8. Playwright MCP: Not desloppify's concern

`--prepare` always works (prints agent instructions). `--import` always works (consumes findings JSON). Browser interaction is the agent's responsibility. Desloppify doesn't detect, manage, or depend on Playwright availability. The agent (Claude Code, etc.) brings its own browser tools.

### Technical Questions (Resolve During Implementation)

- How to handle authenticated routes (persona needs to log in first)
- Screenshot storage strategy (inline base64 in findings JSON vs separate files)
- Rate limiting between page loads to avoid overwhelming dev servers
- Timeout handling for scenarios that get stuck
- Whether to use `browser_snapshot` (DOM/accessibility tree) or `browser_take_screenshot` (visual) for evidence

---

## Appendix: Key Files for Implementation

| Component | File Path (relative to repo root) |
|-----------|----------------------------------|
| Command registry | `desloppify/app/commands/registry.py` |
| Issue factory | `desloppify/engine/_state/filtering.py` (`make_issue`) |
| WorkItem TypedDict | `desloppify/engine/_state/schema_types_issues.py` |
| Work item kinds/origins | `desloppify/engine/_state/issue_semantics.py` |
| State load/save | `desloppify/engine/_state/persistence.py` |
| State schema | `desloppify/engine/_state/schema.py` |
| Scoring policy | `desloppify/engine/_scoring/policy/core.py` |
| Detector registry | `desloppify/base/registry/` |
| Queue types | `desloppify/engine/_work_queue/types.py` |
| Next render | `desloppify/app/commands/next/render.py` (line 143-146 for file display) |
| Next compact render | `desloppify/app/commands/next/render_support.py` (line 272) |
| Resolution logic | `desloppify/engine/_state/resolution.py` |
| Pattern matching | `desloppify/engine/_state/filtering.py` (`_matches_pattern`) |
| Plan resolve | `desloppify/app/commands/plan/override/resolve_cmd.py` |
| Review system (model) | `desloppify/intelligence/review/__init__.py` |
| Scan reconciliation | `desloppify/engine/_plan/scan_issue_reconcile.py` |
| Skill docs | `docs/SKILL.md` |
| Fork architecture | `desloppify-fork-architecture.md` |
