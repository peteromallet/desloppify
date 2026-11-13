"""Tests for Rust detector phases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from desloppify.base.discovery.paths import get_area
from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine.detectors.complexity import detect_complexity
from desloppify.languages.rust.phases import RUST_COMPLEXITY_SIGNALS, phase_coupling


def _write(tmp_path: Path, relpath: str, content: str) -> None:
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.mark.parametrize(
    "source",
    [
        """fn compare(expected: u64, expected_count: u64) -> bool {
    let expected_next = expected + 1;
    let expectation = expected_count + 1;
    let unwrapped_value = expectation;
    expected_next == unwrapped_value
}""",
        """fn fallback(value: Option<u64>) {
    let _ = value.unwrap_or(0);
    let _ = value.unwrap_or_default();
    let _ = value.unwrap_or_else(|| 0);
    let _ = value.unwrap_or(1);
    let _ = value.unwrap_or_default();
}""",
    ],
)
def test_rust_complexity_ignores_identifier_prefixes_and_safe_fallbacks(tmp_path, source):
    _write(tmp_path, "src/lib.rs", source)
    signals = [s for s in RUST_COMPLEXITY_SIGNALS if s.name == "error branching"]
    entries, total = detect_complexity(
        tmp_path,
        signals=signals,
        file_finder=lambda root: [str(root / "src/lib.rs")],
        threshold=1,
        min_loc=0,
    )
    assert total == 1
    assert entries == []


@pytest.mark.parametrize(
    "call",
    [
        "value.unwrap();",
        "value.unwrap_err();",
        'value.expect ("message");',
        'value.expect_err\n("message");',
        'panic! { "message" };',
        'todo!["message"];',
        'unimplemented!("message");',
    ],
)
def test_rust_complexity_preserves_panicking_call_detection(tmp_path, call):
    _write(tmp_path, "src/lib.rs", "fn sample() {\n" + "\n".join([call] * 5) + "\n}")
    signals = [s for s in RUST_COMPLEXITY_SIGNALS if s.name == "error branching"]
    entries, _ = detect_complexity(
        tmp_path,
        signals=signals,
        file_finder=lambda root: [str(root / "src/lib.rs")],
        threshold=1,
        min_loc=0,
    )
    assert len(entries) == 1
    assert entries[0]["signals"] == ["5 error branching"]
    assert entries[0]["score"] == 2


def test_phase_coupling_does_not_emit_generic_cycles_for_rust_sibling_uses(tmp_path):
    _write(tmp_path, "Cargo.toml", "[package]\nname = 'demo-app'\nversion = '0.1.0'\n")
    _write(tmp_path, "src/main.rs", "mod foo;\nmod bar;\nfn main() {}\n")
    _write(tmp_path, "src/foo.rs", "use crate::bar::Bar;\npub struct Foo;\n")
    _write(tmp_path, "src/bar.rs", "use crate::foo::Foo;\npub struct Bar;\n")

    lang = SimpleNamespace(
        barrel_names={"lib.rs"},
        dep_graph=None,
        entry_patterns=["src/main.rs"],
        extensions=[".rs"],
        get_area=get_area,
        zone_map=None,
    )

    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        issues, potentials = phase_coupling(tmp_path, lang)

    assert [issue for issue in issues if issue["detector"] == "cycles"] == []
    assert potentials["cycles"] == 0
