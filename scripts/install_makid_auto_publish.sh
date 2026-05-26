#!/bin/zsh
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT_DIR="$HOME/Library/Application Support/makid"
AGENT_DIR="$APP_SUPPORT_DIR/web-play-agent"
RUNNER_PATH="$AGENT_DIR/run_auto_publish.sh"
HASH_CONFIG_PATH="$AGENT_DIR/expected-hashes.tsv"
AUTO_SCRIPT="$PROJECT_DIR/scripts/makid_auto_publish.sh"
PUBLISHER_SCRIPT="$PROJECT_DIR/makid_publish_web_audio_v0_3.py"
LABEL="com.makid.web-play.publish-data"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_PATH="$HOME/Library/Logs/makid-web-play-publish.log"
ERROR_LOG_PATH="$HOME/Library/Logs/makid-web-play-publish-error.log"
DB_PATH="${MAKID_SOURCE_DB:-$HOME/Library/Application Support/makid/MAKID.db}"

hash_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

for required_file in "$AUTO_SCRIPT" "$PUBLISHER_SCRIPT"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required file not found: $required_file" >&2
    exit 1
  fi
done

mkdir -p "$APP_SUPPORT_DIR" "$AGENT_DIR"
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs"
chmod 700 "$APP_SUPPORT_DIR" "$AGENT_DIR"
touch "$LOG_PATH" "$ERROR_LOG_PATH"
chmod 600 "$LOG_PATH" "$ERROR_LOG_PATH"

{
  printf 'project_dir\t%s\n' "$PROJECT_DIR"
  printf 'auto_script\t%s\n' "$AUTO_SCRIPT"
  printf 'auto_hash\t%s\n' "$(hash_file "$AUTO_SCRIPT")"
  printf 'publisher_script\t%s\n' "$PUBLISHER_SCRIPT"
  printf 'publisher_hash\t%s\n' "$(hash_file "$PUBLISHER_SCRIPT")"
} > "$HASH_CONFIG_PATH"
chmod 600 "$HASH_CONFIG_PATH"

cat > "$RUNNER_PATH" <<'RUNNER'
#!/bin/zsh
set -euo pipefail
umask 077

RUNNER_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$RUNNER_DIR/expected-hashes.tsv"

read_config_value() {
  local key="$1"

  awk -F '\t' -v key="$key" '
    $1 == key {
      print substr($0, index($0, "\t") + 1)
      found = 1
      exit
    }
    END {
      exit found ? 0 : 1
    }
  ' "$CONFIG_FILE"
}

hash_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

fail_changed() {
  local file="$1"

  echo "Auto-publish refused to run because a guarded file changed:" >&2
  echo "$file" >&2
  echo "Review the change, then reinstall the agent:" >&2
  echo "cd \"$PROJECT_DIR\" && npm run auto:install" >&2
  exit 1
}

PROJECT_DIR="$(read_config_value project_dir)"
AUTO_SCRIPT="$(read_config_value auto_script)"
EXPECTED_AUTO_HASH="$(read_config_value auto_hash)"
PUBLISHER_SCRIPT="$(read_config_value publisher_script)"
EXPECTED_PUBLISHER_HASH="$(read_config_value publisher_hash)"

[[ -f "$AUTO_SCRIPT" ]] || fail_changed "$AUTO_SCRIPT"
[[ -f "$PUBLISHER_SCRIPT" ]] || fail_changed "$PUBLISHER_SCRIPT"

[[ "$(hash_file "$AUTO_SCRIPT")" == "$EXPECTED_AUTO_HASH" ]] || fail_changed "$AUTO_SCRIPT"
[[ "$(hash_file "$PUBLISHER_SCRIPT")" == "$EXPECTED_PUBLISHER_HASH" ]] || fail_changed "$PUBLISHER_SCRIPT"

exec /bin/zsh "$AUTO_SCRIPT"
RUNNER
chmod 700 "$RUNNER_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER_PATH</string>
  </array>

  <key>WatchPaths</key>
  <array>
    <string>$DB_PATH</string>
  </array>

  <key>StartInterval</key>
  <integer>300</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>Umask</key>
  <integer>63</integer>

  <key>StandardOutPath</key>
  <string>$LOG_PATH</string>

  <key>StandardErrorPath</key>
  <string>$ERROR_LOG_PATH</string>
</dict>
</plist>
PLIST
chmod 600 "$PLIST_PATH"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed $LABEL"
echo "Watching: $DB_PATH"
echo "Runner: $RUNNER_PATH"
echo "Hash config: $HASH_CONFIG_PATH"
echo "Log: $LOG_PATH"
echo "Error log: $ERROR_LOG_PATH"
