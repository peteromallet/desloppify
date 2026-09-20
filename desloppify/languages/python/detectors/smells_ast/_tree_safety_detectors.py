"""Safety/security oriented tree-level smell detectors."""

from __future__ import annotations

import ast
import re

from desloppify.languages.python.detectors.smells_ast._helpers import _iter_nodes
from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors_runtime import (
    _detect_import_time_boundary_mutations as _detect_import_time_boundary_mutations,
)
from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors_runtime import (
    _detect_silent_except as _detect_silent_except,
)
from desloppify.languages.python.detectors.smells_ast._tree_safety_detectors_runtime import (
    _detect_sys_exit_in_library as _detect_sys_exit_in_library,
)

__all__ = [
    "_detect_import_time_boundary_mutations",
    "_detect_naive_comment_strip",
    "_detect_regex_backtrack",
    "_detect_silent_except",
    "_detect_subprocess_no_timeout",
    "_detect_sys_exit_in_library",
    "_detect_unsafe_file_write",
]


def _detect_subprocess_no_timeout(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag subprocess.run/Popen/call/check_call/check_output without timeout=."""
    _SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}
    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, ast.Call):
        # Match subprocess.run(...) or subprocess.call(...) etc.
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_FUNCS:
            # Check if the receiver is 'subprocess'
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                if not has_timeout:
                    results.append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "content": f"subprocess.{func.attr}() without timeout",
                        }
                    )
    return results


def _detect_unsafe_file_write(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag Path.write_text/write_bytes and open(..., 'w') without atomic pattern.

    Looks for .write_text() or .write_bytes() calls that aren't preceded by
    a nearby os.replace() or os.rename() call in the same function.
    Also flags open(file, 'w') without evidence of temp+rename.
    """
    # A module function such as ``atomic_io.write_text(...)`` is not
    # ``pathlib.Path.write_text(...)``.  Track direct module imports so the
    # attribute-name heuristic does not misclassify project atomic writers.
    module_aliases = {
        alias.asname or alias.name.split(".", 1)[0]
        for statement in tree.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
    }

    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Collect all method calls and check for atomic patterns in this function
        has_atomic_pattern = False
        write_calls: list[ast.Call] = []

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func

            # Check for os.replace or os.rename (indicates atomic write pattern)
            if isinstance(func, ast.Attribute) and func.attr in ("replace", "rename"):
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    has_atomic_pattern = True

            # Check for shutil.move (also indicates careful file handling)
            if isinstance(func, ast.Attribute) and func.attr == "move":
                if isinstance(func.value, ast.Name) and func.value.id == "shutil":
                    has_atomic_pattern = True

            # Collect .write_text() and .write_bytes() calls
            if isinstance(func, ast.Attribute) and func.attr in (
                "write_text",
                "write_bytes",
            ):
                if isinstance(func.value, ast.Name) and func.value.id in module_aliases:
                    continue
                write_calls.append(child)

        # Only flag if no atomic pattern exists in the same function
        if not has_atomic_pattern:
            for call in write_calls:
                results.append(
                    {
                        "file": filepath,
                        "line": call.lineno,
                        "content": f".{call.func.attr}() in {node.name}() without atomic write pattern",
                    }
                )
    return results


def _detect_regex_backtrack(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag regex patterns vulnerable to catastrophic backtracking (ReDoS).

    Detects nested quantifiers like (a+)+, (a*)*b, ([^)]*|.)*,
    and overlapping alternation inside quantifiers.
    """
    _RE_FUNCS = {
        "compile",
        "search",
        "match",
        "fullmatch",
        "findall",
        "finditer",
        "sub",
        "subn",
        "split",
    }
    # Nested quantifier: group with inner +/* quantifier, outer +/* quantifier.
    # Only + and * are dangerous — ? (zero-or-one) can never cause ReDoS.
    _NESTED_QUANT = re.compile(
        r"\([^)]*[+*][^)]*\)[+*]"  # (stuff+stuff)+ or (stuff*stuff)*
        r"|"
        r"\(\?:[^)]*[+*][^)]*\)[+*]"  # (?:stuff+stuff)+
    )

    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, ast.Call):
        # Match re.X(...) or compiled.X(...)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _RE_FUNCS:
            if isinstance(func.value, ast.Name) and func.value.id == "re":
                pass  # re.compile(...) etc.
            else:
                continue
        elif isinstance(func, ast.Name) and func.id in _RE_FUNCS:
            pass  # Bare compile(...) etc. (rare)
        else:
            continue

        # Extract pattern string from first arg
        if not node.args:
            continue
        pat_node = node.args[0]
        if not isinstance(pat_node, ast.Constant) or not isinstance(
            pat_node.value, str
        ):
            continue
        pattern = pat_node.value

        # Check for nested quantifiers
        m_bt = _NESTED_QUANT.search(pattern)
        if not m_bt:
            continue

        # Extract the flagged fragment for safety checks
        frag = m_bt.group(0)

        # Safe: negated character classes [^X]+ can't overlap with adjacent chars
        if re.search(r"\[\^[^\]]+\][+*]", frag):
            continue

        # Safe: inner quantifier is on a literal-anchored subpattern like \.\w+
        # The required literal prevents ambiguous backtracking
        if re.search(r"\\.\w*[+*]", frag):
            continue

        results.append(
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"pattern: {pattern[:80]}",
            }
        )
    return results


def _detect_naive_comment_strip(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag re.sub() calls that strip comments without string awareness.

    Detects patterns like re.sub(r"//[^\\n]*", "") or re.sub(r"/\\*.*?\\*/", "")
    which corrupt URLs and other legitimate // or /* sequences inside strings.
    """
    _COMMENT_PATTERNS = (
        r"//",  # Line comment stripping
        r"/\*",  # Block comment stripping
        r"#[^\n]",  # Python comment stripping (when applied to non-Python content)
    )

    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, ast.Call):
        func = node.func
        # Match re.sub(...)
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "sub"
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
        ):
            continue

        if len(node.args) < 2:
            continue
        pat_node = node.args[0]
        if not isinstance(pat_node, ast.Constant) or not isinstance(
            pat_node.value, str
        ):
            continue
        pattern = pat_node.value

        # Check if this is a comment-stripping pattern
        for comment_sig in _COMMENT_PATTERNS:
            if comment_sig in pattern:
                # Check replacement is empty or whitespace
                repl_node = node.args[1]
                if isinstance(repl_node, ast.Constant) and isinstance(
                    repl_node.value, str
                ):
                    if repl_node.value.strip() == "":
                        results.append(
                            {
                                "file": filepath,
                                "line": node.lineno,
                                "content": f're.sub(r"{pattern[:60]}", "") — not string-aware',
                            }
                        )
                        break
    return results
