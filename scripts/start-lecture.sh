#!/bin/zsh
# Late-to-lecture: open Speech Tool in Lecture mode and start a new recording.
# Global hotkey: Control-Option-L (installed by scripts/install-lecture-hotkey.sh).
# Start the user-scoped service on demand; never depends on an IDE or terminal.
set -euo pipefail

PORT=8787
BASE="http://127.0.0.1:${PORT}"
QUERY="mode=lecture&record=1"

# Optional local Calendar autofill (EventKit helper). Never talks to Google.
HELPER=""
for candidate in \
  "$HOME/Library/Application Support/SpeechTool/runtime/bin/calendar-current" \
  "$(cd "$(dirname "$0")" && pwd)/calendar-current"
do
  if [[ -x "$candidate" ]]; then
    HELPER="$candidate"
    break
  fi
done

if [[ -n "$HELPER" ]]; then
  SUGGEST="$("$HELPER" 2>/dev/null || true)"
  COURSE="$(printf '%s' "$SUGGEST" | /usr/bin/python3 -c 'import sys,json,urllib.parse
raw=sys.stdin.read().strip()
if not raw:
  raise SystemExit
try:
  data=json.loads(raw.splitlines()[-1])
except Exception:
  raise SystemExit
course=(data.get("course") or data.get("event_title") or "").strip()
if course:
  print(urllib.parse.quote(course))
' 2>/dev/null || true)"
  if [[ -n "${COURSE:-}" ]]; then
    QUERY="${QUERY}&course=${COURSE}"
  fi
fi

URL="${BASE}/?${QUERY}"

if ! curl -sf --max-time 1 "${BASE}/api/health" >/dev/null; then
  DOMAIN="gui/$(id -u)"
  LABEL="com.speechtool.server"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  if [[ ! -f "$PLIST" ]]; then
    osascript -e 'display alert "Speech Tool needs setup" message "Run scripts/install-desktop.py --install once. After setup, no terminal is needed."'
    exit 1
  fi
  if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl bootstrap "$DOMAIN" "$PLIST"
  fi
  launchctl kickstart "$DOMAIN/$LABEL" 2>/dev/null || true
  for attempt in {1..100}; do
    if curl -sf --max-time 1 "${BASE}/api/health" >/dev/null; then break; fi
    sleep 0.2
  done
  if ! curl -sf --max-time 1 "${BASE}/api/health" >/dev/null; then
    osascript -e 'display alert "Speech Tool could not start" message "Check ~/Library/Application Support/SpeechTool/runtime/server.log. Your saved recordings are safe."'
    exit 1
  fi
fi

# Force a new Chrome tab with the query string. `open` can reuse an existing
# Speech tab (URL already stripped), which would not start recording.
AS_URL=$(printf '%s' "$URL" | /usr/bin/python3 -c 'import sys; print(sys.stdin.read().replace("\\", "\\\\").replace("\"", "\\\""))')
if ! osascript <<APPLESCRIPT
tell application "Google Chrome"
  activate
  open location "${AS_URL}"
end tell
APPLESCRIPT
then
  open -a "Google Chrome" "$URL"
fi
