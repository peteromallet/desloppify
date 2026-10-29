from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import desloppify.languages.cxx.treesitter as cxx_treesitter
from desloppify.languages._framework.runtime_support.runtime import make_lang_run
from desloppify.languages._framework.treesitter import (
    C_SPEC,
    CPP_SPEC,
    disable_parse_cache,
    enable_parse_cache,
    is_available,
)
from desloppify.languages._framework.treesitter.analysis import cohesion, smells
from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser
from desloppify.languages._framework.treesitter.analysis.smells import (
    detect_unreachable_code,
)
from desloppify.languages._framework.treesitter.phases import make_ast_smells_phase
from desloppify.languages.cxx import CxxConfig

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _phase(label):
    return next(phase for phase in CxxConfig().phases if phase.label == label)


@pytest.mark.parametrize("representation", ["arguments", "command"])
def test_c_file_explicitly_compiled_as_cpp_keeps_unreachable_throw(
    tmp_path, representation
):
    source = tmp_path / "native.c"
    source.write_bytes((_FIXTURES / "native_c" / "cpp_override.c").read_bytes())
    invocation = (
        ["c++", "-x", "c++", "-std=c++17", "-c", "native.c"]
        if representation == "arguments"
        else "c++ -x c++ -std=c++17 -c native.c"
    )
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": "native.c",
                    representation: invocation,
                }
            ]
        )
    )
    lang = SimpleNamespace(file_finder=lambda _: [str(source)])

    issues, potentials = _phase("AST smells").run(tmp_path, lang)

    assert len(issues) == 1
    assert issues[0]["summary"] == "Unreachable code after throw_statement"
    assert issues[0]["id"].endswith("unreachable_code::4")
    assert potentials == {"unreachable_code": 1}


def test_c_callback_named_throw_is_not_an_exception(tmp_path):
    source = tmp_path / "callback.c"
    source.write_bytes((_FIXTURES / "native_c" / "callback.c").read_bytes())

    # Reuse the scan cache to verify that C and C++ trees stay separate.
    enable_parse_cache()
    try:
        for spec in (C_SPEC, CPP_SPEC):
            parser, _ = _get_parser(spec.grammar)
            assert not parser.parse(source.read_bytes()).root_node.has_error
        assert len(detect_unreachable_code([str(source)], CPP_SPEC)) == 2
        assert detect_unreachable_code([str(source)], C_SPEC) == [
            {"file": str(source), "line": 9, "after": "return_statement"}
        ]

        issues, potentials = _phase("AST smells").run(
            tmp_path, make_lang_run(CxxConfig())
        )
    finally:
        disable_parse_cache()

    assert len(issues) == 1
    assert issues[0]["summary"] == "Unreachable code after return_statement"
    assert issues[0]["id"].endswith("unreachable_code::9")
    assert potentials == {"unreachable_code": 1}


@pytest.mark.parametrize(
    "suffix",
    [
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hh",
        ".hpp",
        ".hxx",
        ".ipp",
        ".inl",
        ".tpp",
        ".txx",
        ".tcc",
    ],
)
def test_mixed_project_preserves_cpp_and_header_findings(tmp_path, suffix):
    native = tmp_path / "native.c"
    native.write_bytes((_FIXTURES / "native_c" / "callback.c").read_bytes())
    cpp = tmp_path / f"widget{suffix}"
    cpp.write_text(
        "void work();\n"
        "template<class T> void sample() {\n"
        "    try { work(); } catch (...) {}\n"
        "    throw 1;\n"
        "    work();\n"
        "}\n"
    )
    lang = make_lang_run(CxxConfig())
    # The established C++ path must still report exactly the same findings.
    cpp_lang = SimpleNamespace(file_finder=lambda _path: [str(cpp)])
    expected_cpp, _ = make_ast_smells_phase(CPP_SPEC).run(tmp_path, cpp_lang)

    issues, potentials = _phase("AST smells").run(tmp_path, lang)

    assert len(issues) == len({issue["id"] for issue in issues}) == 3
    assert potentials == {"empty_catch": 1, "unreachable_code": 2}
    assert [
        issue for issue in issues if issue["file"].endswith(cpp.name)
    ] == expected_cpp


def test_native_c17_constructs_do_not_produce_smells(tmp_path):
    source = tmp_path / "native.c"
    source.write_bytes((_FIXTURES / "native_c" / "constructs.c").read_bytes())

    issues, potentials = _phase("AST smells").run(tmp_path, make_lang_run(CxxConfig()))

    assert issues == []
    assert potentials == {}


@pytest.mark.parametrize("suffixes", [(".c",), (".c", ".cpp")])
@pytest.mark.parametrize(
    "compile_command", [None, "cc -std=c17 clusters.c", "g++ -xc -std=c17 clusters.c"]
)
def test_cohesion_combines_c_and_cpp_findings(tmp_path, suffixes, compile_command):
    # Three pairs and two standalone functions: five disconnected clusters.
    functions = [
        f"int leaf{i}(void) {{ return {i}; }}\n"
        f"int root{i}(void) {{ return leaf{i}(); }}\n"
        for i in range(3)
    ]
    functions.extend(
        ["int solo1(void) { return 1; }\n", "int solo2(void) { return 2; }\n"]
    )
    content = "".join(functions) + "\n" * 200
    for suffix in suffixes:
        # mutable is an ordinary C identifier. The C++ query silently misses
        # its definition, dropping this file below the eight-function minimum.
        source = content.replace("solo1", "mutable") if suffix == ".c" else content
        (tmp_path / f"clusters{suffix}").write_text(source)
    if compile_command is not None:
        (tmp_path / "compile_commands.json").write_text(
            json.dumps([{"file": "clusters.c", "command": compile_command}])
        )

    assert cohesion.detect_responsibility_cohesion(
        [str(tmp_path / "clusters.c")], CPP_SPEC
    ) == ([], 1)

    issues, potentials = _phase("Responsibility cohesion").run(
        tmp_path, make_lang_run(CxxConfig())
    )

    assert len(issues) == len({issue["id"] for issue in issues}) == len(suffixes)
    assert {Path(issue["file"]).suffix for issue in issues} == set(suffixes)
    assert all(issue["detail"]["cluster_count"] == 5 for issue in issues)
    assert potentials == {"responsibility_cohesion": len(suffixes)}


def test_phases_use_runtime_file_finder_once_per_grammar(tmp_path, monkeypatch):
    files = [
        "src/./native.c",
        str(tmp_path / "dir.with.c" / "other.c"),
        "src/widget.cpp",
        "include/shared.h",
    ]
    calls = []

    def record(detector):
        def detect(file_list, spec):
            calls.append((detector, spec.grammar, file_list))
            return ([], len(file_list)) if detector == "cohesion" else []

        return detect

    monkeypatch.setattr(smells, "detect_empty_catches", record("catches"))
    monkeypatch.setattr(smells, "detect_unreachable_code", record("unreachable"))
    monkeypatch.setattr(cohesion, "detect_responsibility_cohesion", record("cohesion"))
    lang = SimpleNamespace(file_finder=lambda _path: files)
    for label in ("AST smells", "Responsibility cohesion"):
        assert _phase(label).run(tmp_path, lang) == ([], {})

    for detector in ("catches", "unreachable", "cohesion"):
        assert [call[1:] for call in calls if call[0] == detector] == [
            ("c", files[:2]),
            ("cpp", files[2:]),
        ]


def test_c_parser_initialization_failure_keeps_cpp_findings(tmp_path, monkeypatch):
    (tmp_path / "native.c").write_text("int f(void) { return 1; }\n")
    (tmp_path / "widget.cpp").write_text("void f() { throw 1; f(); }\n")

    def get_parser(grammar):
        if grammar == "c":
            raise ImportError("C parser unavailable")
        return _get_parser(grammar)

    monkeypatch.setattr(smells, "_get_parser", get_parser)
    monkeypatch.setattr(cohesion, "_get_parser", get_parser)
    lang = make_lang_run(CxxConfig())

    issues, potentials = _phase("AST smells").run(tmp_path, lang)

    assert len(issues) == 1
    assert issues[0]["file"].endswith("widget.cpp")
    assert potentials == {"unreachable_code": 1}
    assert _phase("Responsibility cohesion").run(tmp_path, lang) == ([], {})


def test_native_c_findings_reach_scan_pipeline(tmp_path):
    from desloppify.engine.planning.scan import generate_issues

    source = tmp_path / "main.c"
    source.write_bytes((_FIXTURES / "native_c" / "callback.c").read_bytes())
    cfg = CxxConfig()
    cfg.phases = [
        phase
        for phase in cfg.phases
        if phase.label in {"AST smells", "Responsibility cohesion"}
    ]

    issues, potentials = generate_issues(tmp_path, cfg)

    assert len(issues) == 1
    assert issues[0]["lang"] == "cxx"
    assert issues[0]["zone"] == "production"
    assert issues[0]["confidence"] == "high"
    assert potentials == {"unreachable_code": 1}


def test_compilation_aware_mixed_project_preserves_each_context(tmp_path):
    (tmp_path / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "callback.c").read_bytes()
    )
    for name in ("override.c", "ordinary.cpp", "shared.h"):
        (tmp_path / name).write_bytes(
            (_FIXTURES / "native_c" / "cpp_override.c").read_bytes()
        )
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"file": "native.c", "arguments": ["g++", "-xc", "native.c"]},
                {"file": "override.c", "command": "gcc -xc++ override.c"},
                {"file": "ordinary.cpp", "command": "gcc ordinary.cpp"},
                {"file": "shared.h", "command": "gcc -xc shared.h"},
            ]
        )
    )

    issues, potentials = _phase("AST smells").run(tmp_path, make_lang_run(CxxConfig()))

    assert len(issues) == len({issue["id"] for issue in issues}) == 4
    assert potentials == {"unreachable_code": 4}
    native = next(issue for issue in issues if issue["file"].endswith("native.c"))
    assert native["id"].endswith("unreachable_code::9")
    assert native["summary"] == "Unreachable code after return_statement"
    assert all(
        issue["summary"] == "Unreachable code after throw_statement"
        for issue in issues
        if issue is not native
    )
    assert all(issue["confidence"] == "high" for issue in issues)


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_compile_contexts_keep_cpp_and_disclose_ambiguity(
    tmp_path, caplog, reverse
):
    (tmp_path / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "cpp_override.c").read_bytes()
    )
    entries = [
        {"file": "native.c", "arguments": ["gcc", "-xc", "native.c"]},
        {"file": "./native.c", "arguments": ["gcc", "-xc++", "native.c"]},
    ]
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(entries[::-1] if reverse else entries)
    )

    issues, potentials = _phase("AST smells").run(tmp_path, make_lang_run(CxxConfig()))

    assert len(issues) == 1
    assert potentials == {"unreachable_code": 1}
    assert issues[0]["summary"] == "Unreachable code after throw_statement"
    assert issues[0]["confidence"] == "low"
    assert issues[0]["detail"]["compilation_languages"] == ["c", "cpp"]
    assert "Conflicting C/C++ compile languages" in caplog.text
    assert "represent only that context" in caplog.text


def test_equivalent_commands_do_not_duplicate_or_reduce_findings(tmp_path, caplog):
    (tmp_path / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "cpp_override.c").read_bytes()
    )
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"file": "native.c", "command": "clang++ native.c"},
                {"file": "./native.c", "arguments": ["cc", "-xc++", "./native.c"]},
            ]
        )
    )

    issues, potentials = _phase("AST smells").run(tmp_path, make_lang_run(CxxConfig()))

    assert len(issues) == 1
    assert potentials == {"unreachable_code": 1}
    assert issues[0]["confidence"] == "high"
    assert "compilation_languages" not in issues[0]["detail"]
    assert not caplog.records


def test_scan_roots_and_metadata_changes_do_not_share_selection(tmp_path):
    cpp_root = tmp_path / "cpp"
    c_root = tmp_path / "c"
    cpp_root.mkdir()
    c_root.mkdir()
    (cpp_root / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "cpp_override.c").read_bytes()
    )
    (c_root / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "callback.c").read_bytes()
    )
    database = cpp_root / "compile_commands.json"
    database.write_text(
        json.dumps([{"file": "native.c", "command": "cc -xc++ native.c"}])
    )
    lang = make_lang_run(CxxConfig())
    phase = next(phase for phase in lang.phases if phase.label == "AST smells")

    for root, after in (
        (cpp_root, "throw_statement"),
        (c_root, "return_statement"),
        (cpp_root, "throw_statement"),
    ):
        issues, potentials = phase.run(root, lang)
        assert len(issues) == 1
        assert issues[0]["summary"] == f"Unreachable code after {after}"
        assert potentials == {"unreachable_code": 1}

    database.write_text("[]")
    (cpp_root / "native.c").write_bytes(
        (_FIXTURES / "native_c" / "callback.c").read_bytes()
    )
    issues, _ = phase.run(cpp_root, lang)
    assert len(issues) == 1
    assert issues[0]["summary"] == "Unreachable code after return_statement"


def test_compilation_database_is_loaded_once_per_phase(tmp_path, monkeypatch):
    for index in range(10):
        (tmp_path / f"native{index}.c").write_text("int f(void) { return 1; }\n")
    original = cxx_treesitter.load_compile_commands
    reads = []

    def load(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(cxx_treesitter, "load_compile_commands", load)
    lang = make_lang_run(CxxConfig())
    for label in ("AST smells", "Responsibility cohesion"):
        assert _phase(label).run(tmp_path, lang) == ([], {})
    assert reads == [tmp_path, tmp_path]


def test_unmatched_or_excluded_metadata_does_not_change_native_c(tmp_path, caplog):
    source = tmp_path / "native.c"
    source.write_bytes((_FIXTURES / "native_c" / "callback.c").read_bytes())
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"file": "other/native.c", "command": "cc -xc++ other/native.c"},
                {"file": "excluded.c", "command": "cc -xc excluded.c"},
                {"file": "excluded.c", "command": "cc -xc++ excluded.c"},
            ]
        )
    )
    lang = SimpleNamespace(file_finder=lambda _: [str(source)])

    issues, _ = _phase("AST smells").run(tmp_path, lang)

    assert len(issues) == 1
    assert issues[0]["summary"] == "Unreachable code after return_statement"
    assert not caplog.records
