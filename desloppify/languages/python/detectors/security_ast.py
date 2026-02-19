"""AST visitor for Python security checks."""

from __future__ import annotations

import ast

from desloppify.engine.detectors.security import rules as security_detector_mod


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor that collects security findings from Python source."""

    def __init__(self, filepath: str, lines: list[str]):
        self.filepath = filepath
        self.lines = lines
        self.entries: list[dict] = []

    def _add(
        self,
        node: ast.AST,
        check_id: str,
        summary: str,
        severity: str,
        confidence: str,
        remediation: str,
    ) -> None:
        line_num = getattr(node, "lineno", 0)
        content = self.lines[line_num - 1] if 0 < line_num <= len(self.lines) else ""
        self.entries.append(
            security_detector_mod.make_security_entry(
                self.filepath,
                line_num,
                content,
                security_detector_mod.SecurityRule(
                    check_id=check_id,
                    summary=summary,
                    severity=severity,
                    confidence=confidence,
                    remediation=remediation,
                ),
            )
        )

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
        if isinstance(node.func, ast.Attribute):
            value = node.func
            parts = [value.attr]
            while isinstance(value.value, ast.Attribute):
                value = value.value
                parts.append(value.attr)
            if isinstance(value.value, ast.Name):
                parts.append(value.value.id)
            return ".".join(reversed(parts))
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""

    @staticmethod
    def _has_shell_true(node: ast.Call) -> bool:
        return any(
            kw.arg == "shell"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )

    def _is_literal_string(self, node: ast.expr) -> bool:
        is_literal = isinstance(node, ast.Constant) and isinstance(node.value, str)
        if is_literal:
            return True
        if isinstance(node, ast.List):
            return all(self._is_literal_string(elt) for elt in node.elts)
        return False

    def _check_shell_injection(self, node: ast.Call):
        name = self._get_func_name(node)
        if name.startswith("subprocess.") and self._has_shell_true(node):
            if node.args and not self._is_literal_string(node.args[0]):
                self._add(
                    node,
                    "shell_injection",
                    f"Shell injection risk: {name}(shell=True) with dynamic command",
                    "critical",
                    "high",
                    "Use subprocess with a list of args instead of shell=True with dynamic strings",
                )
        if name in ("os.system", "os.popen"):
            if node.args and not self._is_literal_string(node.args[0]):
                self._add(
                    node,
                    "shell_injection",
                    f"Shell injection risk: {name}() with dynamic command",
                    "critical",
                    "high",
                    "Use subprocess.run() with a list of arguments instead",
                )

    def _check_unsafe_deserialization(self, node: ast.Call):
        name = self._get_func_name(node)
        if name in {
            "pickle.loads",
            "pickle.load",
            "cPickle.loads",
            "cPickle.load",
            "marshal.loads",
            "marshal.load",
            "shelve.open",
        }:
            self._add(
                node,
                "unsafe_deserialization",
                f"Unsafe deserialization: {name}() can execute arbitrary code",
                "critical",
                "high",
                "Use json.loads() or a safer serialization format",
            )

    def _check_sql_injection(self, node: ast.Call):
        name = self._get_func_name(node)
        if not name.endswith(".execute") or not node.args:
            return
        arg = node.args[0]
        remediation = "Use parameterized queries: cursor.execute('SELECT ?', (val,))"
        if isinstance(arg, ast.JoinedStr):
            self._add(
                node,
                "sql_injection",
                "SQL injection risk: f-string used in .execute()",
                "critical",
                "high",
                remediation,
            )
        elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
            self._add(
                node,
                "sql_injection",
                "SQL injection risk: string concatenation in .execute()",
                "critical",
                "high",
                remediation,
            )
        elif isinstance(arg, ast.Call):
            if isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
                self._add(
                    node,
                    "sql_injection",
                    "SQL injection risk: .format() in .execute()",
                    "critical",
                    "high",
                    remediation,
                )
        elif isinstance(arg, ast.Mod):
            self._add(
                node,
                "sql_injection",
                "SQL injection risk: % formatting in .execute()",
                "critical",
                "high",
                remediation,
            )

    def _check_unsafe_yaml(self, node: ast.Call):
        if self._get_func_name(node) != "yaml.load":
            return
        has_safe_loader = False
        for kw in node.keywords:
            if kw.arg != "Loader":
                continue
            if isinstance(kw.value, ast.Attribute) and kw.value.attr in (
                "SafeLoader",
                "CSafeLoader",
            ):
                has_safe_loader = True
            elif isinstance(kw.value, ast.Name) and kw.value.id in (
                "SafeLoader",
                "CSafeLoader",
            ):
                has_safe_loader = True
        if not has_safe_loader:
            self._add(
                node,
                "unsafe_yaml",
                "Unsafe YAML: yaml.load() without SafeLoader",
                "high",
                "high",
                "Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader)",
            )

    def _check_unsafe_tempfile(self, node: ast.Call):
        if self._get_func_name(node) == "tempfile.mktemp":
            self._add(
                node,
                "unsafe_tempfile",
                "Unsafe tempfile: tempfile.mktemp() is vulnerable to race conditions",
                "high",
                "high",
                "Use tempfile.mkstemp() or tempfile.NamedTemporaryFile() instead",
            )

    def _check_assert_security(self, node: ast.Assert):
        test_dump = ast.dump(node.test)
        for attr in (
            "is_authenticated",
            "has_permission",
            "authorized",
            "is_staff",
            "is_superuser",
            "is_admin",
            "has_perm",
        ):
            if attr in test_dump:
                self._add(
                    node,
                    "assert_security",
                    f"Security assert: assert with '{attr}' is disabled in optimized mode (-O)",
                    "medium",
                    "medium",
                    "Use an if-statement with a proper exception instead of assert for security checks",
                )
                break
