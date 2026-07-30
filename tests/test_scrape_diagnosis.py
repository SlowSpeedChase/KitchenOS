"""Tests for honest diagnosis of failed recipe scrapes.

Regression cover for the 2026-07-29 batch failure on heb.com, which reported
"No structured recipe (JSON-LD) found on page". That message blamed the page for
lacking a recipe. What actually happened: Imperva/Incapsula served a ~900-byte
challenge page with HTTP 200 and zero JSON-LD. The recipe is there; we were
blocked. A wrong diagnosis sends the next reader looking for a parser bug.
"""
import requests
from unittest.mock import patch, Mock

from recipe_sources import (
    looks_like_bot_wall,
    scrape_recipe_from_url,
    fetch_recipe_with_diagnosis,
)


# Trimmed from the real response captured from heb.com on 2026-07-29.
HEB_INCAPSULA_WALL = (
    '<html style="height:100%"><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW">'
    '<meta name="format-detection" content="telephone=no">'
    '<script src="/u-How-Aleppose-Yet-this-gone-Bear-Bound-say-Hayl" async></script></head>'
    '<body style="margin:0px;height:100%"><iframe id="main-iframe" '
    'src="/_Incapsula_Resource?SWUDNSAI=31&xinfo=2-13698587-0%200NNN%20RT&'
    'incident_id=1178000740050542284-647199216627"></iframe></body></html>'
)

CLOUDFLARE_WALL = (
    '<html><head><title>Just a moment...</title></head>'
    '<body><div id="cf-browser-verification"></div>'
    '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
    '</body></html>'
)

REAL_RECIPE_HTML = '''
<html><head>
<script type="application/ld+json">
{"@type": "Recipe", "name": "Larb Lettuce Wraps", "recipeIngredient": ["1 lb pork"]}
</script>
</head><body><h1>Larb</h1></body></html>
'''

# allrecipes.com and bonappetit.com both serve *working* 500KB+ recipe pages that
# carry Cloudflare's challenge-platform script — it is injected into ordinary
# pages, not just interstitials. Matching that marker alone flagged both as
# blocked and would have killed scraping on every Cloudflare-fronted recipe site.
CLOUDFLARE_FRONTED_REAL_PAGE = '''
<html><head>
<script src="/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js"></script>
<script type="application/ld+json">
{"@type": "Recipe", "name": "World's Best Lasagna", "recipeIngredient": ["1 lb beef"]}
</script>
</head><body><h1>Lasagna</h1></body></html>
'''


def _mock_response(text, status_code=200):
    resp = Mock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = Mock()
    return resp


class TestLooksLikeBotWall:
    """Marker detection must be specific enough not to libel real recipe pages."""

    def test_detects_incapsula(self):
        assert looks_like_bot_wall(HEB_INCAPSULA_WALL) is True

    def test_detects_cloudflare_challenge(self):
        assert looks_like_bot_wall(CLOUDFLARE_WALL) is True

    def test_real_recipe_page_is_not_a_wall(self):
        assert looks_like_bot_wall(REAL_RECIPE_HTML) is False

    def test_empty_html_is_not_a_wall(self):
        assert looks_like_bot_wall("") is False
        assert looks_like_bot_wall(None) is False

    def test_cloudflare_script_on_a_real_recipe_page_is_not_a_wall(self):
        """Regression: the marker rides along on working pages (allrecipes,
        bonappetit). Content present means we were not blocked."""
        assert looks_like_bot_wall(CLOUDFLARE_FRONTED_REAL_PAGE) is False

    def test_recipe_mentioning_captcha_prose_is_not_a_wall(self):
        """A blog post that merely says 'captcha' must not be called a bot wall."""
        html = (
            '<html><body><p>I had to solve a captcha to get this recipe, '
            'access denied at first!</p>'
            '<script type="application/ld+json">{"@type":"Recipe","name":"X"}</script>'
            '</body></html>'
        )
        assert looks_like_bot_wall(html) is False


class TestFetchRecipeWithDiagnosis:
    """Returns (recipe, failure_reason) — exactly one is None."""

    def test_bot_wall_reports_blocked_not_missing_recipe(self):
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response(HEB_INCAPSULA_WALL)
            recipe, reason = fetch_recipe_with_diagnosis(
                "https://www.heb.com/recipe/recipe-detail/thai-style-larb-lettuce-wraps"
            )
        assert recipe is None
        assert reason is not None
        # The whole point: it must NOT claim the page has no recipe.
        assert "JSON-LD" not in reason
        assert "heb.com" in reason
        assert "block" in reason.lower() or "challenge" in reason.lower()

    def test_http_403_reports_blocked(self):
        """A hard 403 is a block, not a parse failure."""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response("Forbidden", status_code=403)
            recipe, reason = fetch_recipe_with_diagnosis("https://example.com/recipe")
        assert recipe is None
        assert "403" in reason
        assert "JSON-LD" not in reason

    def test_genuinely_recipeless_page_still_says_no_json_ld(self):
        """The original message is correct here and must survive."""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response('<html><body>About us</body></html>')
            recipe, reason = fetch_recipe_with_diagnosis("https://example.com/about")
        assert recipe is None
        assert "JSON-LD" in reason

    def test_cloudflare_fronted_page_still_yields_its_recipe(self):
        """The regression that matters: a real recipe must survive the marker."""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response(CLOUDFLARE_FRONTED_REAL_PAGE)
            recipe, reason = fetch_recipe_with_diagnosis(
                "https://www.allrecipes.com/recipe/23600/worlds-best-lasagna/"
            )
        assert reason is None
        assert recipe["recipe_name"] == "World's Best Lasagna"

    def test_success_returns_recipe_and_no_reason(self):
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response(REAL_RECIPE_HTML)
            recipe, reason = fetch_recipe_with_diagnosis("https://example.com/recipe")
        assert reason is None
        assert recipe["recipe_name"] == "Larb Lettuce Wraps"

    def test_network_error_reports_unreachable(self):
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            recipe, reason = fetch_recipe_with_diagnosis("https://example.com/recipe")
        assert recipe is None
        assert "JSON-LD" not in reason


class TestScrapeRecipeFromUrlContractUnchanged:
    """5 call sites rely on None-means-try-the-next-link. Don't break them."""

    def test_still_returns_bare_recipe_dict(self):
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response(REAL_RECIPE_HTML)
            result = scrape_recipe_from_url("https://example.com/recipe")
        assert result["recipe_name"] == "Larb Lettuce Wraps"

    def test_still_returns_none_on_bot_wall(self):
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.return_value = _mock_response(HEB_INCAPSULA_WALL)
            assert scrape_recipe_from_url("https://example.com/recipe") is None
