"""Shared static text blocks for triage stage prompts."""

from __future__ import annotations

from typing import Literal

_STAGES = ("strategize", "observe", "reflect", "organize", "enrich", "sense-check")
PromptMode = Literal["self_record", "output_only"]

_OBSERVE_FALSE_POSITIVE_GUIDANCE = """\
**The review system has a high false-positive rate.** Issues frequently:
- Claim "12 unsafe casts" when there are actually 2
- Describe code that was already refactored
- Propose over-engineering that would make things worse
- Count props/returns/args wrong
- Propose fixes whose complexity exceeds the problem (e.g., adding a 3-file abstraction
  to eliminate 5 lines of duplication)
- Flag issues where the current code is "good enough" — imperfect but clear, simple,
  and not causing real problems

Your job is to catch these. A report that just restates issue titles is **worthless**.
The value you add is reading the actual code and forming an independent judgment.

Use the `not-worth-it` verdict when: the issue is technically real but the fix would add
more complexity than it removes, or the current code is simple and readable despite being
theoretically suboptimal. YAGNI — if nobody is actually confused or blocked by this code,
it doesn't need fixing.
"""

_OBSERVE_VERIFICATION_CHECKLIST = """\
**For EVERY issue you must:**
- Open and read the actual source file
- Verify specific claims: count the actual casts, props, returns, line count
- Check if the suggested fix already exists (common false positive)
- Report a clear verdict: genuine / false positive / exaggerated / over-engineering / not-worth-it
"""

_OBSERVE_EXAMPLE_REPORT_QUALITY = """\
**What a GOOD report looks like:**
- "[34580232] taskType is plain string — FALSE POSITIVE. Uses branded string union KnownTaskType
  with ~25 literals in src/types/database.ts line 50. The issue describes code that doesn't exist."
- "[b634fc71] useGenerationsPaneController returns 60+ values — GENUINE. Confirmed 65 properties
  at lines 217-282. Mixes pane lifecycle, filters, gallery data, interaction, and navigation."

**What a LAZY report looks like (will be rejected):**
- "There are several convention issues that should be addressed"
- "The type safety dimension has some genuine concerns"
- Listing issue titles without any verification or independent analysis
"""

_OBSERVE_STRUCTURED_TEMPLATE = """\
```
- hash: <issue hash>
  verdict: genuine | false-positive | exaggerated | over-engineering | not-worth-it
  verdict_reasoning: <what you verified in the code and why that leads to this verdict>
  files_read: [<file paths you opened>]
  recommendation: <what to do next>
```
"""

_PREAMBLE_SELF_RECORD = """\
You are a triage subagent with full codebase access and the desloppify CLI.
Your job is to complete the **{stage}** stage of triage planning.

Repo root: {repo_root}

## Standards

You are expected to produce **exceptional** work. The output of this triage becomes the
actual plan that an executor follows — if you are lazy, vague, or sloppy, real work gets
wasted. Concretely:

- **Read the actual source code.** Every opinion you form must come from reading the file,
  not from reading the issue title. Issues frequently exaggerate, miscount, or describe
  code that has already been fixed. Trust nothing until you verify it.
- **Have specific opinions.** "This seems like it could be an issue" is worthless. "This is
  a false positive because line 47 already uses the pattern the issue suggests" is useful.
- **Do the hard thinking.** If two issues seem related, figure out WHY. If something should
  be skipped, explain the specific reason for THIS issue, not a generic category.
- **Don't take shortcuts.** Reading 5 files and extrapolating to 30 is lazy. Read all 30.
  If you have too many, use subagents to parallelize — don't skip.
- The prompt below already contains the authoritative stage contract and prior reports.
  Do NOT search old triage run artifacts for alternate instructions unless you hit a
  concrete mismatch you need to explain.

Use the desloppify CLI to record your work. Every command you run mutates plan.json directly.
The orchestrator will review your work and confirm the stage after you record it.
Use the exact CLI command prefix shown in the CLI Command Reference: `{cli_command}`.
Do NOT debug, repair, reinstall, or inspect the CLI/environment. If the command fails, stop
and explain the failure in your stdout summary.

After you finish recording the stage, write a short plain-text summary to stdout describing
what you changed, which commands you ran, and any blockers you hit. The runner requires
non-empty stdout output.

**CRITICAL: Only run commands for YOUR stage ({stage}).** Do NOT re-run earlier stages
(e.g., do not run `--stage observe` if you are the organize subagent). Earlier stages
are already confirmed. Re-running them will corrupt the plan state.
"""

_PREAMBLE_OUTPUT_ONLY = """\
You are a triage analysis subagent with full codebase access.
Your job is to complete the **{stage}** stage of triage planning.

Repo root: {repo_root}

## Standards

You are expected to produce **exceptional** work. The output of this triage becomes the
actual plan that an executor follows — if you are lazy, vague, or sloppy, real work gets
wasted. Concretely:

- **Read the actual source code.** Every opinion you form must come from reading the file,
  not from reading the issue title. Issues frequently exaggerate, miscount, or describe
  code that has already been fixed. Trust nothing until you verify it.
- **Have specific opinions.** "This seems like it could be an issue" is worthless. "This is
  a false positive because line 47 already uses the pattern the issue suggests" is useful.
- **Do the hard thinking.** If two issues seem related, figure out WHY. If something should
  be skipped, explain the specific reason for THIS issue, not a generic category.
- **Don't take shortcuts.** Reading 5 files and extrapolating to 30 is lazy. Read all 30.
  If you have too many, use subagents to parallelize — don't skip.
- The prompt below already contains the authoritative stage contract and prior reports.
  Do NOT search old triage run artifacts for alternate instructions unless you hit a
  concrete mismatch you need to explain.

## Output Contract

- **Do NOT run any `desloppify` commands.**
- **Do NOT debug, repair, reinstall, or inspect the `desloppify` CLI/environment.**
- **Do NOT mutate `plan.json` directly or indirectly.**
- Use shell/read-only repo inspection as needed, but your only deliverable is a plain-text
  stage report for the orchestrator to record and confirm.
- If the prompt mentions CLI commands, treat them as background context for the orchestrator,
  not instructions for you to execute.
"""

_CLI_REFERENCE_TEMPLATE = """\
## CLI Command Reference

### Stage recording
```
{cli_command} plan triage --stage strategize --report "<json briefing>"
{cli_command} plan triage --stage observe --report "<analysis>"
{cli_command} plan triage --stage reflect --report "<strategy>" --attestation "<80+ chars>"
{cli_command} plan triage --stage organize --report "<summary>" --attestation "<80+ chars>"
{cli_command} plan triage --stage enrich --report "<enrichment summary>" --attestation "<80+ chars>"
{cli_command} plan triage --stage sense-check --report "<verification summary>" --attestation "<80+ chars>"
```

### Cluster management
```
{cli_command} plan cluster create <name> --description "<what this cluster addresses>"
{cli_command} plan cluster add <name> <issue-patterns...>
{cli_command} plan cluster remove <name> <issue-patterns...>
{cli_command} plan cluster update <name> --description "<desc>" --steps "step 1" "step 2"
{cli_command} plan cluster update <name> --add-step "<title>" --detail "<sub-points>" --effort small --issue-refs <id1> <id2>
{cli_command} plan cluster update <name> --update-step N --detail "<sub-points>" --effort medium --issue-refs <id1>
{cli_command} plan cluster update <name> --depends-on <other-cluster-name>
{cli_command} plan cluster delete <name>
{cli_command} plan cluster show <name>
{cli_command} plan cluster list --verbose
{cli_command} plan promote <pattern>
{cli_command} plan promote <pattern> top
{cli_command} plan promote <pattern> before -t <target>
```

### Skip/dismiss
```
{cli_command} plan skip --permanent <pattern> --note "<reason>" --attest "I have reviewed this triage skip against the code and I am not gaming the score by suppressing a real defect."
```
**Important:** The --attest value MUST contain the words "reviewed" and "not gaming" (exact phrases required by validation).
Every review issue in the active triage run must end up either in a manual cluster or permanently skipped. Leaving issues unassigned is an invalid triage result.

### Issue investigation
```
{cli_command} show <issue-id-or-pattern> --no-budget    # full issue detail with suggestion
{cli_command} show review --status open --no-budget     # all open review issues
{cli_command} backlog --count 20                        # inspect backlog-only detector work
```

### Effort tags
Valid values: trivial, small, medium, large. Set on steps via --effort flag.
"""

def triage_prompt_preamble(mode: PromptMode) -> str:
    """Return the shared prompt preamble for the requested runner mode."""
    if mode == "output_only":
        return _PREAMBLE_OUTPUT_ONLY
    return _PREAMBLE_SELF_RECORD


def render_cli_reference(cli_command: str = "desloppify") -> str:
    """Render the CLI reference with the exact command prefix to execute."""
    return _CLI_REFERENCE_TEMPLATE.format(cli_command=cli_command)


def observe_false_positive_guidance() -> str:
    """Return the shared observe-stage false-positive guidance block."""
    return _OBSERVE_FALSE_POSITIVE_GUIDANCE


def observe_verification_checklist() -> str:
    """Return the shared observe-stage verification checklist."""
    return _OBSERVE_VERIFICATION_CHECKLIST


def observe_example_report_quality() -> str:
    """Return shared examples of acceptable observe reporting quality."""
    return _OBSERVE_EXAMPLE_REPORT_QUALITY


def observe_structured_template() -> str:
    """Return the shared structured observe template."""
    return _OBSERVE_STRUCTURED_TEMPLATE


__all__ = [
    "PromptMode",
    "_CLI_REFERENCE_TEMPLATE",
    "_STAGES",
    "observe_example_report_quality",
    "observe_false_positive_guidance",
    "observe_structured_template",
    "observe_verification_checklist",
    "render_cli_reference",
    "triage_prompt_preamble",
]
