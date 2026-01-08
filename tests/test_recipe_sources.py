"""Tests for recipe_sources module"""

import pytest
from unittest.mock import patch, Mock
import requests
from recipe_sources import find_recipe_link, scrape_recipe_from_url, parse_json_ld_recipe, has_recipe_in_description


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


class TestParseJsonLdRecipe:
    """Tests for JSON-LD recipe parsing"""

    def test_parses_basic_recipe(self):
        """Parses standard Schema.org Recipe"""
        json_ld = {
            "@type": "Recipe",
            "name": "Pasta Aglio e Olio",
            "description": "A simple garlic pasta",
            "prepTime": "PT10M",
            "cookTime": "PT15M",
            "recipeYield": "4 servings",
            "recipeIngredient": [
                "1/2 lb linguine",
                "4 cloves garlic",
            ],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Boil pasta"},
                {"@type": "HowToStep", "text": "Saute garlic"},
            ],
            "recipeCuisine": "Italian",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["recipe_name"] == "Pasta Aglio e Olio"
        assert result["description"] == "A simple garlic pasta"
        assert result["prep_time"] == "10 minutes"
        assert result["cook_time"] == "15 minutes"
        assert result["cuisine"] == "Italian"
        assert len(result["ingredients"]) == 2
        assert len(result["instructions"]) == 2

    def test_handles_string_instructions(self):
        """Handles instructions as plain strings"""
        json_ld = {
            "@type": "Recipe",
            "name": "Simple Recipe",
            "recipeInstructions": ["Step one", "Step two"],
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["instructions"][0]["text"] == "Step one"
        assert result["instructions"][1]["step"] == 2

    def test_handles_single_instruction_string(self):
        """Handles single instruction as string"""
        json_ld = {
            "@type": "Recipe",
            "name": "Simple Recipe",
            "recipeInstructions": "Mix everything and bake.",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["instructions"][0]["text"] == "Mix everything and bake."

    def test_parses_iso_duration(self):
        """Parses ISO 8601 duration format"""
        json_ld = {
            "@type": "Recipe",
            "name": "Test",
            "prepTime": "PT1H30M",
            "cookTime": "PT45M",
        }
        result = parse_json_ld_recipe(json_ld)
        assert result["prep_time"] == "1 hour 30 minutes"
        assert result["cook_time"] == "45 minutes"

    def test_handles_missing_fields(self):
        """Returns None for missing optional fields"""
        json_ld = {"@type": "Recipe", "name": "Minimal Recipe"}
        result = parse_json_ld_recipe(json_ld)
        assert result["recipe_name"] == "Minimal Recipe"
        assert result["prep_time"] is None
        assert result["ingredients"] == []


class TestScrapeRecipeFromUrl:
    """Tests for scrape_recipe_from_url function"""

    def test_extracts_json_ld_recipe(self):
        """Extracts recipe from JSON-LD script tag"""
        html = '''
        <html>
        <head>
        <script type="application/ld+json">
        {"@type": "Recipe", "name": "Test Recipe", "recipeIngredient": ["1 cup flour"]}
        </script>
        </head>
        </html>
        '''
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result is not None
            assert result["recipe_name"] == "Test Recipe"
            assert len(result["ingredients"]) == 1

    def test_handles_graph_json_ld(self):
        """Handles JSON-LD with @graph array"""
        html = '''
        <html>
        <script type="application/ld+json">
        {"@graph": [
            {"@type": "WebPage", "name": "Page"},
            {"@type": "Recipe", "name": "Graph Recipe"}
        ]}
        </script>
        </html>
        '''
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result["recipe_name"] == "Graph Recipe"

    def test_returns_none_on_timeout(self):
        """Returns None on request timeout"""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result is None

    def test_returns_none_on_404(self):
        """Returns None on HTTP error"""
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
            mock_get.return_value = mock_response
            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result is None

    def test_returns_none_when_no_recipe_schema(self):
        """Returns None when page has no recipe JSON-LD"""
        html = '<html><body><h1>Not a recipe</h1></body></html>'
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/page")
            assert result is None

    def test_handles_type_as_array(self):
        """Handles @type as array"""
        html = '''
        <html>
        <script type="application/ld+json">
        {"@type": ["Recipe", "HowTo"], "name": "Array Type Recipe"}
        </script>
        </html>
        '''
        with patch('recipe_sources.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            result = scrape_recipe_from_url("https://example.com/recipe")
            assert result["recipe_name"] == "Array Type Recipe"


class TestParseRecipeFromDescription:
    """Tests for parse_recipe_from_description function"""

    def test_detects_recipe_in_description(self):
        """Returns True when description looks like a recipe"""
        description = """
*Ingredients*
1/2 cup flour
2 eggs

*Method*
Mix and bake.
"""
        assert has_recipe_in_description(description) is True

    def test_rejects_non_recipe_description(self):
        """Returns False for descriptions without recipe"""
        description = "Thanks for watching! Subscribe for more."
        assert has_recipe_in_description(description) is False


class TestIngredientParsing:
    """Tests for ingredient parsing from JSON-LD"""

    def test_parses_to_new_format(self):
        """Outputs amount/unit/item format"""
        from recipe_sources import _parse_ingredients
        ingredients = ["500 g chicken", "2 cups flour"]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert result[0]["item"] == "chicken"

        assert result[1]["amount"] == "2"
        assert result[1]["unit"] == "cup"

    def test_handles_comma_format(self):
        """Handles 'Item, amount unit' format"""
        from recipe_sources import _parse_ingredients
        ingredients = ["Chicken Breasts, 500 g"]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "500"
        assert result[0]["unit"] == "g"
        assert "chicken" in result[0]["item"].lower()

    def test_handles_dict_with_amount(self):
        """Handles dict input with amount field"""
        from recipe_sources import _parse_ingredients
        ingredients = [{"amount": "2", "unit": "cups", "name": "flour"}]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "2"
        assert result[0]["unit"] == "cups"
        assert result[0]["item"] == "flour"

    def test_handles_legacy_dict_format(self):
        """Handles legacy dict with quantity field"""
        from recipe_sources import _parse_ingredients
        ingredients = [{"quantity": "2 cups", "name": "flour"}]
        result = _parse_ingredients(ingredients)

        assert result[0]["amount"] == "2"
        assert result[0]["unit"] == "cup"
        assert result[0]["item"] == "flour"

    def test_handles_empty_list(self):
        """Returns empty list for empty input"""
        from recipe_sources import _parse_ingredients
        assert _parse_ingredients([]) == []
        assert _parse_ingredients(None) == []

    def test_all_have_inferred_false(self):
        """All parsed ingredients have inferred=False"""
        from recipe_sources import _parse_ingredients
        ingredients = ["1 cup sugar", "2 eggs"]
        result = _parse_ingredients(ingredients)

        for ing in result:
            assert ing["inferred"] is False


class TestExtractCookingTips:
    """Tests for extract_cooking_tips function"""

    def test_returns_empty_list_for_no_transcript(self):
        """Returns empty list when no transcript"""
        from recipe_sources import extract_cooking_tips
        result = extract_cooking_tips("", {"recipe_name": "Test"})
        assert result == []

    def test_returns_list_type(self):
        """Always returns a list"""
        from recipe_sources import extract_cooking_tips
        result = extract_cooking_tips("", {})
        assert isinstance(result, list)
