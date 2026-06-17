# lib/ conventions

Library modules powering the KitchenOS pipeline. Each file should have a top-level docstring explaining its role — read that first when navigating an unfamiliar module.

## Conventions

- **Vault paths**: derive every recipe/meal-plan/meals path from `paths.py` helpers (`vault_root()`, `recipes_dir()`, `meal_plans_dir()`, `meals_dir()`). Never hardcode a vault path or join `~/KitchenOS/vault/...` directly. The vault location is overridable via the `KITCHENOS_VAULT` env var, and only `paths.py` honors it.
- **Controlled vocabularies** live in `normalizer.py` (recipe tags) and `inventory.py` (`CATEGORIES`, `LOCATIONS`, `SOURCES`). When adding a new tag-like field, add a `*_MAP` and route it through `normalize_field()` rather than letting raw AI output flow through.
- **Backups before destructive writes**: any code that overwrites a recipe file should call `backup.create_backup()` first. Backups live in a sibling `.history/` folder and auto-clean after 30 days.
- **Atomic JSON writes**: see `item_aliases.py` for the `tmp + replace` pattern. Use it for any small JSON sidecar that would corrupt if a write is interrupted (alias cache, task cache).
- **Sidecar caches**: keyed by `<basename>.<purpose>.json` next to the source file (e.g. `2026-W03.tasks.json` next to `2026-W03.md`). Freshness check: `sidecar_mtime >= source_mtime`.
- **DB access**: all SQLite access goes through `inventory_db.py` — never open `sqlite3` connections elsewhere. Tests point the DB at a temp file via the `KITCHENOS_DB` env var (`tmp_db` fixture in `tests/conftest.py`).
