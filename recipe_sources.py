"""Recipe source extraction: webpage scraping, description parsing, tips extraction"""

import re
from typing import Optional


# Known recipe domains (no keyword needed)
KNOWN_RECIPE_DOMAINS = [
    "bingingwithbabish.com",
    "seriouseats.com",
    "bonappetit.com",
    "food52.com",
    "smittenkitchen.com",
    "budgetbytes.com",
    "allrecipes.com",
    "epicurious.com",
    "foodnetwork.com",
    "delish.com",
    "tasty.co",
    "thekitchn.com",
]

# Domains to exclude
EXCLUDED_DOMAINS = [
    "patreon.com",
    "instagram.com",
    "twitter.com",
    "facebook.com",
    "tiktok.com",
    "amazon.com",
    "amzn.to",
    "youtube.com",
    "youtu.be",
]

# Keywords that indicate a recipe link
RECIPE_KEYWORDS = [
    "recipe",
    "recipes",
    "full recipe",
    "written recipe",
    "ingredients",
]


def find_recipe_link(description: str) -> Optional[str]:
    """
    Find a recipe URL in a video description.

    Priority:
    1. Explicit label (e.g., "Recipe: https://...")
    2. URL on same line as recipe keyword
    3. URL from known recipe domain

    Returns:
        Recipe URL if found, None otherwise
    """
    if not description:
        return None

    # URL pattern
    url_pattern = r'https?://[^\s<>"\')\]]+'

    lines = description.split('\n')

    # Pass 1: Look for explicit label "Recipe:" or "Full recipe:" at start of line
    for line in lines:
        line_lower = line.lower().strip()
        if line_lower.startswith("recipe:") or line_lower.startswith("full recipe:"):
            urls = re.findall(url_pattern, line)
            for url in urls:
                if not _is_excluded_domain(url):
                    return url

    # Pass 2: Look for URLs on same line as recipe keywords
    for line in lines:
        line_lower = line.lower()
        has_keyword = any(kw in line_lower for kw in RECIPE_KEYWORDS)
        if has_keyword:
            urls = re.findall(url_pattern, line)
            for url in urls:
                if not _is_excluded_domain(url):
                    return url

    # Pass 3: Look for known recipe domains anywhere
    all_urls = re.findall(url_pattern, description)
    for url in all_urls:
        if _is_known_recipe_domain(url) and not _is_excluded_domain(url):
            return url

    return None


def _is_excluded_domain(url: str) -> bool:
    """Check if URL is from an excluded domain"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)


def _is_known_recipe_domain(url: str) -> bool:
    """Check if URL is from a known recipe domain"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in KNOWN_RECIPE_DOMAINS)
