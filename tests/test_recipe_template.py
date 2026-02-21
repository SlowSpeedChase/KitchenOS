"""Tests for recipe template"""
from templates.recipe_template import (
    format_recipe_markdown,
    generate_tools_callout,
    generate_nutrition_section,
    API_BASE_URL,
)


def test_generate_tools_callout():
    """Tools callout should include both buttons with correct filename"""
    callout = generate_tools_callout("Pasta Aglio E Olio.md")

    assert "> [!tools]- Tools" in callout
    assert "name Re-extract" in callout
    assert "name Refresh Template" in callout
    # Filename should be URL-encoded
    assert "reprocess?file=Pasta%20Aglio%20E%20Olio.md" in callout
    assert "refresh?file=Pasta%20Aglio%20E%20Olio.md" in callout


def test_api_base_url_uses_tailscale():
    assert API_BASE_URL == "http://100.111.6.10:5001"


def test_tools_callout_contains_add_to_meal_plan():
    result = generate_tools_callout("Test Recipe.md")
    assert "Add to Meal Plan" in result
    assert "add-to-meal-plan" in result
    assert "recipe=Test%20Recipe.md" in result


def test_tools_callout_uses_tailscale_ip():
    result = generate_tools_callout("Test.md")
    assert "100.111.6.10:5001" in result
    assert "localhost" not in result


def test_format_recipe_markdown_includes_tools_callout():
    """Recipe markdown should include tools callout after frontmatter"""
    recipe_data = {
        "recipe_name": "Test Recipe",
        "description": "A test",
        "ingredients": [],
        "instructions": [],
    }

    result = format_recipe_markdown(
        recipe_data,
        video_url="https://youtube.com/watch?v=abc123",
        video_title="Test Video",
        channel="Test Channel"
    )

    assert "> [!tools]- Tools" in result
    assert "reprocess?file=Test%20Recipe.md" in result


class TestNutritionSection:
    def test_generate_nutrition_section_with_data(self):
        """Nutrition section should generate markdown table when data present"""
        recipe_data = {
            "calories": 450,
            "nutrition_protein": 25,
            "carbs": 45,
            "fat": 18,
            "serving_size": "1 cup",
            "nutrition_source": "nutritionix",
        }
        result = generate_nutrition_section(recipe_data)

        assert "## Nutrition (per serving)" in result
        assert "| Calories | Protein | Carbs | Fat |" in result
        assert "| 450" in result
        assert "| 25g" in result
        assert "| 45g" in result
        assert "| 18g" in result
        assert "*Serving size: 1 cup" in result
        assert "Nutritionix" in result

    def test_generate_nutrition_section_without_data(self):
        """Nutrition section should return empty string when no calories"""
        recipe_data = {}
        result = generate_nutrition_section(recipe_data)
        assert result == ""

    def test_includes_nutrition_in_frontmatter(self):
        """Recipe frontmatter should include nutrition fields"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "calories": 450,
            "nutrition_protein": 25,
            "carbs": 45,
            "fat": 18,
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "calories: 450" in result
        assert "nutrition_protein: 25" in result
        assert "carbs: 45" in result
        assert "fat: 18" in result
        assert 'serving_size: "1 cup"' in result
        assert 'nutrition_source: "nutritionix"' in result

    def test_includes_nutrition_table_in_body(self):
        """Recipe body should include nutrition table after ingredients"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "calories": 450,
            "nutrition_protein": 25,
            "carbs": 45,
            "fat": 18,
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "## Nutrition (per serving)" in result
        assert "| Calories | Protein | Carbs | Fat |" in result
        assert "| 450" in result
        assert "*Serving size: 1 cup" in result

    def test_omits_nutrition_section_when_no_data(self):
        """Recipe should not include nutrition section when no calorie data"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "ingredients": [],
            "instructions": [],
            "equipment": [],
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "## Nutrition (per serving)" not in result

    def test_nutrition_with_null_values(self):
        """Frontmatter should handle null nutrition values"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "ingredients": [],
            "instructions": [],
            "equipment": [],
            # No nutrition data
        }
        result = format_recipe_markdown(recipe_data, "http://example.com", "Test Video", "Test Channel")

        assert "calories: null" in result
        assert "nutrition_protein: null" in result
        assert "carbs: null" in result
        assert "fat: null" in result
        assert "serving_size: null" in result
        assert "nutrition_source: null" in result


class TestImageSupport:
    def test_template_includes_cssclasses(self):
        """Recipe frontmatter should include cssclasses: [recipe]"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "cssclasses:" in result
        assert "  - recipe" in result

    def test_template_includes_banner_when_image(self):
        """Frontmatter should include banner when image_filename is provided"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert 'banner: "[[Test Recipe.jpg]]"' in result

    def test_template_includes_inline_image_when_image(self):
        """Body should include ![[image]] embed when image_filename is provided"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "![[Test Recipe.jpg]]" in result

    def test_template_no_banner_without_image(self):
        """Frontmatter should have banner: null when no image"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "banner: null" in result

    def test_template_no_inline_image_without_image(self):
        """Body should not include ![[]] embed when no image"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "![[" not in result

    def test_inline_image_before_description(self):
        """Image embed should appear before the description blockquote"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "ingredients": [],
            "instructions": [],
            "image_filename": "Test Recipe.jpg",
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        image_pos = result.find("![[Test Recipe.jpg]]")
        desc_pos = result.find("> A test")
        assert image_pos < desc_pos


class TestSeasonalFrontmatter:
    def test_seasonal_fields_in_output(self):
        """Seasonal fields should appear in frontmatter"""
        recipe_data = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [],
            "instructions": [],
            "seasonal_ingredients": ["tomato", "basil"],
            "peak_months": [4, 5, 6, 10, 11],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "seasonal_ingredients:" in result
        assert "peak_months:" in result

    def test_empty_seasonal_fields(self):
        """Empty seasonal data should render as empty lists"""
        recipe_data = {
            "recipe_name": "Test",
            "description": "Test recipe",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(recipe_data, "http://test.com", "Test", "Channel")
        assert "seasonal_ingredients: []" in result
        assert "peak_months: []" in result
