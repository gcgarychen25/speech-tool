"""Approved lossless retention: verify, wait 14 days, then remove canonical WAV.

WebM and segment files are never removed. Original event hashes remain unchanged.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.request

from .archive import archive_one, native_pcm_hash, sha256

GRACE_SECONDS = 14 * 24 * 3600


def atomic_json(path: Path, value: dict):
    fd, temporary = tempfile.mkstemp(prefix='.retention-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def archive_reference(root: Path, event_id: str, source_hash: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', event_id) or not re.fullmatch(r'[0-9a-f]{64}', source_hash or ''):
        raise ValueError('Invalid archive identity')
    base = (root / 'audio_archive').resolve()
    folder = base / event_id / (source_hash + '-flac')
    if not folder.resolve().is_relative_to(base):
        raise ValueError('Archive escapes store')
    manifest = json.loads((folder / 'manifest.json').read_text())
    archive = folder / 'reference.flac'
    if archive.is_symlink() or manifest.get('archive_filename') != archive.name:
        raise ValueError('Invalid archive path')
    if (manifest.get('source_sha256') != source_hash or manifest.get('event_id') != event_id
            or manifest.get('lossy') is not False or manifest.get('codec') != 'flac'
            or not manifest.get('native_pcm_sha256') or sha256(archive) != manifest.get('archive_sha256')):
        raise ValueError('Archive integrity verification failed')
    return archive


def retain_event(root: Path, event_dir: Path, *, now: float | None = None, allow_removal: bool = False) -> dict:
    injected_clock = now is not None
    now = time.time() if now is None else now
    event = json.loads((event_dir / 'event.json').read_text())
    eid = event_dir.name
    name = event.get('audio_filename', '')
    if Path(name).name != name or Path(name).suffix.lower() != '.wav':
        return {'event_id': eid, 'status': 'compressed_or_noncanonical_retained'}
    source = event_dir / name
    if event_dir.is_symlink() or source.is_symlink():
        raise ValueError('Symlinked raw source is not eligible')
    raw = event_dir / 'transcript.raw.txt'
    if event.get('asr_status') != 'completed' or not raw.exists() or not raw.read_text().strip():
        return {'event_id': eid, 'status': 'transcription_not_complete'}
    digest = event.get('audio_sha256')
    if not digest:
        return {'event_id': eid, 'status': 'missing_original_hash_retained'}
    if source.exists():
        if sha256(source) != digest:
            raise ValueError('Original audio hash changed')
        row = archive_one(source, root / 'audio_archive', eid)
        if row['status'] not in {'verified', 'already_verified'}:
            return row
    archive = archive_reference(root, eid, digest)
    receipt_path = archive.parent / 'retention.json'
    # Separate receipt starts the grace period only when retention is enabled.
    if not receipt_path.exists():
        if not source.exists() or native_pcm_hash(source) != native_pcm_hash(archive):
            raise ValueError('Cannot establish lossless retention baseline')
        verified_at = now if injected_clock else time.time()
        atomic_json(receipt_path, {'verified_at': verified_at, 'delete_not_before': verified_at + GRACE_SECONDS,
                                  'source_sha256': digest, 'archive_sha256': sha256(archive)})
    receipt = json.loads(receipt_path.read_text())
    if (receipt['source_sha256'] != digest or receipt['archive_sha256'] != sha256(archive)
            or not math.isfinite(receipt['verified_at']) or not math.isfinite(receipt['delete_not_before'])
            or receipt['delete_not_before'] < receipt['verified_at'] + GRACE_SECONDS):
        raise ValueError('Invalid retention receipt')
    result = {'event_id': eid, 'archive': str(archive), 'delete_not_before': receipt['delete_not_before']}
    if not source.exists():
        return {**result, 'status': 'archived_original_removed'}
    if now < receipt['delete_not_before']:
        return {**result, 'status': 'grace_period_original_retained'}
    if not allow_removal:
        return {**result, 'status': 'playback_service_not_verified_original_retained'}
    # Re-read eligibility and verify both files immediately before removing only
    # the exact canonical WAV. Never remove a failed/running ASR source.
    current = json.loads((event_dir / 'event.json').read_text())
    if current.get('asr_status') != 'completed' or current.get('audio_sha256') != digest:
        return {**result, 'status': 'event_changed_original_retained'}
    if sha256(source) != digest or native_pcm_hash(source) != native_pcm_hash(archive):
        raise ValueError('Final lossless verification failed')
    source.unlink()
    atomic_json(receipt_path, {**receipt, 'original_removed_at': now})
    return {**result, 'status': 'original_removed_lossless_copy_verified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        candidates = []
        for path in sorted((args.root / 'events').glob('*/event.json')):
            event = json.loads(path.read_text())
            name = event.get('audio_filename', '')
            source = path.parent / name
            if Path(name).name == name and source.suffix.lower() == '.wav' and source.is_file():
                candidates.append({'event_id': path.parent.name, 'bytes': source.stat().st_size,
                                   'asr_status': event.get('asr_status')})
        print(json.dumps({'mode': 'dry_run', 'canonical_wav_files': candidates,
                          'grace_days_from_verification': 14, 'webm': 'unchanged', 'deleted': 0}))
        return
    policy = json.loads((args.root / 'audio_retention_policy.json').read_text())
    if policy.get('mode') != 'lossless_wav_flac' or policy.get('retention_days') != 14:
        raise ValueError('Explicit approved lossless policy required')
    # An offline/rolled-back playback service must never trigger reclamation.
    allow_removal = False
    try:
        with urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3) as response:
            health = json.load(response)
            allow_removal = health.get('audio_archive_protocol') == 1
    except Exception:
        pass
    with (args.root / '.audio-retention.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        failures = 0
        for path in sorted((args.root / 'events').glob('*/event.json')):
            try:
                row = retain_event(args.root, path.parent, allow_removal=allow_removal)
                if row['status'] != 'compressed_or_noncanonical_retained':
                    print(json.dumps(row), flush=True)
            except Exception as exc:
                failures += 1
                print(json.dumps({'event_id': path.parent.name, 'status': 'failed_original_retained', 'error': str(exc)}), flush=True)
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
