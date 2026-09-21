from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_LEXICON_PATH = Path(__file__).resolve().parents[2] / "docs" / "asr_lexicon.json"


@lru_cache(maxsize=1)
def load_lexicon() -> list[dict]:
    if not _LEXICON_PATH.exists():
        return []
    local = _LEXICON_PATH.with_name("asr_lexicon.local.json")
    data = json.loads((local if local.exists() else _LEXICON_PATH).read_text(encoding="utf-8"))
    return list(data.get("entries") or [])


NOTE_PROMPT = (
    "Mandarin in Simplified Chinese mixed with English. "
    "Terms: Whisper, ASR, CUDA, KV cache, DeepSeek, Perlmutter."
)


def course_key(course: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", course.lower())
    for key, aliases in {"cs4787": ("4787", "5777"), "systemsllm": ("5470", "systemsllm"),
                         "rust": ("5416", "4414", "rust"), "robotics": ("6758",),
                         "frontiercv": ("5672", "frontiercv"), "marin": ("marin",)}.items():
        if any(alias in value for alias in aliases):
            return key
    return value


def course_entries(course: str | None):
    if course is None:  # Legacy callers can still inspect the whole glossary.
        return load_lexicon()
    key = course_key(course)
    return [entry for entry in load_lexicon() if key and course_key(entry.get("course", "")) == key]


def whisper_initial_prompt(kind: str | None = None, course: str | None = None) -> str:
    if kind != "lecture_chunk":
        return NOTE_PROMPT
    intended: list[str] = []
    seen: set[str] = set()
    for entry in course_entries(course):
        term = str(entry.get("intended") or "").strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        intended.append(term)
        if len(intended) >= 36:
            break
    if not intended:
        return "Lecture in English and Simplified Chinese."
    return (
        "Lecture in English and Simplified Chinese. Technical terms: "
        + ", ".join(intended)
        + "."
    )


def polish_lexicon_block(course: str | None = None) -> str:
    lines = []
    for entry in course_entries(course):
        heard = str(entry.get("heard") or "").strip()
        intended = str(entry.get("intended") or "").strip()
        if heard and intended and heard.lower() != intended.lower():
            context = entry.get("context")
            lines.append(f"- {heard} → {intended}" + (f" (only {context})" if context else ""))
    if not lines:
        return ""
    return (
        "Possible ASR confusions — correct only when the surrounding meaning supports it:\n"
        + "\n".join(lines)
        + "\n\n"
    )
