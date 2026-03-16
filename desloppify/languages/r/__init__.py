"""R language plugin — lintr + tree-sitter."""

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import R_SPEC

generic_lang(
    name="r",
    extensions=[".R", ".r"],
    tools=[
        {
            "label": "lintr",
            "cmd": (
                "Rscript -e \"lintr::lint_dir('.')\""
            ),
            "fmt": "gnu",
            "id": "lintr_lint",
            "tier": 2,
            "fix_cmd": None,
        },
    ],
    exclude=[".Rhistory", ".RData", ".Rproj.user", "renv", "packrat"],
    depth="shallow",
    detect_markers=["DESCRIPTION", ".Rproj"],
    default_src="R",
    treesitter_spec=R_SPEC,
)

__all__ = [
    "generic_lang",
    "R_SPEC",
]
