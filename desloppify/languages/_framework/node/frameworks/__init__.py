"""Node ecosystem framework scanners (Next.js, etc).

Framework presence detection now lives under
``desloppify.languages._framework.frameworks``.

This package remains the shared home for framework scanners and helper code so
JS/TS language plugins can reuse the same framework checks without duplicating
logic or importing across plugins.
"""

from __future__ import annotations

__all__: list[str] = []
