"""Tests for review context heuristic signal gatherers."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from desloppify.review.context import (
    _gather_ai_debt_signals,
    _gather_auth_context,
    _gather_migration_signals,
    _classify_error_strategy,
    build_review_context,
    _serialize_context,
    ReviewContext,
)
from desloppify.review.context_holistic import build_holistic_context
from desloppify.state import _empty_state


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_rel():
    """Mock rel() to return filename only."""
    with patch(
        "desloppify.review.context.rel",
        side_effect=lambda x: x.split("/")[-1] if "/" in str(x) else str(x),
    ):
        yield


# ── AI Debt Signals ──────────────────────────────────────────────

class TestGatherAiDebtSignals:
    """Tests for _gather_ai_debt_signals."""

    def test_high_comment_ratio_detected(self):
        """Files with >30% comment lines should be flagged."""
        # 4 comment lines out of 5 total = 80%
        content = textwrap.dedent("""\
            # comment 1
            # comment 2
            # comment 3
            # comment 4
            x = 1
        """)
        result = _gather_ai_debt_signals({"/src/chatty.py": content})
        assert "chatty.py" in result["file_signals"]
        sig = result["file_signals"]["chatty.py"]
        assert "comment_ratio" in sig
        assert sig["comment_ratio"] > 0.3

    def test_comment_ratio_not_flagged_when_low(self):
        """Files with <=30% comments should NOT be flagged for comment_ratio."""
        content = textwrap.dedent("""\
            x = 1
            y = 2
            z = 3
            # one comment
        """)
        result = _gather_ai_debt_signals({"/src/normal.py": content})
        signals = result["file_signals"]
        if "normal.py" in signals:
            assert "comment_ratio" not in signals["normal.py"]

    def test_log_density_detected(self):
        """Files with >3 logs per function should be flagged."""
        # 1 function, 4 log calls => density 4.0
        content = textwrap.dedent("""\
            def process():
                console.log("start")
                console.log("mid 1")
                console.log("mid 2")
                console.log("end")
                return True
        """)
        result = _gather_ai_debt_signals({"/src/noisy.py": content})
        assert "noisy.py" in result["file_signals"]
        sig = result["file_signals"]["noisy.py"]
        assert "log_density" in sig
        assert sig["log_density"] > 3.0

    def test_log_density_includes_python_logging(self):
        """Python logging.* calls should be counted as logs."""
        content = textwrap.dedent("""\
            def handle():
                logging.debug("a")
                logging.info("b")
                logging.warning("c")
                logging.error("d")
        """)
        result = _gather_ai_debt_signals({"/src/logged.py": content})
        assert "logged.py" in result["file_signals"]
        assert "log_density" in result["file_signals"]["logged.py"]

    def test_log_density_not_flagged_when_low(self):
        """Files with <=3 logs per function should NOT be flagged."""
        content = textwrap.dedent("""\
            def foo():
                console.log("ok")
                return 1

            def bar():
                console.log("ok")
                return 2
        """)
        result = _gather_ai_debt_signals({"/src/ok.py": content})
        signals = result["file_signals"]
        if "ok.py" in signals:
            assert "log_density" not in signals["ok.py"]

    def test_guard_density_detected(self):
        """Files with >2 guard clauses per function should be flagged."""
        # 1 function, 3 null checks => density 3.0
        content = textwrap.dedent("""\
            function validate(a, b, c) {
                if (a === null) return;
                if (b === undefined) return;
                if (c === null) return;
                return a + b + c;
            }
        """)
        result = _gather_ai_debt_signals({"/src/guards.ts": content})
        assert "guards.ts" in result["file_signals"]
        sig = result["file_signals"]["guards.ts"]
        assert "guard_density" in sig
        assert sig["guard_density"] > 2.0

    def test_guard_density_multiple_null_checks(self):
        """Multiple null/undefined checks per function trigger guard_density."""
        # 1 function, 3 null-check guards => density 3.0
        content = textwrap.dedent("""\
            function validate(a, b, c) {
                if (a === null) return;
                if (b !== null) doSomething();
                if (c === undefined) return;
                return a + b + c;
            }
        """)
        result = _gather_ai_debt_signals({"/src/guards2.ts": content})
        assert "guards2.ts" in result["file_signals"]
        assert "guard_density" in result["file_signals"]["guards2.ts"]

    def test_no_signals_for_clean_file(self):
        """A normal file should produce no per-file signals."""
        content = textwrap.dedent("""\
            def add(a, b):
                return a + b

            def subtract(a, b):
                return a - b
        """)
        result = _gather_ai_debt_signals({"/src/clean.py": content})
        assert result["file_signals"] == {}

    def test_top_20_limit(self):
        """Only top 20 files by signal count are returned."""
        files = {}
        for i in range(30):
            # Each file has high comment ratio
            files[f"/src/file{i}.py"] = (
                "# comment\n" * 8 + "x = 1\n" * 2
            )
        result = _gather_ai_debt_signals(files)
        assert len(result["file_signals"]) <= 20

    def test_empty_input(self):
        """Empty file_contents should return empty signals."""
        result = _gather_ai_debt_signals({})
        assert result["file_signals"] == {}
        assert result["codebase_avg_comment_ratio"] == 0.0

    def test_codebase_avg_comment_ratio(self):
        """Average comment ratio is computed across all files."""
        files = {
            "/src/a.py": "# comment\nx = 1\n",         # 50%
            "/src/b.py": "x = 1\ny = 2\nz = 3\nw = 4\n",  # 0%
        }
        result = _gather_ai_debt_signals(files)
        avg = result["codebase_avg_comment_ratio"]
        assert 0.2 <= avg <= 0.3  # (0.5 + 0.0) / 2 = 0.25

    def test_empty_content_file_skipped(self):
        """A file with empty string content should be skipped (no lines)."""
        result = _gather_ai_debt_signals({"/src/empty.py": ""})
        assert result["file_signals"] == {}

    def test_multiple_signals_on_same_file(self):
        """A file can have multiple signals simultaneously."""
        # High comments + high log density + high guard density
        content = textwrap.dedent("""\
            # comment 1
            # comment 2
            # comment 3
            # comment 4
            function handler() {
                console.log("a")
                console.log("b")
                console.log("c")
                console.log("d")
                if (x === null) return;
                if (y === undefined) return;
                if (z === null) return;
            }
        """)
        result = _gather_ai_debt_signals({"/src/messy.ts": content})
        sig = result["file_signals"]["messy.ts"]
        assert "comment_ratio" in sig
        assert "log_density" in sig
        assert "guard_density" in sig

    def test_js_style_comments_detected(self):
        """// and /* style comments should be counted."""
        content = "// comment\n/* comment */\nvar x = 1;\n"
        result = _gather_ai_debt_signals({"/src/js.ts": content})
        # 2/3 comment lines = 0.67
        assert "js.ts" in result["file_signals"]
        assert result["file_signals"]["js.ts"]["comment_ratio"] > 0.3

    def test_star_comment_continuation_detected(self):
        """Lines starting with * (JSDoc/block comment continuation) should count."""
        content = textwrap.dedent("""\
            /**
             * This is a JSDoc comment
             * with multiple lines
             * and more lines
             */
            function foo() {}
        """)
        result = _gather_ai_debt_signals({"/src/jsdoc.ts": content})
        # 5 out of 6 lines are comment-ish
        assert "jsdoc.ts" in result["file_signals"]


# ── Auth Context ─────────────────────────────────────────────────

class TestGatherAuthContext:
    """Tests for _gather_auth_context."""

    def test_python_route_with_auth_detected(self):
        """Python route decorator + auth decorator should be detected."""
        content = textwrap.dedent("""\
            @app.get("/users")
            @login_required
            def get_users():
                return users

            @app.post("/users")
            def create_user():
                return new_user
        """)
        result = _gather_auth_context({"/src/routes.py": content})
        assert "route_auth_coverage" in result
        ra = result["route_auth_coverage"]["routes.py"]
        assert ra["handlers"] == 2
        assert ra["with_auth"] == 1
        assert ra["without_auth"] == 1

    def test_ts_route_detection(self):
        """TypeScript Next.js-style route handlers should be detected."""
        content = textwrap.dedent("""\
            export async function GET(req) {
                return Response.json({ok: true});
            }

            export async function POST(req) {
                const session = await getServerSession();
                return Response.json({ok: true});
            }
        """)
        result = _gather_auth_context({"/src/route.ts": content})
        assert "route_auth_coverage" in result
        ra = result["route_auth_coverage"]["route.ts"]
        assert ra["handlers"] == 2
        assert ra["with_auth"] == 1  # getServerSession counts as auth
        assert ra["without_auth"] == 1

    def test_express_routes_detected(self):
        """Express-style app.get/post should be detected as route handlers."""
        content = textwrap.dedent("""\
            app.get("/api/data", handler);
            app.post("/api/submit", handler);
        """)
        result = _gather_auth_context({"/src/server.ts": content})
        assert "route_auth_coverage" in result
        ra = result["route_auth_coverage"]["server.ts"]
        assert ra["handlers"] == 2

    def test_rls_table_coverage_with_and_without(self):
        """SQL files should track CREATE TABLE vs ENABLE RLS."""
        content = textwrap.dedent("""\
            CREATE TABLE users (id serial primary key);
            CREATE TABLE posts (id serial primary key);
            CREATE TABLE comments (id serial primary key);

            ALTER TABLE users ENABLE ROW LEVEL SECURITY;
            CREATE POLICY read_own ON posts;
        """)
        result = _gather_auth_context({"/migrations/001.sql": content})
        assert "rls_coverage" in result
        rls = result["rls_coverage"]
        assert "users" in rls["with_rls"]
        assert "posts" in rls["with_rls"]
        assert "comments" in rls["without_rls"]

    def test_rls_case_insensitive(self):
        """RLS detection should be case-insensitive."""
        content = textwrap.dedent("""\
            create table my_table (id int);
            alter table my_table enable row level security;
        """)
        result = _gather_auth_context({"/sql/schema.sql": content})
        assert "rls_coverage" in result
        assert "my_table" in result["rls_coverage"]["with_rls"]

    def test_rls_if_not_exists(self):
        """CREATE TABLE IF NOT EXISTS should be detected."""
        content = "CREATE TABLE IF NOT EXISTS settings (id int);\n"
        result = _gather_auth_context({"/sql/init.sql": content})
        assert "rls_coverage" in result
        assert "settings" in result["rls_coverage"]["without_rls"]

    def test_service_role_detection(self):
        """Files with both service_role AND createClient should be flagged."""
        content = textwrap.dedent("""\
            const client = createClient(url, key);
            const admin = createClient(url, service_role);
        """)
        result = _gather_auth_context({"/src/admin.ts": content})
        assert "service_role_usage" in result
        assert "admin.ts" in result["service_role_usage"]

    def test_service_role_without_create_client_not_flagged(self):
        """service_role mention without createClient should NOT be flagged."""
        content = "const key = process.env.SERVICE_ROLE;\n"
        result = _gather_auth_context({"/src/config.ts": content})
        assert "service_role_usage" not in result

    def test_service_role_variants(self):
        """All service_role naming variants should be detected."""
        for variant in ["service_role", "SERVICE_ROLE", "serviceRole"]:
            content = f"const x = createClient(url, {variant});\n"
            result = _gather_auth_context({f"/src/{variant}.ts": content})
            assert "service_role_usage" in result, f"Failed for variant: {variant}"

    def test_auth_pattern_counting(self):
        """Auth pattern count should reflect number of auth checks in file."""
        content = textwrap.dedent("""\
            const session = getServerSession();
            if (!session.user) return;
            const user = request.user;
        """)
        result = _gather_auth_context({"/src/check.ts": content})
        assert "auth_patterns" in result
        assert result["auth_patterns"]["check.ts"] >= 2

    def test_auth_decorator_patterns(self):
        """Various auth decorators should be counted."""
        content = textwrap.dedent("""\
            @require_auth
            def endpoint1(): pass

            @auth_required
            def endpoint2(): pass

            @requires_auth
            def endpoint3(): pass
        """)
        result = _gather_auth_context({"/src/api.py": content})
        assert "auth_patterns" in result
        assert result["auth_patterns"]["api.py"] == 3

    def test_empty_input_returns_empty(self):
        """Empty file_contents should return empty dict."""
        result = _gather_auth_context({})
        assert result == {}

    def test_no_routes_no_route_auth_key(self):
        """Files without route handlers should not produce route_auth_coverage."""
        content = "def helper():\n    return 42\n"
        result = _gather_auth_context({"/src/util.py": content})
        assert "route_auth_coverage" not in result

    def test_with_auth_capped_to_handler_count(self):
        """with_auth should never exceed handler count even if auth checks > routes."""
        content = textwrap.dedent("""\
            @app.get("/one")
            @login_required
            @require_auth
            @auth_required
            def endpoint():
                session = getServerSession()
                return request.user
        """)
        result = _gather_auth_context({"/src/over.py": content})
        ra = result["route_auth_coverage"]["over.py"]
        assert ra["with_auth"] <= ra["handlers"]
        assert ra["without_auth"] >= 0

    def test_router_decorator_detected(self):
        """@router.get/post decorators should be detected."""
        content = textwrap.dedent("""\
            @router.get("/items")
            def list_items(): pass

            @router.post("/items")
            def create_item(): pass
        """)
        result = _gather_auth_context({"/src/items.py": content})
        assert "route_auth_coverage" in result
        assert result["route_auth_coverage"]["items.py"]["handlers"] == 2


# ── Migration Signals ────────────────────────────────────────────

class TestGatherMigrationSignals:
    """Tests for _gather_migration_signals."""

    def test_deprecated_markers_counted(self):
        """@deprecated, @Deprecated, and DEPRECATED should be counted."""
        content = textwrap.dedent("""\
            @deprecated
            def old_func():
                pass

            @Deprecated
            class OldClass:
                pass

            # DEPRECATED: don't use this
            x = 1
        """)
        result = _gather_migration_signals({"/src/old.py": content}, "python")
        assert "deprecated_markers" in result
        dm = result["deprecated_markers"]
        assert dm["total"] == 3
        assert dm["files"]["old.py"] == 3

    def test_deprecated_across_files(self):
        """Deprecated counts should aggregate across files."""
        files = {
            "/src/a.py": "@deprecated\ndef f(): pass\n",
            "/src/b.py": "DEPRECATED\nDEPRECATED\n",
        }
        result = _gather_migration_signals(files, "python")
        dm = result["deprecated_markers"]
        assert dm["total"] == 3
        assert dm["files"]["a.py"] == 1
        assert dm["files"]["b.py"] == 2

    def test_migration_todos_detected(self):
        """TODO/FIXME/HACK with migration keywords should be detected.

        Note: the regex uses ``[^:\\n]*`` between the marker and keyword,
        so the keyword must appear before any colon on the same line.
        """
        content = textwrap.dedent("""\
            # FIXME legacy code needs removal
            # TODO remove after v2 cleanup
            # HACK old api workaround
            # TODO: regular todo - not migration
        """)
        result = _gather_migration_signals({"/src/migrate.py": content}, "python")
        assert "migration_todos" in result
        todos = result["migration_todos"]
        assert len(todos) == 3
        assert all(t["file"] == "migrate.py" for t in todos)

    def test_migration_todo_text_truncated(self):
        """Migration TODO text should be truncated to 120 chars."""
        long_text = "TODO: migrate " + "x" * 200
        result = _gather_migration_signals({"/src/long.py": long_text}, "python")
        if result.get("migration_todos"):
            for todo in result["migration_todos"]:
                assert len(todo["text"]) <= 120

    def test_migration_todos_capped_at_30(self):
        """At most 30 migration TODOs should be returned."""
        lines = "\n".join(f"# TODO: migrate item {i}" for i in range(40))
        result = _gather_migration_signals({"/src/many.py": lines}, "python")
        assert len(result.get("migration_todos", [])) <= 30

    def test_pattern_pairs_ts(self):
        """TypeScript pattern pairs should be detected when both old and new coexist."""
        content_old = textwrap.dedent("""\
            const axios = require('axios');
            var x = 1;
        """)
        content_new = textwrap.dedent("""\
            import { fetch } from 'node-fetch';
            const y = 2;
            let z = 3;
        """)
        files = {"/src/old.ts": content_old, "/src/new.ts": content_new}
        result = _gather_migration_signals(files, "typescript")
        assert "pattern_pairs" in result
        pair_names = [p["name"] for p in result["pattern_pairs"]]
        assert "require\u2192import" in pair_names
        assert "var\u2192let/const" in pair_names

    def test_pattern_pairs_py(self):
        """Python pattern pairs should detect old+new coexistence."""
        files = {
            "/src/old.py": "import os\nresult = os.path.join('a', 'b')\n",
            "/src/new.py": "from pathlib import Path\np = Path('a') / 'b'\n",
        }
        result = _gather_migration_signals(files, "python")
        assert "pattern_pairs" in result
        pair_names = [p["name"] for p in result["pattern_pairs"]]
        assert "os.path\u2192pathlib" in pair_names

    def test_pattern_pairs_not_detected_when_only_old(self):
        """Pattern pairs should NOT be detected when only old pattern exists."""
        content = "var x = 1;\nvar y = 2;\n"
        result = _gather_migration_signals({"/src/old.ts": content}, "typescript")
        # var->let/const should not appear since there are no let/const
        pairs = result.get("pattern_pairs", [])
        pair_names = [p["name"] for p in pairs]
        assert "var\u2192let/const" not in pair_names

    def test_pattern_pairs_counts(self):
        """Pattern pairs should report old_count and new_count."""
        files = {
            "/src/a.ts": "var x = 1;\n",
            "/src/b.ts": "let y = 2;\n",
            "/src/c.ts": "const z = 3;\n",
        }
        result = _gather_migration_signals(files, "typescript")
        if "pattern_pairs" in result:
            for pair in result["pattern_pairs"]:
                if pair["name"] == "var\u2192let/const":
                    assert pair["old_count"] == 1
                    assert pair["new_count"] == 2

    def test_mixed_extensions_detected(self):
        """Files with same stem but .js and .ts should be flagged."""
        files = {
            "/src/utils.js": "var x = 1;",
            "/src/utils.ts": "const x = 1;",
            "/src/helper.tsx": "export default function() {}",
            "/src/helper.jsx": "export default function() {}",
        }
        result = _gather_migration_signals(files, "typescript")
        assert "mixed_extensions" in result
        assert "utils" in result["mixed_extensions"]
        assert "helper" in result["mixed_extensions"]

    def test_mixed_extensions_not_flagged_for_different_stems(self):
        """Different file stems should not be flagged as mixed."""
        files = {
            "/src/utils.js": "var x = 1;",
            "/src/helper.ts": "const x = 1;",
        }
        result = _gather_migration_signals(files, "typescript")
        assert "mixed_extensions" not in result

    def test_mixed_extensions_ignores_py(self):
        """Non-JS/TS extensions should be ignored for mixed extension check."""
        files = {
            "/src/utils.py": "x = 1",
            "/src/utils.ts": "const x = 1;",
        }
        result = _gather_migration_signals(files, "typescript")
        # .py is not in the tracked set, so utils should not be flagged
        assert "mixed_extensions" not in result

    def test_mixed_extensions_capped_at_20(self):
        """At most 20 mixed extension stems should be returned."""
        files = {}
        for i in range(25):
            files[f"/src/file{i}.js"] = "var x;"
            files[f"/src/file{i}.ts"] = "const x: number;"
        result = _gather_migration_signals(files, "typescript")
        assert len(result.get("mixed_extensions", [])) <= 20

    def test_empty_input(self):
        """Empty file_contents should return empty dict."""
        result = _gather_migration_signals({}, "python")
        assert result == {}

    def test_no_deprecated_no_key(self):
        """If no deprecated markers found, key should be absent."""
        content = "def foo():\n    return 1\n"
        result = _gather_migration_signals({"/src/clean.py": content}, "python")
        assert "deprecated_markers" not in result

    def test_hack_with_migration_keyword(self):
        """HACK comments with migration keywords should be captured."""
        content = "# HACK old api workaround needs cleanup\n"
        result = _gather_migration_signals({"/src/hack.py": content}, "python")
        assert "migration_todos" in result
        assert len(result["migration_todos"]) == 1


# ── Error Strategy Classification ────────────────────────────────

class TestClassifyErrorStrategy:
    """Tests for _classify_error_strategy."""

    def test_throw_strategy(self):
        """Files predominantly using throw/raise should classify as 'throw'."""
        content = textwrap.dedent("""\
            def validate(x):
                if not x:
                    raise ValueError("bad")
                if x < 0:
                    raise TypeError("negative")
        """)
        assert _classify_error_strategy(content) == "throw"

    def test_return_null_strategy(self):
        """Files predominantly returning null/None should classify as 'return_null'."""
        content = textwrap.dedent("""\
            def find(x):
                if not x:
                    return None
                if x < 0:
                    return None
                return x
        """)
        assert _classify_error_strategy(content) == "return_null"

    def test_result_type_strategy(self):
        """Files using Result/Either/Ok/Err should classify as 'result_type'."""
        content = textwrap.dedent("""\
            fn process() -> Result<(), Error> {
                let value = Ok(42);
                let other = Err("bad");
                Result::Ok(value)
            }
        """)
        assert _classify_error_strategy(content) == "result_type"

    def test_try_catch_strategy(self):
        """Files using try/catch blocks should classify as 'try_catch'."""
        content = textwrap.dedent("""\
            function work() {
                try {
                    doA();
                } catch(e) {}
                try {
                    doB();
                } catch(e) {}
                try {
                    doC();
                } catch(e) {}
            }
        """)
        assert _classify_error_strategy(content) == "try_catch"

    def test_try_python_style(self):
        """Python try: should also count as try_catch."""
        content = textwrap.dedent("""\
            def work():
                try:
                    do_a()
                except:
                    pass
                try:
                    do_b()
                except:
                    pass
                try:
                    do_c()
                except:
                    pass
        """)
        assert _classify_error_strategy(content) == "try_catch"

    def test_mixed_strategy(self):
        """Files with no dominant strategy (none >60%) should be 'mixed'."""
        content = textwrap.dedent("""\
            def a():
                raise ValueError("bad")
            def b():
                return None
            def c():
                try:
                    pass
                except:
                    pass
        """)
        result = _classify_error_strategy(content)
        # Each strategy has roughly 1/3, so none > 60%
        assert result == "mixed"

    def test_none_for_empty_content(self):
        """Empty content should return None."""
        assert _classify_error_strategy("") is None

    def test_none_for_no_error_patterns(self):
        """Content with no error patterns should return None."""
        content = textwrap.dedent("""\
            def add(a, b):
                return a + b
        """)
        assert _classify_error_strategy(content) is None

    def test_throw_js_style(self):
        """JS-style 'throw new Error' should count as throw."""
        content = textwrap.dedent("""\
            function validate(x) {
                if (!x) throw new Error("missing");
                if (x < 0) throw new TypeError("negative");
                if (x > 100) throw new RangeError("too big");
            }
        """)
        assert _classify_error_strategy(content) == "throw"

    def test_return_undefined(self):
        """return undefined should classify as return_null."""
        content = textwrap.dedent("""\
            function find(x) {
                if (!x) return undefined;
                if (x < 0) return undefined;
                if (x > 100) return undefined;
                return x;
            }
        """)
        assert _classify_error_strategy(content) == "return_null"

    def test_dominant_threshold_boundary(self):
        """At exactly 60%, strategy IS dominant (check uses strict < 0.6)."""
        # 3 throws + 2 return nulls = 5 total, throw is 60% = 0.6 -> NOT < 0.6 -> dominant
        content = textwrap.dedent("""\
            def a(): raise ValueError("a")
            def b(): raise ValueError("b")
            def c(): raise ValueError("c")
            def d(): return None
            def e(): return None
        """)
        result = _classify_error_strategy(content)
        # 3/5 = 0.6, which is NOT < 0.6, so it counts as dominant
        assert result == "throw"

    def test_mixed_below_60_percent(self):
        """Below 60%, no strategy is dominant so result should be 'mixed'."""
        # 2 throws + 2 return nulls + 1 try = 5 total, max is 2/5 = 40% < 60%
        content = textwrap.dedent("""\
            def a(): raise ValueError("a")
            def b(): raise ValueError("b")
            def c(): return None
            def d(): return None
            def e():
                try:
                    pass
                except:
                    pass
        """)
        result = _classify_error_strategy(content)
        assert result == "mixed"


# ── Integration: build_review_context ─────────────────────────────

class TestBuildReviewContext:
    """Tests for build_review_context populating signal fields."""

    @pytest.fixture
    def mock_lang(self):
        lang = MagicMock()
        lang.name = "typescript"
        lang.file_finder = MagicMock(return_value=[])
        lang._zone_map = None
        lang._dep_graph = None
        return lang

    @pytest.fixture
    def empty_state(self):
        return _empty_state()

    def test_ai_debt_signals_populated(self, mock_lang, empty_state):
        """build_review_context should populate ai_debt_signals."""
        # Create a file with high comment ratio
        comment_heavy = "# comment\n" * 8 + "x = 1\n" * 2

        with patch("desloppify.review.context.read_file_text",
                    return_value=comment_heavy):
            ctx = build_review_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/chatty.py"],
            )

        assert ctx.ai_debt_signals is not None
        assert "file_signals" in ctx.ai_debt_signals

    def test_auth_patterns_populated(self, mock_lang, empty_state):
        """build_review_context should populate auth_patterns."""
        route_content = textwrap.dedent("""\
            @app.get("/users")
            @login_required
            def get_users():
                return []
        """)

        with patch("desloppify.review.context.read_file_text",
                    return_value=route_content):
            ctx = build_review_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/routes.py"],
            )

        assert ctx.auth_patterns is not None
        assert "route_auth_coverage" in ctx.auth_patterns or "auth_patterns" in ctx.auth_patterns

    def test_error_strategies_populated(self, mock_lang, empty_state):
        """build_review_context should populate error_strategies."""
        throw_content = textwrap.dedent("""\
            function validate(x) {
                if (!x) throw new Error("missing");
                if (x < 0) throw new Error("negative");
                if (x > 100) throw new Error("too big");
            }
        """)

        with patch("desloppify.review.context.read_file_text",
                    return_value=throw_content):
            ctx = build_review_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/validate.ts"],
            )

        assert ctx.error_strategies is not None
        assert len(ctx.error_strategies) > 0

    def test_empty_files_returns_default_context(self, mock_lang, empty_state):
        """build_review_context with no files should return empty context."""
        ctx = build_review_context(
            Path("/project"), mock_lang, empty_state, files=[],
        )
        assert ctx.ai_debt_signals == {}
        assert ctx.auth_patterns == {}
        assert ctx.error_strategies == {}


# ── Integration: build_holistic_context ───────────────────────────

class TestBuildHolisticContext:
    """Tests for build_holistic_context including signal sections."""

    @pytest.fixture
    def mock_lang(self):
        lang = MagicMock()
        lang.name = "typescript"
        lang.file_finder = MagicMock(return_value=[])
        lang._zone_map = None
        lang._dep_graph = None
        return lang

    @pytest.fixture
    def empty_state(self):
        return _empty_state()

    def test_authorization_section_present_with_routes(self, mock_lang, empty_state):
        """build_holistic_context should include authorization when route handlers exist."""
        content = textwrap.dedent("""\
            @app.get("/api/data")
            def get_data():
                return []
        """)

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=content):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/api.py"],
            )

        assert "authorization" in ctx

    def test_ai_debt_section_present_with_signals(self, mock_lang, empty_state):
        """build_holistic_context should include ai_debt_signals when files have signals."""
        comment_heavy = "# comment\n" * 8 + "x = 1\n" * 2

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=comment_heavy):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/chatty.py"],
            )

        assert "ai_debt_signals" in ctx

    def test_migration_signals_present(self, mock_lang, empty_state):
        """build_holistic_context should include migration_signals when deprecated markers exist."""
        content = "@deprecated\ndef old(): pass\n"

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=content):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/old.py"],
            )

        assert "migration_signals" in ctx

    def test_no_auth_section_when_no_routes(self, mock_lang, empty_state):
        """build_holistic_context should NOT include authorization when no route handlers."""
        content = "def helper():\n    return 42\n"

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=content):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/util.py"],
            )

        assert "authorization" not in ctx

    def test_no_ai_debt_when_clean(self, mock_lang, empty_state):
        """build_holistic_context should NOT include ai_debt_signals when no signals."""
        content = "def add(a, b):\n    return a + b\n"

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=content):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/clean.py"],
            )

        assert "ai_debt_signals" not in ctx

    def test_codebase_stats_always_present(self, mock_lang, empty_state):
        """build_holistic_context should always include codebase_stats."""
        content = "x = 1\n"

        with patch("desloppify.review.context_holistic.read_file_text",
                    return_value=content):
            ctx = build_holistic_context(
                Path("/project"), mock_lang, empty_state,
                files=["/project/src/x.py"],
            )

        assert "codebase_stats" in ctx
        assert "total_files" in ctx["codebase_stats"]
        assert "total_loc" in ctx["codebase_stats"]


# ── Serialization ─────────────────────────────────────────────────

class TestSerializeContext:
    """Tests for _serialize_context."""

    def test_always_present_fields(self):
        """Core fields should always be present in serialized output."""
        ctx = ReviewContext()
        d = _serialize_context(ctx)
        assert "naming_vocabulary" in d
        assert "error_conventions" in d
        assert "module_patterns" in d
        assert "import_graph_summary" in d
        assert "zone_distribution" in d
        assert "existing_findings" in d
        assert "codebase_stats" in d
        assert "sibling_conventions" in d

    def test_ai_debt_signals_included_when_populated(self):
        """ai_debt_signals should be included when non-empty."""
        ctx = ReviewContext()
        ctx.ai_debt_signals = {"file_signals": {"a.py": {"comment_ratio": 0.5}},
                               "codebase_avg_comment_ratio": 0.1}
        d = _serialize_context(ctx)
        assert "ai_debt_signals" in d

    def test_ai_debt_signals_excluded_when_empty(self):
        """ai_debt_signals should be excluded when empty."""
        ctx = ReviewContext()
        ctx.ai_debt_signals = {}
        d = _serialize_context(ctx)
        assert "ai_debt_signals" not in d

    def test_auth_patterns_included_when_populated(self):
        """auth_patterns should be included when non-empty."""
        ctx = ReviewContext()
        ctx.auth_patterns = {"route_auth_coverage": {"api.py": {"handlers": 2}}}
        d = _serialize_context(ctx)
        assert "auth_patterns" in d

    def test_auth_patterns_excluded_when_empty(self):
        """auth_patterns should be excluded when empty."""
        ctx = ReviewContext()
        ctx.auth_patterns = {}
        d = _serialize_context(ctx)
        assert "auth_patterns" not in d

    def test_error_strategies_included_when_populated(self):
        """error_strategies should be included when non-empty."""
        ctx = ReviewContext()
        ctx.error_strategies = {"api.py": "throw"}
        d = _serialize_context(ctx)
        assert "error_strategies" in d

    def test_error_strategies_excluded_when_empty(self):
        """error_strategies should be excluded when empty."""
        ctx = ReviewContext()
        ctx.error_strategies = {}
        d = _serialize_context(ctx)
        assert "error_strategies" not in d

    def test_all_conditional_fields_present(self):
        """All three conditional fields should appear when populated."""
        ctx = ReviewContext()
        ctx.ai_debt_signals = {"file_signals": {}, "codebase_avg_comment_ratio": 0.0}
        ctx.auth_patterns = {"auth_patterns": {"a.py": 1}}
        ctx.error_strategies = {"a.py": "throw"}
        d = _serialize_context(ctx)
        # ai_debt_signals has truthy value (non-empty dict with keys)
        assert "ai_debt_signals" in d
        assert "auth_patterns" in d
        assert "error_strategies" in d

    def test_serialized_values_match_context(self):
        """Serialized values should exactly match the ReviewContext attributes."""
        ctx = ReviewContext()
        ctx.naming_vocabulary = {"prefixes": {"get": 5}, "total_names": 10}
        ctx.error_conventions = {"try_catch": 3}
        ctx.ai_debt_signals = {"file_signals": {"x.py": {"log_density": 4.0}},
                               "codebase_avg_comment_ratio": 0.15}
        d = _serialize_context(ctx)
        assert d["naming_vocabulary"] == ctx.naming_vocabulary
        assert d["error_conventions"] == ctx.error_conventions
        assert d["ai_debt_signals"] == ctx.ai_debt_signals
