#!/usr/bin/env python3
"""Regenerate the 'Dashboards/KitchenOS Web.md' vault note.

A tap-anywhere launcher for the KitchenOS web app whose links point at the
Tailscale host (``KITCHENOS_API_BASE``), so they work from any device on the
tailnet. Run after changing the web base URL. See lib/web_dashboard.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import web_dashboard  # noqa: E402


def main() -> int:
    path = web_dashboard.write_note()
    print(f"Wrote {path}")
    print(f"Base URL: {web_dashboard.base_url()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
