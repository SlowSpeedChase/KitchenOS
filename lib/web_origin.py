"""One validated public origin for generated KitchenOS links.

KITCHENOS_WEB_BASE_URL takes precedence over deprecated KITCHENOS_API_BASE.
Internal service calls deliberately keep their own loopback HTTP endpoints.
"""
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

CANONICAL_WEB_ORIGIN = "https://chases-mac-mini.taila69703.ts.net"


def web_origin(environ: Mapping[str, str] = os.environ) -> str:
    """Resolve an HTTP(S) origin, stripping root slashes; reject URL extras."""
    raw = environ.get("KITCHENOS_WEB_BASE_URL",
                      environ.get("KITCHENOS_API_BASE", CANONICAL_WEB_ORIGIN))
    error = "KitchenOS web origin must be HTTP(S), with a host and no credentials, path, query, or fragment"
    try:
        parsed = urlsplit(raw)
        _ = parsed.port  # Validate malformed/out-of-range ports too.
    except ValueError:
        raise ValueError(error) from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path.strip("/") or "?" in raw or "#" in raw
            or any(char.isspace() or ord(char) < 32 for char in raw)
            or "\\" in raw):
        raise ValueError(error)
    return raw.rstrip("/")
