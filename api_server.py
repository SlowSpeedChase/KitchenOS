#!/usr/bin/env python3
"""Simple API server for iOS Shortcuts integration."""

from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import os
import re
import warnings
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL 1.1.1+')

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

app = Flask(__name__)


def youtube_parser(input_str):
    """Extract video ID from URL or return as-is."""
    # Handle youtu.be short URLs
    match = re.search(r'youtu\.be/([^?&]+)', input_str)
    if match:
        return match.group(1)
    # Handle standard YouTube URLs
    match = re.search(r'v=([^&]+)', input_str)
    if match:
        return match.group(1)
    return input_str


def get_video_description(video_id):
    """Fetch video description from YouTube API."""
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(part='snippet', id=video_id)
        response = request.execute()

        if 'items' in response and len(response['items']) > 0:
            return response['items'][0]['snippet']['description']
        return None
    except Exception as e:
        return f"[Error fetching description: {e}]"


def get_transcript(video_id):
    """Fetch transcript from YouTube."""
    try:
        api = YouTubeTranscriptApi()
        try:
            transcript_data = api.fetch(video_id, languages=['en'])
        except:
            transcript_data = api.fetch(video_id)

        return ' '.join([segment.text for segment in transcript_data])
    except Exception as e:
        return None


@app.route('/transcript', methods=['GET', 'POST'])
def get_video_info():
    """Main endpoint - accepts URL via GET param or POST body."""
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url') or request.form.get('url')
    else:
        url = request.args.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    video_id = youtube_parser(url)

    # Build the output blob
    output_parts = []

    # Get transcript
    transcript = get_transcript(video_id)
    if transcript:
        output_parts.append("TRANSCRIPT:")
        output_parts.append(transcript)
    else:
        output_parts.append("TRANSCRIPT: No transcript available")

    output_parts.append("")  # blank line

    # Get description
    description = get_video_description(video_id)
    if description:
        output_parts.append("DESCRIPTION:")
        output_parts.append(description)
    else:
        output_parts.append("DESCRIPTION: No description available")

    combined_text = '\n'.join(output_parts)

    return jsonify({
        'text': combined_text,
        'video_id': video_id
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
