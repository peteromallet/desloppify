"""Tests for desloppify.engine.detectors.base — dataclass construction and field access."""

from desloppify.engine.detectors.base import (
    ClassInfo,
    ComplexitySignal,
    FunctionInfo,
    GodRule,
)

# ── FunctionInfo ─────────────────────────────────────────────


def test_function_info_required_fields():
    """FunctionInfo populates required fields correctly."""
    fi = FunctionInfo(
        name="foo", file="bar.py", line=1, end_line=10, loc=10, body="pass"
    )
    assert fi.name == "foo"
    assert fi.file == "bar.py"
    assert fi.line == 1
    assert fi.end_line == 10
    assert fi.loc == 10
    assert fi.body == "pass"


def test_function_info_defaults():
    """FunctionInfo optional fields have correct defaults."""
    fi = FunctionInfo(name="f", file="x.py", line=1, end_line=2, loc=2, body="")
    assert fi.normalized == ""
    assert fi.body_hash == ""
    assert fi.params == []


def test_function_info_params():
    """FunctionInfo params field is populated when supplied."""
    fi = FunctionInfo(
        name="f",
        file="x.py",
        line=1,
        end_line=5,
        loc=5,
        body="pass",
        params=["a", "b", "c"],
    )
    assert fi.params == ["a", "b", "c"]


def test_function_info_params_isolation():
    """FunctionInfo default list is not shared across instances."""
    fi1 = FunctionInfo(name="a", file="a.py", line=1, end_line=2, loc=1, body="")
    fi2 = FunctionInfo(name="b", file="b.py", line=1, end_line=2, loc=1, body="")
    fi1.params.append("x")
    assert fi2.params == []


# ── ClassInfo ────────────────────────────────────────────────


def test_class_info_required_fields():
    """ClassInfo populates required fields correctly."""
    ci = ClassInfo(name="Foo", file="bar.py", line=1, loc=100)
    assert ci.name == "Foo"
    assert ci.file == "bar.py"
    assert ci.line == 1
    assert ci.loc == 100


def test_class_info_defaults():
    """ClassInfo optional fields have correct defaults."""
    ci = ClassInfo(name="Foo", file="bar.py", line=1, loc=100)
    assert ci.methods == []
    assert ci.attributes == []
    assert ci.base_classes == []
    assert ci.metrics == {}


def test_class_info_with_methods():
    """ClassInfo holds FunctionInfo objects in methods."""
    fn = FunctionInfo(
        name="do_it", file="bar.py", line=5, end_line=10, loc=5, body="pass"
    )
    ci = ClassInfo(name="Foo", file="bar.py", line=1, loc=100, methods=[fn])
    assert len(ci.methods) == 1
    assert ci.methods[0].name == "do_it"


def test_class_info_metrics():
    """ClassInfo metrics dict holds hook counts etc."""
    ci = ClassInfo(
        name="App",
        file="app.tsx",
        line=1,
        loc=200,
        metrics={"context_hooks": 3, "use_effects": 5},
    )
    assert ci.metrics["context_hooks"] == 3
    assert ci.metrics["use_effects"] == 5


def test_class_info_list_isolation():
    """ClassInfo default lists are not shared across instances."""
    c1 = ClassInfo(name="A", file="a.py", line=1, loc=10)
    c2 = ClassInfo(name="B", file="b.py", line=1, loc=10)
    c1.methods.append("x")
    c1.attributes.append("y")
    c1.base_classes.append("z")
    assert c2.methods == []
    assert c2.attributes == []
    assert c2.base_classes == []


# ── ComplexitySignal ─────────────────────────────────────────


def test_complexity_signal_pattern_based():
    """ComplexitySignal with a regex pattern."""
    cs = ComplexitySignal(
        name="nested_if", pattern=r"if\s+.*if\s+", weight=2, threshold=3
    )
    assert cs.name == "nested_if"
    assert cs.pattern == r"if\s+.*if\s+"
    assert cs.weight == 2
    assert cs.threshold == 3
    assert cs.compute is None


def test_complexity_signal_compute_based():
    """ComplexitySignal with a compute function."""

    def my_compute(content, lines):
        return (5, "5 deep nesting")

    cs = ComplexitySignal(name="nesting", compute=my_compute)
    assert cs.name == "nesting"
    assert cs.pattern is None
    assert cs.weight == 1
    assert cs.threshold == 0
    assert cs.compute is my_compute
    assert cs.compute("", []) == (5, "5 deep nesting")


def test_complexity_signal_defaults():
    """ComplexitySignal defaults: weight=1, threshold=0, no compute."""
    cs = ComplexitySignal(name="foo")
    assert cs.weight == 1
    assert cs.threshold == 0
    assert cs.pattern is None
    assert cs.compute is None


# ── GodRule ──────────────────────────────────────────────────


def test_god_rule_construction():
    """GodRule stores name, description, extract, threshold."""

    def extract_fn(ci):
        return ci.loc

    gr = GodRule(
        name="too_big",
        description="Class is too large",
        extract=extract_fn,
        threshold=500,
    )
    assert gr.name == "too_big"
    assert gr.description == "Class is too large"
    assert gr.threshold == 500
    assert gr.extract is extract_fn


def test_god_rule_extract_callable():
    """GodRule extract callable works on ClassInfo."""
    ci = ClassInfo(
        name="God",
        file="g.py",
        line=1,
        loc=1000,
        methods=[
            FunctionInfo(name="m", file="g.py", line=2, end_line=3, loc=1, body="")
        ]
        * 50,
    )
    gr = GodRule(
        name="methods",
        description="Too many methods",
        extract=lambda c: len(c.methods),
        threshold=20,
    )
    assert gr.extract(ci) == 50
    assert gr.extract(ci) >= gr.threshold
