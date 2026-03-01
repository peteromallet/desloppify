"""Focused unit tests for context_holistic.budget helpers."""

from __future__ import annotations

import ast

from desloppify.intelligence.review.context_holistic import budget as budget_mod


def _parse(content: str) -> ast.Module:
    """Convenience: parse Python source into an AST module."""
    return ast.parse(content)


def test_count_signature_params_ignores_instance_receiver_tokens():
    assert budget_mod._count_signature_params("self, a, b, cls, this, c") == 3
    assert budget_mod._count_signature_params("   ") == 0


def test_extract_type_names_handles_generics_and_qualified_names():
    raw = "IRepo, pkg.Service<T>, (BaseProtocol), invalid-token"
    names = budget_mod._extract_type_names(raw)
    assert names == ["IRepo", "Service", "BaseProtocol"]


def test_abstractions_context_reports_wrapper_and_indirection_signals(tmp_path):
    util_file = tmp_path / "pkg" / "utils.py"
    contracts_file = tmp_path / "pkg" / "contracts.ts"
    service_file = tmp_path / "pkg" / "service.py"

    util_content = (
        "def wrap_user(value):\n"
        "    return make_user(value)\n\n"
        "def make_user(value):\n"
        "    return value\n"
    )
    contracts_content = "interface Repo {}\nclass SqlRepo implements Repo {}\n"
    service_content = (
        "def build(a, b, c, d, e, f, g):\n"
        "    return a\n\n"
        "value = root.one.two.three.four\n"
        "config config config config config config config config config config\n"
    )

    util_file.parent.mkdir(parents=True, exist_ok=True)
    util_file.write_text(util_content)
    contracts_file.write_text(contracts_content)
    service_file.write_text(service_content)

    file_contents = {
        str(util_file): util_content,
        str(contracts_file): contracts_content,
        str(service_file): service_content,
    }

    context = budget_mod._abstractions_context(file_contents)

    assert context["summary"]["total_wrappers"] >= 1
    assert context["summary"]["one_impl_interface_count"] == 1
    assert context["util_files"][0]["file"].endswith("utils.py")
    assert "pass_through_wrappers" in context
    assert "indirection_hotspots" in context
    assert "wide_param_bags" in context
    assert 0 <= context["sub_axes"]["abstraction_leverage"] <= 100
    assert 0 <= context["sub_axes"]["indirection_cost"] <= 100
    assert 0 <= context["sub_axes"]["interface_honesty"] <= 100


def test_codebase_stats_counts_files_and_loc():
    stats = budget_mod._codebase_stats({"a.py": "x\n", "b.py": "one\ntwo\nthree\n"})
    assert stats == {"total_files": 2, "total_loc": 4}


# ── _score_clamped ────────────────────────────────────────


def test_score_clamped_typical_value():
    assert budget_mod._score_clamped(75.3) == 75


def test_score_clamped_rounds_half_up():
    assert budget_mod._score_clamped(50.5) == 50  # Python banker's rounding


def test_score_clamped_clamps_below_zero():
    assert budget_mod._score_clamped(-15.0) == 0


def test_score_clamped_clamps_above_100():
    assert budget_mod._score_clamped(200.0) == 100


def test_score_clamped_zero_and_100_boundaries():
    assert budget_mod._score_clamped(0.0) == 0
    assert budget_mod._score_clamped(100.0) == 100


# ── _count_signature_params edge cases ────────────────────


def test_count_signature_params_empty_string():
    assert budget_mod._count_signature_params("") == 0


def test_count_signature_params_only_receivers():
    assert budget_mod._count_signature_params("self") == 0
    assert budget_mod._count_signature_params("cls") == 0
    assert budget_mod._count_signature_params("this") == 0
    assert budget_mod._count_signature_params("self, cls") == 0


def test_count_signature_params_with_type_annotations():
    assert budget_mod._count_signature_params("a: int, b: str, c: float") == 3


def test_count_signature_params_with_defaults():
    assert budget_mod._count_signature_params("a=1, b=None") == 2


def test_count_signature_params_trailing_comma():
    # trailing comma produces empty split elements that get filtered
    assert budget_mod._count_signature_params("a, b,") == 2


# ── _extract_type_names edge cases ────────────────────────


def test_extract_type_names_empty_string():
    assert budget_mod._extract_type_names("") == []


def test_extract_type_names_single_name():
    assert budget_mod._extract_type_names("Foo") == ["Foo"]


def test_extract_type_names_strips_colon_suffix():
    assert budget_mod._extract_type_names("Foo:") == ["Foo"]


def test_extract_type_names_rejects_non_identifiers():
    assert budget_mod._extract_type_names("123, -, !@#") == []


# ── _abstractions_context scoring edge cases ──────────────


def test_abstractions_context_empty_input():
    """Empty file dict produces zero-count summary."""
    context = budget_mod._abstractions_context({})
    assert context["summary"]["total_wrappers"] == 0
    assert context["summary"]["total_function_signatures"] == 0
    assert context["summary"]["one_impl_interface_count"] == 0
    assert context["sub_axes"]["abstraction_leverage"] == 100
    assert context["sub_axes"]["indirection_cost"] == 100
    assert context["sub_axes"]["interface_honesty"] == 100
    assert context["util_files"] == []
    assert "pass_through_wrappers" not in context
    assert "one_impl_interfaces" not in context


def test_abstractions_context_interface_with_multiple_impls_not_reported(tmp_path):
    """Interfaces with 2+ implementations should not appear in one_impl_interfaces."""
    f1 = tmp_path / "pkg" / "contract.ts"
    f1.parent.mkdir(parents=True, exist_ok=True)
    f1.write_text("interface IRepo {}\n")

    f2 = tmp_path / "pkg" / "sql.ts"
    f2.write_text("class SqlRepo implements IRepo {}\n")

    f3 = tmp_path / "pkg" / "mongo.ts"
    f3.write_text("class MongoRepo implements IRepo {}\n")

    file_contents = {
        str(f1): f1.read_text(),
        str(f2): f2.read_text(),
        str(f3): f3.read_text(),
    }

    context = budget_mod._abstractions_context(file_contents)
    assert context["summary"]["one_impl_interface_count"] == 0
    assert "one_impl_interfaces" not in context


def test_abstractions_context_python_protocol_detected(tmp_path):
    """Python Protocol classes are detected as interface declarations."""
    f = tmp_path / "pkg" / "types.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class HandlerProtocol:\n    pass\n")

    context = budget_mod._abstractions_context({str(f): f.read_text()})
    # Protocol declared but 0 implementations -> one_impl_interface_count stays 0
    # (it needs exactly 1 impl to be counted)
    assert context["summary"]["one_impl_interface_count"] == 0


def test_abstractions_context_wrapper_rate_calculation(tmp_path):
    """Verify wrapper rate = total_wrappers / total_function_signatures."""
    f = tmp_path / "pkg" / "mod.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "def alpha(x):\n"
        "    return beta(x)\n\n"
        "def beta(x):\n"
        "    return x\n\n"
        "def gamma(x):\n"
        "    return x * 2\n"
    )
    f.write_text(content)

    context = budget_mod._abstractions_context({str(f): content})
    summary = context["summary"]
    assert summary["total_wrappers"] == 1  # alpha -> beta
    assert summary["total_function_signatures"] == 3
    assert summary["wrapper_rate"] == round(1 / 3, 3)


def test_find_python_passthrough_wrappers_handles_docstring_only_wrapper():
    content = (
        "def wrap(x):\n"
        '    \"\"\"Thin wrapper.\"\"\"\n'
        "    return build(x)\n"
    )
    assert budget_mod._find_python_passthrough_wrappers(_parse(content)) == [
        ("wrap", "build")
    ]


def test_find_python_passthrough_wrappers_handles_large_comment_runs_without_hanging():
    comments = "\n".join("    # comment" for _ in range(1500))
    content = (
        "def wrap(x):\n"
        f"{comments}\n"
        "    value = build(x)\n"
    )
    assert budget_mod._find_python_passthrough_wrappers(_parse(content)) == []


# ── Delegation-heavy classes ──────────────────────────────


def test_delegation_heavy_class_detected():
    """A class with 5/6 forwarding methods is flagged with full evidence."""
    content = (
        "class Proxy:\n"
        "    def __init__(self, inner):\n"
        "        self._inner = inner\n"
        "    def alpha(self):\n"
        "        return self._inner.alpha()\n"
        "    def beta(self, x):\n"
        "        return self._inner.beta(x)\n"
        "    def gamma(self):\n"
        "        return self._inner.gamma()\n"
        "    def delta(self):\n"
        "        return self._inner.delta()\n"
        "    def epsilon(self):\n"
        "        return self._inner.epsilon()\n"
        "    def real_work(self):\n"
        "        return 42\n"
    )
    results = budget_mod._find_delegation_heavy_classes(_parse(content))
    assert len(results) == 1
    r = results[0]
    assert r["class_name"] == "Proxy"
    assert r["delegation_ratio"] == round(5 / 6, 2)
    assert r["method_count"] == 6
    assert r["delegate_count"] == 5
    assert r["delegate_target"] == "_inner"
    assert set(r["sample_methods"]) == {"alpha", "beta", "gamma", "delta", "epsilon"}
    assert r["line"] == 1


def test_delegation_heavy_class_not_flagged_below_threshold():
    """A class with 2/5 forwarding methods is NOT flagged (ratio 0.4 < 0.5)."""
    content = (
        "class Mixed:\n"
        "    def __init__(self, dep):\n"
        "        self._dep = dep\n"
        "    def a(self):\n"
        "        return self._dep.a()\n"
        "    def b(self):\n"
        "        return self._dep.b()\n"
        "    def c(self):\n"
        "        return 1\n"
        "    def d(self):\n"
        "        return 2\n"
        "    def e(self):\n"
        "        return 3\n"
    )
    results = budget_mod._find_delegation_heavy_classes(_parse(content))
    assert len(results) == 0


def test_delegation_heavy_class_skips_small_classes():
    """Classes with <= 3 non-init methods are skipped."""
    content = (
        "class Small:\n"
        "    def __init__(self, dep):\n"
        "        self._dep = dep\n"
        "    def a(self):\n"
        "        return self._dep.a()\n"
        "    def b(self):\n"
        "        return self._dep.b()\n"
    )
    results = budget_mod._find_delegation_heavy_classes(_parse(content))
    assert len(results) == 0


# ── Facade modules ────────────────────────────────────────


def test_facade_module_detected():
    """A module with only imports and __all__ is detected as a facade with samples."""
    content = (
        "from ._internal import Alpha, Beta, Gamma, Delta\n"
        "from ._other import Epsilon\n"
        "\n"
        "__all__ = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon']\n"
    )
    result = budget_mod._find_facade_modules(_parse(content), loc=4)
    assert result is not None
    assert result["re_export_ratio"] >= 0.7
    assert result["defined_symbols"] == 0
    assert result["re_exported_symbols"] == 5
    assert result["loc"] == 4
    assert set(result["samples"]) == {"Alpha", "Beta", "Gamma", "Delta", "Epsilon"}


def test_facade_module_not_flagged_with_definitions():
    """A module that defines its own functions isn't a facade."""
    content = (
        "from ._internal import helper\n"
        "\n"
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 2\n"
        "\n"
        "def gamma():\n"
        "    return 3\n"
        "\n"
        "def delta():\n"
        "    return 4\n"
    )
    result = budget_mod._find_facade_modules(_parse(content), loc=13)
    assert result is None


def test_facade_module_not_flagged_with_few_names():
    """A module with <3 total public names is not flagged."""
    content = "from ._internal import Alpha\n"
    result = budget_mod._find_facade_modules(_parse(content), loc=1)
    assert result is None


# ── TypedDict violations ──────────────────────────────────


def test_typed_dict_get_violation_detected():
    """TypedDict with Required fields accessed via .get() is flagged with line and field."""
    decl_content = (
        "from typing import TypedDict\n"
        "\n"
        "class Config(TypedDict):\n"
        "    name: str\n"
        "    value: int\n"
    )
    usage_content = (
        "from .types import Config\n"
        "\n"
        "def process(cfg: Config) -> str:\n"
        "    return cfg.get('name', '')\n"
    )
    defs: dict = {}
    budget_mod._collect_typed_dict_defs(_parse(decl_content), defs)
    assert "Config" in defs
    parsed_trees = {
        "/fake/types.py": _parse(decl_content),
        "/fake/usage.py": _parse(usage_content),
    }
    violations = budget_mod._find_typed_dict_usage_violations(parsed_trees, defs)
    assert len(violations) == 1
    v = violations[0]
    assert v["typed_dict_name"] == "Config"
    assert v["violation_type"] == "get"
    assert v["count"] == 1
    assert v["line"] == 4
    assert v["field"] == "name"


def test_typed_dict_no_violation_without_annotation():
    """Variables not annotated as TypedDict don't trigger violations."""
    decl_content = (
        "from typing import TypedDict\n"
        "\n"
        "class Config(TypedDict):\n"
        "    name: str\n"
    )
    usage_content = (
        "def process(cfg) -> str:\n"  # no annotation
        "    return cfg.get('name', '')\n"
    )
    defs: dict = {}
    budget_mod._collect_typed_dict_defs(_parse(decl_content), defs)
    parsed_trees = {
        "/fake/types.py": _parse(decl_content),
        "/fake/usage.py": _parse(usage_content),
    }
    violations = budget_mod._find_typed_dict_usage_violations(parsed_trees, defs)
    assert len(violations) == 0


def test_typed_dict_no_violations_returns_empty():
    """No TypedDict classes means no violations."""
    parsed_trees = {
        "/fake/mod.py": _parse("def foo():\n    return {}.get('x')\n"),
    }
    violations = budget_mod._find_typed_dict_usage_violations(parsed_trees, {})
    assert violations == []


# ── Economy sub-axes in _abstractions_context ─────────────


def test_abstractions_context_includes_economy_sub_axes():
    """New sub-axes appear in the context output."""
    context = budget_mod._abstractions_context({})
    sub = context["sub_axes"]
    assert "delegation_density" in sub
    assert "definition_directness" in sub
    assert "type_discipline" in sub
    assert sub["delegation_density"] == 100
    assert sub["definition_directness"] == 100
    assert sub["type_discipline"] == 100


def test_abstractions_context_economy_summary_keys():
    """New summary keys appear in the context output."""
    context = budget_mod._abstractions_context({})
    summary = context["summary"]
    assert summary["delegation_heavy_class_count"] == 0
    assert summary["facade_module_count"] == 0
    assert summary["typed_dict_violation_count"] == 0


def test_delegation_density_decreases_with_violations(tmp_path):
    """delegation_density sub-axis drops when delegation-heavy classes exist."""
    content = (
        "class Proxy:\n"
        "    def __init__(self, dep):\n"
        "        self._dep = dep\n"
        "    def a(self):\n"
        "        return self._dep.a()\n"
        "    def b(self):\n"
        "        return self._dep.b()\n"
        "    def c(self):\n"
        "        return self._dep.c()\n"
        "    def d(self):\n"
        "        return self._dep.d()\n"
        "    def e(self):\n"
        "        return self._dep.e()\n"
    )
    f = tmp_path / "proxy.py"
    f.write_text(content)
    context = budget_mod._abstractions_context({str(f): content})
    assert context["sub_axes"]["delegation_density"] < 100
    assert context["summary"]["delegation_heavy_class_count"] == 1
