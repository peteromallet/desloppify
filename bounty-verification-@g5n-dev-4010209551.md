# Bounty Verification: S222 — Unsafe Deserialization via Unvalidated File Writes

**Submission:** [S222 by @g5n-dev](https://github.com/peteromallet/desloppify/issues/204#issuecomment-4010209551)
**File:** `desloppify/base/discovery/file_paths.py` (lines 96–105 at commit `6eb2065`)

## Verdict: NO

The submission claims five security vulnerabilities in `safe_write_text()`. Empirical testing disproves the core claims.

---

### Claim 1: No permission control — mkstemp 0600 becomes 0644 after os.replace

**WRONG.** `os.replace()` uses the `rename()` syscall, which preserves the source inode's permissions. Empirical test confirms the file retains mode `0600` after replacement. Permissions do NOT change to match umask.

### Claim 2: TOCTOU race condition via "predictable location"

**WRONG.** `tempfile.mkstemp()` generates random filenames (e.g., `tmp9wtsg0lq.tmp`), not predictable ones like `filepath.tmp` as claimed. The file is also created atomically with `O_EXCL`, preventing pre-creation attacks.

### Claim 3: Symlink following — os.replace follows symlinks at target

**WRONG.** `os.replace()` replaces the directory entry at the destination. If the destination is a symlink, the symlink itself is replaced with the new file — it does NOT follow the symlink to overwrite the target. Empirical test confirms the original target file is untouched.

### Claim 4: No content validation before write

**Not a real issue.** `safe_write_text` is a low-level utility function. Content validation belongs in callers, not in a generic file-write helper. This is standard separation of concerns.

### Claim 5: Silent failure mode

**WRONG.** The `except OSError` block cleans up the temp file and then **re-raises** the exception. The failure is not silent — it propagates to the caller.

### Attack scenario: symlink in .desloppify/

The described scenario (`.desloppify/state.json -> /etc/critical_config`) does not work because `os.replace()` replaces the symlink, not the symlink target. The system file remains unmodified.

---

### Title mismatch

The title references "Unsafe Deserialization" but the function performs no deserialization whatsoever — it only writes text to disk.

## Scores

| Criterion | Score |
|-----------|-------|
| Significance | 2/10 |
| Originality | 3/10 |
| Core Impact | 1/10 |
| Overall | 2/10 |
