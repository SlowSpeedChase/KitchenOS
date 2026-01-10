"""Tests for recipe template"""
from templates.recipe_template import format_recipe_markdown, generate_tools_callout


def test_generate_tools_callout():
    """Tools callout should include both buttons with correct filename"""
    callout = generate_tools_callout("Pasta Aglio E Olio.md")

    assert "> [!tools]- Tools" in callout
    assert "name Re-extract" in callout
    assert "name Refresh Template" in callout
    # Filename should be URL-encoded
    assert "reprocess?file=Pasta%20Aglio%20E%20Olio.md" in callout
    assert "refresh?file=Pasta%20Aglio%20E%20Olio.md" in callout


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
