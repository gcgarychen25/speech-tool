#!/usr/bin/env python3
"""Read-only publication checks. Reports categories and paths, never secret values."""
import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath

PATTERNS = {
    'credential token': re.compile(rb'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'personal home path': re.compile(rb'(?:/Users/|/home/)[A-Za-z0-9_.-]+/'),
    'email address': re.compile(rb'[A-Za-z0-9._%+-]+@(?!(?:users\.noreply\.github\.com|example\.(?:com|org|net))\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'recording identifier': re.compile(rb'(?:sessions|events)/[0-9a-f]{8}-[0-9a-f-]{27,}'),
    'literal credential': re.compile(rb'(?i)(?:api[_-]?key|password|secret|token)\s*[:=]\s*[\x27\x22][A-Za-z0-9_+./=-]{16,}[\x27\x22]'),
}
PRIVATE_DIRS = {'data', 'recordings', 'events', 'sessions', 'notes', 'audio_archive', 'runtime', 'backups', '.private', 'local', 'verification_artifacts', '.venv', '__pycache__'}
PRIVATE_NAMES = {'.cursorrules', 'AGENTS.local.md', 'asr_lexicon.local.json', 'clean_transcript.py'}
PRIVATE_SUFFIXES = {'.wav', '.webm', '.flac', '.mp3', '.m4a', '.ogg', '.opus', '.log', '.db', '.sqlite', '.zip', '.gz', '.pem', '.key', '.pyc'}


def git(*args):
    return subprocess.check_output(['git', *args])


def inspect(path, data):
    p = PurePosixPath(path)
    issues = []
    if (set(p.parts) & PRIVATE_DIRS or p.name in PRIVATE_NAMES or p.suffix in PRIVATE_SUFFIXES
            or p.name.startswith(('raw_transcript', 'cleaned_transcript', 'event_path_index'))
            or p.name.startswith('.env') and p.name != '.env.example'):
        issues.append('private artifact path')
    if b'\0' in data:
        issues.append('binary requires exclusion or explicit policy review')
    issues.extend(label for label, pattern in PATTERNS.items() if pattern.search(data))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--index', action='store_true')
    group.add_argument('--history')
    args = parser.parse_args()
    findings = set()
    trees = []
    if args.index:
        for line in git('ls-files', '--stage', '-z').split(b'\0'):
            if not line:
                continue
            meta, path = line.split(b'\t', 1)
            mode, oid, stage = meta.split()
            if mode != b'100644' and mode != b'100755' or stage != b'0':
                findings.add((path.decode(), 'unsupported file mode or unresolved merge'))
            trees.append((oid.decode(), path.decode()))
    else:
        commit = git('rev-parse', '--verify', args.history + '^{commit}').decode().strip()
        for rev in git('rev-list', commit).decode().split():
            emails = git('show', '-s', '--format=%ae%n%ce', rev).decode().splitlines()
            if any(not email.endswith('@users.noreply.github.com') for email in emails):
                findings.add((rev[:12], 'commit identity is not GitHub noreply'))
            for issue in inspect('commit-message', git('show', '-s', '--format=%B', rev)):
                findings.add((rev[:12], issue))
            for row in git('ls-tree', '-r', '-z', rev).split(b'\0'):
                if not row:
                    continue
                meta, path = row.split(b'\t', 1)
                mode, kind, oid = meta.split()
                if kind != b'blob' or mode not in {b'100644', b'100755'}:
                    findings.add((path.decode(), 'unsupported file mode'))
                    continue
                trees.append((oid.decode(), path.decode()))
    for oid, path in set(trees):
        for issue in inspect(path, git('cat-file', 'blob', oid)):
            findings.add((path, issue))
    for path, issue in sorted(findings):
        print(f'BLOCKED: {path}: {issue}', file=sys.stderr)
    if findings:
        return 1
    print('Privacy pattern checks passed; human content review is still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
