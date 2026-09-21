"""Verified, non-destructive audio reference copies. Originals are never removed.

Run with --apply for a batch or --apply --watch for automatic future copies.
Without --apply, print eligible sources and estimated input size only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def decoded_samples(path: Path) -> int:
    """Count fully decoded mono 16k PCM bytes; do not trust missing WebM duration."""
    with tempfile.TemporaryFile() as pcm, tempfile.TemporaryFile() as errors:
        result = subprocess.run(['ffmpeg','-hide_banner','-v','error','-xerror','-i',str(path),
                                 '-map','0:a:0','-ac','1','-ar','16000','-f','s16le','-'],
                                stdout=pcm,stderr=errors,timeout=600)
        if result.returncode:
            raise ValueError('Audio did not fully decode')
        return pcm.tell() // 2


def native_pcm_hash(path: Path) -> str:
    with tempfile.TemporaryFile() as pcm:
        subprocess.run(['ffmpeg','-hide_banner','-v','error','-xerror','-i',str(path),
                        '-map','0:a:0','-f','s32le','-'],stdout=pcm,stderr=subprocess.PIPE,
                       check=True,timeout=600)
        pcm.seek(0)
        h=hashlib.sha256()
        for part in iter(lambda: pcm.read(1024*1024),b''): h.update(part)
        return h.hexdigest()


def archive_one(source: Path, destination: Path, event_id: str, lossy: bool = False) -> dict:
    source = source.resolve(strict=True)
    if not lossy and source.suffix.lower() != '.wav':
        return {'event_id':event_id,'status':'already_compressed_retained','original_retained':True}
    before = sha256(source)
    folder = destination / event_id / (before + ('-opus32' if lossy else '-flac'))
    folder.mkdir(parents=True, exist_ok=True)
    # A per-source lock prevents concurrent batch/watch processes racing.
    lock = folder / 'writing.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return {'event_id':event_id,'status':'busy_or_interrupted','path':str(folder)}
    os.close(fd)
    try:
        manifest = folder / 'manifest.json'
        if manifest.exists():
            saved = json.loads(manifest.read_text())
            archive = folder / saved['archive_filename']
            if saved['source_sha256'] != before or not archive.exists() or sha256(archive) != saved['archive_sha256']:
                raise ValueError('Existing archive verification failed; left unchanged')
            return {**saved,'status':'already_verified'}
        target = folder / ('reference.opus' if lossy else 'reference.flac')
        if target.exists():
            raise FileExistsError('Uncommitted archive exists; manual inspection required')
        with tempfile.TemporaryDirectory(prefix='encoding-',dir=folder) as temp:
            candidate = Path(temp) / target.name
            codec_args = ['-ac','1','-ar','48000','-c:a','libopus','-b:a','32k',
                          '-application','audio','-vbr','on'] if lossy else ['-c:a','flac']
            subprocess.run(['ffmpeg','-hide_banner','-v','error','-n','-i',str(source),
                            '-map','0:a:0','-vn',*codec_args,str(candidate)],
                           capture_output=True,check=True,timeout=600)
            original_samples = decoded_samples(source)
            archive_samples = decoded_samples(candidate)
            if not original_samples or abs(original_samples-archive_samples) > 1600:
                raise ValueError('Decoded duration mismatch exceeds 100 ms')
            pcm_hash = None
            if not lossy:
                pcm_hash = native_pcm_hash(source)
                if native_pcm_hash(candidate) != pcm_hash:
                    raise ValueError('Lossless PCM identity check failed')
            if sha256(source) != before:
                raise ValueError('Source changed during encoding; no archive published')
            if candidate.stat().st_size >= source.stat().st_size:
                return {'event_id':event_id,'status':'not_smaller','original_retained':True}
            row = {'event_id':event_id,'status':'verified','source_path':str(source),
                   'source_sha256':before,'source_bytes':source.stat().st_size,
                   'archive_filename':target.name,'archive_sha256':sha256(candidate),
                   'archive_bytes':candidate.stat().st_size,'duration_seconds':archive_samples/16000,
                   'duration_difference_seconds':abs(original_samples-archive_samples)/16000,
                   'codec':'opus' if lossy else 'flac','lossy':lossy,'native_pcm_sha256':pcm_hash,
                   'original_retained':True,'quality_review':'decode/duration only; not listening approval' if lossy else 'native PCM identity verified'}
            os.replace(candidate,target)
            with manifest.open('x') as handle:
                json.dump(row,handle,indent=2)
            return row
    finally:
        lock.unlink(missing_ok=True)


def eligible(root: Path):
    for path in sorted((root/'events').glob('*/event.json')):
        event = json.loads(path.read_text())
        raw = path.parent/'transcript.raw.txt'
        if event.get('asr_status') != 'completed' or not raw.exists() or not raw.read_text().strip():
            continue
        # Include segmented legacy notes rather than silently losing their audio.
        sources = list(path.parent.glob('audio.*'))
        sources += [p for p in (path.parent/'segments').glob('seg-*')
                    if p.suffix.lower() in {'.wav','.webm','.mp3','.m4a','.ogg','.opus'}
                    and p.with_suffix('.raw.json').exists()]
        for audio in sorted(sources):
            if '.asr.' in audio.name:
                continue
            if audio.is_file():
                yield path.parent.name,audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--lossy',action='store_true',help='Experimental Opus32 copies; not approved as replacements')
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--event-id',action='append',default=[])
    args=parser.parse_args()
    if args.watch and not args.apply:
        parser.error('--watch requires --apply')
    if args.destination.resolve().is_relative_to((args.root/'events').resolve()):
        parser.error('Archive destination must be outside raw events')
    while True:
        rows=[(eid,p) for eid,p in eligible(args.root) if not args.event_id or eid in args.event_id]
        if args.limit: rows=rows[:args.limit]
        if not args.apply:
            print(json.dumps({'eligible_files':len(rows),'source_bytes':sum(p.stat().st_size for _,p in rows),
                              'mode':'dry_run','originals_deleted':False}))
            return
        for eid,path in rows:
            try: print(json.dumps(archive_one(path,args.destination,eid,args.lossy)),flush=True)
            except Exception as exc: print(json.dumps({'event_id':eid,'status':'failed','error':str(exc)}),flush=True)
        if not args.watch: return
        time.sleep(60)


if __name__ == '__main__':
    main()
