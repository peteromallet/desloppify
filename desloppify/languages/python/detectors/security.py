"""Python-specific security detectors — shell injection, unsafe deserialization, etc.

Uses AST analysis where possible for precision, falls back to regex for simpler patterns.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

from desloppify.engine.detectors.security import rules as security_detector_mod
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages.python.detectors.security_ast import _SecurityVisitor

logger = logging.getLogger(__name__)

# ── Regex-based checks ──

_DEBUG_MODE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*DEBUG\s*=\s*True\b"), "DEBUG = True"),
    (re.compile(r"app\.run\([^)]*debug\s*=\s*True"), "app.run(debug=True)"),
    (re.compile(r"\.run_server\([^)]*debug\s*=\s*True"), "run_server(debug=True)"),
]

_XXE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(?<!defused)xml\.etree\.ElementTree\.parse\s*\("),
        "Use defusedxml.ElementTree.parse() instead",
    ),
    (
        re.compile(r"(?<!defused)xml\.sax\.parse\s*\("),
        "Use defusedxml.sax.parse() instead",
    ),
    (
        re.compile(r"(?<!defused)xml\.dom\.minidom\.parse\s*\("),
        "Use defusedxml.minidom.parse() instead",
    ),
]

_WEAK_HASH_RE = re.compile(r"hashlib\.(?:md5|sha1)\s*\(")
_PASSWORD_CONTEXT_RE = re.compile(r"(?i)(?:password|passwd|credential)")

_INSECURE_COOKIE_RE = re.compile(r"set_cookie\s*\(")
_SECURE_COOKIE_RE = re.compile(r"secure\s*=\s*True")

# Lines that are defining patterns/constants — not actual code
_PATTERN_LINE_RE = re.compile(r"re\.compile\(|re\.search\(|re\.match\(|re\.findall\(")


def detect_python_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Detect Python-specific security issues.

    Returns (entries, files_scanned).
    """
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if not filepath.endswith(".py"):
            continue
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR):
                continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            logger.debug(
                "Skipping unreadable python file %s in security detector: %s",
                filepath,
                exc,
            )
            continue

        scanned += 1
        lines = content.splitlines()

        # AST-based checks
        ast_parse_failed = False
        try:
            tree = ast.parse(content, filename=filepath)
            visitor = _SecurityVisitor(filepath, lines)
            visitor.visit(tree)
            entries.extend(visitor.entries)
        except SyntaxError as exc:
            logger.debug(
                "Skipping unparseable python file %s in security detector: %s",
                filepath,
                exc,
            )
            ast_parse_failed = True
        if ast_parse_failed:
            logger.debug(
                "Falling back to regex-only checks for %s after AST parse failure",
                filepath,
            )

        # Regex-based checks
        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue

            # Skip lines that are inside regex/pattern definitions
            is_pattern_line = _PATTERN_LINE_RE.search(line) is not None

            # Debug mode
            if not is_pattern_line:
                for pattern, label in _DEBUG_MODE_PATTERNS:
                    if pattern.search(line):
                        entries.append(
                            security_detector_mod.make_security_entry(
                                filepath,
                                line_num,
                                line,
                                security_detector_mod.SecurityRule(
                                    check_id="debug_mode",
                                    summary=f"Debug mode enabled: {label}",
                                    severity="medium",
                                    confidence="medium",
                                    remediation="Ensure debug mode is disabled in production via environment variables",
                                ),
                            )
                        )

            # XXE vulnerabilities
            if not is_pattern_line:
                for pattern, remediation in _XXE_PATTERNS:
                    if pattern.search(line):
                        entries.append(
                            security_detector_mod.make_security_entry(
                                filepath,
                                line_num,
                                line,
                                security_detector_mod.SecurityRule(
                                    check_id="xxe_vuln",
                                    summary="Potential XXE vulnerability: using stdlib XML parser",
                                    severity="high",
                                    confidence="medium",
                                    remediation=remediation,
                                ),
                            )
                        )

            # Weak password hashing
            if _WEAK_HASH_RE.search(line):
                context = "\n".join(
                    lines[max(0, line_num - 3) : min(len(lines), line_num + 2)]
                )
                if _PASSWORD_CONTEXT_RE.search(context):
                    entries.append(
                        security_detector_mod.make_security_entry(
                            filepath,
                            line_num,
                            line,
                            security_detector_mod.SecurityRule(
                                check_id="weak_password_hash",
                                summary="Weak hash near password context: MD5/SHA1 is unsuitable for passwords",
                                severity="medium",
                                confidence="medium",
                                remediation="Use bcrypt, argon2, or scrypt for password hashing",
                            ),
                        )
                    )

            # Insecure cookie
            if _INSECURE_COOKIE_RE.search(line):
                # Check a few lines around for secure=True
                context = "\n".join(
                    lines[max(0, line_num - 1) : min(len(lines), line_num + 3)]
                )
                if not _SECURE_COOKIE_RE.search(context):
                    entries.append(
                        security_detector_mod.make_security_entry(
                            filepath,
                            line_num,
                            line,
                            security_detector_mod.SecurityRule(
                                check_id="insecure_cookie",
                                summary="Cookie set without secure=True",
                                severity="low",
                                confidence="low",
                                remediation="Set secure=True and httponly=True on cookies",
                            ),
                        )
                    )

    return entries, scanned
