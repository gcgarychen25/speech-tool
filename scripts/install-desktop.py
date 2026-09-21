#!/usr/bin/env python3
"""Install user-scoped background service and Spotlight launcher; dry-run by default."""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys
import hashlib
import shutil
import time
import json
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.speechtool.server"


def unload_service(domain, label):
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    deadline = time.monotonic() + 10
    while subprocess.run(["launchctl", "print", f"{domain}/{label}"], capture_output=True).returncode == 0:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Service is still unloading: {label}")
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--replace-service", action="store_true", help="Back up and replace this tool's installed service")
    parser.add_argument("--enable-audio-retention", action="store_true", help="Approved lossless WAV archival with a 14-day verified grace period")
    args = parser.parse_args()
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    app = Path.home() / "Applications/Speech Tool.app"
    runtime = Path.home() / "Library/Application Support/SpeechTool/runtime"
    python = runtime / "venv/bin/python"
    if not python.exists():
        sys.exit("Create the dedicated runtime/venv and install Speech Tool dependencies first; do not use an evictable Desktop venv.")
    files = sorted((ROOT / "src/speech_tool").glob("*.py"))
    files += sorted((ROOT / "web").glob("*.js")) + sorted((ROOT / "web").glob("*.html"))
    files += [ROOT / "docs/asr_lexicon.json", ROOT / "scripts/start-lecture.sh"]
    local_lexicon = ROOT / "docs/asr_lexicon.local.json"
    if local_lexicon.exists():
        files.append(local_lexicon)
    signature = hashlib.sha256()
    for path in files:
        signature.update(str(path.relative_to(ROOT)).encode())
        signature.update(path.read_bytes())
    release = runtime / "releases" / signature.hexdigest()[:16]
    config = {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "speech_tool", "--no-open", "--no-replace"],
        "WorkingDirectory": str(release),
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 15,
        "EnvironmentVariables": {"PATH": f"{python.resolve().parent}:{Path.home()}/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(release / "src")},
        "StandardOutPath": str(runtime / "server.log"),
        "StandardErrorPath": str(runtime / "server.log"),
    }
    print(f"Service: {plist}\nLauncher: {app}\nPython: {python}\nLogs: {runtime / 'server.log'}")
    print(f"Local release: {release}\nOriginal recordings are not changed. --replace-service restarts only this tool's service.")
    if not args.install:
        return
    if not python.exists():
        sys.exit("Missing project .venv/bin/python")
    runtime.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    for path in files:
        dest = release / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.read_bytes() != path.read_bytes():
            sys.exit(f"Release collision: {dest}")
        if not dest.exists():
            shutil.copy2(path, dest)
    domain = f"gui/{os.getuid()}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if plist.exists():
        previous = plistlib.loads(plist.read_bytes())
        if previous != config:
            if not args.replace_service or previous.get("Label") != LABEL or "speech_tool" not in previous.get("ProgramArguments", []):
                sys.exit("Existing service differs; review it and use --replace-service for an approved update.")
            shutil.copy2(plist, runtime / f"server.before-{stamp}.plist")
            unload_service(domain, LABEL)
    plist.write_bytes(plistlib.dumps(config))
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    launcher = contents / "MacOS/launch"
    launcher.write_text("#!/bin/zsh\nexec /bin/zsh " + shlex.quote(str(release / "scripts/start-lecture.sh")) + "\n")
    launcher.chmod(0o755)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "launch", "CFBundleIdentifier": "com.speechtool.launcher",
        "CFBundleName": "Speech Tool", "CFBundlePackageType": "APPL", "LSUIElement": True,
    }))
    if subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True).returncode:
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    # Existing global hotkey must also survive Desktop file eviction.
    hotkey_plist = plist.with_name("com.speechtool.lecture-hotkey.plist")
    hotkey_binary = ROOT / "scripts/lecture-hotkey"
    if hotkey_plist.exists() and hotkey_binary.exists():
        hotkey = plistlib.loads(hotkey_plist.read_bytes())
        if hotkey.get("Label") != "com.speechtool.lecture-hotkey":
            sys.exit("Unexpected hotkey label; left unchanged")
        dest = runtime / "bin/lecture-hotkey"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(hotkey_binary, dest)
        dest.chmod(0o755)
        arguments = [str(dest), str(release / "scripts/start-lecture.sh")]
        if hotkey.get("ProgramArguments") != arguments:
            shutil.copy2(hotkey_plist, runtime / f"hotkey.before-{stamp}.plist")
            hotkey["ProgramArguments"] = arguments
            unload_service(domain, "com.speechtool.lecture-hotkey")
            hotkey_plist.write_bytes(plistlib.dumps(hotkey))
        if subprocess.run(["launchctl", "print", f"{domain}/com.speechtool.lecture-hotkey"], capture_output=True).returncode:
            subprocess.run(["launchctl", "bootstrap", domain, str(hotkey_plist)], check=True)
    policy_path = runtime.parent / 'audio_retention_policy.json'
    if args.enable_audio_retention and not policy_path.exists():
        policy_path.write_text(json.dumps({'mode': 'lossless_wav_flac', 'retention_days': 14,
                                          'approved_at': datetime.now(timezone.utc).isoformat()}, indent=2))
    if policy_path.exists():
        policy = json.loads(policy_path.read_text())
        if policy.get('mode') != 'lossless_wav_flac' or policy.get('retention_days') != 14:
            sys.exit('Unexpected retention policy; archive service left unchanged.')
        archive_label = 'com.speechtool.audio-retention'
        archive_plist = plist.with_name(archive_label + '.plist')
        archive_config = {
            'Label': archive_label,
            'ProgramArguments': [str(python), '-m', 'speech_tool.retention', '--root', str(runtime.parent), '--apply'],
            'WorkingDirectory': str(release), 'RunAtLoad': True, 'StartInterval': 3600,
            'ProcessType': 'Background', 'LowPriorityIO': True, 'Nice': 10,
            'EnvironmentVariables': config['EnvironmentVariables'],
            'StandardOutPath': str(runtime / 'audio-retention.log'),
            'StandardErrorPath': str(runtime / 'audio-retention.log'),
        }
        if archive_plist.exists():
            previous = plistlib.loads(archive_plist.read_bytes())
            if previous.get('Label') != archive_label:
                sys.exit('Unexpected archive service; left unchanged.')
            if previous != archive_config:
                shutil.copy2(archive_plist, runtime / f'archive.before-{stamp}.plist')
                unload_service(domain, archive_label)
        archive_plist.write_bytes(plistlib.dumps(archive_config))
        if subprocess.run(['launchctl', 'print', f'{domain}/{archive_label}'], capture_output=True).returncode:
            subprocess.run(['launchctl', 'bootstrap', domain, str(archive_plist)], check=True)
        print('Lossless WAV archival enabled hourly; originals retained for 14 days after verification. WebM unchanged.')
    print("Installed. Open Speech Tool with Spotlight or Control-Option-L.")


if __name__ == "__main__":
    main()
