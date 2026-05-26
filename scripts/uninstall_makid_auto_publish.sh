#!/bin/zsh
set -euo pipefail
umask 077

LABEL="com.makid.web-play.publish-data"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
AGENT_DIR="$HOME/Library/Application Support/makid/web-play-agent"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
rm -f "$PLIST_PATH"
rm -f "$AGENT_DIR/run_auto_publish.sh" "$AGENT_DIR/expected-hashes.tsv"
rmdir "$AGENT_DIR" 2>/dev/null || true

echo "Uninstalled $LABEL"
