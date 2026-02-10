import argparse
import json
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import sys
import os
import re
import warnings
import yt_dlp
import openai
import tempfile
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Suppress SSL warnings
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

# Get API keys from environment variables
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

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

def print_virtual_env():
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print(f"Virtual environment: {sys.prefix}")
    else:
        print("No virtual environment detected")

def get_video_description(video_id, is_short=False):
    """Backwards compatible wrapper - returns description string only"""
    metadata = get_video_metadata(video_id, is_short=is_short)
    if metadata:
        return metadata['description']
    return None


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


def get_video_metadata(video_id, is_short=False):
    """Fetch video title, channel, and description.

    Uses YouTube API for regular videos, yt-dlp for Shorts.
    """
    if is_short:
        return get_video_metadata_ytdlp(video_id, is_short=True)

    # Use YouTube API for regular videos
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

def get_first_comment(video_id: str) -> Optional[dict]:
    """Fetch the first (usually pinned) comment on a video.

    Uses YouTube Data API commentThreads endpoint sorted by relevance,
    which surfaces pinned comments first.

    Args:
        video_id: YouTube video ID (works for both regular videos and Shorts)

    Returns:
        Dict with keys: text, author. None if comments are disabled,
        unavailable, or API call fails.
    """
    if not YOUTUBE_API_KEY:
        return None

    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            order='relevance',
            maxResults=1,
        )
        response = request.execute()

        items = response.get('items', [])
        if not items:
            return None

        snippet = items[0]['snippet']['topLevelComment']['snippet']
        return {
            'text': snippet.get('textOriginal', ''),
            'author': snippet.get('authorDisplayName', ''),
        }

    except Exception as e:
        print(f"Could not fetch comments: {e}", file=sys.stderr)
        return None


def print_transcript(video_id):
    try:
        # Create API instance
        api = YouTubeTranscriptApi()
        
        # Try to get transcript - start with English
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
            print("Found English transcript:")
            for segment in transcript_data:
                print(segment.text)
            return True
        except:
            # If no English, try any available transcript
            try:
                transcript_data = api.fetch(video_id)
                print("Found transcript:")
                for segment in transcript_data:
                    print(segment.text)
                return True
            except:
                pass
            
        print("No readable transcripts found for this video.")
        return False
        
    except Exception as e:
        print(f"Error fetching transcript: {str(e)}")
        print("This could mean:")
        print("- The video doesn't have transcripts/captions available")
        print("- The video is private or restricted")
        print("- There's a network connectivity issue")
        return False

def get_transcript(video_id):
    """Fetch transcript and return as string with source indicator.

    Returns:
        dict with keys:
            - text: The transcript text as a string, or None if unavailable
            - source: 'youtube' or 'whisper' if successful, None if failed
            - error: Error message string, or None if successful
    """
    try:
        api = YouTubeTranscriptApi()

        # Try English first
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        # Try any available transcript
        try:
            transcript_data = api.fetch(video_id)
            text = '\n'.join(segment.text for segment in transcript_data)
            return {'text': text, 'source': 'youtube', 'error': None}
        except:
            pass

        # Fallback to Whisper
        if OPENAI_API_KEY:
            audio_file = download_audio(video_id)
            if audio_file:
                whisper_result = transcribe_with_whisper_text(audio_file)
                if whisper_result:
                    return {'text': whisper_result, 'source': 'whisper', 'error': None}

        return {'text': None, 'source': None, 'error': 'No transcript available'}

    except Exception as e:
        return {'text': None, 'source': None, 'error': str(e)}

def download_audio(video_id):
    """Download audio from YouTube video and return file path"""
    try:
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f"{video_id}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find the downloaded file
        audio_file = os.path.join(temp_dir, f"{video_id}.mp3")
        if os.path.exists(audio_file):
            return audio_file
        else:
            print(f"Audio file not found at expected path: {audio_file}")
            return None
            
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return None

def transcribe_with_whisper(audio_file_path):
    """Transcribe audio file using OpenAI Whisper API"""
    if not OPENAI_API_KEY:
        print("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")
        return False
    
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        with open(audio_file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        
        print("Whisper transcription:")
        print(transcript)
        return True
        
    except Exception as e:
        print(f"Error with Whisper transcription: {e}")
        return False
    finally:
        # Clean up the audio file
        try:
            os.remove(audio_file_path)
            # Also remove the temp directory if it's empty
            temp_dir = os.path.dirname(audio_file_path)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass

def transcribe_with_whisper_text(audio_file_path):
    """Transcribe audio file using OpenAI Whisper API, return text only"""
    if not OPENAI_API_KEY:
        return None

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        with open(audio_file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )

        return transcript

    except Exception as e:
        print(f"Whisper error: {e}", file=sys.stderr)
        return None
    finally:
        try:
            os.remove(audio_file_path)
            temp_dir = os.path.dirname(audio_file_path)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcript and description.")
    parser.add_argument('video_id_in', type=str, help='The ID or URL of the YouTube video')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of formatted text')
    args = parser.parse_args()

    parsed = youtube_parser(args.video_id_in)
    video_id = parsed['video_id']
    is_short = parsed['is_short']

    if args.json:
        # JSON output mode for n8n integration
        output = {
            'success': False,
            'video_id': video_id,
            'is_short': is_short,
            'title': None,
            'channel': None,
            'transcript': None,
            'description': None,
            'transcript_source': None,
            'error': None
        }

        # Get metadata (uses yt-dlp for Shorts)
        metadata = get_video_metadata(video_id, is_short=is_short)
        if metadata:
            output['title'] = metadata['title']
            output['channel'] = metadata['channel']
            output['description'] = metadata['description']

        # Get transcript
        transcript_result = get_transcript(video_id)
        output['transcript'] = transcript_result['text']
        output['transcript_source'] = transcript_result['source']

        if transcript_result['error'] and not metadata:
            output['error'] = transcript_result['error']
        else:
            output['success'] = True

        print(json.dumps(output, ensure_ascii=False))
    else:
        # Original text output mode (keep existing behavior)
        video_type = "Short" if is_short else "video"
        print(f"Processing {video_type} ID: {video_id}")

        print("\n" + "="*50)
        print("TRANSCRIPT:")
        print("="*50)
        transcript_success = print_transcript(video_id)

        # If YouTube transcript failed, try Whisper as fallback
        if not transcript_success:
            print("\nNo YouTube transcript available. Trying Whisper transcription...")
            audio_file = download_audio(video_id)
            if audio_file:
                whisper_success = transcribe_with_whisper(audio_file)
                if not whisper_success:
                    print("Whisper transcription also failed.")
            else:
                print("Could not download audio for Whisper transcription.")

        # Print the video description
        print("\n" + "="*50)
        print("VIDEO DESCRIPTION:")
        print("="*50)
        description = get_video_description(video_id, is_short=is_short)
        if description:
            print(description)
        else:
            print("No description found for the video.")


# Running script requires exact path to venv to work; otherwise it throws an errror that it cannot find the youtube api
