# Origins

Historical record from the initial build (Jan 2026), salvaged from the retired
`docs/IMPLEMENTATION_SUMMARY.md` and `docs/SESSION_SUMMARY.md`. For the current
architecture, see `docs/ARCHITECTURE.md`.

## Why standalone over n8n

The original design proposed an n8n-orchestrated pipeline:

```
YouTube URL → n8n → Python → Ollama → n8n → Obsidian
```

with entry points via an iOS Share Sheet webhook and a daily Apple Reminders poll.
n8n workflows were built for both, but had persistent issues: path escaping for
directories with spaces, unreliable Execute Command node behavior, and webhook
activation/restart requirements.

The n8n phase was abandoned in favor of a standalone Python pipeline:

```
YouTube URL → extract_recipe.py → Ollama → Obsidian
```

Advantages of the simpler approach:
- No external dependencies (n8n not required)
- Easier to debug and maintain
- Works directly from the command line
- Can still be wrapped by automation tools later

## Lessons learned

1. **Start simple** - The standalone script works better than the complex n8n orchestration.
2. **Paths with spaces cause problems** - project was moved to a space-free path.
3. **Python 3.9 has f-string limitations** - can't use backslashes in expressions (moot once the project moved to Python 3.11).
4. **Ollama JSON mode is reliable** - format enforcement works well with `mistral:7b`.
