from __future__ import annotations

import subprocess

from speech_tool.config import DEFAULT_BROWSER


def activate_browser(port: int) -> None:
    url = f"http://127.0.0.1:{port}/"
    app = DEFAULT_BROWSER
    _close_and_open_chrome(app, url)


def _close_and_open_chrome(app: str, url: str) -> None:
    needle = url.replace("http://", "").rstrip("/")
    script = f'''
    tell application "System Events"
      set chromeRunning to (exists process "{app}")
    end tell
    if chromeRunning then
      tell application "{app}"
        repeat with w in windows
          try
            set tabList to tabs of w
            repeat with t in reverse of tabList
              try
                if (URL of t as text) contains "{needle}" then close t
              end try
            end repeat
          end try
        end repeat
      end tell
    end if
    do shell script "open -a " & quoted form of "{app}" & " " & quoted form of "{url}"
    tell application "{app}" to activate
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        subprocess.run(["open", "-a", app, url], check=False)
