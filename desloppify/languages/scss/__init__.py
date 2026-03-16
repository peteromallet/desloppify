"""SCSS language plugin -- stylelint."""

from desloppify.languages._framework.generic_support.core import generic_lang

generic_lang(
    name="scss",
    extensions=[".scss", ".sass"],
    tools=[
        {
            "label": "stylelint",
            "cmd": "stylelint {file_path} --formatter json --max-warnings 1000",
            "fmt": "json",
            "id": "stylelint_issue",
            "tier": 2,
            "fix_cmd": "stylelint --fix {file_path}",
        },
    ],
    exclude=["node_modules", "_output", ".quarto", "vendor"],
    detect_markers=["_scss", ".stylelintrc"],
    treesitter_spec=None,
)

__all__ = [
    "generic_lang",
]
