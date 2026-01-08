import argparse
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
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Suppress SSL warnings
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

# Get API keys from environment variables
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

def youtube_parser(input_str):
    # Check if input is a URL
    match = re.search(r'v=([^&]+)', input_str)
    if match:
        video_id = match.group(1)
        return video_id
    else:
        # Assume input is a video ID
        return input_str

def print_virtual_env():
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print(f"Virtual environment: {sys.prefix}")
    else:
        print("No virtual environment detected")

def get_video_description(video_id):
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(
            part='snippet',
            id=video_id
        )
        response = request.execute()
        
        if 'items' in response and len(response['items']) > 0:
            description = response['items'][0]['snippet']['description']
            return description
        else:
            return None
    except Exception as e:
        print(f"Error fetching video description: {e}")
        print("This could mean:")
        print("- Invalid API key")
        print("- API quota exceeded")
        print("- Invalid video ID")
        print("- Network connectivity issue")
        return None

def get_video_metadata(video_id):
    """Fetch video title, channel, and description from YouTube API"""
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

    video_id = youtube_parser(args.video_id_in)
    print(f"Processing video ID: {video_id}")

    # Print the transcript
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
    description = get_video_description(video_id)
    if description:
        print(description)
    else:
        print("No description found for the video.")


# Running script requires exact path to venv to work; otherwise it throws an errror that it cannot find the youtube api
