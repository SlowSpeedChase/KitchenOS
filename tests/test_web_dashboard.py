"""Tests for the KitchenOS Web dashboard generator."""

from lib import web_dashboard as wd


class TestBaseUrl:
    def test_default_is_tailnet_host(self, monkeypatch):
        monkeypatch.delenv("KITCHENOS_API_BASE", raising=False)
        assert wd.base_url() == wd.DEFAULT_API_BASE
        assert "ts.net" in wd.base_url()  # MagicDNS, not a raw 100.x IP

    def test_env_override_wins_and_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("KITCHENOS_API_BASE", "http://box.tailnet.ts.net:5001/")
        assert wd.base_url() == "http://box.tailnet.ts.net:5001"


class TestRenderMarkdown:
    def test_links_all_key_routes_against_base(self):
        base = "http://box.tailnet.ts.net:5001"
        md = wd.render_markdown(base)
        for path in ("/meal-planner", "/nutrition-review", "/system-health",
                     "/current/meal-plan", "/current/shopping-list"):
            assert f"({base}{path})" in md

    def test_has_frontmatter_and_generated_banner(self):
        md = wd.render_markdown("http://x.ts.net:5001")
        assert md.startswith("---\ntype: web-dashboard\n---")
        assert "**Generated**" in md
        assert "Do not edit here" in md

    def test_no_localhost_links(self):
        # The whole point: links must be reachable off the server host.
        md = wd.render_markdown("http://box.tailnet.ts.net:5001")
        assert "localhost" not in md
        assert "127.0.0.1" not in md

    def test_uses_env_base_when_none_passed(self, monkeypatch):
        monkeypatch.setenv("KITCHENOS_API_BASE", "http://envhost.ts.net:5001")
        md = wd.render_markdown()
        assert "http://envhost.ts.net:5001/meal-planner" in md


class TestWriteNote:
    def test_writes_into_dashboards_subdir(self, tmp_vault):
        path = wd.write_note()
        assert path.exists()
        assert path.parent.name == "Dashboards"
        assert path.name == "KitchenOS Web.md"
        assert "Meal Planner" in path.read_text(encoding="utf-8")
