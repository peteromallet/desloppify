"""Shared regex patterns for GDScript source parsing."""

from __future__ import annotations

import re

LOAD_PATH_RE = re.compile(
    r"""(?:preload|load)\(\s*['"](?P<path>res://[^'"]+\.gd)['"]\s*\)"""
)
EXTENDS_RE = re.compile(r"""(?m)^\s*extends\s+['"](?P<path>res://[^'"]+\.gd)['"]""")

# `class_name Foo` registers Foo in Godot's global class registry, making the
# script reachable from any other script by bare identifier, with no import.
CLASS_NAME_RE = re.compile(r"(?m)^\s*class_name\s+(?P<name>[A-Za-z_]\w*)")

# Scenes and resources attach scripts by path:
#   [ext_resource type="Script" path="res://foo.gd" id="1_abc"]
# Attribute order varies between Godot versions, so match the header loosely
# and pull the path out of its attributes.
SCENE_EXT_RESOURCE_RE = re.compile(r"(?m)^\[ext_resource\s+(?P<attrs>[^\]]*)\]")
RES_PATH_ATTR_RE = re.compile(r'path\s*=\s*"(?P<path>res://[^"]+\.gd)"')

# project.godot autoload entries are singletons the engine loads at boot:
#   [autoload]
#   NetworkManager="*res://Scripts/Net/network_manager.gd"
AUTOLOAD_SECTION_RE = re.compile(r"(?ms)^\[autoload\]\s*$(?P<body>.*?)(?=^\[|\Z)")
AUTOLOAD_PATH_RE = re.compile(r"""["']\*?(?P<path>res://[^"']+\.gd)["']""")

# Any bare `res://…gd` literal is a runtime reference: registries and catalogs
# routinely hold a script path in a data table and `load()` it later, which no
# preload/extends pattern can see.
RES_SCRIPT_LITERAL_RE = re.compile(r"""["'](?P<path>res://[^"']+\.gd)["']""")

# Comments and string literals yield false identifier matches when scanning for
# class_name usage, so strip them first.
COMMENT_RE = re.compile(r"(?m)#.*$")
STRING_RE = re.compile(r"""(?s)\"\"\".*?\"\"\"|'''.*?'''|"[^"\n]*"|'[^'\n]*'""")

__all__ = [
    "AUTOLOAD_PATH_RE",
    "AUTOLOAD_SECTION_RE",
    "CLASS_NAME_RE",
    "COMMENT_RE",
    "EXTENDS_RE",
    "LOAD_PATH_RE",
    "RES_PATH_ATTR_RE",
    "RES_SCRIPT_LITERAL_RE",
    "SCENE_EXT_RESOURCE_RE",
    "STRING_RE",
]
