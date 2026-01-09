#!/bin/bash
# KitchenOS URI Handler
# Handles kitchenos:// URLs and calls the local API server

set -e

URI="$1"
API_BASE="http://localhost:5001"

# Parse the URI: kitchenos://action?param=value
ACTION=$(echo "$URI" | sed -E 's|kitchenos://([^?]+).*|\1|')
QUERY=$(echo "$URI" | sed -E 's|.*\?(.*)|\1|')

# Extract week parameter
WEEK=$(echo "$QUERY" | sed -E 's|.*week=([^&]+).*|\1|')

# Function to show notification
notify() {
    local title="$1"
    local message="$2"
    osascript -e "display notification \"$message\" with title \"$title\""
}

# Check if API server is running
if ! curl -s "$API_BASE/health" > /dev/null 2>&1; then
    notify "KitchenOS" "Server not running. Start it first."
    exit 1
fi

case "$ACTION" in
    "generate-shopping-list")
        RESPONSE=$(curl -s -X POST "$API_BASE/generate-shopping-list" \
            -H "Content-Type: application/json" \
            -d "{\"week\": \"$WEEK\"}")

        SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")

        if [ "$SUCCESS" = "True" ]; then
            COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('item_count', 0))")
            notify "KitchenOS" "Shopping list created with $COUNT items"
        else
            ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'Unknown error'))")
            notify "KitchenOS Error" "$ERROR"
        fi
        ;;

    "send-to-reminders")
        RESPONSE=$(curl -s -X POST "$API_BASE/send-to-reminders" \
            -H "Content-Type: application/json" \
            -d "{\"week\": \"$WEEK\"}")

        SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")

        if [ "$SUCCESS" = "True" ]; then
            SENT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items_sent', 0))")
            SKIPPED=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items_skipped', 0))")
            notify "KitchenOS" "Sent $SENT items to Reminders ($SKIPPED already checked)"
        else
            ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'Unknown error'))")
            notify "KitchenOS Error" "$ERROR"
        fi
        ;;

    *)
        notify "KitchenOS Error" "Unknown action: $ACTION"
        exit 1
        ;;
esac
