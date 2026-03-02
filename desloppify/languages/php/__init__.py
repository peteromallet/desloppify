"""PHP language plugin — phpstan + tree-sitter + Laravel-aware hooks."""

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.languages._framework.generic import generic_lang
from desloppify.languages._framework.treesitter import PHP_SPEC
from desloppify.languages.php import test_coverage as _test_coverage_mod

# ── Zone rules ────────────────────────────────────────────────

PHP_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, ["/database/migrations/", "/storage/", "/bootstrap/cache/"]),
    ZoneRule(Zone.TEST, [
        "/tests/", "Test.php", "TestCase.php",
        "/factories/", "Pest.php",
    ]),
    ZoneRule(Zone.CONFIG, [
        "/config/", "composer.json", ".env", ".env.example",
        "phpunit.xml", "phpstan.neon", "webpack.mix.js", "vite.config.js",
    ]),
    ZoneRule(Zone.SCRIPT, [
        "artisan",
        "/database/seeders/",
    ]),
] + COMMON_ZONE_RULES

# ── Entry patterns (files legitimately having zero importers) ─

PHP_ENTRY_PATTERNS = [
    # Laravel runtime entrypoints
    "/routes/",
    "/app/Http/Controllers/",
    "/app/Console/Commands/",
    "/app/Http/Middleware/",
    "/app/Providers/",
    "/app/Jobs/",
    "/app/Listeners/",
    "/app/Mail/",
    "/app/Notifications/",
    "/app/Policies/",
    "/app/Events/",
    "/app/Observers/",
    "/app/Rules/",
    "/app/Casts/",
    # Test files
    "/tests/",
    "Test.php",
    # Config / bootstrap
    "/config/",
    "/database/migrations/",
    "/database/seeders/",
    "/database/factories/",
    "/resources/views/",
]

# ── Plugin registration ──────────────────────────────────────

generic_lang(
    name="php",
    extensions=[".php"],
    tools=[
        {
            "label": "phpstan",
            "cmd": "phpstan analyse --error-format=json --no-progress",
            "fmt": "json",
            "id": "phpstan_error",
            "tier": 2,
            "fix_cmd": None,
        },
    ],
    exclude=[
        "vendor", "storage", "bootstrap/cache", "node_modules",
        "_ide_helper.php", "_ide_helper_models.php", ".phpstorm.meta.php",
    ],
    depth="shallow",
    detect_markers=["composer.json"],
    treesitter_spec=PHP_SPEC,
    zone_rules=PHP_ZONE_RULES,
    test_coverage_module=_test_coverage_mod,
    entry_patterns=PHP_ENTRY_PATTERNS,
)
