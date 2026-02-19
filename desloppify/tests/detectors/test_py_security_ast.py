"""Direct tests for Python security AST visitor internals."""

from __future__ import annotations

import ast
import textwrap

from desloppify.languages.python.detectors.security_ast import _SecurityVisitor


def _collect(source: str) -> list[dict]:
    code = textwrap.dedent(source).strip() + "\n"
    visitor = _SecurityVisitor("sample.py", code.splitlines())
    visitor.visit(ast.parse(code, filename="sample.py"))
    return visitor.entries


def test_shell_injection_is_flagged_for_dynamic_shell_true():
    entries = _collect(
        """
        import subprocess
        cmd = f"ls {user_input}"
        subprocess.run(cmd, shell=True)
        """
    )
    assert any(entry["detail"]["kind"] == "shell_injection" for entry in entries)


def test_literal_shell_command_is_not_flagged():
    entries = _collect(
        """
        import subprocess
        subprocess.run("ls -la", shell=True)
        """
    )
    assert not any(entry["detail"]["kind"] == "shell_injection" for entry in entries)


def test_yaml_safe_loader_is_not_flagged():
    entries = _collect(
        """
        import yaml
        yaml.load(data, Loader=yaml.SafeLoader)
        """
    )
    assert not any(entry["detail"]["kind"] == "unsafe_yaml" for entry in entries)


def test_assert_security_pattern_is_flagged():
    entries = _collect(
        """
        def check(user):
            assert user.is_authenticated
        """
    )
    assert any(entry["detail"]["kind"] == "assert_security" for entry in entries)
