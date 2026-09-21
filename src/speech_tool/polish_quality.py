"""Conservative checks for obvious cleanup failures, not semantic verification."""
import re


def polish_quality_issue(raw: str, cleaned: str) -> str | None:
    source = ''.join(c for c in raw if c.isalpha())
    output = ''.join(c for c in cleaned if c.isalpha())
    if len(source) < 40:
        return None
    def han(text):
        return sum('\u3400' <= c <= '\u9fff' for c in text) / max(len(text), 1)
    if han(source) < .02 and han(output) > .15 and len(output) > 15:
        return 'Unexpected translation; original language retained in raw transcript'
    if han(source) > .6 and han(output) < .1 and len(output) > 40:
        return 'Unexpected translation; original language retained in raw transcript'
    if len(source) >= 200 and len(output) < len(source) * .45:
        return 'Cleanup removed too much text; raw transcript retained'
    return None
