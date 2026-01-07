# YouTube Video Info Fetcher

This script fetches YouTube video transcripts and descriptions using the YouTube API.

## Setup

1. **Virtual Environment**: Make sure you're using the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

2. **API Key**: Set your YouTube API key as an environment variable:
   ```bash
   export YOUTUBE_API_KEY="your_api_key_here"
   ```
   Or modify the API_KEY variable in the script directly.

## Usage

Run the script with a YouTube video ID or URL:

```bash
/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python main.py "VIDEO_ID_HERE"
# or
/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python main.py "https://www.youtube.com/watch?v=VIDEO_ID_HERE"
```

### Examples:
```bash
/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python main.py "dQw4w9WgXcQ"
/Users/chaseeasterling/Documents/GitHub/yt_vid_info/.venv/bin/python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Features

- ✅ Extracts video descriptions using YouTube Data API
- ✅ Attempts to fetch transcripts in multiple languages
- ✅ Handles errors gracefully
- ✅ Supports both video IDs and full YouTube URLs
- ✅ Improved error messages

## Common Issues

### 1. "No readable transcripts found"
This means:
- The video doesn't have captions/transcripts available
- The video is private or restricted
- Transcripts are disabled by the creator

### 2. "Error fetching video description"
This could mean:
- Invalid API key
- API quota exceeded
- Invalid video ID
- Network connectivity issue

### 3. SSL Warning
The urllib3 warning is harmless and doesn't affect functionality. It's just a compatibility notice.

## Dependencies

- `youtube-transcript-api` - For fetching transcripts
- `google-api-python-client` - For YouTube Data API
- `argparse` - For command line arguments

All dependencies are installed in the virtual environment.
