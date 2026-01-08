# iOS Shortcut Setup

Extract recipes from YouTube videos via iOS Share Sheet. Works from anywhere using Tailscale.

## Prerequisites

- Tailscale installed on Mac and iOS device (same Tailnet)
- API server running on Mac
- Ollama running on Mac

## Step 1: Find Your Mac's Tailscale IP

```bash
tailscale ip -4
```

This returns something like `100.x.y.z`. Save this - it stays stable.

## Step 2: Start the Server on Your Mac

```bash
cd /Users/chaseeasterling/KitchenOS
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

## Step 3: Create the iOS Shortcut

1. Open **Shortcuts** app on iPhone/iPad
2. Tap **+** to create new shortcut
3. Name it "Extract Recipe"

### Add These Actions

**Action 1: Receive Input**
- Add: **Receive** what **URLs** from **Share Sheet**

**Action 2: Get Contents of URL**
- Add: **Get Contents of URL**
- URL: `http://100.111.6.10:5001/extract`
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

## Step 4: Use the Shortcut

1. Watch a YouTube video in Safari or YouTube app
2. Tap **Share**
3. Tap **Extract Recipe**
4. Wait 30-60 seconds
5. Get notification with recipe name

The recipe is now in your Obsidian vault.

## Running Server at Startup (Optional)

Create a LaunchAgent to start the server automatically:

```bash
cat > ~/Library/LaunchAgents/com.kitchenos.api.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kitchenos.api</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/chaseeasterling/KitchenOS/.venv/bin/python</string>
        <string>/Users/chaseeasterling/KitchenOS/api_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/chaseeasterling/KitchenOS</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PORT</key>
        <string>5001</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/chaseeasterling/KitchenOS/server.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/chaseeasterling/KitchenOS/server.log</string>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.kitchenos.api.plist
```

To stop:
```bash
launchctl unload ~/Library/LaunchAgents/com.kitchenos.api.plist
```

## Troubleshooting

**"Could not connect to server"**
- Check Tailscale is connected on both devices
- Verify server is running: `curl http://localhost:5001/health`
- Check your Tailscale IP is correct

**"Extraction failed"**
- Ensure Ollama is running: `ollama serve`
- Check server logs: `tail -f /Users/chaseeasterling/KitchenOS/server.log`

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
