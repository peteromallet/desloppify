# Lua Language Plugin for Desloppify

Provides Lua analysis via [luacheck](https://github.com/mpeterv/luacheck).

## Supported extensions

`.lua`

## Requirements

```bash
# Install luacheck (requires Lua + LuaRocks)
luarocks install luacheck
```

## Project detection

The plugin activates on any project containing `.lua` files.

## Usage

```bash
# Scan a project
desloppify scan --path <project>
```

Luacheck does not support auto-fix; there is no autofix command for this plugin.
