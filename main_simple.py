#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie/.venv/lib/python3.9/site-packages')

import argparse
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import os
import re
import warnings
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
        return None

def print_transcript(video_id):
    try:
        # Try to get transcript in different languages
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to find an English transcript first
        try:
            transcript = transcript_list.find_transcript(['en'])
            transcript_data = transcript.fetch()
            print("Found English transcript:")
            for segment in transcript_data:
                print(segment['text'])
            return True
        except:
            # If no English, try any available transcript
            for transcript in transcript_list:
                try:
                    transcript_data = transcript.fetch()
                    print(f"Found transcript in language: {transcript.language}")
                    for segment in transcript_data:
                        print(segment['text'])
                    return True
                except:
                    continue
            
        print("No readable transcripts found for this video.")
        print("Note: Whisper fallback is available in the full version.")
        return False
        
    except Exception as e:
        print(f"Error fetching transcript: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch YouTube video transcript and description.")
    parser.add_argument('video_id_in', type=str, help='The ID or URL of the YouTube video')
    args = parser.parse_args()

    video_id = youtube_parser(args.video_id_in)
    print(f"Processing video ID: {video_id}")

    # Print the transcript
    print("\n" + "="*50)
    print("TRANSCRIPT:")
    print("="*50)
    transcript_success = print_transcript(video_id)
    
    # Print the video description
    print("\n" + "="*50)
    print("VIDEO DESCRIPTION:")
    print("="*50)
    description = get_video_description(video_id)
    if description:
        print(description)
    else:
        print("No description found for the video.")