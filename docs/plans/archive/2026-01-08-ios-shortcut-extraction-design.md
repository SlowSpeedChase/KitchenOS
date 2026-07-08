# iOS Shortcut Recipe Extraction Design

## Overview

Add a `/extract` endpoint to the existing Flask API server so iOS Shortcuts can trigger full recipe extraction via Share Sheet. Uses Tailscale for connectivity from anywhere.

## Requirements

- Share YouTube video from iOS → recipe saved to Obsidian
- Works from anywhere (via Tailscale, not just local network)
- Shows notification with recipe name on success
- Simple synchronous flow (no job queuing)

## Architecture

### Current State

```
api_server.py
  └── /transcript  → returns transcript + description (no extraction)
  └── /health      → health check
```

### New State

```
api_server.py
  └── /transcript  → returns transcript + description
  └── /extract     → runs full extraction, saves to Obsidian  ← NEW
  └── /health      → health check
```

## Implementation

### `/extract` Endpoint

```python
import subprocess
from pathlib import Path

@app.route('/extract', methods=['POST'])
def extract_recipe():
    """Run full recipe extraction and save to Obsidian."""
    data = request.get_json(force=True, silent=True) or {}
    url = data.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        result = subprocess.run(
            ['.venv/bin/python', 'extract_recipe.py', url],
            capture_output=True,
            text=True,
            cwd='/Users/chaseeasterling/KitchenOS',
            timeout=300  # 5 min timeout
        )

        # Parse output for "SAVED: /path/to/file.md"
        if result.returncode == 0 and 'SAVED:' in result.stdout:
            saved_line = [l for l in result.stdout.split('\n') if 'SAVED:' in l][0]
            filepath = saved_line.split('SAVED:')[1].strip()
            recipe_name = Path(filepath).stem
            return jsonify({'status': 'success', 'recipe': recipe_name})
        else:
            error_msg = result.stderr.strip() if result.stderr else 'Extraction failed'
            return jsonify({'status': 'error', 'message': error_msg}), 500

    except subprocess.TimeoutExpired:
        return jsonify({'status': 'error', 'message': 'Extraction timed out (5 min)'}), 504
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
```

### iOS Shortcut Flow

```
┌─────────────────────────────────────────┐
│  Receive [URLs] from Share Sheet        │
├─────────────────────────────────────────┤
│  Get Contents of URL                    │
│  URL: http://<tailscale-ip>:5001/extract│
│  Method: POST                           │
│  Body: JSON { "url": [Shortcut Input] } │
├─────────────────────────────────────────┤
│  If [status] = "success"                │
│    Show Notification: "Recipe Extracted"│
│    Body: [recipe]                       │
│  Otherwise                              │
│    Show Notification: "Extraction Failed│
│    Body: [message]                      │
└─────────────────────────────────────────┘
```

### Connectivity

- Mac runs `api_server.py` on port 5001
- Mac's Tailscale IP is stable (e.g., `100.x.y.z`)
- iOS device on same Tailnet can reach `http://100.x.y.z:5001/extract`
- Works from anywhere with internet

## Files Changed

| File | Change |
|------|--------|
| `api_server.py` | Add `/extract` endpoint |
| `iOS_SHORTCUT_SETUP.md` | Rewrite for extraction + Tailscale |

## Error Handling

| Scenario | Response |
|----------|----------|
| No URL provided | 400: `{"error": "No URL provided"}` |
| Extraction fails | 500: `{"status": "error", "message": "<stderr>"}` |
| Timeout (5 min) | 504: `{"status": "error", "message": "Extraction timed out"}` |
| Ollama not running | 500: error message from script |

## Testing

```bash
# Start server
cd /Users/chaseeasterling/KitchenOS
PORT=5001 .venv/bin/python api_server.py

# Test extraction (from another terminal)
curl -X POST http://localhost:5001/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=bJUiWdM__Qw"}'
```

## Future Considerations

- **Async mode**: If extractions get slow, add job queue with polling
- **Auth**: Add API key if exposing beyond Tailnet
- **Menu bar integration**: Show remote extractions in history
