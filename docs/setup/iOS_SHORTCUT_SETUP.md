# iOS Shortcut Setup

> **Legacy/alternate path.** The primary way to extract recipes on iOS is now the native
> KitchenOS app (Siri / App Intents) — see `docs/API.md` for the Siri-facing routes. This
> Share-Sheet `/extract` shortcut still works and remains useful for ad-hoc extraction from
> a browser share sheet, but it is no longer the main flow.

Extract recipes from YouTube videos via iOS Share Sheet. Works from anywhere using Tailscale.

## Prerequisites

- Tailscale installed on Mac and iOS device (same Tailnet)
- API server running on Mac
- Ollama running on Mac

## Step 1: Start the Server on Your Mac

```bash
cd /Users/chaseeasterling/Dev/KitchenOS
PORT=5001 .venv/bin/python api_server.py
```

Or run in background:
```bash
PORT=5001 nohup .venv/bin/python api_server.py > server.log 2>&1 &
```

Verify it's running:
```bash
curl http://localhost:5001/health
# Should return: {"status":"ok"}
```

## Step 2: Create the iOS Shortcut

1. Open **Shortcuts** app on iPhone/iPad
2. Tap **+** to create new shortcut
3. Name it "Extract Recipe"

### Add These Actions

**Action 1: Receive Input**
- Add: **Receive** what **URLs** from **Share Sheet**

**Action 2: Get Contents of URL**
- Add: **Get Contents of URL**
- URL: `http://chases-mac-mini.taila69703.ts.net:5001/extract`
- Method: **POST**
- Request Body: **JSON**
- Add key: `url` with value: select **Shortcut Input**

**Action 3: Show Result**
- Add: **If**
- Condition: **Dictionary Value** for key `status` **equals** `success`
- Then: **Show Notification**
  - Title: `Recipe Saved`
  - Body: Select **Dictionary Value** for key `recipe`
- Otherwise: **Show Notification**
  - Title: `Extraction Failed`
  - Body: Select **Dictionary Value** for key `message`

### Enable Share Sheet

1. Tap the shortcut name at top
2. Tap **Share Sheet**
3. Enable **Show in Share Sheet**
4. Under "Share Sheet Types", select only **URLs**

## Step 3: Use the Shortcut

1. Watch a YouTube video in Safari or YouTube app
2. Tap **Share**
3. Tap **Extract Recipe**
4. Wait 30-60 seconds
5. Get notification with recipe name

The recipe is now in your Obsidian vault.

## Running Server at Startup (Optional)

The `com.kitchenos.api` LaunchAgent starts the server automatically. The plist lives in
the repo at `ops/com.kitchenos.api.plist` — see `docs/OPERATIONS.md` for the install/
restart/uninstall commands rather than hand-authoring one here.

## Troubleshooting

**"Could not connect to server"**
- Check Tailscale is connected on both devices
- Verify server is running: `curl http://localhost:5001/health`
- Check the Mac's Tailscale hostname (`chases-mac-mini.taila69703.ts.net`) resolves from the iOS device

**"Extraction failed"**
- Ensure Ollama is running: `ollama serve`
- Check server logs: `tail -f /Users/chaseeasterling/Dev/KitchenOS/logs/server.log`

**"Extraction timed out"**
- Video may be very long
- Try again - Ollama may have been slow to respond

**Shortcut times out before extraction completes**
- iOS Shortcuts can timeout on long requests
- If this happens frequently, consider reducing video length or checking Ollama performance

## API Reference

### POST /extract

Extracts recipe from YouTube video and saves to Obsidian.

**Request:**
```json
{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}
```

**Success Response (200):**
```json
{"status": "success", "recipe": "2026-01-08-pasta-aglio-e-olio"}
```

**Error Response (500):**
```json
{"status": "error", "message": "Error description"}
```

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```
