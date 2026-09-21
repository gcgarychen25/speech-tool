#!/bin/zsh
# Late-to-lecture: open Speech Tool in Lecture mode and start a new recording.
# Global hotkey: Control-Option-L (installed by scripts/install-lecture-hotkey.sh).
# Start the user-scoped service on demand; never depends on an IDE or terminal.
set -euo pipefail

URL="http://127.0.0.1:8787/?mode=lecture&record=1"

if ! curl -sf --max-time 1 "http://127.0.0.1:8787/api/health" >/dev/null; then
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
    if curl -sf --max-time 1 "http://127.0.0.1:8787/api/health" >/dev/null; then break; fi
    sleep 0.2
  done
  if ! curl -sf --max-time 1 "http://127.0.0.1:8787/api/health" >/dev/null; then
    osascript -e 'display alert "Speech Tool could not start" message "Check ~/Library/Application Support/SpeechTool/runtime/server.log. Your saved recordings are safe."'
    exit 1
  fi
fi

# Force a new Chrome tab with the query string. `open` can reuse an existing
# Speech tab (URL already stripped), which would not start recording.
if ! osascript <<'APPLESCRIPT'
tell application "Google Chrome"
  activate
  open location "http://127.0.0.1:8787/?mode=lecture&record=1"
end tell
APPLESCRIPT
then
  open -a "Google Chrome" "$URL"
fi
