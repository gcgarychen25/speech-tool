from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class Correction:
    polished: str
    copied: str
    unified_diff: str
    replacements: list[dict]

    @property
    def changed(self) -> bool:
        return self.polished != self.copied


def build_correction(polished: str, copied: str) -> Correction:
    left = polished.splitlines(keepends=True) or [""]
    right = copied.splitlines(keepends=True) or [""]
    unified = "".join(
        difflib.unified_diff(left, right, fromfile="polished", tofile="copied", lineterm="\n")
    )
    replacements: list[dict] = []
    matcher = difflib.SequenceMatcher(a=polished, b=copied, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        replacements.append(
            {
                "op": tag,
                "from": polished[i1:i2],
                "to": copied[j1:j2],
            }
        )
    return Correction(
        polished=polished,
        copied=copied,
        unified_diff=unified,
        replacements=replacements,
    )
