#!/bin/bash
# Rebuild + register the kitchenos:// URL-scheme handler app.
#
# The Obsidian meal-plan buttons open kitchenos://... URLs. macOS routes those
# to KitchenOSHandler.app (built here from handler.applescript), which forwards
# the URL to handler.sh -> the local API server.
#
# The .app is a binary bundle and is NOT committed to git, so it must be rebuilt
# after any machine rebuild / fresh clone. Run this script once; that's it.
#
#   ./scripts/kitchenos-uri-handler/install.sh
#
# Requires: the com.kitchenos.api LaunchAgent running (button no-ops otherwise).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/KitchenOSHandler.app"
PLIST="$APP/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

echo "Building $APP ..."
rm -rf "$APP"
osacompile -o "$APP" "$DIR/handler.applescript"

echo "Registering kitchenos:// URL scheme ..."
$PB -c "Add :CFBundleURLTypes array" "$PLIST"
$PB -c "Add :CFBundleURLTypes:0 dict" "$PLIST"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLName string com.kitchenos.uri" "$PLIST"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$PLIST"
$PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string kitchenos" "$PLIST"
$PB -c "Set :CFBundleIdentifier com.kitchenos.urihandler" "$PLIST"
$PB -c "Add :LSUIElement bool true" "$PLIST"

echo "Signing (ad-hoc) ..."
codesign --force --deep -s - "$APP"

echo "Registering with LaunchServices ..."
"$LSREG" -f "$APP"

echo "Done. kitchenos:// is now handled by KitchenOSHandler.app"
echo "Test: open \"kitchenos://generate-shopping-list?week=\$(date +%G-W%V)\""
