#!/bin/zsh
# Compile the Control-Option-L helper and load it as a login LaunchAgent.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/scripts/lecture-hotkey"
SCRIPT="$ROOT/scripts/start-lecture.sh"
PLIST="$HOME/Library/LaunchAgents/com.speechtool.lecture-hotkey.plist"
LABEL="com.speechtool.lecture-hotkey"

chmod +x "$SCRIPT"
swiftc -O -framework Cocoa -framework Carbon -o "$BIN" "$ROOT/scripts/lecture-hotkey.swift"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BIN}</string>
    <string>${SCRIPT}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>LimitLoadToSessionType</key>
  <string>Aqua</string>
  <key>StandardOutPath</key>
  <string>/tmp/speech-tool-lecture-hotkey.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/speech-tool-lecture-hotkey.log</string>
</dict>
</plist>
EOF

UID_NUM="$(id -u)"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
echo "Loaded ${LABEL}. Press Control-Option-L to start a lecture recording."
