"""Tests for the package-aware Kotlin dependency graph."""

from __future__ import annotations

from pathlib import Path

from desloppify.languages.kotlin.deps import (
    ENTRYPOINT_IMPORTER,
    build_kotlin_dep_graph,
    strip_comments_and_strings,
    top_level_names,
)


def _write(root: Path, rel: str, text: str) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _imports(graph: dict, path: str) -> set[str]:
    return graph[path]["imports"]


def test_top_level_names_cover_declaration_forms() -> None:
    code = strip_comments_and_strings(
        """
@Composable
fun Screen(modifier: Modifier) { val inner = 1 }
private fun <T> List<T>.second(): T = this[1]
internal val Modifier.belowBar: Modifier get() = this
const val MAX_ITEMS = 10
data class Point(
    val x: Int,
    val y: Int,
) {
    fun nested() = Unit
}
enum class Theme { Light, Dark }
sealed interface Event
object Registry
fun interface Callback { fun call() }
typealias Grid = Array<IntArray>
"""
    )
    # `second` is private to its file, so other files cannot use it.
    assert top_level_names(code) == {
        "Screen",
        "belowBar",
        "MAX_ITEMS",
        "Point",
        "Theme",
        "Event",
        "Registry",
        "Callback",
        "Grid",
    }


def test_strip_keeps_template_references_and_drops_comments() -> None:
    code = strip_comments_and_strings(
        'val a = "plain Hidden text ${Shown.value} and $alsoShown" // Comment\n'
        "/* Block /* nested */ Gone */ val b = 'x'\n"
    )
    assert "Hidden" not in code
    assert "Comment" not in code
    assert "Gone" not in code
    assert "Shown" in code
    assert "alsoShown" in code
    assert code.count("\n") == 2


def test_graph_links_imports_same_package_and_wildcards(tmp_path: Path) -> None:
    model = _write(
        tmp_path,
        "app/src/main/java/com/acme/model/Models.kt",
        "package com.acme.model\n\nclass Book(val title: String)\nenum class Kind { A, B }\n",
    )
    helpers = _write(
        tmp_path,
        "app/src/main/java/com/acme/model/Helpers.kt",
        "package com.acme.model\n\nfun Book.shout() = title.uppercase()\n",
    )
    unrelated = _write(
        tmp_path,
        "app/src/main/java/com/acme/model/Unused.kt",
        "package com.acme.model\n\nclass Unused\n",
    )
    explicit = _write(
        tmp_path,
        "app/src/main/java/com/acme/ui/Screen.kt",
        "package com.acme.ui\n\nimport com.acme.model.Book\nimport com.acme.model.Kind.A\n"
        "import com.acme.model.shout as loud\n\nfun show(book: Book) = book.loud()\n",
    )
    wildcard = _write(
        tmp_path,
        "app/src/main/java/com/acme/ui/List.kt",
        "package com.acme.ui\n\nimport com.acme.model.*\n\nfun list(books: List<Book>) = show(books[0])\n",
    )
    same_package_test = _write(
        tmp_path,
        "app/src/test/java/com/acme/model/BookTest.kt",
        "package com.acme.model\n\nclass BookTest { fun t() = Book(\"x\").shout() }\n",
    )

    graph = build_kotlin_dep_graph(
        tmp_path, [model, helpers, unrelated, explicit, wildcard, same_package_test]
    )

    assert _imports(graph, explicit) == {model, helpers}
    # Wildcard picks only the package files whose names are used, plus
    # same-package `show` from Screen.kt.
    assert _imports(graph, wildcard) == {model, explicit}
    assert _imports(graph, helpers) == {model}
    assert _imports(graph, same_package_test) == {model, helpers}
    assert graph[unrelated]["importer_count"] == 0
    assert graph[model]["importers"] == {helpers, explicit, wildcard, same_package_test}
    assert graph[model]["importer_count"] == 4


def test_names_in_comments_and_strings_do_not_link(tmp_path: Path) -> None:
    target = _write(tmp_path, "src/a/Target.kt", "package a\n\nclass Target\n")
    user = _write(
        tmp_path,
        "src/a/User.kt",
        'package a\n\n// Target is mentioned here\nval label = "Target"\n',
    )
    graph = build_kotlin_dep_graph(tmp_path, [target, user])
    assert graph[target]["importer_count"] == 0


def test_private_top_level_names_do_not_link_files(tmp_path: Path) -> None:
    measurer = _write(
        tmp_path,
        "src/text/Measurer.kt",
        "package text\n\nprivate fun Layout.lines() = 1\nclass Measurer { fun m(p: Pager) = p }\n",
    )
    pager = _write(
        tmp_path,
        "src/text/Pager.kt",
        "package text\n\nclass Pager { fun page() { val lines = 3 } }\n",
    )
    graph = build_kotlin_dep_graph(tmp_path, [measurer, pager])
    assert _imports(graph, measurer) == {pager}
    assert _imports(graph, pager) == set()


def test_manifest_components_are_entry_points(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "app/build.gradle.kts",
        'android {\n    namespace = "com.acme.app"\n}\n',
    )
    _write(
        tmp_path,
        "app/src/main/AndroidManifest.xml",
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <application android:name=".App">\n'
        '    <activity\n        android:name=".MainActivity"\n        android:exported="true" />\n'
        '    <service android:name="com.acme.app.sync.SyncService" />\n'
        "  </application>\n</manifest>\n",
    )
    app = _write(tmp_path, "app/src/main/java/com/acme/app/App.kt", "package com.acme.app\n\nclass App\n")
    activity = _write(
        tmp_path,
        "app/src/main/java/com/acme/app/MainActivity.kt",
        "package com.acme.app\n\nclass MainActivity\n",
    )
    service = _write(
        tmp_path,
        "app/src/main/java/com/acme/app/sync/Sync.kt",
        "package com.acme.app.sync\n\nclass SyncService\n",
    )
    other = _write(
        tmp_path,
        "app/src/main/java/com/acme/app/Other.kt",
        "package com.acme.app\n\nclass Other\n",
    )
    # A stale manifest in build output must not count.
    _write(
        tmp_path,
        "app/build/intermediates/AndroidManifest.xml",
        '<manifest><application><activity android:name="com.acme.app.Other" /></application></manifest>',
    )

    graph = build_kotlin_dep_graph(tmp_path, [app, activity, service, other])

    for entry in (app, activity, service):
        assert graph[entry]["importers"] == {ENTRYPOINT_IMPORTER}
    assert graph[other]["importer_count"] == 0


def test_kotlin_plugin_uses_package_aware_graph(tmp_path: Path) -> None:
    from desloppify.languages import get_lang

    lang = get_lang("kotlin")
    a = _write(tmp_path, "src/main/kotlin/p/A.kt", "package p\n\nfun helper() = 1\n")
    b = _write(tmp_path, "src/main/kotlin/p/B.kt", "package p\n\nval x = helper()\n")
    graph = lang.build_dep_graph(tmp_path)
    resolved = {Path(k).resolve(): v for k, v in graph.items()}
    assert resolved[Path(a).resolve()]["importer_count"] == 1
    assert Path(b).resolve() in {Path(p).resolve() for p in resolved[Path(a).resolve()]["importers"]}
    assert ".gradle.kts" in lang.entry_patterns


def test_kotlin_zones_put_gradle_scripts_in_config() -> None:
    from desloppify.engine.policy.zones import Zone, classify_file
    from desloppify.languages.kotlin import KOTLIN_ZONE_RULES

    assert classify_file("app/build.gradle.kts", KOTLIN_ZONE_RULES) == Zone.CONFIG
    assert classify_file("settings.gradle.kts", KOTLIN_ZONE_RULES) == Zone.CONFIG
    assert classify_file("app/src/androidTest/java/p/UiTest.kt", KOTLIN_ZONE_RULES) == Zone.TEST
    assert classify_file("app/src/test/java/p/UnitTest.kt", KOTLIN_ZONE_RULES) == Zone.TEST
    assert classify_file("app/src/main/java/p/Screen.kt", KOTLIN_ZONE_RULES) == Zone.PRODUCTION
