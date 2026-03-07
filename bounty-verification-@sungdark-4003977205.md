# Bounty Verification: S121 @sungdark — Python Version, Build Backend, Type Annotations

**Submission:** https://github.com/peteromallet/desloppify/issues/204#issuecomment-4003977205
**Snapshot commit:** 6eb2065

## Claims Verified

### Issue 1: Python Version Compatibility Flaw (NotRequired requires 3.11)

**Claim:** The code uses `NotRequired` type annotations from Python 3.11, restricting usability to 3.11+ "for no valid reason."

**INVALID.** The project explicitly declares `requires-python = ">=3.11"` in `pyproject.toml`. This is a deliberate, documented design decision — the project targets Python 3.11, 3.12, and 3.13 as shown in the classifiers. Using `NotRequired` from `typing` (a stdlib module available in the target version) is correct engineering, not a flaw. There is no obligation to support older Python versions, and the submitter's claim that this "violates the principle of progressive upgrade" is not a recognized engineering principle for internal tools.

### Issue 2: Installation Mechanism Defect (editable install)

**Claim:** The build backend doesn't support `pip install -e .`, preventing editable installation.

**FACTUALLY WRONG.** The project uses `setuptools>=68.0` as its build backend. Setuptools 68+ fully supports PEP 660 editable installs. Testing confirms that `pip install -e .` fails only because the system Python is 3.10, which doesn't meet the `requires-python>=3.11` constraint — a Python version mismatch, not a build backend limitation.

### Issue 3: Excessive Type Annotation

**Claim:** Overuse of complex type annotations (TypedDict + NotRequired) reduces readability and limits compatibility.

**INVALID.** This is a subjective style opinion, not a structural engineering issue. `TypedDict` with `NotRequired` is standard Python typing for the project's target version (3.11+). The annotations improve IDE support, catch bugs at type-check time, and document data shapes. The "compatibility" concern is the same as Issue 1 — the project intentionally targets 3.11+.

## Duplicate Check

No prior submissions raise the same concerns. S085 (also by @sungdark) covers different architectural topics.

## Assessment

All three claims are invalid:
1. Using stdlib features available in the declared target Python version is correct, not poor engineering.
2. The editable install claim is factually incorrect — the build backend works fine.
3. "Excessive typing" is a style preference, not an engineering defect.

The submission demonstrates a misunderstanding of the project's Python version targeting strategy and confuses a version constraint with a build system bug.

## Verdict

| Question | Answer | Reasoning |
|----------|--------|-----------|
| **Is this poor engineering?** | NO | The project correctly uses stdlib features for its declared target Python version |
| **Is this at least somewhat significant?** | NO | Claims are either factually wrong or subjective style preferences |

**Final verdict:** NO
