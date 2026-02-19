"""Focused unit tests for context_holistic.budget helpers."""

from __future__ import annotations

from desloppify.intelligence.review.context_holistic import budget as budget_mod


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

