"""Tests for recipe index."""

import tempfile
from pathlib import Path

from lib.recipe_index import get_recipe_index


class TestGetRecipeIndex:
    """Test scanning recipes folder for metadata."""

    def test_extracts_name_from_filename(self):
        """Recipe name comes from filename (stem), not frontmatter title."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Pasta Aglio E Olio.md").write_text(
                '---\ntitle: "Pasta Aglio E Olio"\ncuisine: "Italian"\nprotein: "none"\n---\n\n# Pasta'
            )
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1
            assert result[0]["name"] == "Pasta Aglio E Olio"

    def test_extracts_filter_fields(self):
        """Should extract cuisine, protein, meal_occasion, difficulty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Butter Chicken.md").write_text(
                '---\ntitle: "Butter Chicken"\ncuisine: "Indian"\nprotein: "chicken"\n'
                'difficulty: "easy"\ndish_type: "curry"\nmeal_occasion: ["weeknight-dinner", "meal-prep"]\n---\n\n# Butter Chicken'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["cuisine"] == "Indian"
            assert result[0]["protein"] == "chicken"
            assert result[0]["difficulty"] == "easy"
            assert result[0]["dish_type"] == "curry"
            assert result[0]["meal_occasion"] == ["weeknight-dinner", "meal-prep"]

    def test_handles_null_fields(self):
        """Null/missing frontmatter fields become None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Simple Recipe.md").write_text(
                '---\ntitle: "Simple Recipe"\ncuisine: null\nprotein: null\n---\n\n# Simple'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["cuisine"] is None
            assert result[0]["protein"] is None

    def test_skips_non_md_files(self):
        """Should only index .md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            (recipes_dir / ".DS_Store").write_text("junk")
            (recipes_dir / "notes.txt").write_text("notes")
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1

    def test_skips_subdirectories(self):
        """Should not recurse into subdirectories like Cooking Mode/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            subdir = recipes_dir / "Cooking Mode"
            subdir.mkdir()
            (subdir / "Recipe.recipe.md").write_text('---\ntitle: "Recipe"\n---\n\n# Recipe')
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1

    def test_sorts_alphabetically(self):
        """Results sorted by name A-Z."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Zucchini Bread.md").write_text('---\ntitle: "Zucchini Bread"\n---\n')
            (recipes_dir / "Apple Pie.md").write_text('---\ntitle: "Apple Pie"\n---\n')
            (recipes_dir / "Mac And Cheese.md").write_text('---\ntitle: "Mac And Cheese"\n---\n')
            result = get_recipe_index(recipes_dir)
            names = [r["name"] for r in result]
            assert names == ["Apple Pie", "Mac And Cheese", "Zucchini Bread"]

    def test_extracts_peak_months(self):
        """Should extract peak_months from frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Summer Salad.md").write_text(
                '---\ntitle: "Summer Salad"\ncuisine: "American"\n'
                'peak_months: [5, 6, 7, 8]\nseasonal_ingredients: ["tomato", "cucumber"]\n---\n\n# Summer Salad'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["peak_months"] == ["5", "6", "7", "8"]

    def test_peak_months_defaults_to_none(self):
        """Missing peak_months becomes None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Old Recipe.md").write_text(
                '---\ntitle: "Old Recipe"\ncuisine: "Italian"\n---\n\n# Old Recipe'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["peak_months"] is None

    def test_handles_missing_frontmatter(self):
        """Files without frontmatter still get indexed with name only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Plain Recipe.md").write_text("# Plain Recipe\n\nJust some text.")
            result = get_recipe_index(recipes_dir)
            assert len(result) == 1
            assert result[0]["name"] == "Plain Recipe"
            assert result[0]["cuisine"] is None

    def test_includes_image_when_file_exists(self):
        """Should return image filename when matching .jpg exists in Images/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Butter Chicken.md").write_text(
                '---\ntitle: "Butter Chicken"\ncuisine: "Indian"\n---\n\n# Butter Chicken'
            )
            images_dir = recipes_dir / "Images"
            images_dir.mkdir()
            (images_dir / "Butter Chicken.jpg").write_text("fake image data")

            result = get_recipe_index(recipes_dir)
            assert result[0]["image"] == "Butter Chicken.jpg"

    def test_image_null_when_no_file(self):
        """Should return image: null when no matching image file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Plain Pasta.md").write_text(
                '---\ntitle: "Plain Pasta"\ncuisine: "Italian"\n---\n\n# Plain Pasta'
            )
            result = get_recipe_index(recipes_dir)
            assert result[0]["image"] is None


class TestGetRecipeIndexWithIngredients:
    """Test ingredient extraction in recipe index."""

    def test_includes_ingredient_items_when_requested(self):
        """Should extract ingredient item names from recipe body."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Chicken Shawarma.md").write_text(
                '---\ntitle: "Chicken Shawarma"\ncuisine: "Middle Eastern"\nprotein: "chicken"\n---\n\n'
                '# Chicken Shawarma\n\n'
                '## Ingredients\n\n'
                '| Amount | Unit | Ingredient |\n'
                '|--------|------|------------|\n'
                '| 2 | lb | chicken thighs |\n'
                '| 1 | cup | greek yogurt |\n'
                '| 3 | cloves | garlic |\n'
                '| 1 | tsp | cumin |\n'
            )
            result = get_recipe_index(recipes_dir, include_ingredients=True)
            assert len(result) == 1
            items = result[0]["ingredient_items"]
            assert "chicken thighs" in items
            assert "greek yogurt" in items
            assert "garlic" in items
            assert "cumin" in items

    def test_ingredient_items_empty_when_no_table(self):
        """Recipes without ingredient tables get empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Simple.md").write_text(
                '---\ntitle: "Simple"\n---\n\n# Simple\n\nJust text.'
            )
            result = get_recipe_index(recipes_dir, include_ingredients=True)
            assert result[0]["ingredient_items"] == []

    def test_no_ingredients_by_default(self):
        """Default call should NOT include ingredient_items (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipes_dir = Path(tmpdir)
            (recipes_dir / "Recipe.md").write_text(
                '---\ntitle: "Recipe"\ncuisine: "Italian"\n---\n\n# Recipe'
            )
            result = get_recipe_index(recipes_dir)
            assert "ingredient_items" not in result[0]
