"""Ruby language plugin — rubocop.

Registers a generic desloppify language plugin for Ruby projects.  RuboCop is
the sole external tool requirement; tree-sitter provides function/class
extraction for duplicate detection and import-graph analysis at no extra cost.
"""

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import RUBY_SPEC

generic_lang(
    name="ruby",
    extensions=[".rb"],
    tools=[
        {
            "label": "rubocop",
            # JSON output is stable across RuboCop versions and machine-parseable.
            "cmd": "rubocop --format=json",
            "fmt": "rubocop",
            "id": "rubocop_offense",
            # Tier 2 = non-blocking advisory finding (not a hard error).
            "tier": 2,
            # --auto-correct applies only offenses RuboCop marks as safe.
            "fix_cmd": "rubocop --auto-correct",
        },
    ],
    exclude=[
        "vendor",    # Bundled third-party gems (vendored dependencies)
        ".bundle",   # Bundler cache directory — not project source
        "coverage",  # SimpleCov / test coverage output
        "tmp",       # Rails/Rack temp files (cache, pids, sockets)
        "log",       # Application log files
        "bin",       # Binstubs and shims
    ],
    # "shallow" depth is upgraded to "standard" automatically when tree-sitter
    # is available (generic_support/core.py:131).  No need to set "full" here.
    depth="shallow",
    # Ruby convention: library source lives in lib/, not the project root.
    default_src="lib",
    # Ruby convention: tests live in spec/ (RSpec) or test/ (Minitest).
    external_test_dirs=["spec", "test"],
    detect_markers=[
        "Gemfile",       # Bundler dependency manifest — most Ruby projects
        "Rakefile",      # Build/task file — present even without Bundler
        ".ruby-version", # rbenv/rvm version pin — reliable project marker
        "*.gemspec",     # Gem specification — present in library/gem projects
    ],
    treesitter_spec=RUBY_SPEC,
)

__all__ = [
    "generic_lang",
    "RUBY_SPEC",
]
