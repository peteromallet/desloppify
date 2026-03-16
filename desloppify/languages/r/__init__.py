"""R language plugin — Jarl, lintr + tree-sitter."""

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import R_SPEC

generic_lang(
    name="r",
    extensions=[".R", ".r"],
    tools=[
        {
            "label": "jarl",
            "cmd": "jarl check .",
            "fmt": "gnu",
            "id": "jarl_lint",
            "tier": 2,
            "fix_cmd": "jarl check . --fix --allow-dirty",
        },
        {
            "label": "lintr",
            "cmd": (
                "Rscript -e \"lintr::lint_dir('.')\""
            ),
            "fmt": "gnu",
            "id": "lintr_lint",
            "tier": 3,
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
