"""One validated public origin for generated KitchenOS links.

KITCHENOS_WEB_BASE_URL takes precedence over deprecated KITCHENOS_API_BASE.
Internal service calls deliberately keep their own loopback HTTP endpoints.
"""
import os
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

CANONICAL_WEB_ORIGIN = "https://chases-mac-mini.taila69703.ts.net"

# urlsplit separates URL parts but does not validate DNS/authority characters.
# Accept DNS labels (including IDNA), IPv4, and bracketed IPv6, with a port.
_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_AUTHORITY = re.compile(
    rf"(?:{_DNS_LABEL}(?:\.{_DNS_LABEL})*\.?|\[[0-9A-Fa-f:.]+\])(?::[0-9]+)?"
)


def web_origin(environ: Mapping[str, str] = os.environ) -> str:
    """Resolve an HTTP(S) origin, stripping root slashes; reject URL extras."""
    raw = environ.get("KITCHENOS_WEB_BASE_URL",
                      environ.get("KITCHENOS_API_BASE", CANONICAL_WEB_ORIGIN))
    error = "KitchenOS web origin must be HTTP(S), with a host and no credentials, path, query, or fragment"
    try:
        parsed = urlsplit(raw)
        _ = parsed.port  # Validate malformed/out-of-range ports too.
        authority = parsed.netloc
        if not authority.startswith("["):
            # Encode only the DNS name: a port is not part of an IDNA label.
            host, separator, port = authority.partition(":")
            authority = host.encode("idna").decode("ascii") + separator + port
    except (ValueError, UnicodeError):
        raise ValueError(error) from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or not _AUTHORITY.fullmatch(authority)
            or parsed.username is not None or parsed.password is not None
            or parsed.path.strip("/") or "?" in raw or "#" in raw
            or any(char.isspace() or ord(char) < 32 for char in raw)
            or "\\" in raw):
        raise ValueError(error)
    return raw.rstrip("/")
