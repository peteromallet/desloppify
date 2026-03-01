"""Tests for AST-based Python code smell detectors."""

import textwrap
from pathlib import Path

from desloppify.languages.python.detectors.smells import detect_smells

# ── Helpers ────────────────────────────────────────────────


def _write_py(tmp_path: Path, code: str, filename: str = "test_mod.py") -> Path:
    """Write a Python file and return the directory containing it."""
    f = tmp_path / filename
    f.write_text(textwrap.dedent(code))
    return tmp_path


def _smell_ids(entries: list[dict]) -> set[str]:
    """Extract the set of smell IDs from detect_smells output."""
    return {e["id"] for e in entries}


# ── empty except ──────────────────────────────────────────


class TestEmptyExcept:
    def test_except_pass(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            try:
                risky()
            except:
                pass
        """,
        )
        entries, _ = detect_smells(path)
        assert "empty_except" in _smell_ids(entries)

    def test_except_with_handling_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            try:
                risky()
            except Exception as e:
                raise RuntimeError("oops") from e
        """,
        )
        entries, _ = detect_smells(path)
        assert "empty_except" not in _smell_ids(entries)


# ── swallowed error ───────────────────────────────────────


class TestSwallowedError:
    def test_only_logging(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            try:
                risky()
            except Exception as e:
                logging.error(e)
        """,
        )
        entries, _ = detect_smells(path)
        assert "swallowed_error" in _smell_ids(entries)

    def test_reraise_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            try:
                risky()
            except Exception as e:
                logging.error(e)
                raise
        """,
        )
        entries, _ = detect_smells(path)
        assert "swallowed_error" not in _smell_ids(entries)


# ── monster function ──────────────────────────────────────


class TestMonsterFunction:
    def test_monster_detected(self, tmp_path):
        body = "\n".join(f"    x_{i} = {i}" for i in range(160))
        code = f"def monster():\n{body}\n"
        path = _write_py(tmp_path, code)
        entries, _ = detect_smells(path)
        assert "monster_function" in _smell_ids(entries)

    def test_small_function_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def small():
                return 42
        """,
        )
        entries, _ = detect_smells(path)
        assert "monster_function" not in _smell_ids(entries)


# ── dead function ─────────────────────────────────────────


class TestDeadFunction:
    def test_pass_only(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def noop():
                pass
        """,
        )
        entries, _ = detect_smells(path)
        assert "dead_function" in _smell_ids(entries)

    def test_return_none(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def noop2():
                return None
        """,
        )
        entries, _ = detect_smells(path)
        assert "dead_function" in _smell_ids(entries)

    def test_real_function_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def real():
                return 42
        """,
        )
        entries, _ = detect_smells(path)
        assert "dead_function" not in _smell_ids(entries)

    def test_decorated_function_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            @abstractmethod
            def interface():
                pass
        """,
        )
        entries, _ = detect_smells(path)
        assert "dead_function" not in _smell_ids(entries)


# ── deferred import ───────────────────────────────────────


class TestDeferredImport:
    def test_import_inside_function(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def lazy():
                import json
                return json.dumps({})
        """,
        )
        entries, _ = detect_smells(path)
        assert "deferred_import" in _smell_ids(entries)

    def test_typing_import_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def typed():
                from typing import Optional
                return None
        """,
        )
        entries, _ = detect_smells(path)
        assert "deferred_import" not in _smell_ids(entries)


# ── inline class ──────────────────────────────────────────


class TestInlineClass:
    def test_class_inside_function(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def outer():
                class Inner:
                    pass
                return Inner()
        """,
        )
        entries, _ = detect_smells(path)
        assert "inline_class" in _smell_ids(entries)


# ── subprocess no timeout ────────────────────────────────


class TestSubprocessNoTimeout:
    def test_subprocess_run_no_timeout(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import subprocess
            def run_it():
                subprocess.run(["ls"])
        """,
        )
        entries, _ = detect_smells(path)
        assert "subprocess_no_timeout" in _smell_ids(entries)

    def test_subprocess_with_timeout_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import subprocess
            def run_it():
                subprocess.run(["ls"], timeout=30)
        """,
        )
        entries, _ = detect_smells(path)
        assert "subprocess_no_timeout" not in _smell_ids(entries)


# ── unreachable code ──────────────────────────────────────


class TestUnreachableCode:
    def test_code_after_return(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def early():
                return 1
                x = 2
        """,
        )
        entries, _ = detect_smells(path)
        assert "unreachable_code" in _smell_ids(entries)

    def test_code_after_raise(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def raiser():
                raise ValueError("bad")
                cleanup()
        """,
        )
        entries, _ = detect_smells(path)
        assert "unreachable_code" in _smell_ids(entries)


# ── constant return ───────────────────────────────────────


class TestConstantReturn:
    def test_always_returns_true(self, tmp_path):
        # Needs >=4 LOC, >=2 returns, conditional logic
        path = _write_py(
            tmp_path,
            """\
            def always_true(x):
                if x > 0:
                    return True
                elif x < 0:
                    return True
                else:
                    return True
        """,
        )
        entries, _ = detect_smells(path)
        assert "constant_return" in _smell_ids(entries)

    def test_varying_returns_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def varying(x):
                if x > 0:
                    return True
                else:
                    return False
        """,
        )
        entries, _ = detect_smells(path)
        assert "constant_return" not in _smell_ids(entries)


# ── unsafe file write ────────────────────────────────────


class TestUnsafeFileWrite:
    def test_write_text_no_atomic(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            from pathlib import Path
            def save(data):
                Path("out.txt").write_text(data)
        """,
        )
        entries, _ = detect_smells(path)
        assert "unsafe_file_write" in _smell_ids(entries)

    def test_write_with_os_replace_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import os
            from pathlib import Path
            def safe_save(data):
                Path("out.tmp").write_text(data)
                os.replace("out.tmp", "out.txt")
        """,
        )
        entries, _ = detect_smells(path)
        assert "unsafe_file_write" not in _smell_ids(entries)


# ── vestigial parameter ──────────────────────────────────


class TestVestigialParameter:
    def test_unused_comment_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def process(
                data,
                legacy_mode=False,  # unused, kept for backward compat
            ):
                return data
        """,
        )
        entries, _ = detect_smells(path)
        assert "vestigial_parameter" in _smell_ids(entries)

    def test_deprecated_comment_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def fetch(url, timeout=30):  # deprecated, no longer used
                return url
        """,
        )
        entries, _ = detect_smells(path)
        assert "vestigial_parameter" in _smell_ids(entries)

    def test_normal_comment_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def fetch(url, timeout=30):  # seconds
                return url
        """,
        )
        entries, _ = detect_smells(path)
        assert "vestigial_parameter" not in _smell_ids(entries)


# ── noop function ─────────────────────────────────────────


class TestNoopFunction:
    def test_noop_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def process(data):
                if not data:
                    return
                logger.info("processing")
                print("done")
                return
        """,
        )
        entries, _ = detect_smells(path)
        assert "noop_function" in _smell_ids(entries)

    def test_real_function_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            def process(data):
                result = transform(data)
                save(result)
                return result
        """,
        )
        entries, _ = detect_smells(path)
        assert "noop_function" not in _smell_ids(entries)

    def test_short_function_not_flagged(self, tmp_path):
        """Functions with < 3 statements (after docstring) are too short to flag."""
        path = _write_py(
            tmp_path,
            """\
            def stub():
                pass
                return
        """,
        )
        entries, _ = detect_smells(path)
        assert "noop_function" not in _smell_ids(entries)

    def test_init_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            class Foo:
                def __init__(self):
                    pass
                    return
                    return
        """,
        )
        entries, _ = detect_smells(path)
        assert "noop_function" not in _smell_ids(entries)

    def test_decorated_not_flagged(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            @abstractmethod
            def interface(self):
                pass
                return
                return
        """,
        )
        entries, _ = detect_smells(path)
        assert "noop_function" not in _smell_ids(entries)


# ── stderr traceback ──────────────────────────────────────


class TestStderrTraceback:
    def test_print_exc_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import traceback
            try:
                risky()
            except Exception:
                traceback.print_exc()
        """,
        )
        entries, _ = detect_smells(path)
        assert "stderr_traceback" in _smell_ids(entries)

    def test_no_traceback_ok(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import logging
            try:
                risky()
            except Exception:
                logging.exception("failed")
        """,
        )
        entries, _ = detect_smells(path)
        assert "stderr_traceback" not in _smell_ids(entries)


# ── boundary purity ───────────────────────────────────────


class TestBoundaryPurity:
    def test_import_time_boundary_mutations_detected(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import sys
            import logging
            from dotenv import load_dotenv

            sys.path.append("/tmp/local")
            load_dotenv()
            logging.basicConfig(level=logging.INFO)
        """,
        )
        entries, _ = detect_smells(path)
        ids = _smell_ids(entries)
        assert "import_path_mutation" in ids
        assert "import_env_mutation" in ids
        assert "import_runtime_init" in ids

    def test_main_guard_suppresses_boundary_mutation_smells(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import sys
            from dotenv import load_dotenv

            if __name__ == "__main__":
                sys.path.insert(0, "/tmp/local")
                load_dotenv()
        """,
        )
        entries, _ = detect_smells(path)
        ids = _smell_ids(entries)
        assert "import_path_mutation" not in ids
        assert "import_env_mutation" not in ids

    def test_function_scope_does_not_trigger_import_time_smell(self, tmp_path):
        path = _write_py(
            tmp_path,
            """\
            import sys

            def configure():
                sys.path.append("/tmp/local")
        """,
        )
        entries, _ = detect_smells(path)
        assert "import_path_mutation" not in _smell_ids(entries)
