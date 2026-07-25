"""Tests for the KitchenOS Web dashboard generator.

``TestPageRegistryIsComplete`` is the net under the "new page → new bookmark"
rule in CLAUDE.md: a browsable page added to ``api_server.py`` fails the suite
until it is either registered in ``SECTIONS`` or listed as unbookmarkable here.
"""

from lib import web_dashboard as wd

# Routes that are GET, take no path arguments, and are not under /api/ — but are
# not pages a human would ever bookmark. Every entry needs a reason; if you find
# yourself adding a real page here, put it in SECTIONS instead.
NOT_BOOKMARKABLE = {
    "/health": "JSON liveness probe, not a page",
    "/calendar.ics": "ICS feed — subscribed in Calendar, not bookmarked",
    "/transcript": "needs ?url=; a tool endpoint, not a destination",
    "/add-to-meal-plan": "needs ?recipe=; opened from a recipe note's button",
    "/reprocess": "needs ?file=; opened from a recipe note's button",
    "/refresh": "needs ?file=; opened from a recipe note's button",
    "/refresh-nutrition": "needs ?week=; opened from the nutrition dashboard",
}


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


class TestHome:
    def test_home_is_the_registry_root_not_a_section_entry(self):
        assert wd.HOME[2] == "/"
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        assert "/" not in registered, "HOME in SECTIONS would make the page list itself"

    def test_markdown_note_links_home_first(self):
        md = wd.render_markdown("http://box.tailnet.ts.net:5001")
        assert "http://box.tailnet.ts.net:5001/" in md
        assert md.index(wd.HOME[1]) < md.index("Meal Planner")


class TestSafariBookmarks:
    """desired_bookmarks() builds from SECTIONS, so HOME must be added explicitly."""

    @staticmethod
    def _wanted():
        from scripts.sync_safari_bookmarks import desired_bookmarks
        return desired_bookmarks("http://box.tailnet.ts.net:5001")

    def test_home_is_bookmarked_first(self):
        wanted = self._wanted()
        assert wanted[0] == (wd.HOME[1], "http://box.tailnet.ts.net:5001/")

    def test_every_section_page_still_bookmarked(self):
        urls = {url for _title, url in self._wanted()}
        for _s, items in wd.SECTIONS:
            for _e, _t, path, _d in items:
                assert f"http://box.tailnet.ts.net:5001{path}" in urls


class TestRenderHtml:
    def test_renders_every_section_and_page(self):
        from html import escape
        html = wd.render_html()
        for section_title, items in wd.SECTIONS:
            assert escape(section_title) in html
            for _emoji, title, path, _desc in items:
                assert escape(title) in html
                assert f'href="{path}"' in html

    def test_links_are_relative_by_default(self):
        html = wd.render_html()
        assert 'href="/review"' in html
        assert "ts.net" not in html

    def test_base_prefixes_links_when_given(self):
        html = wd.render_html("http://box.tailnet.ts.net:5001")
        assert 'href="http://box.tailnet.ts.net:5001/review"' in html

    def test_is_a_fragment_not_a_document(self):
        html = wd.render_html()
        assert "<!doctype" not in html.lower()
        assert "<body" not in html.lower()

    def test_escapes_text_so_prose_cannot_inject_markup(self, monkeypatch):
        monkeypatch.setattr(
            wd, "SECTIONS",
            [("S & T", [("x", "A<b>Title", "/p", 'desc "quoted" & <i>')])],
        )
        html = wd.render_html()
        assert "A&lt;b&gt;Title" in html
        assert "<b>" not in html
        assert "<i>" not in html
        assert "S &amp; T" in html


class TestPageRegistryIsComplete:
    """SECTIONS must account for every browsable page api_server serves."""

    @staticmethod
    def _candidate_routes():
        # Imported lazily: pulling in api_server is slow and only this test needs it.
        import api_server

        return {
            rule.rule
            for rule in api_server.app.url_map.iter_rules()
            # Parameterised routes (/recipe/<name>, /images/<path:filename>) can't
            # be bookmarked as a fixed URL, so they're structurally exempt.
            if "GET" in rule.methods
            and not rule.arguments
            and not rule.rule.startswith("/api/")
            and not rule.rule.startswith("/static/")
        }

    def test_every_browsable_route_is_registered_or_exempt(self):
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        registered.add(wd.HOME[2])  # the registry root, rendered by the page itself
        unaccounted = self._candidate_routes() - registered - set(NOT_BOOKMARKABLE)
        assert not unaccounted, (
            f"new page route(s) {sorted(unaccounted)} are neither in "
            "lib/web_dashboard.py SECTIONS nor in NOT_BOOKMARKABLE. Add a page to "
            "SECTIONS (then run scripts/generate_web_dashboard.py and "
            "scripts/sync_safari_bookmarks.py --apply), or list it as "
            "unbookmarkable here with a reason."
        )

    def test_registry_has_no_dead_routes(self):
        registered = {path for _s, items in wd.SECTIONS for _e, _t, path, _d in items}
        registered.add(wd.HOME[2])
        assert not registered - self._candidate_routes(), (
            "SECTIONS lists route(s) api_server no longer serves — the launcher "
            "note and the Safari bookmarks would 404."
        )

    def test_exempt_list_has_no_dead_routes(self):
        assert not set(NOT_BOOKMARKABLE) - self._candidate_routes(), (
            "NOT_BOOKMARKABLE lists route(s) that no longer exist — drop them."
        )


class TestWriteNote:
    def test_writes_into_dashboards_subdir(self, tmp_vault):
        path = wd.write_note()
        assert path.exists()
        assert path.parent.name == "Dashboards"
        assert path.name == "KitchenOS Web.md"
        assert "Meal Planner" in path.read_text(encoding="utf-8")
