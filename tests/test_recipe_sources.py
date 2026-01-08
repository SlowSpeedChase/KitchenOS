"""Tests for recipe_sources module"""

import pytest
from recipe_sources import find_recipe_link


class TestFindRecipeLink:
    """Tests for find_recipe_link function"""

    def test_explicit_recipe_label(self):
        """Finds URL after 'Recipe:' label"""
        description = """Check out my channel!
Recipe: https://www.bingingwithbabish.com/recipes/pasta
Follow me on Instagram"""
        result = find_recipe_link(description)
        assert result == "https://www.bingingwithbabish.com/recipes/pasta"

    def test_full_recipe_label(self):
        """Finds URL after 'Full recipe:' label"""
        description = "Full recipe: https://example.com/recipe"
        result = find_recipe_link(description)
        assert result == "https://example.com/recipe"

    def test_nearby_keyword(self):
        """Finds URL on same line as 'recipe' keyword"""
        description = "Get the recipe here: https://seriouseats.com/pasta"
        result = find_recipe_link(description)
        assert result == "https://seriouseats.com/pasta"

    def test_known_domain(self):
        """Finds URL from known recipe domain without keyword"""
        description = """Links:
https://www.bonappetit.com/recipe/chicken
https://patreon.com/channel"""
        result = find_recipe_link(description)
        assert result == "https://www.bonappetit.com/recipe/chicken"

    def test_excludes_social_media(self):
        """Ignores social media URLs"""
        description = """Recipe links:
https://instagram.com/chef
https://twitter.com/chef"""
        result = find_recipe_link(description)
        assert result is None

    def test_excludes_affiliate_links(self):
        """Ignores Amazon affiliate URLs"""
        description = "Buy the pan: https://amzn.to/abc123"
        result = find_recipe_link(description)
        assert result is None

    def test_excludes_youtube(self):
        """Ignores YouTube URLs"""
        description = "Watch this: https://youtube.com/watch?v=abc"
        result = find_recipe_link(description)
        assert result is None

    def test_no_recipe_link(self):
        """Returns None when no recipe link found"""
        description = "Thanks for watching! Like and subscribe."
        result = find_recipe_link(description)
        assert result is None

    def test_first_match_wins(self):
        """Returns first matching URL"""
        description = """Recipe: https://first.com/recipe
Recipe: https://second.com/recipe"""
        result = find_recipe_link(description)
        assert result == "https://first.com/recipe"
