from __future__ import annotations

import re

_REPEAT = re.compile(r"(.)\1{8,}")
_LOOP = re.compile(r"(.{8,40})(?:\s+\1){4,}")


def is_noise_transcript(text: str, duration_seconds: float = 0.0) -> bool:
    """True when a chunk is leftover mic noise, not lecture speech."""
    body = (text or "").strip()
    if not body:
        return True
    letters = re.findall(r"[A-Za-z\u4e00-\u9fff]", body)
    if len(body) >= 80 and len(letters) / max(len(body), 1) < 0.12:
        return True
    if _REPEAT.search(body) or _LOOP.search(body):
        return True
    # A regex "word" would treat a whole Chinese sentence as one token, so a
    # normal lecture minute would look as sparse as leftover microphone noise.
    speech_units = len(re.findall(r"[A-Za-z']+", body)) + len(re.findall(r"[\u4e00-\u9fff]", body))
    if duration_seconds >= 45 and speech_units / (duration_seconds / 60) < 18:
        return True
    return False
