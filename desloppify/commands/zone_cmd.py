"""zone command: show/set/clear zone classifications."""

from pathlib import Path

from ..utils import colorize, rel
from ._helpers import state_path
from ..zones import Zone


def cmd_zone(args):
    """Handle zone subcommands: show, set, clear."""
    action = getattr(args, "zone_action", None)
    if action == "show":
        _zone_show(args)
    elif action == "set":
        _zone_set(args)
    elif action == "clear":
        _zone_clear(args)
    else:
        print(colorize("Usage: desloppify zone {show|set|clear}", "red"))


def _zone_show(args):
    """Show zone classifications for all scanned files."""
    from ..state import load_state
    from ._helpers import resolve_lang

    sp = state_path(args)
    load_state(sp)  # validate state file exists/loads
    lang = resolve_lang(args)
    if not lang or not lang.file_finder:
        print(colorize("No language detected — run a scan first.", "red"))
        return

    path = Path(args.path)
    overrides = args._config.get("zone_overrides", {})

    from ..zones import FileZoneMap
    files = lang.file_finder(path)
    zone_map = FileZoneMap(files, lang.zone_rules, rel_fn=rel, overrides=overrides or None)

    # Group files by zone
    by_zone: dict[str, list[str]] = {}
    for f in sorted(files, key=lambda f: rel(f)):
        zone = zone_map.get(f)
        by_zone.setdefault(zone.value, []).append(f)

    total = len(files)
    print(colorize(f"\nZone classifications ({total} files)\n", "bold"))

    for zone_val in ["production", "test", "config", "generated", "script", "vendor"]:
        zone_files = by_zone.get(zone_val, [])
        if not zone_files:
            continue
        print(colorize(f"  {zone_val} ({len(zone_files)} files)", "bold"))
        for f in zone_files:
            rp = rel(f)
            is_override = rp in overrides
            suffix = colorize(" (override)", "cyan") if is_override else ""
            print(f"    {rp}{suffix}")
        print()

    if overrides:
        print(colorize(f"  {len(overrides)} override(s) active", "dim"))
    print(colorize("  Override: desloppify zone set <file> <zone>", "dim"))
    print(colorize("  Clear:    desloppify zone clear <file>", "dim"))


def _zone_set(args):
    """Set a zone override for a file."""
    from ..config import save_config

    filepath = args.zone_path
    zone_value = args.zone_value

    # Validate zone value
    valid_zones = {z.value for z in Zone}
    if zone_value not in valid_zones:
        print(colorize(f"Invalid zone: {zone_value}. Valid: {', '.join(sorted(valid_zones))}", "red"))
        return

    config = args._config
    config.setdefault("zone_overrides", {})[filepath] = zone_value
    save_config(config)
    print(f"  Set {filepath} → {zone_value}")
    print(colorize("  Run `desloppify scan` to apply.", "dim"))


def _zone_clear(args):
    """Clear a zone override for a file."""
    from ..config import save_config

    filepath = args.zone_path

    overrides = args._config.get("zone_overrides", {})
    if filepath in overrides:
        del overrides[filepath]
        save_config(args._config)
        print(f"  Cleared override for {filepath}")
        print(colorize("  Run `desloppify scan` to apply.", "dim"))
    else:
        print(colorize(f"  No override found for {filepath}", "yellow"))
