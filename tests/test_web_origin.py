"""Public-origin validation without touching service configuration or data."""
import pytest

from lib.web_origin import web_origin as resolve

CANONICAL = "https://chases-mac-mini.taila69703.ts.net"


def test_default_is_canonical_https():
    assert resolve({}) == CANONICAL


def test_new_variable_wins_over_legacy():
    assert resolve({"KITCHENOS_WEB_BASE_URL": "https://new.example/", "KITCHENOS_API_BASE": "http://old.example:5001"}) == "https://new.example"


def test_legacy_override_remains_supported():
    assert resolve({"KITCHENOS_API_BASE": "http://legacy.example:5001/"}) == "http://legacy.example:5001"


@pytest.mark.parametrize("value", ["https://host.example", "https://host.example/", "https://host.example///"])
def test_trailing_slashes_are_normalized(value):
    assert resolve({"KITCHENOS_WEB_BASE_URL": value}) == "https://host.example"


@pytest.mark.parametrize("value", ["https://user:secret@host.example", "https://host.example/path", "https://host.example?q=1", "https://host.example#fragment", "ftp://host.example", "host.example", "https://", "", "https://host.example:bad", "https://host.example?", "https://host.example#"])
def test_rejects_non_origins(value):
    with pytest.raises(ValueError):
        resolve({"KITCHENOS_WEB_BASE_URL": value})


def test_internal_mcp_stays_loopback():
    from lib.mcp_tools import API_BASE
    assert API_BASE == "http://localhost:5001"
