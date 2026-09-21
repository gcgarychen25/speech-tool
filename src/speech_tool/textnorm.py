from __future__ import annotations

import re

_HAN = re.compile(r"[\u4e00-\u9fff]")


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese characters to Simplified when present."""
    if not text or not _HAN.search(text):
        return text
    try:
        from zhconv import convert
    except ImportError:
        return text
    return convert(text, "zh-cn")
