"""SCSS/Sass language plugin for desloppify."""

from __future__ import annotations

from desloppify.languages._framework.generic_support.core import generic_lang


def register() -> None:
    """Register SCSS language plugin with desloppify framework."""
    generic_lang(
        name="scss",
        extensions=[".scss", ".sass"],
        tools=[{
            'label': 'stylelint',
            'cmd': 'stylelint "**/*.scss" "**/*.sass" --formatter unix --max-warnings 1000',
            'fmt': 'gnu',
            'id': 'stylelint_issue',
            'tier': 2,
            'fix_cmd': 'stylelint --fix "**/*.scss" "**/*.sass"',
        }],
        exclude=["node_modules", "_output", ".quarto", "vendor"],
        detect_markers=["_scss", ".stylelintrc"],
        treesitter_spec=None,
    )


__all__ = ["register"]
