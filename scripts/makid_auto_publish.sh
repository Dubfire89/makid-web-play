#!/bin/zsh
set -euo pipefail
umask 077

PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_SUPPORT_DIR="$HOME/Library/Application Support/makid"
STATE_DIR="$APP_SUPPORT_DIR/web_export"
FINGERPRINT_FILE="$STATE_DIR/FileTable.sha256"
LOCK_DIR="${TMPDIR:-/tmp}/makid-web-play-publish.lock"
DELAY_SECONDS="${MAKID_AUTO_PUBLISH_DELAY_SECONDS:-10}"

read_env_value() {
  local key="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    return 1
  fi

  awk -F= -v key="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == key {
      value = substr($0, index($0, "=") + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^["'\'']|["'\'']$/, "", value)
      print value
    }
  ' "$file" | tail -n 1
}

DB_PATH="${MAKID_SOURCE_DB:-}"

if [[ -z "$DB_PATH" ]]; then
  DB_PATH="$(read_env_value MAKID_SOURCE_DB "$PROJECT_DIR/.env.local" || true)"
fi

if [[ -z "$DB_PATH" ]]; then
  DB_PATH="$APP_SUPPORT_DIR/MAKID.db"
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "MAKID database not found: $DB_PATH"
  exit 1
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Publisher already running. Skipping this trigger."
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap cleanup EXIT

mkdir -p "$STATE_DIR"
chmod 700 "$APP_SUPPORT_DIR" "$STATE_DIR" 2>/dev/null || true
sleep "$DELAY_SECONDS"

fingerprint_file_table() {
  sqlite3 "$DB_PATH" <<'SQL' | shasum -a 256 | awk '{print $1}'
PRAGMA query_only=ON;
.mode tabs
SELECT
  IFNULL(id, '') || char(9) ||
  IFNULL(name, '') || char(9) ||
  IFNULL(ext, '') || char(9) ||
  IFNULL(path, '') || char(9) ||
  IFNULL(size, '') || char(9) ||
  IFNULL(createdAt, '') || char(9) ||
  IFNULL(lastModified, '') || char(9) ||
  IFNULL(hash, '')
FROM File
ORDER BY id;
SQL
}

fingerprint=""

for attempt in {1..6}; do
  if fingerprint="$(fingerprint_file_table)" && [[ -n "$fingerprint" ]]; then
    break
  fi

  echo "Could not read File table yet. Retry $attempt/6..."
  sleep 5
done

if [[ -z "$fingerprint" ]]; then
  echo "Could not fingerprint File table: $DB_PATH"
  exit 1
fi

previous_fingerprint=""

if [[ -f "$FINGERPRINT_FILE" ]]; then
  previous_fingerprint="$(cat "$FINGERPRINT_FILE")"
fi

if [[ "$fingerprint" == "$previous_fingerprint" ]]; then
  echo "MAKID File table unchanged. Skipping publisher."
  exit 0
fi

echo "MAKID File table changed. Running publisher directly..."
cd "$PROJECT_DIR"
/usr/bin/python3 "$PROJECT_DIR/makid_publish_web_audio_v0_3.py"
echo "$fingerprint" > "$FINGERPRINT_FILE"
chmod 600 "$FINGERPRINT_FILE" 2>/dev/null || true
echo "Publisher complete."
