"""Tests for recipe parser module"""
import tempfile
from pathlib import Path
from lib.recipe_parser import parse_recipe_file, extract_my_notes, extract_video_id, find_existing_recipe


def test_parse_recipe_file_extracts_frontmatter():
    """Should extract frontmatter as dict"""
    content = '''---
title: "Pasta Aglio e Olio"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
servings: 2
---

# Pasta Aglio e Olio

Content here
'''
    result = parse_recipe_file(content)

    assert result['frontmatter']['title'] == 'Pasta Aglio e Olio'
    assert result['frontmatter']['source_url'] == 'https://www.youtube.com/watch?v=bJUiWdM__Qw'
    assert result['frontmatter']['servings'] == 2


def test_parse_recipe_file_extracts_body():
    """Should extract body content after frontmatter"""
    content = '''---
title: "Test"
---

# Test Recipe

Some content here.
'''
    result = parse_recipe_file(content)

    assert '# Test Recipe' in result['body']
    assert 'Some content here.' in result['body']


def test_extract_my_notes_returns_notes_section():
    """Should extract content after ## My Notes heading"""
    content = '''# Recipe

## Ingredients

- flour

## My Notes

This is my personal note.
I added extra garlic.
'''
    notes = extract_my_notes(content)

    assert 'This is my personal note.' in notes
    assert 'I added extra garlic.' in notes


def test_extract_my_notes_returns_empty_when_missing():
    """Should return empty string if no My Notes section"""
    content = '''# Recipe

## Ingredients

- flour
'''
    notes = extract_my_notes(content)

    assert notes == ''


def test_extract_my_notes_preserves_formatting():
    """Should preserve markdown formatting in notes"""
    content = '''## My Notes

- Item 1
- Item 2

**Bold text** and *italic*
'''
    notes = extract_my_notes(content)

    assert '- Item 1' in notes
    assert '**Bold text**' in notes


def test_extract_video_id_from_watch_url():
    """Should extract video ID from standard YouTube URL"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_from_short_url():
    """Should extract video ID from youtu.be URL"""
    url = "https://youtu.be/bJUiWdM__Qw"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_extract_video_id_with_extra_params():
    """Should extract video ID even with extra URL params"""
    url = "https://www.youtube.com/watch?v=bJUiWdM__Qw&t=120"

    video_id = extract_video_id(url)

    assert video_id == "bJUiWdM__Qw"


def test_find_existing_recipe_finds_match():
    """Should find recipe file with matching video ID"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        recipe = recipes_dir / "2026-01-07-pasta.md"
        recipe.write_text('''---
title: "Pasta"
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---

# Pasta
''')
        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")
        assert result == recipe


def test_find_existing_recipe_returns_none_when_not_found():
    """Should return None when no matching recipe exists"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        result = find_existing_recipe(recipes_dir, "nonexistent123")
        assert result is None


def test_find_existing_recipe_ignores_history_folder():
    """Should not search in .history directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recipes_dir = Path(tmpdir)
        history_dir = recipes_dir / ".history"
        history_dir.mkdir()
        backup = history_dir / "2026-01-07-pasta.md"
        backup.write_text('''---
source_url: "https://www.youtube.com/watch?v=bJUiWdM__Qw"
---
''')
        result = find_existing_recipe(recipes_dir, "bJUiWdM__Qw")
        assert result is None
