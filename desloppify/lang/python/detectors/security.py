"""Python-specific security detectors — shell injection, unsafe deserialization, etc.

Uses AST analysis where possible for precision, falls back to regex for simpler patterns.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ....zones import FileZoneMap, Zone

# ── AST visitor for Python security checks ──


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor that collects security findings from Python source."""

    def __init__(self, filepath: str, lines: list[str]):
        self.filepath = filepath
        self.lines = lines
        self.entries: list[dict] = []

    def _add(self, node: ast.AST, check_id: str, summary: str,
             severity: str, confidence: str, remediation: str):
        line_num = getattr(node, "lineno", 0)
        content = self.lines[line_num - 1] if 0 < line_num <= len(self.lines) else ""
        from ....detectors.security import make_security_entry
        self.entries.append(make_security_entry(
            self.filepath, line_num, check_id,
            summary, severity, confidence,
            content, remediation,
        ))

    def visit_Call(self, node: ast.Call):
        self._check_shell_injection(node)
        self._check_unsafe_deserialization(node)
        self._check_sql_injection(node)
        self._check_unsafe_yaml(node)
        self._check_unsafe_tempfile(node)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        self._check_assert_security(node)
        self.generic_visit(node)

    def _get_func_name(self, node: ast.Call) -> str:
        """Get dotted function name from a Call node."""
        if isinstance(node.func, ast.Attribute):
            val = node.func
            parts = [val.attr]
            while isinstance(val.value, ast.Attribute):
                val = val.value
                parts.append(val.attr)
            if isinstance(val.value, ast.Name):
                parts.append(val.value.id)
            return ".".join(reversed(parts))
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""

    def _has_shell_true(self, node: ast.Call) -> bool:
        """Check if a call has shell=True keyword."""
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                return True
        return False

    def _is_literal_string(self, node: ast.expr) -> bool:
        """Check if an expression is a plain string literal (not f-string, format, or concat)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        if isinstance(node, ast.List):
            return all(self._is_literal_string(elt) for elt in node.elts)
        return False

    def _check_shell_injection(self, node: ast.Call):
        name = self._get_func_name(node)
        # subprocess.* with shell=True and non-literal command
        if name.startswith("subprocess.") and self._has_shell_true(node):
            if node.args and not self._is_literal_string(node.args[0]):
                self._add(node, "shell_injection",
                          f"Shell injection risk: {name}(shell=True) with dynamic command",
                          "critical", "high",
                          "Use subprocess with a list of args instead of shell=True with dynamic strings")
        # os.system() / os.popen() with non-literal arg
        if name in ("os.system", "os.popen"):
            if node.args and not self._is_literal_string(node.args[0]):
                self._add(node, "shell_injection",
                          f"Shell injection risk: {name}() with dynamic command",
                          "critical", "high",
                          "Use subprocess.run() with a list of arguments instead")

    def _check_unsafe_deserialization(self, node: ast.Call):
        name = self._get_func_name(node)
        unsafe_funcs = {
            "pickle.loads", "pickle.load",
            "cPickle.loads", "cPickle.load",
            "marshal.loads", "marshal.load",
            "shelve.open",
        }
        if name in unsafe_funcs:
            self._add(node, "unsafe_deserialization",
                      f"Unsafe deserialization: {name}() can execute arbitrary code",
                      "critical", "high",
                      "Use json.loads() or a safer serialization format")

    def _check_sql_injection(self, node: ast.Call):
        name = self._get_func_name(node)
        if not name.endswith(".execute"):
            return
        if not node.args:
            return
        arg = node.args[0]
        # f-string, format call, or concatenation
        if isinstance(arg, ast.JoinedStr):
            self._add(node, "sql_injection",
                      "SQL injection risk: f-string used in .execute()",
                      "critical", "high",
                      "Use parameterized queries: cursor.execute('SELECT ?', (val,))")
        elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
            self._add(node, "sql_injection",
                      "SQL injection risk: string concatenation in .execute()",
                      "critical", "high",
                      "Use parameterized queries: cursor.execute('SELECT ?', (val,))")
        elif isinstance(arg, ast.Call):
            # Check for .format() call: the func is Attribute with attr="format"
            if isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
                self._add(node, "sql_injection",
                          "SQL injection risk: .format() in .execute()",
                          "critical", "high",
                          "Use parameterized queries: cursor.execute('SELECT ?', (val,))")
        elif isinstance(arg, ast.Mod):
            self._add(node, "sql_injection",
                      "SQL injection risk: % formatting in .execute()",
                      "critical", "high",
                      "Use parameterized queries: cursor.execute('SELECT ?', (val,))")

    def _check_unsafe_yaml(self, node: ast.Call):
        name = self._get_func_name(node)
        if name != "yaml.load":
            return
        # Check for Loader keyword
        has_safe_loader = False
        for kw in node.keywords:
            if kw.arg == "Loader":
                # Check if it's SafeLoader or yaml.SafeLoader
                if isinstance(kw.value, ast.Attribute):
                    if kw.value.attr in ("SafeLoader", "CSafeLoader"):
                        has_safe_loader = True
                elif isinstance(kw.value, ast.Name):
                    if kw.value.id in ("SafeLoader", "CSafeLoader"):
                        has_safe_loader = True
        if not has_safe_loader:
            self._add(node, "unsafe_yaml",
                      "Unsafe YAML: yaml.load() without SafeLoader",
                      "high", "high",
                      "Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader)")

    def _check_unsafe_tempfile(self, node: ast.Call):
        name = self._get_func_name(node)
        if name == "tempfile.mktemp":
            self._add(node, "unsafe_tempfile",
                      "Unsafe tempfile: tempfile.mktemp() is vulnerable to race conditions",
                      "high", "high",
                      "Use tempfile.mkstemp() or tempfile.NamedTemporaryFile() instead")

    def _check_assert_security(self, node: ast.Assert):
        """Flag assert statements used for security checks (disabled in -O mode)."""
        test = node.test
        src = ast.dump(test)
        security_attrs = (
            "is_authenticated", "has_permission", "authorized",
            "is_staff", "is_superuser", "is_admin", "has_perm",
        )
        for attr in security_attrs:
            if attr in src:
                self._add(node, "assert_security",
                          f"Security assert: assert with '{attr}' is disabled in optimized mode (-O)",
                          "medium", "medium",
                          "Use an if-statement with a proper exception instead of assert for security checks")
                break


# ── Regex-based checks ──

_DEBUG_MODE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*DEBUG\s*=\s*True\b"), "DEBUG = True"),
    (re.compile(r"app\.run\([^)]*debug\s*=\s*True"), "app.run(debug=True)"),
    (re.compile(r"\.run_server\([^)]*debug\s*=\s*True"), "run_server(debug=True)"),
]

_XXE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<!defused)xml\.etree\.ElementTree\.parse\s*\("),
     "Use defusedxml.ElementTree.parse() instead"),
    (re.compile(r"(?<!defused)xml\.sax\.parse\s*\("),
     "Use defusedxml.sax.parse() instead"),
    (re.compile(r"(?<!defused)xml\.dom\.minidom\.parse\s*\("),
     "Use defusedxml.minidom.parse() instead"),
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
    from ....detectors.security import make_security_entry

    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if not filepath.endswith(".py"):
            continue
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.GENERATED, Zone.VENDOR):
                continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue

        scanned += 1
        lines = content.splitlines()

        # AST-based checks
        try:
            tree = ast.parse(content, filename=filepath)
            visitor = _SecurityVisitor(filepath, lines)
            visitor.visit(tree)
            entries.extend(visitor.entries)
        except SyntaxError:
            pass

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
                        entries.append(make_security_entry(
                            filepath, line_num, "debug_mode",
                            f"Debug mode enabled: {label}",
                            "medium", "medium", line,
                            "Ensure debug mode is disabled in production via environment variables",
                        ))

            # XXE vulnerabilities
            if not is_pattern_line:
                for pattern, remediation in _XXE_PATTERNS:
                    if pattern.search(line):
                        entries.append(make_security_entry(
                            filepath, line_num, "xxe_vuln",
                            "Potential XXE vulnerability: using stdlib XML parser",
                            "high", "medium", line, remediation,
                        ))

            # Weak password hashing
            if _WEAK_HASH_RE.search(line):
                context = "\n".join(lines[max(0, line_num - 3):min(len(lines), line_num + 2)])
                if _PASSWORD_CONTEXT_RE.search(context):
                    entries.append(make_security_entry(
                        filepath, line_num, "weak_password_hash",
                        "Weak hash near password context: MD5/SHA1 is unsuitable for passwords",
                        "medium", "medium", line,
                        "Use bcrypt, argon2, or scrypt for password hashing",
                    ))

            # Insecure cookie
            if _INSECURE_COOKIE_RE.search(line):
                # Check a few lines around for secure=True
                context = "\n".join(lines[max(0, line_num - 1):min(len(lines), line_num + 3)])
                if not _SECURE_COOKIE_RE.search(context):
                    entries.append(make_security_entry(
                        filepath, line_num, "insecure_cookie",
                        "Cookie set without secure=True",
                        "low", "low", line,
                        "Set secure=True and httponly=True on cookies",
                    ))

    return entries, scanned
