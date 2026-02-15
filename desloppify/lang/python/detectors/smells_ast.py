"""AST-based Python code smell detectors."""

import ast
import re
from pathlib import Path


def _detect_ast_smells(filepath: str, content: str, smell_counts: dict[str, list]):
    """Detect AST-based code smells by dispatching to focused detectors."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _detect_monster_functions(filepath, node, smell_counts)
            _detect_dead_functions(filepath, node, smell_counts)
            _detect_deferred_imports(filepath, node, smell_counts)
            _detect_inline_classes(filepath, node, smell_counts)
            _detect_lru_cache_mutable(filepath, node, tree, smell_counts)

    _detect_subprocess_no_timeout(filepath, tree, smell_counts)
    _detect_mutable_class_var(filepath, tree, smell_counts)
    _detect_unsafe_file_write(filepath, tree, smell_counts)
    _detect_unreachable_code(filepath, tree, smell_counts)
    _detect_constant_return(filepath, tree, smell_counts)
    _detect_regex_backtrack(filepath, tree, smell_counts)
    _detect_naive_comment_strip(filepath, tree, smell_counts)
    _detect_callback_logging(filepath, tree, smell_counts)
    _detect_hardcoded_path_sep(filepath, tree, smell_counts)
    _detect_lost_exception_context(filepath, tree, smell_counts)
    _detect_noop_function(filepath, tree, smell_counts)
    _detect_sys_exit_in_library(filepath, tree, smell_counts)
    _detect_silent_except(filepath, tree, smell_counts)
    _detect_optional_param_sprawl(filepath, tree, smell_counts)
    _detect_annotation_quality(filepath, tree, smell_counts)


def _detect_monster_functions(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag functions longer than 150 LOC."""
    if not (hasattr(node, "end_lineno") and node.end_lineno):
        return
    loc = node.end_lineno - node.lineno + 1
    if loc > 150:
        smell_counts["monster_function"].append({
            "file": filepath, "line": node.lineno, "content": f"{node.name}() — {loc} LOC",
        })


def _is_return_none(stmt: ast.AST) -> bool:
    """Check if a statement is `return` or `return None`."""
    if not isinstance(stmt, ast.Return):
        return False
    return stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)


def _is_docstring(stmt: ast.AST) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.JoinedStr))


def _detect_dead_functions(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag functions whose body is only pass, return, or return None."""
    if node.decorator_list:
        return
    body = node.body
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass) or _is_return_none(stmt):
            smell_counts["dead_function"].append({
                "file": filepath, "line": node.lineno,
                "content": f"{node.name}() — body is only {ast.dump(stmt)[:40]}",
            })
    elif len(body) == 2:
        first, second = body
        if not _is_docstring(first):
            return
        if isinstance(second, ast.Pass):
            desc = "docstring + pass"
        elif _is_return_none(second):
            desc = "docstring + return None"
        else:
            return
        smell_counts["dead_function"].append({
            "file": filepath, "line": node.lineno, "content": f"{node.name}() — {desc}",
        })


def _detect_deferred_imports(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag function-level imports (possible circular import workarounds)."""
    _SKIP_MODULES = ("typing", "typing_extensions", "__future__")
    for child in ast.walk(node):
        if not isinstance(child, (ast.Import, ast.ImportFrom)) or child.lineno <= node.lineno:
            continue
        module = getattr(child, "module", None) or ""
        if module in _SKIP_MODULES:
            continue
        names = ", ".join(a.name for a in child.names[:3])
        if len(child.names) > 3:
            names += f", +{len(child.names) - 3}"
        smell_counts["deferred_import"].append({
            "file": filepath, "line": child.lineno,
            "content": f"import {module or names} inside {node.name}()",
        })
        break  # Only flag once per function


def _detect_inline_classes(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag classes defined inside functions."""
    for child in node.body:
        if isinstance(child, ast.ClassDef):
            smell_counts["inline_class"].append({
                "file": filepath, "line": child.lineno,
                "content": f"class {child.name} defined inside {node.name}()",
            })


def _detect_subprocess_no_timeout(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag subprocess.run/Popen/call/check_call/check_output without timeout=."""
    _SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match subprocess.run(...) or subprocess.call(...) etc.
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_FUNCS:
            # Check if the receiver is 'subprocess'
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                if not has_timeout:
                    smell_counts["subprocess_no_timeout"].append({
                        "file": filepath, "line": node.lineno,
                        "content": f"subprocess.{func.attr}() without timeout",
                    })


def _detect_mutable_class_var(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag class-level mutable defaults (shared across all instances).

    Detects: class Foo: data = [] / data = {} / data: list = []
    Skips dataclasses (which use field(default_factory=...)) and __init__ assignments.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Skip dataclasses (they handle mutable defaults via field())
        is_dataclass = any(
            (isinstance(d, ast.Name) and d.id == "dataclass") or
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass") or
            (isinstance(d, ast.Attribute) and d.attr == "dataclass")
            for d in node.decorator_list
        )
        if is_dataclass:
            continue

        for stmt in node.body:
            # Plain assignment: data = [] or data = {}
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.value, (ast.List, ast.Dict, ast.Set)):
                    names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                    for name in names:
                        smell_counts["mutable_class_var"].append({
                            "file": filepath, "line": stmt.lineno,
                            "content": f"{node.name}.{name} = {ast.dump(stmt.value)[:40]}",
                        })
            # Annotated assignment: data: list = []
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                if isinstance(stmt.value, (ast.List, ast.Dict, ast.Set)):
                    name = stmt.target.id if isinstance(stmt.target, ast.Name) else "?"
                    smell_counts["mutable_class_var"].append({
                        "file": filepath, "line": stmt.lineno,
                        "content": f"{node.name}.{name}: ... = {ast.dump(stmt.value)[:40]}",
                    })


def _detect_lru_cache_mutable(filepath: str, node: ast.AST, tree: ast.Module,
                               smell_counts: dict[str, list]):
    """Flag @lru_cache/@cache functions that reference module-level mutable variables.

    Finds globals referenced in the function body that aren't in the parameter list,
    checking if those names are assigned to mutable values at module level.
    """
    # Check if this function has @lru_cache or @cache decorator
    has_cache = False
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in ("lru_cache", "cache"):
            has_cache = True
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            if dec.func.id in ("lru_cache", "cache"):
                has_cache = True
        elif isinstance(dec, ast.Attribute) and dec.attr in ("lru_cache", "cache"):
            has_cache = True
    if not has_cache:
        return

    # Get parameter names
    param_names = set()
    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
        param_names.add(arg.arg)
    if node.args.vararg:
        param_names.add(node.args.vararg.arg)
    if node.args.kwarg:
        param_names.add(node.args.kwarg.arg)

    # Collect module-level mutable assignments
    module_mutables = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and isinstance(stmt.value, (ast.List, ast.Dict, ast.Set, ast.Call)):
                    module_mutables.add(target.id)
        elif isinstance(stmt, ast.AnnAssign) and stmt.target and isinstance(stmt.target, ast.Name):
            if stmt.value and isinstance(stmt.value, (ast.List, ast.Dict, ast.Set, ast.Call)):
                module_mutables.add(stmt.target.id)

    # Find Name references in function body that point to module-level mutables
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in module_mutables and child.id not in param_names:
            smell_counts["lru_cache_mutable"].append({
                "file": filepath, "line": node.lineno,
                "content": f"@lru_cache on {node.name}() reads mutable global '{child.id}'",
            })
            return  # One warning per function is enough


def _collect_module_constants(filepath: str, content: str,
                              constants_by_key: dict[tuple[str, str], list[tuple[str, int]]]):
    """Collect module-level constant assignments for cross-file duplicate detection.

    Only collects UPPER_CASE or _UPPER_CASE names assigned to simple literals
    (dicts, lists, sets, tuples, numbers, strings).
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and re.match(r"^_?[A-Z][A-Z0-9_]+$", target.id):
                    try:
                        value_repr = ast.dump(node.value)
                    except (RecursionError, ValueError):
                        continue
                    if len(value_repr) > 500:
                        continue  # Skip very large constants
                    key = (target.id, value_repr)
                    constants_by_key.setdefault(key, []).append((filepath, node.lineno))


def _detect_duplicate_constants(constants_by_key: dict[tuple[str, str], list[tuple[str, int]]],
                                 smell_counts: dict[str, list]):
    """Flag constants defined identically in multiple files."""
    for (name, _value_repr), locations in constants_by_key.items():
        if len(locations) < 2:
            continue
        # Check that locations are in distinct files
        files = set(fp for fp, _ in locations)
        if len(files) < 2:
            continue
        for filepath, lineno in locations:
            other_files = [fp for fp, _ in locations if fp != filepath]
            smell_counts["duplicate_constant"].append({
                "file": filepath,
                "line": lineno,
                "content": f"{name} also defined in {', '.join(Path(f).name for f in other_files[:3])}",
            })


def _detect_unsafe_file_write(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag Path.write_text/write_bytes and open(..., 'w') without atomic pattern.

    Looks for .write_text() or .write_bytes() calls that aren't preceded by
    a nearby os.replace() or os.rename() call in the same function.
    Also flags open(file, 'w') without evidence of temp+rename.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

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
            if isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes"):
                write_calls.append(child)

        # Only flag if no atomic pattern exists in the same function
        if not has_atomic_pattern:
            for call in write_calls:
                smell_counts["unsafe_file_write"].append({
                    "file": filepath, "line": call.lineno,
                    "content": f".{call.func.attr}() in {node.name}() without atomic write pattern",
                })


def _detect_unreachable_code(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag statements after unconditional return/raise/break/continue.

    Walks every statement block (function body, if/else body, etc.) and flags
    any statement that follows an unconditional flow-control statement.
    """
    _TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)

    def _check_block(stmts: list[ast.stmt]):
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, _TERMINAL) and i < len(stmts) - 1:
                next_stmt = stmts[i + 1]
                # Skip flagging string constants (often used as section markers)
                if isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Constant):
                    continue
                smell_counts["unreachable_code"].append({
                    "file": filepath, "line": next_stmt.lineno,
                    "content": f"unreachable after {type(stmt).__name__.lower()} on line {stmt.lineno}",
                })
            # Recurse into compound statements
            for attr in ("body", "orelse", "finalbody", "handlers"):
                block = getattr(stmt, attr, None)
                if isinstance(block, list):
                    child_stmts = [s for s in block if isinstance(s, ast.stmt)]
                    if child_stmts:
                        _check_block(child_stmts)
            # ExceptHandler has a body too
            if isinstance(stmt, ast.ExceptHandler):
                _check_block(stmt.body)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_block(node.body)


def _detect_constant_return(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag functions that always return the same constant value.

    Analyzes all return paths — if every return statement returns the same
    literal value (True, False, None, a number, or a string), the function
    likely has dead logic or is a stub masquerading as real code.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Skip tiny functions (stubs/pass-only already caught by dead_function)
        if not hasattr(node, "end_lineno") or not node.end_lineno:
            continue
        loc = node.end_lineno - node.lineno + 1
        if loc < 4:
            continue
        # Skip decorated functions (properties, abstractmethods, etc.)
        if node.decorator_list:
            continue

        returns = []
        has_conditional = False
        for child in ast.walk(node):
            if isinstance(child, ast.Return):
                returns.append(child)
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With,
                                   ast.Try, ast.ExceptHandler)):
                has_conditional = True

        # Need at least 2 returns and some conditional logic to be interesting
        if len(returns) < 2 or not has_conditional:
            continue

        # Extract constant values from all returns
        values = set()
        all_constant = True
        for ret in returns:
            if ret.value is None:
                values.add(repr(None))
            elif isinstance(ret.value, ast.Constant):
                values.add(repr(ret.value.value))
            else:
                all_constant = False
                break

        if all_constant and len(values) == 1:
            val = next(iter(values))
            # Skip functions that always return None — they're just procedures
            if val == "None":
                continue
            smell_counts["constant_return"].append({
                "file": filepath, "line": node.lineno,
                "content": f"{node.name}() always returns {val} ({len(returns)} return sites)",
            })


def _detect_regex_backtrack(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag regex patterns vulnerable to catastrophic backtracking (ReDoS).

    Detects nested quantifiers like (a+)+, (a*)*b, ([^)]*|.)*,
    and overlapping alternation inside quantifiers.
    """
    _RE_FUNCS = {"compile", "search", "match", "fullmatch", "findall",
                 "finditer", "sub", "subn", "split"}
    # Nested quantifier: group with inner +/* quantifier, outer +/* quantifier.
    # Only + and * are dangerous — ? (zero-or-one) can never cause ReDoS.
    _NESTED_QUANT = re.compile(
        r"\([^)]*[+*][^)]*\)[+*]"  # (stuff+stuff)+ or (stuff*stuff)*
        r"|"
        r"\(\?:[^)]*[+*][^)]*\)[+*]"  # (?:stuff+stuff)+
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

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
        if not isinstance(pat_node, ast.Constant) or not isinstance(pat_node.value, str):
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

        smell_counts["regex_backtrack"].append({
            "file": filepath, "line": node.lineno,
            "content": f"pattern: {pattern[:80]}",
        })


def _detect_naive_comment_strip(filepath: str, tree: ast.Module, smell_counts: dict[str, list]):
    """Flag re.sub() calls that strip comments without string awareness.

    Detects patterns like re.sub(r"//[^\\n]*", "") or re.sub(r"/\\*.*?\\*/", "")
    which corrupt URLs and other legitimate // or /* sequences inside strings.
    """
    _COMMENT_PATTERNS = (
        r"//",           # Line comment stripping
        r"/\*",          # Block comment stripping
        r"#[^\n]",       # Python comment stripping (when applied to non-Python content)
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match re.sub(...)
        if not (isinstance(func, ast.Attribute) and func.attr == "sub"
                and isinstance(func.value, ast.Name) and func.value.id == "re"):
            continue

        if len(node.args) < 2:
            continue
        pat_node = node.args[0]
        if not isinstance(pat_node, ast.Constant) or not isinstance(pat_node.value, str):
            continue
        pattern = pat_node.value

        # Check if this is a comment-stripping pattern
        for comment_sig in _COMMENT_PATTERNS:
            if comment_sig in pattern:
                # Check replacement is empty or whitespace
                repl_node = node.args[1]
                if isinstance(repl_node, ast.Constant) and isinstance(repl_node.value, str):
                    if repl_node.value.strip() == "":
                        smell_counts["naive_comment_strip"].append({
                            "file": filepath, "line": node.lineno,
                            "content": f're.sub(r"{pattern[:60]}", "") — not string-aware',
                        })
                        break


def _detect_star_import_no_all(filepath: str, content: str, scan_root: Path,
                                smell_counts: dict[str, list]):
    """Flag `from X import *` where the target module has no __all__.

    Resolves relative and absolute imports within the scan root and checks
    whether the target .py file defines __all__. Only flags targets that
    are part of the scanned project (not stdlib/third-party).
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    file_path = Path(filepath)
    file_dir = file_path.parent

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        # Only care about star imports
        if not any(alias.name == "*" for alias in node.names):
            continue

        module = node.module or ""
        level = node.level  # 0 = absolute, 1+ = relative

        # Resolve to a file path
        target = _resolve_import_target(module, level, file_dir, scan_root)
        if target is None:
            continue

        # Check if target defines __all__
        try:
            target_content = target.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        if re.search(r"^__all__\s*=", target_content, re.MULTILINE):
            continue  # Has __all__, controlled export — skip

        smell_counts["star_import_no_all"].append({
            "file": filepath,
            "line": node.lineno,
            "content": f"from {('.' * level) + module} import * (target has no __all__)",
        })


def _resolve_import_target(module: str, level: int, file_dir: Path,
                            scan_root: Path) -> Path | None:
    """Resolve a Python import to a file path within the scan root.

    Returns the target .py file, or None if unresolvable or outside the project.
    """
    if level > 0:
        # Relative import — go up (level - 1) directories from file_dir
        base = file_dir
        for _ in range(level - 1):
            base = base.parent
    else:
        # Absolute import — start from scan root's parent (package root)
        base = scan_root.parent

    # Convert module dotted path to filesystem path
    parts = module.split(".") if module else []
    target_dir = base / Path(*parts) if parts else base

    # Check for package (__init__.py) or module (.py)
    init_path = target_dir / "__init__.py"
    if init_path.is_file():
        return init_path

    module_path = target_dir.with_suffix(".py")
    if module_path.is_file():
        return module_path

    return None


# ── Callback logging detector ───────────────────────────────────

_CALLBACK_LOG_NAMES = {
    "dprint", "debug_print", "debug_func", "log_func", "log_fn",
    "print_fn", "logger_func", "log_callback", "print_func",
    "debug_log", "verbose_print", "trace_func",
}


def _detect_callback_logging(filepath: str, tree: ast.Module,
                              smell_counts: dict[str, list]):
    """Flag functions that accept a logging callback parameter.

    Detects parameters matching common logging-callback names (dprint, log_func, etc.)
    that are actually called with string arguments in the function body.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Check each parameter name
        for arg in node.args.args + node.args.kwonlyargs:
            name = arg.arg
            if name not in _CALLBACK_LOG_NAMES:
                continue

            # Verify it's actually called in the body (not just accepted)
            call_count = 0
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == name):
                    call_count += 1

            if call_count >= 1:
                smell_counts["callback_logging"].append({
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}({name}=...) — called {call_count} time(s)",
                })


# ── Hardcoded path separator detector ───────────────────────

# Variable names that strongly suggest filesystem paths (not module specifiers)
_PATH_VAR_NAMES = {
    "filepath", "file_path", "filename", "file_name",
    "dirpath", "dir_path", "dirname", "dir_name", "directory",
    "rel_path", "abs_path", "rel_file", "rel_dir", "full_path",
    "base_path", "parent_path", "scan_path",
}

# Substrings that suggest a variable holds a path
_PATH_NAME_PARTS = {"filepath", "dirpath", "file_path", "dir_path"}


def _looks_like_path_var(name: str) -> bool:
    """Check if a variable name suggests it holds a filesystem path."""
    lower = name.lower()
    if lower in _PATH_VAR_NAMES:
        return True
    # Check for path-related substrings: e.g., old_filepath, scan_path
    return any(part in lower for part in _PATH_NAME_PARTS)


def _detect_hardcoded_path_sep(filepath: str, tree: ast.Module,
                                smell_counts: dict[str, list]):
    """Flag .split('/') on path-like variables, and os.path.join mixed with '/'.

    Detects two patterns:
    1. path_var.split('/') — should use os.sep or normalize with replace('\\\\', '/')
    2. f-strings or concatenation building paths with hardcoded '/' separators
       on variables with path-like names
    """
    for node in ast.walk(tree):
        # Pattern 1: var.split("/") where var looks like a path
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "split"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "/"):
            # Check what's being split
            obj = node.func.value
            var_name = ""
            if isinstance(obj, ast.Name):
                var_name = obj.id
            elif isinstance(obj, ast.Attribute):
                var_name = obj.attr
            # Also catch chained: os.path.relpath(...).split("/")
            elif isinstance(obj, ast.Call):
                if (isinstance(obj.func, ast.Attribute)
                        and obj.func.attr in ("relpath", "relative_to")):
                    smell_counts["hardcoded_path_sep"].append({
                        "file": filepath,
                        "line": node.lineno,
                        "content": f'{ast.dump(obj.func)[:40]}.split("/")',
                    })
                    continue

            if var_name and _looks_like_path_var(var_name):
                smell_counts["hardcoded_path_sep"].append({
                    "file": filepath,
                    "line": node.lineno,
                    "content": f'{var_name}.split("/")',
                })

        # Pattern 2: path_var.startswith("something/with/slashes")
        # Skip module specifiers (@/, http://, etc.)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "/" in node.args[0].value
                and not node.args[0].value.startswith(("@", "http", "//"))):
            obj = node.func.value
            var_name = ""
            if isinstance(obj, ast.Name):
                var_name = obj.id
            elif isinstance(obj, ast.Attribute):
                var_name = obj.attr
            if var_name and _looks_like_path_var(var_name):
                smell_counts["hardcoded_path_sep"].append({
                    "file": filepath,
                    "line": node.lineno,
                    "content": f'{var_name}.startswith("{node.args[0].value}")',
                })


# ── Lost exception context detector (#48) ────────────────


def _detect_lost_exception_context(filepath: str, tree: ast.Module,
                                    smell_counts: dict[str, list]):
    """Flag `raise X` inside except handlers that lack `from` (loses chain).

    Bare `raise` (re-raise) preserves the chain implicitly, so it's not flagged.
    Only flags explicit `raise SomeException(...)` without `from orig`.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Raise):
                continue
            # Bare raise (re-raise) — chain is preserved implicitly
            if child.exc is None:
                continue
            # Has `from` clause — chain is preserved explicitly
            if child.cause is not None:
                continue
            exc_str = ast.dump(child.exc)[:60]
            smell_counts["lost_exception_context"].append({
                "file": filepath,
                "line": child.lineno,
                "content": f"raise without 'from' in except handler: {exc_str}",
            })


# ── Vestigial parameter detector (#49) ───────────────────

_VESTIGIAL_KEYWORDS = re.compile(
    r"\b(?:unused|legacy|backward|compat|deprecated|no longer|kept for)\b", re.IGNORECASE
)


def _detect_vestigial_parameter(filepath: str, content: str, lines: list[str],
                                 smell_counts: dict[str, list]):
    """Flag function parameters annotated as unused/deprecated in nearby comments.

    Scans comments within the line range of each function signature for keywords
    like 'unused', 'legacy', 'deprecated', 'backward compat', etc.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Determine the line range of the signature (def line through first body line)
        sig_start = node.lineno - 1  # 0-indexed
        if node.body:
            sig_end = node.body[0].lineno - 1  # exclusive
        else:
            sig_end = sig_start + 1

        # Scan comments in the signature range
        for i in range(sig_start, min(sig_end, len(lines))):
            line = lines[i]
            comment_idx = line.find("#")
            if comment_idx == -1:
                continue
            comment = line[comment_idx:]
            if _VESTIGIAL_KEYWORDS.search(comment):
                smell_counts["vestigial_parameter"].append({
                    "file": filepath,
                    "line": i + 1,
                    "content": f"{node.name}(): {comment.strip()[:80]}",
                })
                break  # One finding per function


# ── Noop function detector (#49) ─────────────────────────

_LOG_CALL_RE = re.compile(r"^(?:logger|log|logging)\.\w+|^print$")


def _is_log_or_print(node: ast.AST) -> bool:
    """Check if a statement is a logging/print call."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    if isinstance(func, ast.Name) and func.id == "print":
        return True
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id in ("logger", "log", "logging"):
            return True
    return False


def _is_trivial_if(node: ast.AST) -> bool:
    """Check if an If statement has only trivial body (return/pass/log)."""
    if not isinstance(node, ast.If):
        return False
    for stmt in node.body + node.orelse:
        if isinstance(stmt, (ast.Pass, ast.Return)):
            continue
        if _is_log_or_print(stmt):
            continue
        if isinstance(stmt, ast.If):
            if not _is_trivial_if(stmt):
                return False
            continue
        return False
    return True


def _detect_noop_function(filepath: str, tree: ast.Module,
                           smell_counts: dict[str, list]):
    """Flag non-trivial functions whose body does nothing useful.

    A function is noop if its body contains only: pass, return, logging calls,
    and early-return ifs with trivial bodies. Excludes __init__, abstract methods,
    property getters, short functions (< 3 statements), and decorated functions.
    """
    _SKIP_NAMES = {"__init__", "__str__", "__repr__", "__enter__", "__exit__",
                   "__del__", "__hash__", "__eq__", "__lt__", "__le__",
                   "__gt__", "__ge__", "__ne__", "__bool__", "__len__"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _SKIP_NAMES:
            continue
        # Skip decorated functions (abstract methods, properties, etc.)
        if node.decorator_list:
            continue
        # Skip short functions — dead_function already catches 1-2 statement bodies
        body = node.body
        # Strip leading docstring
        if body and _is_docstring(body[0]):
            body = body[1:]
        if len(body) < 3:
            continue

        # Check if every statement is trivial
        all_trivial = True
        for stmt in body:
            if isinstance(stmt, (ast.Pass, ast.Return)):
                continue
            if _is_log_or_print(stmt):
                continue
            if _is_trivial_if(stmt):
                continue
            all_trivial = False
            break

        if all_trivial:
            smell_counts["noop_function"].append({
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() — {len(body)} statements, all trivial (pass/return/log)",
            })


# ── sys.exit in library code (#75) ───────────────────────

_CLI_FILENAMES = {"cli.py", "__main__.py", "manage.py", "setup.py"}
_CLI_DIR_PATTERNS = {"/commands/", "/management/"}


def _detect_sys_exit_in_library(filepath: str, tree: ast.Module,
                                 smell_counts: dict[str, list]):
    """Flag sys.exit() calls outside CLI entry points.

    Library code should raise exceptions, not terminate the process.
    CLI entry points (cli.py, __main__.py, commands/) are excluded.
    """
    basename = Path(filepath).name
    if basename in _CLI_FILENAMES:
        return
    # Skip command modules (they're CLI entry points)
    if any(pat in filepath for pat in _CLI_DIR_PATTERNS):
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # sys.exit(...)
        if (isinstance(func, ast.Attribute) and func.attr == "exit"
                and isinstance(func.value, ast.Name) and func.value.id == "sys"):
            smell_counts["sys_exit_in_library"].append({
                "file": filepath, "line": node.lineno,
                "content": "sys.exit() in library code — raise an exception instead",
            })
        # exit(...) or quit(...)
        elif isinstance(func, ast.Name) and func.id in ("exit", "quit"):
            smell_counts["sys_exit_in_library"].append({
                "file": filepath, "line": node.lineno,
                "content": f"{func.id}() in library code — raise an exception instead",
            })


# ── Silent except handler (#75) ──────────────────────────


def _detect_silent_except(filepath: str, tree: ast.Module,
                           smell_counts: dict[str, list]):
    """Flag except handlers whose body is only pass or continue with no logging.

    Silent error suppression hides bugs. The handler should at minimum log
    the error or add a comment explaining why it's safe to ignore.
    """
    _LOG_NAMES = {"print", "log", "logger", "logging", "warn", "warning"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        if not body:
            continue

        # Check if the body is ONLY pass/continue statements (no logging, no raise)
        all_silent = True
        for stmt in body:
            if isinstance(stmt, (ast.Pass, ast.Continue)):
                continue
            # Allow if there's any expression (could be a log call)
            all_silent = False
            break

        if not all_silent or not body:
            continue

        # Build description from the except clause
        if node.type is None:
            clause = "except:"
        elif isinstance(node.type, ast.Name):
            clause = f"except {node.type.id}:"
        elif isinstance(node.type, ast.Tuple):
            names = [n.id for n in node.type.elts if isinstance(n, ast.Name)]
            clause = f"except ({', '.join(names)}):"
        else:
            clause = "except ...:"

        body_text = "pass" if isinstance(body[0], ast.Pass) else "continue"
        smell_counts["silent_except"].append({
            "file": filepath, "line": node.lineno,
            "content": f"{clause} {body_text} — error silently suppressed",
        })


# ── Optional parameter sprawl (#71) ─────────────────────


def _detect_optional_param_sprawl(filepath: str, tree: ast.Module,
                                    smell_counts: dict[str, list]):
    """Flag functions with too many optional parameters.

    Triggers when: optional >= 4 AND optional > required AND total >= 5.
    Excludes __init__ on dataclass-decorated classes and test functions.
    """
    # Collect dataclass class names to exclude their __init__
    dataclass_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Name) and dec.id == "dataclass") or (
                    isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)
                    and dec.func.id == "dataclass"
                ):
                    dataclass_classes.add(node.name)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Skip test functions
        if node.name.startswith("test_"):
            continue

        # Skip dataclass __init__
        if node.name == "__init__":
            # Check if this is inside a dataclass
            parent_is_dataclass = False
            for parent in ast.walk(tree):
                if isinstance(parent, ast.ClassDef) and parent.name in dataclass_classes:
                    if node in ast.walk(parent):
                        parent_is_dataclass = True
                        break
            if parent_is_dataclass:
                continue

        args = node.args
        # Count required vs optional positional args
        n_defaults = len(args.defaults)
        n_positional = len(args.args)
        # Skip 'self'/'cls'
        if n_positional > 0 and args.args[0].arg in ("self", "cls"):
            n_positional -= 1

        required = n_positional - n_defaults
        # kw_defaults can have None entries for kw-only args without defaults
        kw_with_default = sum(1 for d in args.kw_defaults if d is not None)
        optional = n_defaults + kw_with_default
        required = n_positional - n_defaults + (len(args.kwonlyargs) - kw_with_default)
        total = required + optional

        if optional >= 4 and optional > required and total >= 5:
            smell_counts["optional_param_sprawl"].append({
                "file": filepath, "line": node.lineno,
                "content": (f"{node.name}() — {total} params ({required} required, "
                            f"{optional} optional) — consider a config object"),
            })


# ── Annotation quality (#67) ────────────────────────────

# Type names that are "bare" (too generic without subscript)
_BARE_TYPES = {"dict", "list", "set", "tuple", "Dict", "List", "Set", "Tuple"}
_BARE_CALLABLE = {"Callable", "Callable"}


def _detect_annotation_quality(filepath: str, tree: ast.Module,
                                smell_counts: dict[str, list]):
    """Flag loose type annotations: bare dict/list returns, untyped Callable.

    Catches:
    - Return type is bare `dict`, `list`, `set`, `tuple` (not subscripted)
    - Parameter type is bare `Callable` (not `Callable[[...], ...]`)
    - Missing return annotation on public functions with 5+ lines
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Skip private, dunder, and test functions
        if node.name.startswith("_") and not node.name.startswith("__"):
            continue
        if node.name.startswith("test_"):
            continue

        # Check return annotation
        ret = node.returns
        if ret is not None:
            if isinstance(ret, ast.Name) and ret.id in _BARE_TYPES:
                smell_counts["annotation_quality"].append({
                    "file": filepath, "line": node.lineno,
                    "content": (f"{node.name}() -> {ret.id} — use "
                                f"{ret.id}[...] for specific types"),
                })
            elif isinstance(ret, ast.Attribute) and ret.attr in _BARE_TYPES:
                smell_counts["annotation_quality"].append({
                    "file": filepath, "line": node.lineno,
                    "content": (f"{node.name}() -> {ret.attr} — use "
                                f"{ret.attr}[...] for specific types"),
                })
        elif not node.name.startswith("__"):
            # Missing return annotation on non-trivial public functions
            if hasattr(node, "end_lineno") and node.end_lineno:
                loc = node.end_lineno - node.lineno + 1
                if loc >= 10:
                    smell_counts["annotation_quality"].append({
                        "file": filepath, "line": node.lineno,
                        "content": f"{node.name}() — public function ({loc} LOC) missing return type",
                    })

        # Check parameter annotations for bare Callable
        all_args = node.args.args + node.args.kwonlyargs
        for arg in all_args:
            if arg.arg in ("self", "cls"):
                continue
            ann = arg.annotation
            if ann is None:
                continue
            if isinstance(ann, ast.Name) and ann.id == "Callable":
                smell_counts["annotation_quality"].append({
                    "file": filepath, "line": node.lineno,
                    "content": (f"{node.name}({arg.arg}: Callable) — "
                                f"specify Callable[[params], return_type]"),
                })
            elif isinstance(ann, ast.Attribute) and ann.attr == "Callable":
                smell_counts["annotation_quality"].append({
                    "file": filepath, "line": node.lineno,
                    "content": (f"{node.name}({arg.arg}: Callable) — "
                                f"specify Callable[[params], return_type]"),
                })
