"""Tests for Razor/Blazor view support in the C# dependency graph.

Views are not scored as C# source, but they are the only place a lot of C# is
referenced from. These tests pin both halves of that: code reachable from a
view is linked, and code reachable from nowhere stays orphaned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import desloppify.languages.csharp.detectors.deps as deps_detector_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod


@pytest.fixture(autouse=True)
def _root(set_project_root):
    """Point PROJECT_ROOT at the tmp directory via RuntimeContext."""
    return set_project_root


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _key(tmp_path: Path, name: str) -> str:
    return str((tmp_path / name).resolve())


def _csproj(tmp_path: Path, name: str = "App.csproj", root_namespace: str = "App"):
    return _write(
        tmp_path,
        name,
        "<Project Sdk=\"Microsoft.NET.Sdk.Web\">\n"
        f"  <PropertyGroup><RootNamespace>{root_namespace}</RootNamespace></PropertyGroup>\n"
        "</Project>\n",
    )


# ── Blazor components ───────────────────────────────────────────


class TestBlazorViews:
    def test_code_behind_is_linked_from_its_view(self, tmp_path):
        """A .razor.cs partial is consumed by its own view, not by nothing."""

        _csproj(tmp_path)
        _write(tmp_path, "Components/Widget.razor", "<div>@Describe()</div>\n")
        _write(
            tmp_path,
            "Components/Widget.razor.cs",
            "namespace App.Components;\n\n"
            "public partial class Widget\n{\n"
            "    private string Describe() => \"widget\";\n}\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        view = _key(tmp_path, "Components/Widget.razor")
        code_behind = _key(tmp_path, "Components/Widget.razor.cs")
        assert view in graph[code_behind]["importers"]
        assert code_behind in graph[view]["imports"]

    def test_type_used_only_in_markup_is_linked(self, tmp_path):
        """A helper named only from markup is reachable."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Services/PriceFormatter.cs",
            "namespace App.Services;\n\n"
            "public static class PriceFormatter\n{\n"
            "    public static string ToDisplay(decimal a) => $\"{a}\";\n}\n",
        )
        _write(
            tmp_path,
            "Pages/Home.razor",
            "@page \"/\"\n@using App.Services\n<p>@PriceFormatter.ToDisplay(1.0m)</p>\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        formatter = _key(tmp_path, "Services/PriceFormatter.cs")
        view = _key(tmp_path, "Pages/Home.razor")
        assert view in graph[formatter]["importers"]

    def test_unreferenced_type_stays_orphaned(self, tmp_path):
        """A `@using` puts a namespace in scope; it does not make it all live."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Services/Used.cs",
            "namespace App.Services;\n\npublic static class Used\n{\n"
            "    public static string Go() => \"x\";\n}\n",
        )
        _write(
            tmp_path,
            "Services/NeverReferenced.cs",
            "namespace App.Services;\n\npublic static class NeverReferenced\n{\n"
            "    public static string Go() => \"x\";\n}\n",
        )
        _write(
            tmp_path,
            "Pages/Home.razor",
            "@page \"/\"\n@using App.Services\n<p>@Used.Go()</p>\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        used = _key(tmp_path, "Services/Used.cs")
        dead = _key(tmp_path, "Services/NeverReferenced.cs")
        view = _key(tmp_path, "Pages/Home.razor")
        assert view in graph[used]["importers"]
        assert view not in graph[dead]["importers"]

    def test_component_tag_creates_edge(self, tmp_path):
        """Rendering <Widget /> links the view that declares it."""

        _csproj(tmp_path)
        _write(tmp_path, "Components/Widget.razor", "<div>widget</div>\n")
        _write(tmp_path, "Pages/Home.razor", "@page \"/\"\n<Widget />\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        widget = _key(tmp_path, "Components/Widget.razor")
        home = _key(tmp_path, "Pages/Home.razor")
        assert home in graph[widget]["importers"]

    def test_component_declared_in_csharp_resolves_from_tag(self, tmp_path):
        """A component with no .razor file still resolves by type name."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Components/Badge.cs",
            "namespace App.Components;\n\npublic class Badge : ComponentBase { }\n",
        )
        _write(
            tmp_path,
            "Pages/Home.razor",
            "@page \"/\"\n@using App.Components\n<Badge />\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        badge = _key(tmp_path, "Components/Badge.cs")
        home = _key(tmp_path, "Pages/Home.razor")
        assert home in graph[badge]["importers"]

    def test_extension_method_called_from_markup_is_linked(self, tmp_path):
        """Extension methods name no type at the call site, so index by method."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Services/DisplayExtensions.cs",
            "namespace App.Services;\n\npublic static class DisplayExtensions\n{\n"
            "    public static string ToBadge(this decimal a) => $\"[{a}]\";\n}\n",
        )
        _write(
            tmp_path,
            "Pages/Home.razor",
            "@page \"/\"\n@using App.Services\n<p>@(1.0m).ToBadge()</p>\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        extensions = _key(tmp_path, "Services/DisplayExtensions.cs")
        home = _key(tmp_path, "Pages/Home.razor")
        assert home in graph[extensions]["importers"]

    def test_ambient_imports_apply_to_subtree(self, tmp_path):
        """_Imports.razor usings are inherited by views below it."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Services/Helper.cs",
            "namespace App.Services;\n\npublic static class Helper\n{\n"
            "    public static string Go() => \"x\";\n}\n",
        )
        _write(tmp_path, "Components/_Imports.razor", "@using App.Services\n")
        # No local @using: the edge can only come from the ambient import file.
        _write(tmp_path, "Components/Deep/Card.razor", "<p>@Helper.Go()</p>\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        helper = _key(tmp_path, "Services/Helper.cs")
        card = _key(tmp_path, "Components/Deep/Card.razor")
        assert card in graph[helper]["importers"]

    def test_page_directive_marks_entrypoint(self, tmp_path):
        """A routable view is reachable by URL, so it is a root."""

        _csproj(tmp_path)
        _write(tmp_path, "Pages/Home.razor", "@page \"/\"\n<h1>Home</h1>\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        home = _key(tmp_path, "Pages/Home.razor")
        assert "__entrypoint__" in graph[home]["importers"]

    def test_razor_comments_are_ignored(self, tmp_path):
        """Commented-out markup must not create edges."""

        _csproj(tmp_path)
        _write(tmp_path, "Components/Widget.razor", "<div>widget</div>\n")
        _write(
            tmp_path,
            "Pages/Home.razor",
            "@page \"/\"\n@*\n<Widget />\n*@\n<p>nothing</p>\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        widget = _key(tmp_path, "Components/Widget.razor")
        home = _key(tmp_path, "Pages/Home.razor")
        assert home not in graph[widget]["importers"]


# ── Razor Pages and MVC ─────────────────────────────────────────


class TestRazorPagesViews:
    def test_page_model_code_behind_is_linked(self, tmp_path):
        """Index.cshtml.cs is consumed by Index.cshtml."""

        _csproj(tmp_path, root_namespace="Web")
        _write(tmp_path, "Pages/Index.cshtml", "@page\n@model IndexModel\n<h1>Hi</h1>\n")
        _write(
            tmp_path,
            "Pages/Index.cshtml.cs",
            "namespace Web.Pages;\n\npublic class IndexModel : PageModel { }\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        view = _key(tmp_path, "Pages/Index.cshtml")
        model = _key(tmp_path, "Pages/Index.cshtml.cs")
        assert view in graph[model]["importers"]

    def test_partial_referenced_by_string_creates_edge(self, tmp_path):
        """<partial name="_Card" /> names a view rather than a type."""

        _csproj(tmp_path, root_namespace="Web")
        _write(tmp_path, "Pages/Shared/_Card.cshtml", "<div>card</div>\n")
        _write(
            tmp_path,
            "Pages/Index.cshtml",
            "@page\n<partial name=\"_Card\" />\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        card = _key(tmp_path, "Pages/Shared/_Card.cshtml")
        index = _key(tmp_path, "Pages/Index.cshtml")
        assert index in graph[card]["importers"]

    def test_layout_referenced_by_string_creates_edge(self, tmp_path):
        """Layout = "_Layout" names a view rather than a type."""

        _csproj(tmp_path, root_namespace="Web")
        _write(tmp_path, "Pages/Shared/_Layout.cshtml", "<html>@RenderBody()</html>\n")
        _write(tmp_path, "Pages/_ViewStart.cshtml", "@{ Layout = \"_Layout\"; }\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        layout = _key(tmp_path, "Pages/Shared/_Layout.cshtml")
        view_start = _key(tmp_path, "Pages/_ViewStart.cshtml")
        assert view_start in graph[layout]["importers"]

    def test_view_component_convention_creates_edge(self, tmp_path):
        """InvokeAsync("Basket") resolves to BasketViewComponent by convention."""

        _csproj(tmp_path, root_namespace="Web")
        _write(
            tmp_path,
            "ViewComponents/BasketViewComponent.cs",
            "namespace Web.ViewComponents;\n\n"
            "public class BasketViewComponent : ViewComponent { }\n",
        )
        _write(
            tmp_path,
            "Pages/Index.cshtml",
            "@page\n@await Component.InvokeAsync(\"Basket\")\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        component = _key(tmp_path, "ViewComponents/BasketViewComponent.cs")
        index = _key(tmp_path, "Pages/Index.cshtml")
        assert index in graph[component]["importers"]

    def test_tag_helper_convention_creates_edge(self, tmp_path):
        """<price-tag /> resolves to PriceTagTagHelper by convention."""

        _csproj(tmp_path, root_namespace="Web")
        _write(
            tmp_path,
            "TagHelpers/PriceTagTagHelper.cs",
            "namespace Web.TagHelpers;\n\npublic class PriceTagTagHelper : TagHelper { }\n",
        )
        _write(tmp_path, "Pages/Index.cshtml", "@page\n<price-tag amount=\"1\" />\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        helper = _key(tmp_path, "TagHelpers/PriceTagTagHelper.cs")
        index = _key(tmp_path, "Pages/Index.cshtml")
        assert index in graph[helper]["importers"]

    def test_unused_tag_helper_is_not_linked_from_views(self, tmp_path):
        """Convention matching must not link a tag helper no view uses."""

        _csproj(tmp_path, root_namespace="Web")
        _write(
            tmp_path,
            "TagHelpers/UnusedTagHelper.cs",
            "namespace Web.TagHelpers;\n\npublic class UnusedTagHelper : TagHelper { }\n",
        )
        _write(tmp_path, "Pages/Index.cshtml", "@page\n<p>nothing custom here</p>\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        helper = _key(tmp_path, "TagHelpers/UnusedTagHelper.cs")
        index = _key(tmp_path, "Pages/Index.cshtml")
        assert index not in graph[helper]["importers"]


# ── Interaction with the shared detectors ───────────────────────


class TestRazorAndOrphanDetection:
    def test_view_files_do_not_appear_orphaned(self, tmp_path):
        """Views are excluded from the orphan check by the extensions filter."""

        _csproj(tmp_path)
        _write(tmp_path, "Pages/Home.razor", "@page \"/\"\n<h1>Home</h1>\n")

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        orphans, _ = orphaned_detector_mod.detect_orphaned_files(
            tmp_path,
            graph,
            extensions=[".cs"],
            options=orphaned_detector_mod.OrphanedDetectionOptions(
                extra_entry_patterns=[],
                extra_barrel_names=set(),
            ),
        )
        orphan_files = {e["file"] for e in orphans}
        assert _key(tmp_path, "Pages/Home.razor") not in orphan_files

    def test_project_without_views_is_unaffected(self, tmp_path):
        """A view-free project builds the same graph as before."""

        _csproj(tmp_path)
        _write(
            tmp_path,
            "Services/Thing.cs",
            "namespace App.Services;\n\npublic class Thing { }\n",
        )

        graph = deps_detector_mod.build_dep_graph(tmp_path)
        thing = _key(tmp_path, "Services/Thing.cs")
        assert thing in graph
        assert graph[thing]["importers"] == set()
