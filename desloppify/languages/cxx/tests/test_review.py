from __future__ import annotations

import os
import time

import desloppify.languages.cxx.review as cxx_review_mod


def test_cxx_module_patterns_and_api_surface():
    content = """
namespace app::core {
class Widget {
public:
    void Run();
};

int BuildWidget();
}
"""
    patterns = cxx_review_mod.module_patterns(content)
    assert "namespace" in patterns
    assert "public_types" in patterns
    assert "public_methods" in patterns

    surface = cxx_review_mod.api_surface({os.path.abspath("widget.hpp"): content})
    assert surface["public_types"] == ["Widget"]
    assert "BuildWidget" in surface["public_functions"]
    assert "Run" in surface["public_functions"]


def test_api_surface_ignores_cpp_implementation_symbols():
    header = """
namespace app::core {
class Widget {
public:
    void Run();
};

int BuildWidget();
}
"""
    impl = """
namespace app::core {
class InternalOnly {};
static int helper() { return 1; }
}
"""

    surface = cxx_review_mod.api_surface(
        {
            os.path.abspath("widget.hpp"): header,
            os.path.abspath("widget.cpp"): impl,
        }
    )

    assert surface["public_types"] == ["Widget"]
    assert surface["public_functions"] == ["BuildWidget", "Run"]


def test_function_detection_bounds_qualified_name_backtracking():
    content = "::".join(["Type"] * 21) + " value = source;"

    started = time.perf_counter()
    patterns = cxx_review_mod.module_patterns(content)
    elapsed = time.perf_counter() - started

    assert patterns == []
    assert elapsed < 0.25
