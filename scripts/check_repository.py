"""Reject runtime data and recognizable credentials in tracked/staged files.

Never prints secret values. This is a guardrail, not a general secret scanner.
"""
import re
import subprocess
import sys
from pathlib import PurePosixPath


def git(*args):
    return subprocess.check_output(['git', *args])


def forbidden(path):
    p = PurePosixPath(path.lower())
    return (
        any(part in {'data', '.test-tmp', 'work', 'logs', 'digests', 'exports', '.venv', 'venv'} for part in p.parts)
        or p.name.startswith(('.env', 'credentials', 'secrets'))
        or p.name in {'settings.json', 'settings.tmp'}
        or p.name.startswith(('settings.local.', 'config.local.'))
        or any(p.name.endswith(suffix) for suffix in ('.db', '.pem', '.key', '.lnk', '.zip'))
        or '.sqlite' in p.name
    )


def main():
    staged = '--staged' in sys.argv
    args = ('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z') if staged else ('ls-files', '-z')
    paths = [p.decode('utf-8') for p in git(*args).split(b'\0') if p]
    patterns = [
        re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{25,}\b'),
        re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{30,}\b'),
        re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}\b'),
    ]
    failed = []
    for path in paths:
        if forbidden(path):
            failed.append((path, 'runtime/private file'))
            continue
        # Read the index, so staged content cannot differ from what is checked.
        content = git('show', ':' + path)
        if any(pattern.search(content) for pattern in patterns):
            failed.append((path, 'possible credential'))
    if failed:
        for path, reason in failed:
            print(f'BLOCKED: {path} ({reason})')
        return 1
    print(f'PASS: {len(paths)} indexed files; no runtime data or recognizable credentials.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
