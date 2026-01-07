#!/bin/bash

# YouTube Video Info Test Script
# Easy way to test the Python script from terminal

SCRIPT_DIR="/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/YT-Vid-Recipie"
PYTHON_PATH="$SCRIPT_DIR/.venv/bin/python"
MAIN_SCRIPT="$SCRIPT_DIR/main.py"

echo "🎥 YouTube Video Info Fetcher - Test Script"
echo "==========================================="
echo ""

# Check if Python script exists
if [[ ! -f "$MAIN_SCRIPT" ]]; then
    echo "❌ Error: main.py not found in $SCRIPT_DIR"
    exit 1
fi

# Check if virtual environment exists
if [[ ! -f "$PYTHON_PATH" ]]; then
    echo "❌ Error: Virtual environment not found at $PYTHON_PATH"
    exit 1
fi

# If argument provided, use it
if [[ $# -eq 1 ]]; then
    echo "🔄 Processing: $1"
    echo ""
    "$PYTHON_PATH" "$MAIN_SCRIPT" "$1"
    echo ""
    echo "✅ Done!"
    exit 0
fi

# Interactive mode
echo "Enter a YouTube URL or Video ID (or 'q' to quit):"
echo "Examples:"
echo "  • dQw4w9WgXcQ"
echo "  • https://www.youtube.com/watch?v=dQw4w9WgXcQ"
echo ""

while true; do
    echo -n "YouTube URL/ID: "
    read -r input
    
    if [[ "$input" == "q" ]] || [[ "$input" == "quit" ]]; then
        echo "👋 Goodbye!"
        break
    fi
    
    if [[ -z "$input" ]]; then
        echo "❌ Please enter a valid URL or video ID"
        continue
    fi
    
    echo ""
    echo "🔄 Processing: $input"
    echo "===================="
    
    # Run the Python script
    "$PYTHON_PATH" "$MAIN_SCRIPT" "$input"
    
    echo ""
    echo "✅ Done! Enter another URL/ID or 'q' to quit:"
    echo ""
done
