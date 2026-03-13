"""Direct coverage for grouped tree-sitter analysis modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.languages._framework.treesitter.analysis.complexity_function_metrics as function_metrics_mod
import desloppify.languages._framework.treesitter.analysis.complexity_nesting as nesting_mod
import desloppify.languages._framework.treesitter.analysis.extractors as extractors_mod
import desloppify.languages._framework.treesitter.analysis.smells as smells_mod
import desloppify.languages._framework.treesitter.analysis.unused_imports as unused_imports_mod


class FakeNode:
    def __init__(
        self,
        type_: str,
        *,
        text: str = "",
        children: list["FakeNode"] | None = None,
        start_point: tuple[int, int] = (0, 0),
        end_point: tuple[int, int] = (0, 0),
        start_byte: int = 0,
        end_byte: int = 0,
    ) -> None:
        self.type = type_
        self.text = text.encode("utf-8")
        self.children = children or []
        self.child_count = len(self.children)
        self.start_point = start_point
        self.end_point = end_point
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.parent: FakeNode | None = None
        for child in self.children:
            child.parent = self


def test_complexity_function_metrics_helpers(monkeypatch) -> None:
    binary = FakeNode(
        "binary_expression",
        children=[FakeNode("identifier", text="a"), FakeNode("&&", text="&&")],
    )
    root = FakeNode("function_definition", children=[FakeNode("if_statement"), binary])
    assert function_metrics_mod._count_decisions(root) == 2

    spec = SimpleNamespace(grammar="python")
    def fake_ensure_parser(cache, _spec, *, with_query=False):
        cache["parser"] = "parser"
        if with_query:
            cache["query"] = "query"
        return True

    monkeypatch.setattr(function_metrics_mod, "_ensure_parser", fake_ensure_parser)
    monkeypatch.setattr(
        function_metrics_mod,
        "get_or_parse_tree",
        lambda *_a, **_k: (b"source", SimpleNamespace(root_node=FakeNode("root"))),
    )
    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.analysis.extractors._run_query",
        lambda *_a, **_k: [(0, {"func": FakeNode("func", children=[FakeNode("parameters", children=[FakeNode("identifier", text="self"), FakeNode("identifier", text="value")])])})],
    )
    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.analysis.extractors._unwrap_node",
        lambda node: node,
    )
    compute = function_metrics_mod.make_max_params_compute(spec)
    assert compute("", [], _filepath="src/app.py") == (1, "1 params")


def test_complexity_nesting_helpers(monkeypatch) -> None:
    root = FakeNode(
        "root",
        children=[
            FakeNode(
                "if_statement",
                children=[FakeNode("while_statement", children=[FakeNode("identifier")])],
            )
        ],
    )
    monkeypatch.setattr(
        nesting_mod,
        "get_or_parse_tree",
        lambda *_a, **_k: (b"source", SimpleNamespace(root_node=root)),
    )
    assert nesting_mod.compute_nesting_depth_ts("src/app.py", SimpleNamespace(grammar="py"), None, None) == 2

    def fake_ensure_parser(cache, _spec, with_query=False):  # noqa: ARG001
        cache["parser"] = "parser"
        cache["language"] = "language"
        return True

    monkeypatch.setattr(nesting_mod, "_ensure_parser", fake_ensure_parser)
    monkeypatch.setattr(nesting_mod, "compute_nesting_depth_ts", lambda *_a, **_k: 3)
    compute = nesting_mod.make_nesting_depth_compute(SimpleNamespace(grammar="py"))
    assert compute("", [], _filepath="src/app.py") == (3, "nesting depth 3")


def test_extractors_helpers_cover_params_and_exports(monkeypatch) -> None:
    params = FakeNode(
        "parameters",
        children=[
            FakeNode("identifier", text="self"),
            FakeNode("identifier", text="value"),
            FakeNode("type_annotation", children=[FakeNode("identifier", text="IgnoredType")]),
        ],
    )
    func_node = FakeNode("func", children=[params])
    assert extractors_mod._extract_param_names(func_node) == ["self", "value"]
    assert extractors_mod._unwrap_node([func_node]) is func_node
    assert extractors_mod._node_text(FakeNode("identifier", text="name")) == "name"

    source = b"def sample(value):\n    a = 1\n    b = 2\n    return value\n"
    function_node = FakeNode(
        "function_definition",
        children=[params],
        start_point=(0, 0),
        end_point=(3, 0),
        start_byte=0,
        end_byte=len(source),
    )
    class_node = FakeNode(
        "class_definition",
        start_point=(0, 0),
        end_point=(4, 0),
        start_byte=0,
        end_byte=len(source),
    )
    name_node = FakeNode("identifier", text="Sample")

    monkeypatch.setattr(extractors_mod, "_get_parser", lambda _grammar: ("parser", "lang"))
    monkeypatch.setattr(extractors_mod, "_make_query", lambda _lang, source: source)
    monkeypatch.setattr(
        extractors_mod,
        "get_or_parse_tree",
        lambda *_a, **_k: (source, SimpleNamespace(root_node=FakeNode("root"))),
    )
    monkeypatch.setattr(
        extractors_mod,
        "_run_query",
        lambda query, _root: (
            [(0, {"func": function_node, "name": name_node})]
            if query == "func query"
            else [(0, {"class": class_node, "name": name_node})]
        ),
    )
    monkeypatch.setattr(extractors_mod, "normalize_body", lambda *_a, **_k: "one\ntwo\nthree")

    spec = SimpleNamespace(grammar="py", function_query="func query", class_query="class query")
    functions = extractors_mod.ts_extract_functions(Path("."), spec, ["src/app.py"])
    classes = extractors_mod.ts_extract_classes(Path("."), spec, ["src/app.py"])

    assert functions[0].name == "Sample"
    assert functions[0].params == ["self", "value"]
    assert classes[0].name == "Sample"
    extractor = extractors_mod.make_ts_extractor(spec, lambda _path: ["src/app.py"])
    assert extractor(Path("."))[0].name == "Sample"


def test_smells_helpers_detect_empty_handlers_and_unreachable_code() -> None:
    empty_body = FakeNode("block", children=[FakeNode("{", text="{"), FakeNode("}", text="}")])
    handler = FakeNode("catch_clause", children=[empty_body])
    assert smells_mod._is_empty_handler(handler) is True

    entries: list[dict] = []
    block = FakeNode(
        "block",
        children=[
            FakeNode("return_statement"),
            FakeNode("expression_statement", start_point=(4, 0)),
        ],
    )
    smells_mod._check_sequence_for_unreachable(block, "src/app.py", entries)
    assert entries == [{"file": "src/app.py", "line": 5, "after": "return_statement"}]


def test_unused_import_helpers_and_detection(monkeypatch) -> None:
    as_alias = FakeNode(
        "import_statement",
        children=[FakeNode("identifier", text="import"), FakeNode("identifier", text="as"), FakeNode("identifier", text="alias")],
    )
    go_alias = FakeNode("import_spec", children=[FakeNode("package_identifier", text="pkg")])
    assert unused_imports_mod._extract_alias(as_alias) == "alias"
    assert unused_imports_mod._extract_alias(go_alias) == "pkg"
    assert unused_imports_mod._extract_import_name("pkg/module") == "module"
    assert unused_imports_mod._extract_import_name("crate::Thing") == "Thing"
    assert unused_imports_mod._extract_import_name("SystemFontLocator.h") == "SystemFontLocator"
    assert unused_imports_mod._extract_import_name("nlohmann/json.hpp") == "json"

    import_node = FakeNode(
        "import_statement",
        children=[FakeNode("identifier", text="import"), FakeNode("string", text="'pkg/module'")],
        start_point=(0, 0),
        end_point=(0, 10),
        start_byte=0,
        end_byte=19,
    )
    path_node = FakeNode("string", text="'pkg/module'")
    monkeypatch.setattr(unused_imports_mod, "_get_parser", lambda _grammar: ("parser", "lang"))
    monkeypatch.setattr(unused_imports_mod, "_make_query", lambda *_a, **_k: "query")
    monkeypatch.setattr(
        unused_imports_mod,
        "get_or_parse_tree",
        lambda *_a, **_k: (
            b"import pkg/module\nprint(other)\n",
            SimpleNamespace(root_node=FakeNode("root")),
        ),
    )
    monkeypatch.setattr(
        unused_imports_mod,
        "_run_query",
        lambda *_a, **_k: [(0, {"import": import_node, "path": path_node})],
    )
    monkeypatch.setattr(unused_imports_mod, "_unwrap_node", lambda node: node)
    monkeypatch.setattr(unused_imports_mod, "_node_text", lambda node: node.text.decode("utf-8"))

    spec = SimpleNamespace(grammar="py", import_query="query")
    entries = unused_imports_mod.detect_unused_imports(["src/app.py"], spec)
    assert entries == [{"file": "src/app.py", "line": 1, "name": "module"}]
