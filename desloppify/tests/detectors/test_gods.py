"""Tests for desloppify.engine.detectors.gods — god class/component detection."""

from desloppify.engine.detectors.base import ClassInfo, FunctionInfo, GodRule
from desloppify.engine.detectors.gods import detect_gods


def _make_class(
    name: str,
    file: str,
    loc: int,
    metrics: dict | None = None,
    methods: list | None = None,
    attributes: list | None = None,
) -> ClassInfo:
    return ClassInfo(
        name,
        file,
        1,
        loc,
        methods or [],
        attributes or [],
        [],
        metrics or {},
    )


def _make_rules() -> list[GodRule]:
    """Standard set of god-class rules for testing."""
    return [
        GodRule(
            name="methods",
            description="methods",
            extract=lambda cls: len(cls.methods),
            threshold=10,
        ),
        GodRule(
            name="loc",
            description="LOC",
            extract=lambda cls: cls.loc,
            threshold=300,
        ),
        GodRule(
            name="attributes",
            description="attributes",
            extract=lambda cls: len(cls.attributes),
            threshold=15,
        ),
    ]


class TestDetectGods:
    def test_empty_input(self):
        entries, total = detect_gods([], _make_rules())
        assert entries == []
        assert total == 0

    def test_class_below_all_thresholds(self):
        cls = _make_class("Small", "a.py", loc=50)
        entries, total = detect_gods([cls], _make_rules())
        assert entries == []
        assert total == 1

    def test_class_violating_one_rule_not_flagged(self):
        """A class violating only one rule should not be flagged (min_reasons=2)."""
        cls = _make_class("BigLoc", "a.py", loc=500)
        entries, total = detect_gods([cls], _make_rules())
        assert entries == []

    def test_class_violating_two_rules_flagged(self):
        """A class violating two rules should be flagged."""
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        cls = _make_class("GodClass", "a.py", loc=500, methods=methods)
        entries, total = detect_gods([cls], _make_rules())
        assert len(entries) == 1
        assert entries[0]["name"] == "GodClass"
        assert len(entries[0]["reasons"]) == 2

    def test_class_violating_all_rules(self):
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(15)
        ]
        attributes = [f"attr_{i}" for i in range(20)]
        cls = _make_class(
            "MegaGod", "a.py", loc=500, methods=methods, attributes=attributes
        )
        entries, total = detect_gods([cls], _make_rules())
        assert len(entries) == 1
        assert len(entries[0]["reasons"]) == 3

    def test_custom_min_reasons(self):
        """With min_reasons=1, a single rule violation should flag."""
        cls = _make_class("BigLoc", "a.py", loc=500)
        entries, total = detect_gods([cls], _make_rules(), min_reasons=1)
        assert len(entries) == 1

    def test_custom_min_reasons_3(self):
        """With min_reasons=3, two violations should NOT flag."""
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        cls = _make_class("TwoViolations", "a.py", loc=500, methods=methods)
        entries, total = detect_gods([cls], _make_rules(), min_reasons=3)
        assert entries == []

    def test_multiple_classes_mixed(self):
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        god = _make_class("GodClass", "a.py", loc=500, methods=methods)
        normal = _make_class("NormalClass", "b.py", loc=50)
        entries, total = detect_gods([god, normal], _make_rules())
        assert len(entries) == 1
        assert entries[0]["name"] == "GodClass"
        assert total == 2

    def test_entry_structure(self):
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        cls = _make_class(
            "GodClass",
            "a.py",
            loc=500,
            metrics={"methods": 12, "loc": 500},
            methods=methods,
        )
        entries, total = detect_gods([cls], _make_rules())
        entry = entries[0]
        assert "file" in entry
        assert "name" in entry
        assert "loc" in entry
        assert "reasons" in entry
        assert "signal_text" in entry
        assert "detail" in entry
        assert isinstance(entry["reasons"], list)
        assert entry["detail"]["name"] == "GodClass"

    def test_sorted_by_loc_descending(self):
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        cls1 = _make_class("SmallGod", "a.py", loc=400, methods=methods)
        cls2 = _make_class("BigGod", "b.py", loc=800, methods=methods)
        entries, total = detect_gods([cls1, cls2], _make_rules())
        assert entries[0]["loc"] > entries[1]["loc"]

    def test_metric_based_rules(self):
        """Rules can use metrics dict for custom extraction."""
        rules = [
            GodRule(
                name="hooks",
                description="hooks",
                extract=lambda cls: cls.metrics.get("hook_count", 0),
                threshold=5,
            ),
            GodRule(
                name="effects",
                description="useEffects",
                extract=lambda cls: cls.metrics.get("use_effects", 0),
                threshold=3,
            ),
        ]
        cls = _make_class(
            "HeavyComponent",
            "App.tsx",
            loc=200,
            metrics={"hook_count": 8, "use_effects": 5},
        )
        entries, total = detect_gods([cls], rules)
        assert len(entries) == 1
        assert "hooks" in entries[0]["reasons"][0]

    def test_signal_text_format(self):
        methods = [
            FunctionInfo(
                name=f"m_{i}", file="a.py", line=i, end_line=i + 5, loc=5, body="pass"
            )
            for i in range(12)
        ]
        cls = _make_class("MyClass", "a.py", loc=500, methods=methods)
        entries, total = detect_gods([cls], _make_rules())
        assert "MyClass" in entries[0]["signal_text"]
