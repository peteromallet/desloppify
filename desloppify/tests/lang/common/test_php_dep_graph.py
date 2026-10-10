"""PHP import graphs preserve the file keys supplied by discovery."""

from __future__ import annotations

import json

import pytest

from desloppify.engine.detectors.orphaned import detect_orphaned_files
from desloppify.languages._framework.treesitter import is_available
from desloppify.languages._framework.treesitter.analysis.unused_imports import (
    detect_unused_imports,
)
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph
from desloppify.languages._framework.treesitter.specs.compiled import PHP_SPEC

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)


@pytest.mark.parametrize("absolute_keys", [False, True])
@pytest.mark.parametrize("scan_directory", [".", "app"])
def test_php_graph_preserves_discovered_file_keys(
    monkeypatch, tmp_path, absolute_keys, scan_directory
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "composer.json").write_text(
        json.dumps({"autoload": {"psr-4": {"App\\": "app/"}}})
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app/Foo.php").write_text("<?php namespace App; class Foo {}")
    (tmp_path / "app/Outside.php").write_text("<?php namespace App; class Outside {}")
    (tmp_path / "app/Bar.php").write_text(
        "<?php namespace App; use App\\{Foo, Outside}; use DateTime; class Bar {}"
    )

    foo_key, bar_key = (
        [str(tmp_path / name) for name in ("app/Foo.php", "app/Bar.php")]
        if absolute_keys
        else ["app/Foo.php", "app/Bar.php"]
    )
    graph = ts_build_dep_graph(
        tmp_path / scan_directory, PHP_SPEC, [foo_key, bar_key]
    )

    assert graph == {
        foo_key: {
            "imports": set(),
            "importers": {bar_key},
            "import_count": 0,
            "importer_count": 1,
        },
        bar_key: {
            "imports": {foo_key},
            "importers": set(),
            "import_count": 1,
            "importer_count": 0,
        },
    }


def test_php_graph_resolves_composer_psr4_outside_conventional_roots(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "composer.json").write_text(
        json.dumps({"autoload": {"psr-4": {"Domain\\": "modules/core/"}}})
    )
    (tmp_path / "modules/core").mkdir(parents=True)
    (tmp_path / "modules/core/Foo.php").write_text(
        "<?php namespace Domain; class Foo {}"
    )
    (tmp_path / "main.php").write_text("<?php use Domain\\Foo; new Foo();")

    graph = ts_build_dep_graph(
        tmp_path, PHP_SPEC, ["main.php", "modules/core/Foo.php"]
    )

    assert graph["main.php"]["imports"] == {"modules/core/Foo.php"}
    assert graph["modules/core/Foo.php"]["importers"] == {"main.php"}


def test_php_same_namespace_reference_prevents_a_false_orphan(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "composer.json").write_text(
        json.dumps({"autoload": {"psr-4": {"App\\": "src/"}}})
    )
    (tmp_path / "src/Domain").mkdir(parents=True)
    (tmp_path / "src/Domain/SharedPolicy.php").write_text(
        """<?php
namespace App\\Domain;

final class SharedPolicy
{
    public function allows(int $value): bool
    {
        if ($value < 0) {
            return false;
        }

        return $value < 100;
    }
}
"""
    )
    (tmp_path / "src/Domain/Consumer.php").write_text(
        "<?php namespace App\\Domain; class Consumer { public function policy() { return new SharedPolicy(); } }"
    )
    policy_key = "src/Domain/SharedPolicy.php"
    consumer_key = "src/Domain/Consumer.php"
    graph = ts_build_dep_graph(tmp_path, PHP_SPEC, [policy_key, consumer_key])

    orphans, _ = detect_orphaned_files(tmp_path, graph, [".php"])

    assert orphans == []
    assert graph[policy_key]["importers"] == {consumer_key}


@pytest.mark.parametrize(
    ("consumer", "dependency_kind"),
    [
        ("class Consumer { public function run() { Dependency::check(); } }", "class"),
        ("class Consumer { public function run() { return Dependency::class; } }", "class"),
        ("class Consumer { public function run() { return Dependency::$state; } }", "class"),
        ("class Consumer { public Dependency $value; }", "class"),
        ("class Consumer { public function run(Dependency $value): Dependency { return $value; } }", "class"),
        ("class Consumer { public ?Dependency $value; }", "class"),
        ("class Consumer { public Dependency|\\DateTime $value; }", "class"),
        ("class Consumer { public Dependency&\\Iterator $value; }", "interface"),
        ("class Consumer extends Dependency {}", "class"),
        ("class Consumer implements Dependency {}", "interface"),
        ("class Consumer { use Dependency; }", "trait"),
        ("#[Dependency] class Consumer {}", "attribute"),
        ("class Consumer { public function run($value) { return $value instanceof Dependency; } }", "class"),
        ("try {} catch (Dependency $error) {}", "exception"),
    ],
    ids=[
        "static-call", "class-constant", "static-property", "property-type", "parameter-and-return-type",
        "nullable-type", "union-type", "intersection-type", "extends", "implements", "trait", "attribute",
        "instanceof", "catch-type",
    ],
)
def test_php_graph_tracks_native_class_reference_contexts(monkeypatch, tmp_path, consumer, dependency_kind) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/Domain").mkdir(parents=True)
    dependency = "src/Domain/Dependency.php"
    caller = "src/Domain/Consumer.php"
    definitions = {
        "class": "class Dependency { public static $state; public static function check() {} }",
        "interface": "interface Dependency {}",
        "trait": "trait Dependency {}",
        "attribute": "#[\\Attribute] class Dependency {}",
        "exception": "class Dependency extends \\Exception {}",
    }
    (tmp_path / dependency).write_text("<?php namespace App\\Domain; " + definitions[dependency_kind])
    (tmp_path / caller).write_text("<?php namespace App\\Domain; " + consumer)

    graph = ts_build_dep_graph(tmp_path, PHP_SPEC, [dependency, caller])

    assert graph[caller]["imports"] == {dependency}
    assert graph[dependency]["importers"] == {caller}


def _php_project_graph(monkeypatch, tmp_path, sources: dict[str, str], *, absolute_keys=False):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "composer.json").write_text(json.dumps({"autoload": {"psr-4": {
        "App\\": "src/", "External\\": "external/", "A\\": "a/", "B\\": "b/",
    }}}))
    for filepath, source in sources.items():
        target = tmp_path / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<?php\n" + source)
    keys = [str(tmp_path / key) if absolute_keys else key for key in sources]
    return ts_build_dep_graph(tmp_path, PHP_SPEC, keys)


@pytest.mark.parametrize("imports", [
    "use External\\Dependency as Selected;",
    "use External\\{Dependency as Selected};",
    "use External\\Group\\{Dependency as Selected};",
])
def test_php_import_alias_shadows_same_namespace_class(monkeypatch, tmp_path, imports) -> None:
    external_namespace = "External\\Group" if "Group" in imports else "External"
    external_key = "external/Group/Dependency.php" if "Group" in imports else "external/Dependency.php"
    local_key = "src/Domain/Selected.php"
    caller = "src/Domain/Consumer.php"
    graph = _php_project_graph(monkeypatch, tmp_path, {
        external_key: f"namespace {external_namespace}; class Dependency {{}}",
        local_key: "namespace App\\Domain; class Selected {}",
        caller: f"namespace App\\Domain; {imports} new Selected();",
    })

    assert graph[caller]["imports"] == {external_key}
    assert graph[local_key]["importers"] == set()


def test_php_namespace_alias_resolves_qualified_class_reference(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Group/Dependency.php": "namespace External\\Group; class Dependency {}",
        "src/Domain/Selected/Dependency.php": "namespace App\\Domain\\Selected; class Dependency {}",
        "src/Domain/Consumer.php": "namespace App\\Domain; use External\\Group as Selected; new selected\\Dependency();",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == {"external/Group/Dependency.php"}
    assert graph["src/Domain/Selected/Dependency.php"]["importers"] == set()


@pytest.mark.parametrize("bracketed", [False, True])
def test_php_namespace_blocks_do_not_leak_aliases(monkeypatch, tmp_path, bracketed) -> None:
    first = "use External\\Dependency as Selected; new Selected();"
    second = "new Selected();"
    caller_source = (
        f"namespace A {{ {first} }} namespace B {{ {second} }}"
        if bracketed else f"namespace A; {first} namespace B; {second}"
    )
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Dependency.php": "namespace External; class Dependency {}",
        "a/Selected.php": "namespace A; class Selected {}",
        "b/Selected.php": "namespace B; class Selected {}",
        "caller.php": caller_source,
    })

    assert graph["caller.php"]["imports"] == {"external/Dependency.php", "b/Selected.php"}
    assert graph["a/Selected.php"]["importers"] == set()


@pytest.mark.parametrize("imports", [
    "use function External\\Dependency as Local;",
    "use const External\\Dependency as Local;",
    "use External\\{function Dependency as Local};",
    "use function External\\{Dependency as Local};",
    "use const External\\{Dependency as Local};",
])
def test_php_function_and_constant_imports_are_not_class_aliases(monkeypatch, tmp_path, imports) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Dependency.php": "namespace External; class Dependency {}",
        "src/Domain/Local.php": "namespace App\\Domain; class Local {}",
        "src/Domain/Consumer.php": f"namespace App\\Domain; {imports} new Local();",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == {"src/Domain/Local.php"}
    assert graph["external/Dependency.php"]["importers"] == set()


@pytest.mark.parametrize("absolute_keys", [False, True])
@pytest.mark.parametrize("scan_directory", [".", "modules"])
def test_php_fully_qualified_class_registration_preserves_scan_keys(
    monkeypatch, tmp_path, absolute_keys, scan_directory
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "composer.json").write_text(json.dumps({"autoload": {"psr-4": {"Domain\\": "modules/core/"}}}))
    (tmp_path / "modules/core").mkdir(parents=True)
    dependency = "modules/core/Dependency.php"
    caller = "modules/bootstrap.php"
    (tmp_path / dependency).write_text("<?php namespace Domain; class Dependency {}")
    (tmp_path / caller).write_text("<?php namespace Boot; register(\\Domain\\Dependency::class);")
    dependency_key = str(tmp_path / dependency) if absolute_keys else dependency
    caller_key = str(tmp_path / caller) if absolute_keys else caller

    graph = ts_build_dep_graph(tmp_path / scan_directory, PHP_SPEC, [dependency_key, caller_key])

    assert graph[caller_key]["imports"] == {dependency_key}
    assert graph[dependency_key]["importers"] == {caller_key}


def test_php_graph_ignores_methods_comments_strings_dynamic_and_relative_scope_names(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "src/Domain/Dependency.php": "namespace App\\Domain; class Dependency {}",
        "src/Domain/Consumer.php": """namespace App\\Domain;
class Consumer extends \\RuntimeException {
    public function Dependency() {
        // new Dependency(); Dependency::class;
        $text = 'new Dependency();';
        $class = 'App\\Domain\\Dependency';
        Dependency();
        $this->Dependency();
        self::Dependency();
        static::Dependency();
        parent::Dependency();
        self::class;
        static::class;
        new static();
        new $class();
        new Consumer();
    }
}""",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == set()
    assert graph["src/Domain/Dependency.php"]["importers"] == set()


def test_php_graph_never_guesses_external_or_unscanned_reference_targets(monkeypatch, tmp_path) -> None:
    (tmp_path / "external").mkdir()
    (tmp_path / "external/Unscanned.php").write_text("<?php namespace External; class Unscanned {}")
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "src/Dependency.php": "namespace App; class Dependency {}",
        "src/Consumer.php": "namespace App; use External\\Unscanned; new Unscanned(); new \\Vendor\\Dependency();",
    })

    assert graph["src/Consumer.php"]["imports"] == set()
    assert graph["src/Dependency.php"]["importers"] == set()


def test_php_relative_and_global_names_bypass_class_aliases(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Dependency.php": "namespace External; class Dependency {}",
        "src/Domain/Dependency.php": "namespace App\\Domain; class Dependency {}",
        "global.php": "class Dependency {}",
        "src/Domain/Consumer.php": "namespace App\\Domain; use External\\Dependency; new namespace\\Dependency(); new \\Dependency();",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == {
        "external/Dependency.php", "src/Domain/Dependency.php", "global.php",
    }


def test_php_imports_bind_in_source_order_and_reset_in_global_blocks(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Dependency.php": "namespace External; class Dependency {}",
        "src/Domain/Selected.php": "namespace App\\Domain; class Selected {}",
        "global.php": "class Selected {}",
        "caller.php": """namespace App\\Domain {
    new Selected();
    use External\\Dependency as Selected;
    new Selected();
}
namespace { new Selected(); }""",
    })

    assert graph["caller.php"]["imports"] == {
        "external/Dependency.php", "src/Domain/Selected.php", "global.php",
    }


def test_php_graph_omits_ambiguous_class_declarations(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "src/Domain/First.php": "namespace App\\Domain; class Dependency {}",
        "src/Domain/Second.php": "namespace App\\Domain; class Dependency {}",
        "src/Domain/Consumer.php": "namespace App\\Domain; new Dependency();",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == set()


def test_php_trait_use_honors_import_alias_instead_of_local_basename(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "external/Dependency.php": "namespace External; trait Dependency {}",
        "src/Domain/Selected.php": "namespace App\\Domain; trait Selected {}",
        "src/Domain/Consumer.php": "namespace App\\Domain; use External\\Dependency as Selected; class Consumer { use Selected; }",
    })

    assert graph["src/Domain/Consumer.php"]["imports"] == {"external/Dependency.php"}
    assert graph["src/Domain/Selected.php"]["importers"] == set()


def test_php_external_import_never_resolves_to_a_local_class_with_the_same_basename(monkeypatch, tmp_path) -> None:
    graph = _php_project_graph(monkeypatch, tmp_path, {
        "src/Dependency.php": "namespace App; class Dependency {}",
        "src/Consumer.php": "namespace App; use Vendor\\Dependency as Selected; new Selected();",
    })

    assert graph["src/Consumer.php"]["imports"] == set()
    assert graph["src/Dependency.php"]["importers"] == set()


@pytest.mark.parametrize("trait_name", ["Dependency", "\\App\\Domain\\Dependency"])
def test_php_trait_composition_is_not_an_unused_namespace_import(monkeypatch, tmp_path, trait_name) -> None:
    caller = "src/Domain/Consumer.php"
    dependency = "src/Domain/Dependency.php"
    graph = _php_project_graph(monkeypatch, tmp_path, {
        dependency: "namespace App\\Domain; trait Dependency {}",
        caller: f"namespace App\\Domain; class Consumer {{ use {trait_name}; }}",
    })

    assert detect_unused_imports([caller], PHP_SPEC) == []
    assert graph[caller]["imports"] == {dependency}


def test_php_unused_namespace_imports_remain_detectable_when_a_trait_import_is_used(monkeypatch, tmp_path) -> None:
    caller = "src/Consumer.php"
    _php_project_graph(monkeypatch, tmp_path, {
        caller: """namespace App;
use Vendor\\Unused;
use Vendor\\Applied;
class Consumer { use Applied; }
""",
    })

    assert detect_unused_imports([caller], PHP_SPEC) == [{"file": caller, "line": 3, "name": "Unused"}]
