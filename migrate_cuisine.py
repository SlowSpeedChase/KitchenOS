#!/usr/bin/env python3
"""
KitchenOS - Cuisine Data Cleanup & Seasonal Population Migration

Fixes inconsistent cuisine values and populates seasonal ingredient data.

Usage:
    python migrate_cuisine.py [--dry-run] [--no-seasonal]
"""

import argparse
import re
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.backup import create_backup
from lib.recipe_parser import parse_recipe_file

OBSIDIAN_RECIPES_PATH = Path(
    "/Users/chaseeasterling/Library/Mobile Documents/"
    "iCloud~md~obsidian/Documents/KitchenOS/Recipes"
)

# Variant consolidation — maps non-standard cuisine values to standard ones.
# None means "clear this value" (handled per-recipe in RECIPE_OVERRIDES or left null).
CUISINE_CORRECTIONS = {
    "Asian-inspired": "Asian",
    "Korean-inspired": "Korean",
    "Korean-American": "Korean",
    "Japanese-American fusion": "Japanese",
    "Chinese (Sichuan) or Asian": "Chinese",
    "Italian (inferred from Murcattt channel)": "Italian",
    "Vegan": None,
    "Vegetarian": None,
    "Not specified": None,
    "International": None,
    "Fusion": None,
    "protein:": None,
}

# Per-recipe overrides — applied first, wins over CUISINE_CORRECTIONS.
# Keys are recipe filenames (stem, no .md extension).
RECIPE_OVERRIDES = {
    # Misclassified
    "Seneyet Jaj O Batata": "Middle Eastern",
    "Macarona Bi Laban": "Middle Eastern",
    "Beef Steak Pepper Lunch Skillet": "Japanese",
    "Spicy Baked Black Bean Nachos": "Tex-Mex",
    "Queso Dip Recipe": "Tex-Mex",
    "Chili Cheese Tortillas": "Tex-Mex",
    "Cilantro Lime Chicken": "Mexican",
    "Ginger-Lime Marinade For Chicken": "Asian",
    # Dietary labels → actual cuisine
    "200G Lentils And 1 Sweet Potato": "Indian",
    "Cauliflower Steak With Butter Bean Puree And Chimichurri": "South American",
    "High-Protein Bean Lentil Dip (Crouton)": "Middle Eastern",
    # Null fills — misclassified or obviously inferable
    "Pasta Aglio E Olio Inspired By Chef": "Italian",
    "Hash Brown Casserole": "American",
    "Rich Fudgy Chocolate Cake": "American",
    "Large Batch Freezer Biscuits": "American",
    "Lime Cheesecake": "American",
    "Meal Prep Systems": "American",
    "19 Calorie Fudgy Brownies (Crouton)": "American",
    "5-Ingredient Cottage Cheese Cookie Dough": "American",
    "Blended Chocolate Salted Caramel Chia Pudding Mousse": "American",
    "Blueberry Donut Holes (Cottage Cheese Or Yogurt)": "American",
    "Charred Cabbage": "American",
    "Cherry Vanilla Breakfast Smoothie": "American",
    "Chewy Peanut Butter Cookies": "American",
    "Chocolate Chip Protein Cookies": "American",
    "Chocolate Cream Pie": "American",
    "Cosmic Brownie Protein Ice Cream": "American",
    "Cottage Cheese Chicken Caesar Wrap": "American",
    "Dairy-Free Dill Dressing": "American",
    "Deconstructed Strawberry Cheesecake 20G Protein": "American",
    "Double Dark Chocolate Granola": "American",
    "Dr. Rupy's No Bake Protein Bar": "American",
    "Goddess Salad": "American",
    "Healthy Blueberry Apple Oatmeal Cake": "American",
    "Healthy Delicious Recipe": "American",
    "High Protein Low Cal Chicken Sandwich": "American",
    "High Protein Sweet Potato, Beef, And Cottage Cheese Bowl": "American",
    "High-Protein Chocolate Chia Pudding Recipe": "American",
    "Matcha Smoothie": "American",
    "Nutella Protein Dessert": "American",
    "Oat Flour Pancakes": "American",
    "Oats With Chia Seeds & Yogurt Recipe": "American",
    "Peanut Butter Chocolate Coffee Smoothie": "American",
    "Protein Cabbage Wraps (Meatless)": "American",
    "Protein Cheesecake": "American",
    "Salted Honey Pistachio Cookies": "American",
    "Slutty Brownie Recipe": "American",
    "Strawberry Buttercream Frosting": "American",
    "Untitled-Recipe": "American",
    # Sriracha Lime → Asian-Inspired
    "Sriracha Lime Chicken Bowls": "Asian",
    # Breakfast Lentils → Indian
    "Breakfast Lentils Vegan Porridge": "Indian",
}


def apply_cuisine_corrections(recipe_name: str, current_cuisine) -> str | None:
    """Apply deterministic cuisine corrections for a recipe.

    Priority: RECIPE_OVERRIDES > CUISINE_CORRECTIONS > pass-through.

    Args:
        recipe_name: Recipe filename stem (no .md)
        current_cuisine: Current cuisine value (str or None)

    Returns:
        Corrected cuisine string, or None if should be null
    """
    # 1. Per-recipe override (highest priority)
    if recipe_name in RECIPE_OVERRIDES:
        return RECIPE_OVERRIDES[recipe_name]

    # 2. General correction map
    if current_cuisine in CUISINE_CORRECTIONS:
        return CUISINE_CORRECTIONS[current_cuisine]

    # 3. Pass through
    return current_cuisine


def update_frontmatter_field(content: str, field: str, value) -> str:
    """Update a single frontmatter field in recipe markdown content.

    Args:
        content: Full markdown file content with YAML frontmatter
        field: Frontmatter field name to update
        value: New value (str, list, int, or None)

    Returns:
        Updated content with the field changed
    """
    # Format value for YAML
    if value is None:
        yaml_value = "null"
    elif isinstance(value, list):
        if not value:
            yaml_value = "[]"
        elif isinstance(value[0], str):
            yaml_value = "[" + ", ".join(f'"{v}"' for v in value) + "]"
        else:
            yaml_value = "[" + ", ".join(str(v) for v in value) + "]"
    elif isinstance(value, str):
        yaml_value = f'"{value}"'
    else:
        yaml_value = str(value)

    # Replace the field line in frontmatter
    pattern = rf'^({field}:\s*).*$'
    replacement = rf'\g<1>{yaml_value}'
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
