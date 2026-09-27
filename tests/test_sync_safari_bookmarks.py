"""Test desired bookmark URLs only; never open Safari or its plist."""
import pytest

from scripts.sync_safari_bookmarks import desired_bookmarks


def test_bookmarks_use_canonical_https():
    wanted = desired_bookmarks()
    assert wanted
    assert all(url.startswith("https://chases-mac-mini.taila69703.ts.net/") for _, url in wanted)


@pytest.mark.parametrize("variable", ["KITCHENOS_WEB_BASE_URL", "KITCHENOS_API_BASE"])
def test_bookmarks_use_origin_override(monkeypatch, variable):
    monkeypatch.setenv(variable, "https://bookmarks.example/")
    assert all(url.startswith("https://bookmarks.example/") for _, url in desired_bookmarks())
