from __future__ import annotations

import subprocess
from pathlib import Path

from speech_tool.config import NOTE_MAX_SECONDS


class MediaError(RuntimeError):
    pass


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MediaError(result.stderr.strip() or "ffprobe failed")
    value = result.stdout.strip()
    if not value or value == "N/A":
        # MediaRecorder WebM (including recovered partial chunks) often lacks
        # container duration. Packet timestamps still establish its length.
        packets = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
            "packet=pts_time,duration_time", "-of", "csv=p=0", str(path),
        ], capture_output=True, text=True, check=False, timeout=30)
        ends = []
        for line in packets.stdout.splitlines():
            fields = line.split(",")
            try:
                ends.append(float(fields[0]) + float(fields[1]))
            except (ValueError, IndexError):
                continue
        if not ends:
            raise MediaError("No decodable audio packets; original upload retained in browser")
        return max(ends)
    return float(value)


def ensure_wav_16k(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MediaError(result.stderr.strip() or "ffmpeg failed")
    return dest


def validate_duration(seconds: float, limit: float | None = None) -> None:
    cap = NOTE_MAX_SECONDS if limit is None else limit
    if seconds > cap + 2:
        raise MediaError(
            f"Recording is {seconds:.1f}s; max supported duration is {cap}s"
        )
