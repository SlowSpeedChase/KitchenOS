# How to Run the YouTube Video Info Fetcher

You now have several easy ways to run your YouTube video info script! Here are all the options:

## 🖥️ Option 1: Terminal with Test Script (Easiest for Testing)

### Single video:
```bash
./test_script.sh "dQw4w9WgXcQ"
# or
./test_script.sh "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### Interactive mode:
```bash
./test_script.sh
```
Then enter URLs/IDs as prompted. Type 'q' to quit.

## 🍎 Option 2: AppleScript (GUI)

### Basic version:
```bash
osascript run_youtube_info.applescript
```

### Advanced version (with clipboard detection and save options):
```bash
osascript run_youtube_info_advanced.applescript
```

## 🔧 Option 3: Direct Python (Original Method)

```bash
/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python main.py "VIDEO_ID_HERE"
```

## 📱 Option 4: Automator App (Most User-Friendly)

Follow the instructions in `create_automator_app.md` to create a drag-and-drop application.

## 🎯 Quick Test Examples

Try these video IDs/URLs for testing:

1. **Rick Astley** (music video, no transcripts):
   - `dQw4w9WgXcQ`
   - `https://www.youtube.com/watch?v=dQw4w9WgXcQ`

2. **Educational content** (more likely to have transcripts):
   - Try any educational YouTube video URL

## 🚀 Recommended for Daily Use

1. **For quick testing**: Use `./test_script.sh`
2. **For GUI experience**: Use the advanced AppleScript
3. **For automation**: Create the Automator app
4. **For integration**: Use the direct Python method

## 🛠️ Troubleshooting

If something doesn't work:
1. Make sure you're in the project directory
2. Check that the virtual environment is activated
3. Verify your API key is valid
4. Test with the shell script first

All methods will show the same output format with clear sections for transcripts and video descriptions.
