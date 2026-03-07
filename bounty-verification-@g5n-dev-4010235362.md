# Bounty Verification: S226 @g5n-dev

## Submission
**SSRF via Hardcoded GitHub Raw URL with No Validation**
- File: `desloppify/app/commands/update_skill.py`
- Function: `_download(filename)`

## Claim
The `_download()` function concatenates `filename` without validation, enabling SSRF if the parameter becomes user-controlled. Additional claims about missing HTTPS certificate validation and MITM risks.

## Analysis

### 1. filename is never user-controlled
`_download()` is called exactly twice in `update_installed_skill()`:
- `_download("SKILL.md")` — hardcoded string literal
- `_download(f"{overlay_name}.md")` — where `overlay_name` comes from `SKILL_TARGETS[interface]`

`SKILL_TARGETS` is a module-level constant dict with fixed values like `"CLAUDE"`, `"CURSOR"`, `"COPILOT"`, etc. The `interface` key is validated against `SKILL_TARGETS` before use. There is no code path where a user-supplied string reaches `_download()`.

### 2. HTTPS certificate validation works by default
Python's `urllib.request.urlopen()` validates HTTPS certificates by default since Python 3.4. The `# noqa: S310` comment suppresses Bandit's `S310` rule which flags *any* use of `urlopen` regardless of context. The comment does not disable certificate checking.

### 3. Repository compromise is not a code bug
The claim that a compromised upstream repository could serve malicious content is true for any software that fetches updates. This is an operational/supply-chain concern, not a vulnerability in this code.

### 4. Speculative future vulnerabilities
The submission's PoC requires "if a future caller passes user-controlled input" — this is speculative. The code as written has no such path.

## Verdict: NO

The submission describes a hypothetical vulnerability that does not exist in the actual codebase. All inputs to `_download()` are hardcoded constants. The MITM and certificate claims are factually incorrect.
