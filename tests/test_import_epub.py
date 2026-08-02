"""Tests for import_epub.py — the EPUB importer's wiring around the shared pipeline."""

from pathlib import Path

import import_epub


def test_book_dietary_badges_survive_enrichment(monkeypatch):
    """enrich_with_ollama replaces list fields wholesale. The badges are printed in
    the book, so inference must not be allowed to drop them."""
    def fake_enrich(recipe_data):
        enriched = dict(recipe_data)
        enriched["dietary"] = ["vegan"]  # model forgets the badges
        return enriched

    monkeypatch.setattr(import_epub, "enrich_with_ollama", fake_enrich)

    result = import_epub.enrich_preserving_book_facts(
        {"recipe_name": "X", "dietary": ["vegan", "nut-free", "gluten-free"]}
    )
    assert result["dietary"] == ["vegan", "nut-free", "gluten-free"]


def test_extra_inferred_dietary_is_kept_behind_book_facts(monkeypatch):
    def fake_enrich(recipe_data):
        enriched = dict(recipe_data)
        enriched["dietary"] = ["high-protein"]
        return enriched

    monkeypatch.setattr(import_epub, "enrich_with_ollama", fake_enrich)

    result = import_epub.enrich_preserving_book_facts(
        {"recipe_name": "X", "dietary": ["vegan", "nut-free"]}
    )
    assert result["dietary"] == ["vegan", "nut-free", "high-protein"]


def test_enrichment_returning_no_dietary_leaves_book_facts_intact(monkeypatch):
    monkeypatch.setattr(import_epub, "enrich_with_ollama", lambda r: dict(r, dietary=[]))
    result = import_epub.enrich_preserving_book_facts(
        {"recipe_name": "X", "dietary": ["vegan", "gluten-free"]}
    )
    assert result["dietary"] == ["vegan", "gluten-free"]


def test_book_title_strips_calibre_decoration():
    assert import_epub.book_title(
        Path("/x/Big Vegan Flavor_ Techniques and 150 Recip - Nisha Vora.epub")
    ) == "Big Vegan Flavor"
