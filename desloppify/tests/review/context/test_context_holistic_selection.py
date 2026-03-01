"""Focused unit tests for context_holistic.selection helpers."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.intelligence.review.context_holistic import selection as selection_mod


def test_select_holistic_files_prefers_explicit_files(tmp_path):
    lang = SimpleNamespace(file_finder=lambda _path: ["ignored.py"])
    explicit = ["alpha.py", "beta.py"]

    selected = selection_mod.select_holistic_files(tmp_path, lang, explicit)

    assert selected == explicit


def test_select_holistic_files_uses_lang_file_finder(tmp_path):
    seen: dict[str, object] = {}

    def _finder(path):
        seen["path"] = path
        return ["picked.py"]

    lang = SimpleNamespace(file_finder=_finder)

    selected = selection_mod.select_holistic_files(tmp_path, lang, None)

    assert selected == ["picked.py"]
    assert seen["path"] == tmp_path


def test_select_holistic_files_skips_excluded_zones(tmp_path):
    class _ZoneMap:
        def __init__(self, zone_by_file):
            self._zone_by_file = zone_by_file

        def get(self, filepath):
            return SimpleNamespace(value=self._zone_by_file.get(filepath, "production"))

    files = ["prod.py", "vendor.py", "test_file.py", "script.py"]
    zone_map = _ZoneMap(
        {
            "prod.py": "production",
            "vendor.py": "vendor",
            "test_file.py": "test",
            "script.py": "script",
        }
    )
    lang = SimpleNamespace(file_finder=lambda _path: files, zone_map=zone_map)

    selected = selection_mod.select_holistic_files(tmp_path, lang, None)

    assert selected == ["prod.py", "script.py"]


def test_sibling_behavior_context_reports_shared_pattern_outlier(tmp_path):
    svc_dir = tmp_path / "service"
    files = {
        str(svc_dir / "alpha.py"): "import shared_one\nimport shared_two\n",
        str(svc_dir / "beta.py"): "import shared_one\nimport shared_two\n",
        str(svc_dir / "gamma.py"): "import shared_two\n",
    }

    context = selection_mod._sibling_behavior_context(files, base_path=tmp_path)

    svc = context["service/"]
    assert "shared_one" in svc["shared_patterns"]
    assert svc["shared_patterns"]["shared_one"]["count"] == 2
    assert svc["shared_patterns"]["shared_one"]["total"] == 3
    assert svc["outliers"][0]["file"] == "service/gamma.py"
    assert "shared_one" in svc["outliers"][0]["missing"]


def test_testing_context_includes_high_importer_untested_file(tmp_path):
    target = tmp_path / "pkg" / "module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return 1\n")

    lang = SimpleNamespace(
        dep_graph={
            str(target.resolve()): {
                "importers": {"consumer_a.py", "consumer_b.py", "consumer_c.py"}
            }
        }
    )
    state = {
        "findings": {
            "tc-1": {
                "detector": "test_coverage",
                "status": "open",
                "file": str(target),
            }
        }
    }
    file_contents = {str(target): target.read_text()}

    context = selection_mod._testing_context(lang, state, file_contents)

    assert context["total_files"] == 1
    assert context["critical_untested"] == [{"file": str(target), "importers": 3}]


# ── _coupling_context ─────────────────────────────────────


def test_coupling_context_detects_module_level_io(tmp_path):
    """Module-level IO calls outside def/class blocks are detected."""
    f = tmp_path / "pkg" / "startup.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    content = "conn = connect('postgresql://...')\nresult = requests.get(url)\n"
    f.write_text(content)

    context = selection_mod._coupling_context({str(f): content})

    assert "module_level_io" in context
    io_entries = context["module_level_io"]
    assert len(io_entries) == 2
    assert any("connect" in entry["code"] for entry in io_entries)
    assert any("requests" in entry["code"] for entry in io_entries)


def test_coupling_context_ignores_io_inside_def_or_class(tmp_path):
    """IO calls on lines starting with def/class/import are skipped."""
    f = tmp_path / "pkg" / "service.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    content = "def connect():\n    pass\nimport subprocess\nclass Manager:\n    pass\n"
    f.write_text(content)

    context = selection_mod._coupling_context({str(f): content})

    assert context == {}


def test_coupling_context_empty_when_no_io_detected():
    context = selection_mod._coupling_context({"a.py": "x = 1\ny = 2\n"})
    assert context == {}


def test_coupling_context_limits_to_first_50_lines(tmp_path):
    """Module-level IO scanning only looks at first 50 lines."""
    f = tmp_path / "pkg" / "big.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    safe_lines = ["x = 1\n"] * 50
    io_line = "conn = open('/etc/hosts')\n"
    content = "".join(safe_lines) + io_line
    f.write_text(content)

    context = selection_mod._coupling_context({str(f): content})

    # The open() call is on line 51 — beyond the 50-line scan window
    assert context == {}


# ── _naming_conventions_context ───────────────────────────


def test_naming_conventions_detects_snake_case_and_camel_case(tmp_path):
    d = tmp_path / "pkg"
    d.mkdir()
    files = {
        str(d / "a.py"): "def get_user():\n    pass\ndef save_user():\n    pass\ndef handle_event():\n    pass\n",
        str(d / "b.ts"): "function getUser() {}\nfunction saveUser() {}\nfunction handleEvent() {}\n",
    }

    context = selection_mod._naming_conventions_context(files)

    assert "pkg/" in context
    assert "snake_case" in context["pkg/"]
    assert "camelCase" in context["pkg/"]


def test_naming_conventions_skips_dirs_with_few_functions(tmp_path):
    """Directories with fewer than 3 total functions are excluded."""
    d = tmp_path / "tiny"
    d.mkdir()
    files = {
        str(d / "a.py"): "def one():\n    pass\n",
        str(d / "b.py"): "def two():\n    pass\n",
    }

    context = selection_mod._naming_conventions_context(files)

    assert "tiny/" not in context


def test_naming_conventions_detects_pascal_case(tmp_path):
    """_naming_conventions_context uses FUNC_NAME_RE which matches function names.
    PascalCase function names (e.g. React components) are detected."""
    d = tmp_path / "components"
    d.mkdir()
    files = {
        str(d / "a.tsx"): "function UserCard() {}\nfunction OrderList() {}\nfunction ProductView() {}\n",
    }

    context = selection_mod._naming_conventions_context(files)

    assert "components/" in context
    assert "PascalCase" in context["components/"]


# ── _error_strategy_context ───────────────────────────────


def test_error_strategy_detects_try_catch_and_throws(tmp_path):
    d = tmp_path / "handlers"
    d.mkdir()
    content = (
        "try {\n"
        "    doSomething();\n"
        "} catch (err) {\n"
        "    throw new Error('fail');\n"
        "}\n"
    )
    files = {str(d / "a.ts"): content}

    context = selection_mod._error_strategy_context(files)

    assert "handlers/" in context
    assert "try_catch" in context["handlers/"]
    assert "throws" in context["handlers/"]


def test_error_strategy_skips_dirs_below_threshold(tmp_path):
    """Directories with < 2 total error pattern matches are excluded."""
    d = tmp_path / "clean"
    d.mkdir()
    files = {str(d / "a.py"): "return None\n"}

    context = selection_mod._error_strategy_context(files)

    # returns_null counts as 1 match, but threshold is 2
    assert "clean/" not in context


def test_error_strategy_empty_input():
    assert selection_mod._error_strategy_context({}) == {}


# ── _dependencies_context ─────────────────────────────────


def test_dependencies_context_extracts_open_cycles():
    state = {
        "findings": {
            "cyc-1": {
                "detector": "cycles",
                "status": "open",
                "summary": "A -> B -> C -> A forms a cycle in the module graph",
            },
            "cyc-2": {
                "detector": "cycles",
                "status": "fixed",
                "summary": "D -> E -> D old cycle (resolved)",
            },
        }
    }

    context = selection_mod._dependencies_context(state)

    assert context["existing_cycles"] == 1
    assert len(context["cycle_summaries"]) == 1
    assert "A -> B -> C" in context["cycle_summaries"][0]


def test_dependencies_context_empty_when_no_cycles():
    state = {"findings": {"f1": {"detector": "smells", "status": "open", "summary": "x"}}}
    assert selection_mod._dependencies_context(state) == {}


def test_dependencies_context_empty_state():
    assert selection_mod._dependencies_context({}) == {}


# ── _api_surface_context ──────────────────────────────────


def test_api_surface_context_calls_lang_hook():
    expected = {"public_exports": 5, "internal_modules": 3}
    lang = SimpleNamespace(review_api_surface_fn=lambda _contents: expected)

    result = selection_mod._api_surface_context(lang, {"a.py": "code"})

    assert result == expected


def test_api_surface_context_returns_empty_when_hook_missing():
    lang = SimpleNamespace()  # no review_api_surface_fn attribute

    result = selection_mod._api_surface_context(lang, {"a.py": "code"})

    assert result == {}


def test_api_surface_context_returns_empty_when_hook_not_callable():
    lang = SimpleNamespace(review_api_surface_fn="not a function")

    result = selection_mod._api_surface_context(lang, {"a.py": "code"})

    assert result == {}


def test_api_surface_context_returns_empty_when_hook_returns_non_dict():
    lang = SimpleNamespace(review_api_surface_fn=lambda _contents: [1, 2, 3])

    result = selection_mod._api_surface_context(lang, {"a.py": "code"})

    assert result == {}


# ── _sibling_behavior_context edge cases ──────────────────


def test_sibling_behavior_context_empty_when_no_shared_patterns(tmp_path):
    """When no import is shared by 60%+ of files, no outliers reported."""
    d = tmp_path / "pkg"
    d.mkdir()
    files = {
        str(d / "a.py"): "import alpha\n",
        str(d / "b.py"): "import beta\n",
        str(d / "c.py"): "import gamma\n",
    }

    context = selection_mod._sibling_behavior_context(files, base_path=tmp_path)

    assert context == {}


def test_sibling_behavior_context_no_outliers_when_all_share_everything(tmp_path):
    """When all files import the same names, no outliers exist -> dir excluded."""
    d = tmp_path / "pkg"
    d.mkdir()
    common = "import shared_one\nimport shared_two\n"
    files = {
        str(d / "a.py"): common,
        str(d / "b.py"): common,
        str(d / "c.py"): common,
    }

    context = selection_mod._sibling_behavior_context(files, base_path=tmp_path)

    assert context == {}


def test_sibling_behavior_context_skips_dirs_with_fewer_than_3_files(tmp_path):
    d = tmp_path / "tiny"
    d.mkdir()
    files = {
        str(d / "a.py"): "import x\n",
        str(d / "b.py"): "import y\n",
    }

    context = selection_mod._sibling_behavior_context(files, base_path=tmp_path)

    assert context == {}


# ── _testing_context edge cases ───────────────────────────


def test_testing_context_no_dep_graph():
    lang = SimpleNamespace(dep_graph=None)
    state = {"findings": {}}
    result = selection_mod._testing_context(lang, state, {"a.py": "code"})
    assert result == {"total_files": 1}


def test_testing_context_no_test_coverage_findings():
    lang = SimpleNamespace(dep_graph={"a.py": {"importers": {"b.py"}}})
    state = {"findings": {"f1": {"detector": "smells", "status": "open"}}}
    result = selection_mod._testing_context(lang, state, {"a.py": "code"})
    assert result == {"total_files": 1}
