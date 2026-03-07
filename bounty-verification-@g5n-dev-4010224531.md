# Bounty Verification: S224 — XXE Vulnerability via Fallback Parser

**Submission:** S224 by @g5n-dev
**Date:** 2026-03-06T08:09:36Z
**Snapshot commit:** 6eb2065

## Claim

The submission reports an XXE (XML External Entity) vulnerability in `desloppify/languages/csharp/detectors/deps_support.py:10-13` where the code falls back from `defusedxml` to the stdlib `xml.etree.ElementTree` parser when `defusedxml` is not installed. Claims CVSS 7.5 and file exfiltration via malicious `.csproj` files.

## Verification (at commit 6eb2065)

### 1. Code pattern — CONFIRMED

`deps_support.py:10-13`:
```python
try:
    import defusedxml.ElementTree as ET
except ModuleNotFoundError:  # pragma: no cover — optional dep
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]
```

Used at line 91: `root = ET.parse(csproj_file).getroot()`

### 2. Dependency status — CONFIRMED

At commit 6eb2065, `pyproject.toml` has `dependencies = []` (empty). `defusedxml>=0.7.0` only appears under `[full]` optional extras.

### 3. XXE file exfiltration claim — INCORRECT

Python's `xml.etree.ElementTree` (backed by expat) does **not** resolve external entities. Testing confirms:
```
>>> ET.parse(xxe_file)
ParseError: undefined entity &xxe;: line 5, column 9
```
The claimed `/etc/passwd` exfiltration PoC does not work. The submission overstates practical impact.

### 4. Entity expansion (billion laughs) — PARTIALLY VALID

Entity expansion attacks do work against stdlib ElementTree on Python 3.10, making the `defusedxml` fallback a legitimate (lower-severity) concern.

### 5. Duplicate check — DUPLICATE OF S153

- **S153** by @codenan42 (2026-03-05T14:02:14Z) — same file, same code, same XXE claim. Already verified **YES_WITH_CAVEATS**.
- **S224** by @g5n-dev (2026-03-06T08:09:36Z) — submitted **18+ hours later**. Identical issue.
- **S229** by @lbbcym (2026-03-06T08:53:06Z) — also a duplicate.

## Verdict

**NO** — Duplicate of S153, which was already verified. S153 was submitted over 18 hours earlier and covers the identical vulnerability: the `defusedxml` → stdlib fallback in `deps_support.py:10-13`. No credit is awarded for duplicate submissions regardless of the quality of the write-up.
