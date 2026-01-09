#!/bin/bash
# Start the API server for iOS Shortcuts

cd "$(dirname "$0")"
source .venv/bin/activate
PORT=5001 python api_server.py
