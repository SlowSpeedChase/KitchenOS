# YouTube Shorts Support Design

Date: 2026-01-08
Status: Implemented
Priority: High

## Problem

YouTube Shorts URLs (`youtube.com/shorts/VIDEO_ID`) cannot be processed because:
1. `youtube_parser()` doesn't recognize the `/shorts/` URL pattern
2. YouTube Data API doesn't return metadata for Shorts

## Solution

**Approach B: Detect Shorts URLs, use yt-dlp for metadata**

- Keep YouTube API for regular videos (fast, reliable)
- Detect `/shorts/` URLs and route to yt-dlp
- yt-dlp already imported for Whisper audio download

## Design

### 1. URL Parser Changes

Update `youtube_parser()` return type from `str` to `dict`:

```python
def youtube_parser(input_str):
    """Parse YouTube URL and return video ID with format info.

    Returns:
        dict with keys:
            - video_id: str
            - is_short: bool (True if /shorts/ URL)
    """
    # Check for Shorts URL: youtube.com/shorts/VIDEO_ID
    match = re.search(r'youtube\.com/shorts/([^?&/]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': True}

    # Check for standard YouTube URL with v= parameter
    match = re.search(r'v=([^&]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': False}

    # Check for youtu.be short URL format
    match = re.search(r'youtu\.be/([^?&]+)', input_str)
    if match:
        return {'video_id': match.group(1), 'is_short': False}

    # Assume input is a video ID
    return {'video_id': input_str, 'is_short': False}
```

### 2. New yt-dlp Metadata Function

```python
def get_video_metadata_ytdlp(video_id, is_short=False):
    """Fetch video metadata using yt-dlp (for Shorts and fallback).

    Returns same structure as get_video_metadata():
        {'title': str, 'channel': str, 'description': str}
        or None on failure
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }

    # Use appropriate URL format
    if is_short:
        url = f"https://www.youtube.com/shorts/{video_id}"
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', ''),
                'channel': info.get('channel', '') or info.get('uploader', ''),
                'description': info.get('description', '')
            }
    except yt_dlp.utils.DownloadError as e:
        print(f"yt-dlp error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error fetching metadata: {e}", file=sys.stderr)
        return None
```

### 3. Metadata Routing

Update `get_video_metadata()` to route based on video type:

```python
def get_video_metadata(video_id, is_short=False):
    """Fetch video metadata.

    Uses YouTube API for regular videos, yt-dlp for Shorts.
    """
    if is_short:
        return get_video_metadata_ytdlp(video_id, is_short=True)

    # Existing YouTube API logic for regular videos
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(
            part='snippet',
            id=video_id
        )
        response = request.execute()

        if 'items' in response and len(response['items']) > 0:
            snippet = response['items'][0]['snippet']
            return {
                'title': snippet.get('title', ''),
                'channel': snippet.get('channelTitle', ''),
                'description': snippet.get('description', '')
            }
        else:
            return None
    except Exception as e:
        print(f"Error fetching video metadata: {e}", file=sys.stderr)
        return None
```

### 4. Video URL Construction

Update callers to construct correct URL format:

```python
# In extract_recipe.py and elsewhere
parsed = youtube_parser(url)
video_id = parsed['video_id']
is_short = parsed['is_short']

if is_short:
    video_url = f"https://www.youtube.com/shorts/{video_id}"
else:
    video_url = f"https://www.youtube.com/watch?v={video_id}"
```

## Files to Modify

| File | Changes |
|------|---------|
| `main.py` | Update `youtube_parser()` return type, add `get_video_metadata_ytdlp()`, update `get_video_metadata()` signature, update `__main__` block |
| `extract_recipe.py` | Unpack dict from `youtube_parser()`, pass `is_short`, construct correct video URL |
| `api_server.py` | Update local `youtube_parser()` and `get_video_description()` with same pattern |
| `main_simple.py` | Update if still in use |

## Edge Cases

### User pastes Short as watch URL
YouTube supports both URL formats for the same video:
- `youtube.com/shorts/ABC123`
- `youtube.com/watch?v=ABC123`

The watch URL works with YouTube API even for Shorts. Only `/shorts/` URLs trigger yt-dlp.

### Transcript availability
Shorts often have auto-generated captions. `get_transcript()` works unchanged since it uses video ID, not URL format.

### yt-dlp failure
If yt-dlp fails for a Short, return error rather than falling back to YouTube API (which won't work for `/shorts/` URLs).

## Test Cases

| Input | Expected Result |
|-------|-----------------|
| `youtube.com/watch?v=ABC123` | `{'video_id': 'ABC123', 'is_short': False}` |
| `youtube.com/shorts/ABC123` | `{'video_id': 'ABC123', 'is_short': True}` |
| `youtube.com/shorts/ABC123?feature=share` | `{'video_id': 'ABC123', 'is_short': True}` |
| `youtu.be/ABC123` | `{'video_id': 'ABC123', 'is_short': False}` |
| `ABC123` | `{'video_id': 'ABC123', 'is_short': False}` |

## Future Considerations

This pattern (platform detection → specialized handler) sets up well for:
- TikTok support (different extractor)
- Instagram Reels (different extractor)
- Other video platforms
