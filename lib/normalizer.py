"""Recipe tag normalizer with controlled vocabularies.

Normalizes inconsistent AI-extracted tag values to a controlled set.
Used by both the migration script (existing recipes) and the import
pipeline (new recipes).
"""

import re


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

PROTEIN_MAP = {
    # Standard values (identity mappings)
    "chicken": "chicken",
    "beef": "beef",
    "pork": "pork",
    "lamb": "lamb",
    "turkey": "turkey",
    "fish": "fish",
    "seafood": "seafood",
    "tofu": "tofu",
    "tempeh": "tempeh",
    "eggs": "eggs",
    "beans": "beans",
    "lentils": "lentils",
    "chickpeas": "chickpeas",
    "dairy": "dairy",
    "protein powder": "protein powder",
    # Cut consolidation → chicken
    "chicken breast": "chicken",
    "chicken breasts": "chicken",
    "chicken thighs": "chicken",
    "chicken thigh": "chicken",
    "chicken wings": "chicken",
    "chicken drumsticks": "chicken",
    "rotisserie chicken": "chicken",
    "chicken leg": "chicken",
    "chicken legs": "chicken",
    # Beef variants
    "ground beef": "beef",
    "beef steak": "beef",
    "steak": "beef",
    # Pork variants
    "smoked sausage": "pork",
    "sausage": "pork",
    "bacon": "pork",
    "ham": "pork",
    "pork chops": "pork",
    "pork chop": "pork",
    "pork belly": "pork",
    "ground pork": "pork",
    # Bean variants
    "black beans": "beans",
    "white beans": "beans",
    "butter beans": "beans",
    "kidney beans": "beans",
    "pinto beans": "beans",
    "cannellini beans": "beans",
    # Dairy variants
    "cheese": "dairy",
    "feta": "dairy",
    "greek yogurt": "dairy",
    "yogurt": "dairy",
    "cottage cheese": "dairy",
    "cream cheese": "dairy",
    "ricotta": "dairy",
    "mozzarella": "dairy",
    "parmesan": "dairy",
    # Fish variants
    "salmon": "fish",
    "tuna": "fish",
    "cod": "fish",
    "tilapia": "fish",
    # Seafood variants
    "shrimp": "seafood",
    "prawns": "seafood",
    "crab": "seafood",
    "lobster": "seafood",
    "scallops": "seafood",
    # Egg variants
    "egg": "eggs",
    "egg whites": "eggs",
    # Chickpea singular
    "chickpea": "chickpeas",
    # Edamame → beans
    "edamame": "beans",
    # Turkey variants
    "ground turkey": "turkey",
    "turkey bacon": "turkey",
    # Multi-protein → primary
    "chicken legs or thighs": "chicken",
    "chicken mince": "chicken",
    "chicken and turkey bacon": "chicken",
    # Sausage/bacon variants
    "breakfast sausage": "pork",
    "breakfast sausage, bacon": "pork",
    # Dairy variants (additional)
    "greek-style yogurt": "dairy",
    "good culture cottage cheese": "dairy",
    "goat cheese": "dairy",
    "dairy (cheese)": "dairy",
    # Smoked fish
    "smoked salmon": "fish",
    # Protein powder variants
    "protein scoop of your choice": "protein powder",
    "protein pancake mix": "protein powder",
    "protein pancake mix and protein powder": "protein powder",
    "kodiak cakes protein pancake mix": "protein powder",
    "grassfed vanilla protein": "protein powder",
}

# Descriptive phrases that should map to None
_PROTEIN_DISCARD_PATTERNS = [
    "no specific",
    "high protein",
    "none",
    "n/a",
    "not specified",
    "various",
    "protein-rich",
    "protein per",
    "plant-based",
    "chia seeds",
    "king oyster",
]

DISH_TYPE_MAP = {
    # Standard values
    "main": "main",
    "side": "side",
    "dessert": "dessert",
    "breakfast": "breakfast",
    "snack": "snack",
    "salad": "salad",
    "soup": "soup",
    "sandwich": "sandwich",
    "appetizer": "appetizer",
    "drink": "drink",
    "sauce": "sauce",
    "bread": "bread",
    "dip": "dip",
    # Variants → main
    "main course": "main",
    "main dish": "main",
    "pasta dish": "main",
    "bowl": "main",
    "entree": "main",
    "entrée": "main",
    # Variants → sandwich
    "wrap": "sandwich",
    # Variants → drink
    "smoothie": "drink",
    "beverage": "drink",
    # Variants → sauce
    "dressing": "sauce",
    "condiment": "sauce",
    # Variants → appetizer
    "starter": "appetizer",
    "finger food": "appetizer",
    "rice ball": "appetizer",
    # More main variants
    "stew": "main",
    "pasta": "main",
    "noodle dish": "main",
    "one-pan dinner": "main",
    "meatballs": "main",
    "pizza": "main",
    "grilled skewers": "main",
    "meal prep": "main",
    "side dish": "side",
    "fermented vegetable side dish": "side",
    # More dessert variants
    "cake": "dessert",
    "cookies": "dessert",
    "baked goods": "dessert",
    "dessert bars": "dessert",
    "frosting": "dessert",
    "biscuit": "dessert",
    # More breakfast variants
    "muffins": "breakfast",
}

DIFFICULTY_MAP = {
    "easy": "easy",
    "medium": "medium",
    "hard": "hard",
}

VALID_DIETARY = {
    "vegan",
    "vegetarian",
    "gluten-free",
    "dairy-free",
    "low-carb",
    "low-calorie",
    "high-protein",
    "high-fiber",
    "keto",
    "paleo",
    "nut-free",
}

VALID_MEAL_OCCASIONS = {
    "weeknight-dinner",
    "packed-lunch",
    "grab-and-go-breakfast",
    "afternoon-snack",
    "weekend-project",
    "date-night",
    "lazy-sunday",
    "crowd-pleaser",
    "meal-prep",
    "brunch",
    "post-workout",
    "family-meal",
}

# Regex to catch numeric gram values like "70g", "42G", "50g (Whole Pizza)", "20G Protein"
_NUMERIC_PROTEIN_RE = re.compile(r"^\d+[gG]")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalize_protein(value):
    """Normalize a protein field value.

    Returns:
        str: normalized protein name
        None: if the value is invalid/descriptive/numeric
        tuple: ("unknown", original) if not recognized
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    # "null" string → None
    if value.lower() == "null":
        return None

    # Numeric gram values → None
    if _NUMERIC_PROTEIN_RE.match(value):
        return None

    lower = value.lower()

    # Descriptive discard phrases
    for pattern in _PROTEIN_DISCARD_PATTERNS:
        if pattern in lower:
            return None

    # Direct map lookup
    if lower in PROTEIN_MAP:
        return PROTEIN_MAP[lower]

    # Comma-separated: take first recognizable
    if "," in value:
        for part in value.split(","):
            part_lower = part.strip().lower()
            if part_lower in PROTEIN_MAP:
                return PROTEIN_MAP[part_lower]
        # If no part matched, try keyword extraction on the full string
        # before giving up

    # Try keyword extraction: look for a known protein keyword in the text
    for keyword in PROTEIN_MAP:
        if keyword in lower:
            return PROTEIN_MAP[keyword]

    return ("unknown", value)


def _normalize_dish_type(value):
    """Normalize a dish_type field value.

    Returns:
        str: normalized dish type
        tuple: ("unknown", original) if not recognized
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    lower = value.lower()

    if lower in DISH_TYPE_MAP:
        return DISH_TYPE_MAP[lower]

    # Comma-separated: take first recognizable
    if "," in lower:
        for part in lower.split(","):
            part = part.strip()
            if part in DISH_TYPE_MAP:
                return DISH_TYPE_MAP[part]

    return ("unknown", value)


def _normalize_difficulty(value):
    """Normalize a difficulty field value.

    Strips parenthetical descriptions before matching.

    Returns:
        str: normalized difficulty
        tuple: ("unknown", original) if not recognized
    """
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    # Strip parenthetical content: "Easy (simple ingredients)" → "Easy"
    cleaned = re.sub(r"\s*\(.*?\)\s*$", "", value).strip()
    lower = cleaned.lower()

    if lower in DIFFICULTY_MAP:
        return DIFFICULTY_MAP[lower]

    return ("unknown", value)


def _normalize_dietary(values):
    """Normalize a dietary array.

    Lowercases, converts spaces to hyphens, deduplicates,
    and removes values not in the controlled vocabulary.

    Returns:
        list: filtered and normalized dietary values
    """
    if not isinstance(values, list):
        return []

    seen = set()
    result = []
    for v in values:
        if not isinstance(v, str):
            continue
        normalized = v.strip().lower().replace(" ", "-")
        if normalized in VALID_DIETARY and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def _normalize_meal_occasion(values):
    """Normalize a meal_occasion array.

    Filters out values not in the valid set.

    Returns:
        list: filtered meal occasion values
    """
    if not isinstance(values, list):
        return []

    result = []
    for v in values:
        if not isinstance(v, str):
            continue
        normalized = v.strip().lower()
        if normalized in VALID_MEAL_OCCASIONS:
            result.append(normalized)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_FIELD_NORMALIZERS = {
    "protein": _normalize_protein,
    "dish_type": _normalize_dish_type,
    "difficulty": _normalize_difficulty,
    "dietary": _normalize_dietary,
    "meal_occasion": _normalize_meal_occasion,
}


def normalize_field(field, value):
    """Normalize a single recipe tag field.

    Args:
        field: field name (protein, dish_type, difficulty, dietary, meal_occasion)
        value: the raw value to normalize

    Returns:
        For string fields: normalized string, None, or ("unknown", original_value)
        For array fields: filtered/normalized list
    """
    normalizer = _FIELD_NORMALIZERS.get(field)
    if normalizer is None:
        return value
    return normalizer(value)


def normalize_recipe_data(recipe_data):
    """Normalize all tag fields in a recipe data dict.

    Modifies and returns the dict. Sets needs_review=True if any
    unknown values are encountered.

    Args:
        recipe_data: dict with recipe fields

    Returns:
        The modified dict with normalized tag fields
    """
    has_unknown = False

    for field, normalizer in _FIELD_NORMALIZERS.items():
        if field not in recipe_data:
            continue
        normalized = normalizer(recipe_data[field])
        recipe_data[field] = normalized

        # Check for unknown tuple
        if isinstance(normalized, tuple) and len(normalized) == 2 and normalized[0] == "unknown":
            has_unknown = True

    if has_unknown:
        recipe_data["needs_review"] = True

    return recipe_data
