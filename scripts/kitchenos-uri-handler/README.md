# KitchenOS URI Handler

Handles `kitchenos://` URLs from Obsidian buttons.

## Installation

### Option 1: Automator App (Recommended)

1. Open Automator
2. Create new "Application"
3. Add "Run Shell Script" action
4. Set shell to `/bin/bash`
5. Set "Pass input" to "as arguments"
6. Add script content:
   ```bash
   /Users/chaseeasterling/KitchenOS/scripts/kitchenos-uri-handler/handler.sh "$1"
   ```
7. Save as `KitchenOSHandler.app` in `/Applications/`
8. Edit `Info.plist` inside app bundle to add URL scheme (see below)

### Adding URL Scheme to Info.plist

Add to `KitchenOSHandler.app/Contents/Info.plist`:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLName</key>
        <string>KitchenOS Handler</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>kitchenos</string>
        </array>
    </dict>
</array>
```

### Option 2: Manual Testing

Test directly from terminal:
```bash
./scripts/kitchenos-uri-handler/handler.sh "kitchenos://generate-shopping-list?week=2026-W04"
```

## Supported URLs

- `kitchenos://generate-shopping-list?week=YYYY-WNN` - Generate shopping list markdown
- `kitchenos://send-to-reminders?week=YYYY-WNN` - Send unchecked items to Apple Reminders

## Requirements

- API server must be running: `curl http://localhost:5001/health`
- macOS (uses osascript for notifications)

## Troubleshooting

If notifications don't appear:
1. Check System Preferences > Notifications
2. Ensure Terminal/Automator has notification permissions
