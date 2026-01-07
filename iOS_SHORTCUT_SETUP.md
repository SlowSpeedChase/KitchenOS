# iOS Shortcut Setup

## Step 1: Start the Server on Your Mac

```bash
cd /Users/chaseeasterling/Documents/Documents\ -\ Chase\'s\ MacBook\ Air\ -\ 1/GitHub/YT-Vid-Recipie
./start_server.sh
```

The server runs on `http://YOUR_MAC_IP:5001`

(Port 5000 is used by macOS AirPlay Receiver, so we use 5001)

Find your Mac's IP:
```bash
ipconfig getifaddr en0
```

## Step 2: Create the iOS Shortcut

1. Open **Shortcuts** app on iPhone/iPad
2. Tap **+** to create new shortcut
3. Add these actions in order:

### Action 1: Get URL Input
- Add: **Receive** (or **Shortcut Input**)
- Set it to accept: **URLs**

### Action 2: Get Contents of URL
- Add: **Get Contents of URL**
- URL: `http://YOUR_MAC_IP:5001/transcript?url=`
- Tap the URL field, then add **Shortcut Input** variable after the `=`
- Method: **GET**

### Action 3: Get Dictionary Value
- Add: **Get Dictionary Value**
- Get: **Value** for **text** in **Contents of URL**

### Action 4: Show Result
- Add: **Quick Look** or **Show Result** or **Copy to Clipboard**
- Input: **Dictionary Value** from previous step

## Step 3: Use the Shortcut

### From Share Sheet:
1. In Safari/YouTube app, tap **Share**
2. Select your shortcut
3. Get the transcript + description blob

### From Clipboard:
Modify the shortcut to use **Clipboard** instead of Shortcut Input

## Alternative: POST Method

If GET doesn't work, use POST:

1. **Get Contents of URL**
   - URL: `http://YOUR_MAC_IP:5001/transcript`
   - Method: **POST**
   - Request Body: **JSON**
   - Add key `url` with value from Shortcut Input

## Troubleshooting

**"Could not connect"**
- Ensure Mac and iPhone are on same WiFi network
- Check the server is running
- Check firewall allows port 5000

**"No transcript available"**
- Video may not have captions
- Try a different video to test

## Keep Server Running

To run the server in background:
```bash
nohup ./start_server.sh > server.log 2>&1 &
```

Stop it with:
```bash
pkill -f api_server.py
```
