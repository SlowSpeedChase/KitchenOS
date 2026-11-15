"""Turn a command's typed destination into a same-origin path.

The engine returns *what* to open (a recipe, a day, a page), never a URL. This
is the only place that becomes a path, so the client never builds one. Shaped
like api_server._handoff_destination, which does the same job for Siri.
"""
from datetime import date
from urllib.parse import quote

from lib import paths
from lib.safe_paths import contained_markdown

_FIXED = {"planner": "/meal-planner", "home": "/", "inventory": "/review"}


def href_for(navigate) -> str | None:
    if not isinstance(navigate, dict):
        return None
    page = navigate.get("page")
    if page in _FIXED:
        return _FIXED[page]
    if page == "recipe":
        name = navigate.get("recipe")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            return None
        try:
            if not contained_markdown(paths.recipes_dir(), name + ".md").is_file():
                return None
        except ValueError:
            return None
        return "/recipe/" + quote(name, safe="")
    if page == "day":
        try:
            day = date.fromisoformat(navigate.get("date"))
        except (TypeError, ValueError):
            return None
        iso = day.isocalendar()
        return (f"/meal-planner?week={iso.year:04d}-W{iso.week:02d}"
                f"&date={day.isoformat()}&view=calendar")
    return None
