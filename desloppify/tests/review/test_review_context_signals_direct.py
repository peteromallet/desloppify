"""Direct tests for review context heuristic signal helpers."""

from __future__ import annotations

import re
from types import SimpleNamespace

import desloppify.intelligence.review.context_signals.ai as signal_ai_mod
import desloppify.intelligence.review.context_signals.auth as signal_auth_mod
import desloppify.intelligence.review.context_signals.migration as signal_migration_mod


def test_gather_ai_debt_signals_collects_comment_log_and_guard_signals():
    file_contents = {
        "a.py": (
            "# c1\n# c2\n# c3\n# c4\n"
            "def f():\n"
            "    logging.error('x')\n    logging.error('y')\n"
            "    logging.error('z')\n    logging.error('w')\n"
            "    try:\n        pass\n    except Exception:\n        pass\n"
            "    try:\n        pass\n    except Exception:\n        pass\n"
            "    try:\n        pass\n    except Exception:\n        pass\n"
        ),
        "b.py": "def ok():\n    return 1\n",
    }
    result = signal_ai_mod.gather_ai_debt_signals(file_contents, rel_fn=lambda p: p)
    assert "a.py" in result["file_signals"]
    signals = result["file_signals"]["a.py"]
    assert "log_density" in signals
    assert result["codebase_avg_comment_ratio"] > 0


def test_gather_auth_context_collects_route_rls_and_service_role():
    file_contents = {
        "api.py": ("@app.get('/x')\ndef route():\n    request.user\n    return 1\n"),
        "schema.sql": (
            "CREATE TABLE accounts(id int);\n"
            "ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;\n"
        ),
        "client.ts": "const k = service_role; createClient(url, key)",
    }
    result = signal_auth_mod.gather_auth_context(file_contents, rel_fn=lambda p: p)
    assert "route_auth_coverage" in result
    assert result["route_auth_coverage"]["api.py"]["handlers"] == 1
    assert result["route_auth_coverage"]["api.py"]["with_auth"] == 0
    assert result["route_auth_coverage"]["api.py"]["without_auth"] == 1
    assert "rls_coverage" in result
    assert result["rls_coverage"]["with_rls"] == ["accounts"]
    assert result["service_role_usage"] == ["client.ts"]
    assert result["auth_patterns"]["api.py"] >= 1
    assert "auth_guard_patterns" not in result
    assert result["auth_usage_patterns"]["api.py"] >= 1


def test_gather_auth_context_excludes_server_only_service_role_paths():
    file_contents = {
        "functions/worker.ts": "const k = service_role; createClient(url, k)",
    }
    result = signal_auth_mod.gather_auth_context(file_contents, rel_fn=lambda p: p)
    assert "service_role_usage" not in result


def test_gather_migration_signals_and_classify_error_strategy():
    file_contents = {
        "old.ts": "@deprecated\nTODO migrate legacy handler\nfoo.oldApi()\n",
        "new.ts": "foo.newApi()\n",
        "dual.ts": "const x = 1\n",
        "dual.js": "const y = 1\n",
    }
    lang_cfg = SimpleNamespace(
        migration_mixed_extensions={".ts", ".js"},
        migration_pattern_pairs=[
            ("api_shift", re.compile(r"oldApi"), re.compile(r"newApi")),
        ],
    )

    result = signal_migration_mod.gather_migration_signals(
        file_contents,
        lang_cfg,
        rel_fn=lambda p: p,
    )
    assert result["deprecated_markers"]["total"] >= 1
    assert result["migration_todos"]
    assert result["pattern_pairs"][0]["name"] == "api_shift"
    assert "dual" in result["mixed_extensions"]

    assert (
        signal_migration_mod.classify_error_strategy(
            "raise ValueError('x')\nraise RuntimeError('y')"
        )
        == "throw"
    )
    assert (
        signal_migration_mod.classify_error_strategy("return None\nreturn null\n")
        == "return_null"
    )
    assert (
        signal_migration_mod.classify_error_strategy(
            "try:\n    pass\nexcept Exception:\n    raise\n"
        )
        == "try_catch"
    )
    assert (
        signal_migration_mod.classify_error_strategy("raise X\nreturn None\n")
        == "mixed"
    )
