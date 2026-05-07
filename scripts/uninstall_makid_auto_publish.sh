#!/bin/zsh
set -euo pipefail

LABEL="com.makid.web-play.publish-data"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Uninstalled $LABEL"
