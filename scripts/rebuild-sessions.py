#!/usr/bin/env python3
"""Create provenance-backed reconstruction candidates without changing raw data or user edits."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from speech_tool.config import data_dir
from speech_tool.store import EventStore


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=data_dir())
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    store = EventStore(args.data_dir)
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for session in store.list_sessions():
        events = store.session_chunks(session.id)
        text = store.session_raw_text(session.id)
        name = f"{session.id}.reconstructed.txt"
        (args.output / name).write_text(text, encoding="utf-8")
        current = store.session_display_text(session.id)
        records.append({"session_id": session.id, "course": session.course, "title": session.title,
            "file": name, "source_event_ids": [e.id for e in events],
            "raw_sha256": {e.id: hashlib.sha256((store.read_raw_transcript(e.id) or "").encode()).hexdigest() for e in events},
            "existing_display_sha256": hashlib.sha256(current.encode()).hexdigest(),
            "duration_seconds": sum(e.duration_seconds for e in events),
            "review_required": current.strip() != text.strip(),
            "warning": "Review class boundaries; raw reconstruction may include mic-left-on content."})
    (args.output / "manifest.json").write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
        "source_store": str(args.data_dir), "sessions": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} reconstruction candidates. Source artifacts unchanged.")


if __name__ == "__main__":
    main()
