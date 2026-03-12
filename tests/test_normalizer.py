"""Tests for recipe tag normalizer module"""

from lib.normalizer import normalize_field, normalize_recipe_data


class TestNormalizeProtein:
    """Tests for protein field normalization"""

    def test_passthrough_standard_values(self):
        """Standard protein values pass through unchanged"""
        assert normalize_field("protein", "chicken") == "chicken"
        assert normalize_field("protein", "beef") == "beef"
        assert normalize_field("protein", "pork") == "pork"
        assert normalize_field("protein", "fish") == "fish"
        assert normalize_field("protein", "tofu") == "tofu"
        assert normalize_field("protein", "eggs") == "eggs"
        assert normalize_field("protein", "beans") == "beans"
        assert normalize_field("protein", "lentils") == "lentils"
        assert normalize_field("protein", "chickpeas") == "chickpeas"

    def test_case_normalization(self):
        """Protein values are lowercased"""
        assert normalize_field("protein", "Chicken") == "chicken"
        assert normalize_field("protein", "BEEF") == "beef"
        assert normalize_field("protein", "Fish") == "fish"

    def test_cut_consolidation(self):
        """Specific cuts consolidate to base protein"""
        assert normalize_field("protein", "Chicken breast") == "chicken"
        assert normalize_field("protein", "chicken thighs") == "chicken"
        assert normalize_field("protein", "Rotisserie chicken") == "chicken"

    def test_ground_beef(self):
        """Ground beef normalizes to beef"""
        assert normalize_field("protein", "ground beef") == "beef"

    def test_pork_variants(self):
        """Pork variants normalize to pork"""
        assert normalize_field("protein", "smoked sausage") == "pork"
        assert normalize_field("protein", "bacon") == "pork"

    def test_bean_variants(self):
        """Bean variants normalize to beans"""
        assert normalize_field("protein", "Black beans") == "beans"
        assert normalize_field("protein", "White beans") == "beans"
        assert normalize_field("protein", "Butter beans") == "beans"

    def test_dairy_variants(self):
        """Dairy variants normalize to dairy"""
        assert normalize_field("protein", "cheese") == "dairy"
        assert normalize_field("protein", "Feta") == "dairy"
        assert normalize_field("protein", "Greek yogurt") == "dairy"
        assert normalize_field("protein", "cottage cheese") == "dairy"

    def test_numeric_values_to_none(self):
        """Numeric protein values (gram amounts) become None"""
        assert normalize_field("protein", "70g") is None
        assert normalize_field("protein", "42g") is None
        assert normalize_field("protein", "30G") is None

    def test_descriptive_text_to_none(self):
        """Descriptive text that isn't a real protein becomes None"""
        assert normalize_field("protein", "No specific protein listed") is None
        assert normalize_field("protein", "High Protein") is None

    def test_null_stays_null(self):
        """None input stays None"""
        assert normalize_field("protein", None) is None

    def test_string_null_to_none(self):
        """String 'null' becomes None"""
        assert normalize_field("protein", "null") is None

    def test_comma_separated_takes_first(self):
        """Comma-separated values: take first recognizable protein"""
        assert normalize_field("protein", "chicken, beef") == "chicken"

    def test_parenthetical_extraction(self):
        """Extract protein keyword from parenthetical text"""
        assert normalize_field("protein", "chicken (if serving with chicken)") == "chicken"


class TestNormalizeDishType:
    """Tests for dish_type field normalization"""

    def test_main_variants(self):
        """Various 'main' synonyms normalize to main"""
        assert normalize_field("dish_type", "Main Course") == "main"
        assert normalize_field("dish_type", "Main Dish") == "main"
        assert normalize_field("dish_type", "pasta dish") == "main"
        assert normalize_field("dish_type", "Bowl") == "main"

    def test_case_normalization(self):
        """Dish types are case-normalized"""
        assert normalize_field("dish_type", "SOUP") == "soup"
        assert normalize_field("dish_type", "Salad") == "salad"
        assert normalize_field("dish_type", "Dessert") == "dessert"

    def test_standard_passthrough(self):
        """Standard dish types pass through"""
        assert normalize_field("dish_type", "main") == "main"
        assert normalize_field("dish_type", "side") == "side"
        assert normalize_field("dish_type", "dessert") == "dessert"
        assert normalize_field("dish_type", "breakfast") == "breakfast"
        assert normalize_field("dish_type", "snack") == "snack"
        assert normalize_field("dish_type", "soup") == "soup"
        assert normalize_field("dish_type", "sandwich") == "sandwich"
        assert normalize_field("dish_type", "appetizer") == "appetizer"
        assert normalize_field("dish_type", "drink") == "drink"
        assert normalize_field("dish_type", "sauce") == "sauce"
        assert normalize_field("dish_type", "bread") == "bread"
        assert normalize_field("dish_type", "dip") == "dip"

    def test_merge_variants(self):
        """Variant dish types merge to standard"""
        assert normalize_field("dish_type", "Wrap") == "sandwich"
        assert normalize_field("dish_type", "Smoothie") == "drink"
        assert normalize_field("dish_type", "Dressing") == "sauce"
        assert normalize_field("dish_type", "Condiment") == "sauce"

    def test_unknown_dish_type(self):
        """Unknown dish types return unknown tuple"""
        result = normalize_field("dish_type", "Casserole")
        assert result == ("unknown", "Casserole")


class TestNormalizeDifficulty:
    """Tests for difficulty field normalization"""

    def test_case_normalization(self):
        """Difficulty values are lowercased"""
        assert normalize_field("difficulty", "Easy") == "easy"
        assert normalize_field("difficulty", "MEDIUM") == "medium"
        assert normalize_field("difficulty", "Hard") == "hard"

    def test_standard_passthrough(self):
        """Standard values pass through"""
        assert normalize_field("difficulty", "easy") == "easy"
        assert normalize_field("difficulty", "medium") == "medium"
        assert normalize_field("difficulty", "hard") == "hard"

    def test_verbose_stripped(self):
        """Parenthetical descriptions are stripped"""
        assert normalize_field("difficulty", "Easy (simple ingredients)") == "easy"
        assert normalize_field("difficulty", "Medium (requires some technique)") == "medium"

    def test_unknown_difficulty(self):
        """Unknown difficulty returns unknown tuple"""
        result = normalize_field("difficulty", "expert")
        assert result == ("unknown", "expert")


class TestNormalizeDietary:
    """Tests for dietary array field normalization"""

    def test_case_and_format_normalization(self):
        """Dietary values are case-normalized and formatted"""
        result = normalize_field("dietary", ["Vegan", "GLUTEN-FREE", "Low Carb"])
        assert "vegan" in result
        assert "gluten-free" in result
        assert "low-carb" in result

    def test_dedup(self):
        """Duplicate dietary values are removed"""
        result = normalize_field("dietary", ["vegan", "Vegan", "VEGAN"])
        assert result == ["vegan"]

    def test_removes_invalid(self):
        """Invalid dietary values are removed"""
        result = normalize_field("dietary", ["vegan", "tasty", "organic"])
        assert result == ["vegan"]

    def test_empty_array_passthrough(self):
        """Empty array passes through"""
        assert normalize_field("dietary", []) == []

    def test_all_valid_values(self):
        """All valid dietary values are accepted"""
        valid = [
            "vegan", "vegetarian", "gluten-free", "dairy-free",
            "low-carb", "low-calorie", "high-protein", "high-fiber",
            "keto", "paleo", "nut-free"
        ]
        result = normalize_field("dietary", valid)
        assert result == valid


class TestNormalizeMealOccasion:
    """Tests for meal_occasion array field normalization"""

    def test_valid_values_pass(self):
        """Valid meal occasions pass through"""
        result = normalize_field("meal_occasion", ["weeknight-dinner", "meal-prep"])
        assert result == ["weeknight-dinner", "meal-prep"]

    def test_removes_leaked_values(self):
        """Dietary/dish type values leaked into meal_occasion are removed"""
        result = normalize_field("meal_occasion", ["weeknight-dinner", "vegan", "dessert"])
        assert result == ["weeknight-dinner"]

    def test_all_valid_occasions(self):
        """All valid meal occasions are accepted"""
        valid = [
            "weeknight-dinner", "packed-lunch", "grab-and-go-breakfast",
            "afternoon-snack", "weekend-project", "date-night",
            "lazy-sunday", "crowd-pleaser", "meal-prep", "brunch",
            "post-workout", "family-meal"
        ]
        result = normalize_field("meal_occasion", valid)
        assert result == valid

    def test_empty_array(self):
        """Empty array passes through"""
        assert normalize_field("meal_occasion", []) == []


class TestNormalizeRecipeData:
    """Tests for full recipe data normalization"""

    def test_normalizes_all_fields(self):
        """All tag fields are normalized in one pass"""
        data = {
            "recipe_name": "Test Recipe",
            "protein": "Chicken breast",
            "dish_type": "Main Course",
            "difficulty": "Easy",
            "dietary": ["Gluten-Free"],
            "meal_occasion": ["weeknight-dinner"],
            "needs_review": False,
        }
        result = normalize_recipe_data(data)
        assert result["protein"] == "chicken"
        assert result["dish_type"] == "main"
        assert result["difficulty"] == "easy"
        assert result["dietary"] == ["gluten-free"]
        assert result["meal_occasion"] == ["weeknight-dinner"]

    def test_unknown_string_sets_needs_review(self):
        """Unknown values trigger needs_review flag"""
        data = {
            "recipe_name": "Test",
            "protein": "unicorn meat",
            "dish_type": "main",
            "difficulty": "easy",
            "dietary": [],
            "meal_occasion": [],
            "needs_review": False,
        }
        result = normalize_recipe_data(data)
        assert result["needs_review"] is True
        # protein should be the unknown tuple
        assert result["protein"] == ("unknown", "unicorn meat")

    def test_known_values_dont_force_needs_review(self):
        """When all values are known, needs_review is not forced True"""
        data = {
            "recipe_name": "Test",
            "protein": "chicken",
            "dish_type": "main",
            "difficulty": "easy",
            "dietary": ["vegan"],
            "meal_occasion": ["weeknight-dinner"],
            "needs_review": False,
        }
        result = normalize_recipe_data(data)
        assert result["needs_review"] is False

    def test_preserves_non_tag_fields(self):
        """Non-tag fields are left untouched"""
        data = {
            "recipe_name": "My Recipe",
            "description": "A great recipe",
            "servings": 4,
            "ingredients": [{"amount": "1", "unit": "cup", "item": "flour"}],
            "protein": "chicken",
            "dish_type": "main",
            "difficulty": "easy",
            "dietary": [],
            "meal_occasion": [],
            "needs_review": False,
        }
        result = normalize_recipe_data(data)
        assert result["recipe_name"] == "My Recipe"
        assert result["description"] == "A great recipe"
        assert result["servings"] == 4
        assert result["ingredients"] == [{"amount": "1", "unit": "cup", "item": "flour"}]

    def test_missing_fields_handled(self):
        """Missing tag fields don't cause errors"""
        data = {"recipe_name": "Minimal"}
        result = normalize_recipe_data(data)
        assert result["recipe_name"] == "Minimal"
