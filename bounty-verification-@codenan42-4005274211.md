# Bounty Verification: S153 — XXE Vulnerability in C# Project Parsing

**Submission:** S153 by @codenan42
**Date:** 2026-03-05T14:02:14Z

## Claim

The submission reports that `desloppify/languages/csharp/detectors/deps_support.py` has an XXE (XML External Entity) vulnerability on default installs because `defusedxml` is only in `[full]` optional dependencies, and the code silently falls back to the unsafe stdlib `xml.etree.ElementTree` parser.

## Verification (at commit 6eb2065)

### 1. Dependency status — CONFIRMED

`pyproject.toml` at commit 6eb2065:
- `dependencies = []` — defusedxml is NOT a base dependency
- `defusedxml>=0.7.0` only appears under `[full]` optional extras

### 2. Unsafe fallback — CONFIRMED

`deps_support.py:10-13`:
```python
try:
    import defusedxml.ElementTree as ET
except ModuleNotFoundError:  # pragma: no cover — optional dep
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]
```

On default install, `defusedxml` is absent and the code silently falls back to the stdlib parser.

### 3. User-controlled file parsing — CONFIRMED

`deps_support.py:91` (`parse_csproj_references`):
```python
root = ET.parse(csproj_file).getroot()
```

Called on `.csproj` files discovered via `find_csproj_files()` (line 79-85) which uses `path.rglob("*.csproj")` — these files are attacker-controlled in scanned repositories.

### 4. Practical impact — LIMITED

- Desloppify is a local CLI code scanning tool, not a network service
- The attacker must plant a malicious `.csproj` in a repository the victim scans
- The victim must be on default install (without `defusedxml`)
- XXE can read local files (SSH keys, credentials) but only in the context of the scanning user

### 5. Duplicate check

S153 (2026-03-05T14:02:14Z) is the **earliest** XXE submission. Later duplicates:
- S224 by g5n-dev (2026-03-06T08:09:36Z) — same issue
- S229 by lbbcym (2026-03-06T08:53:06Z) — same issue with proposed patch

## Verdict

**YES_WITH_CAVEATS** — The XXE vulnerability via unsafe fallback is real and correctly identified. The code path from `rglob("*.csproj")` → `ET.parse()` with stdlib fallback is a genuine security-by-optional-dependency antipattern. However, the practical blast radius is limited since desloppify is a local CLI tool, not a web service, and exploitation requires planting malicious files in a scanned repository.
