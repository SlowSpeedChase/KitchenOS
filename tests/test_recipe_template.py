"""Tests for recipe template"""
import pytest
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
    assert API_BASE_URL == "http://chases-mac-mini.taila69703.ts.net:5001"


def test_tools_callout_contains_add_to_meal_plan():
    result = generate_tools_callout("Test Recipe.md")
    assert "Add to Meal Plan" in result
    assert "add-to-meal-plan" in result
    assert "recipe=Test%20Recipe.md" in result


def test_tools_callout_uses_tailscale_hostname():
    result = generate_tools_callout("Test.md")
    assert "chases-mac-mini.taila69703.ts.net:5001" in result
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
            "nutrition_calories": 450,   # was "calories"
            "nutrition_protein": 25,
            "nutrition_carbs": 45,       # was "carbs"
            "nutrition_fat": 18,         # was "fat"
            # Load-bearing: the heading follows this. Without it the macros are
            # whole-batch totals (the engine divided by 1) and the section says so.
            "servings": 4,
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

    @pytest.mark.parametrize("servings", [None, "null", "none", "", 0, "__absent__"])
    def test_no_servings_is_labelled_whole_recipe(self, servings):
        """Without a servings count the engine divided by 1, so these are totals.

        Printing "(per serving)" over them isn't vague, it's false — it read a
        1,339-calorie tray of yogurt pops as one serving.
        """
        recipe_data = {
            "nutrition_calories": 1339,
            "nutrition_protein": 19,
            "nutrition_carbs": 207,
            "nutrition_fat": 52,
            "nutrition_source": "fdc",
        }
        if servings != "__absent__":
            recipe_data["servings"] = servings
        result = generate_nutrition_section(recipe_data)

        assert "## Nutrition (whole recipe)" in result
        assert "(per serving)" not in result
        assert "no servings count" in result

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
            "nutrition_calories": 450,
            "nutrition_protein": 25,
            "nutrition_carbs": 45,
            "nutrition_fat": 18,
            "nutrition_source": "nutritionix",
            "ingredients": [],
            "instructions": [],
        }
        result = format_recipe_markdown(
            recipe_data,
            video_url="https://youtube.com/watch?v=abc123",
            video_title="Test Video",
            channel="Test Channel"
        )
        assert "nutrition_calories: 450" in result
        assert "nutrition_protein: 25" in result
        assert "nutrition_carbs: 45" in result
        assert "nutrition_fat: 18" in result
        assert 'serving_size: "1 cup"' in result
        assert 'nutrition_source: "nutritionix"' in result
        assert "\ncalories:" not in result
        assert "\ncarbs:" not in result
        assert "\nfat:" not in result

    def test_includes_nutrition_table_in_body(self):
        """Recipe body should include nutrition table after ingredients"""
        recipe_data = {
            "recipe_name": "Test Recipe",
            "description": "A test",
            "servings": 4,
            "serving_size": "1 cup",
            "nutrition_calories": 450,
            "nutrition_protein": 25,
            "nutrition_carbs": 45,
            "nutrition_fat": 18,
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

        assert "nutrition_calories: null" in result
        assert "nutrition_protein: null" in result
        assert "nutrition_carbs: null" in result
        assert "nutrition_fat: null" in result
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


class TestFrontmatterIsEscaped:
    """A video title is not trusted input.

    Six frontmatter fields were interpolated as f'"{value}"' straight from the
    YouTube API or an LLM extraction. A channel whose title contains a double
    quote — or three hyphens, which end a YAML document — produced a recipe file
    whose frontmatter did not parse. Every tool downstream reads that file.
    """

    def _render(self, **kw):
        from templates.recipe_template import format_recipe_markdown
        data = {"recipe_name": kw.pop("recipe_name", "Test Recipe"),
                "ingredients": [], "instructions": []}
        data.update(kw.pop("data", {}))
        return format_recipe_markdown(
            data,
            kw.pop("video_url", "https://youtube.com/watch?v=abc"),
            kw.pop("video_title", "A Video"),
            kw.pop("channel", "A Channel"),
        )

    def _fm(self, content):
        import yaml
        from lib import frontmatter
        fm, _ = frontmatter.split_frontmatter(content)
        assert fm is not None, "frontmatter did not parse as a block"
        return yaml.safe_load(fm)

    def test_a_quote_in_the_video_title_keeps_the_file_parseable(self):
        out = self._render(video_title='The 9" Skillet "Trick"')
        assert self._fm(out)["video_title"] == 'The 9" Skillet "Trick"'

    def test_a_triple_dash_in_the_video_title_does_not_end_the_document(self):
        out = self._render(video_title="Noodles --- the viral one")
        fm = self._fm(out)
        assert fm["video_title"] == "Noodles --- the viral one"
        assert fm["source_url"] == "https://youtube.com/watch?v=abc"  # still present

    def test_a_quote_in_the_channel_name_is_escaped(self):
        out = self._render(channel='Bob\'s "Kitchen"')
        assert self._fm(out)["source_channel"] == 'Bob\'s "Kitchen"'

    def test_a_quote_in_the_recipe_name_is_escaped(self):
        out = self._render(recipe_name='The "Best" Chili')
        assert self._fm(out)["title"] == 'The "Best" Chili'

    def test_a_newline_in_the_video_title_cannot_inject_a_key(self):
        out = self._render(video_title="Chili\nservings: 999")
        fm = self._fm(out)
        assert fm["video_title"] == "Chili\nservings: 999"
        assert fm["servings"] != 999

    def test_a_quote_in_confidence_notes_is_escaped(self):
        out = self._render(data={"confidence_notes": 'guessed the 2" ginger'})
        assert self._fm(out)["confidence_notes"] == 'guessed the 2" ginger'

    def test_a_quote_in_a_quoted_optional_field_is_escaped(self):
        out = self._render(data={"serving_size": '1 x 9" slice'})
        assert self._fm(out)["serving_size"] == '1 x 9" slice'

    def test_brackets_are_still_escaped_in_the_body_link_label(self):
        """The Korean/Japanese bracket fix must survive the escaping change."""
        out = self._render(video_title="[감자치즈빵] Potato Bread")
        assert r"[\[감자치즈빵\] Potato Bread]" in out

    def test_the_body_link_label_is_not_json_escaped(self):
        """The label is markdown, not YAML — it must not gain backslash-quotes."""
        out = self._render(video_title='The 9" Skillet')
        body = out.split("---", 2)[2]
        assert '9" Skillet' in body
        assert r'9\" Skillet' not in body

    def test_an_ordinary_recipe_is_unchanged_in_shape(self):
        out = self._render()
        fm = self._fm(out)
        assert fm["title"] == "Test Recipe"
        assert fm["video_title"] == "A Video"
        assert fm["source_channel"] == "A Channel"
