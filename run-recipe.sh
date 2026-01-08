#!/bin/bash
# Wrapper script for n8n to call the Python recipe extractor
# Filters output to only return the JSON line
cd "/Users/chaseeasterling/Documents/Documents - Chase's MacBook Air - 1/GitHub/KitchenOS"
.venv/bin/python main.py --json "$1" 2>/dev/null | grep '^{' | tail -1
