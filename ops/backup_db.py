#!/usr/bin/env python3
"""SQLite online backups and isolated restore rehearsals; never restore live DBs."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from zoneinfo import ZoneInfo

NAMES = ('records.sqlite3', 'ai_quota.sqlite3')


def private_directory(path):
    if path.is_symlink():
        raise ValueError('Directory symlinks are not accepted')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError(f'Directory must be owned by the current user and private: {path}')


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_db(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        result = db.execute('PRAGMA integrity_check').fetchall()
        if result != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('SQLite foreign-key check failed')
        digest = hashlib.sha256()
        for line in db.iterdump():
            digest.update(line.encode('utf-8'))
            digest.update(bytes([10]))
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            quoted = '"' + name.replace('"', '""') + '"'
            tables[name] = db.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]
    return {'logical_sha256': digest.hexdigest(), 'tables': tables}


def sqlite_copy(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'Source must be an existing regular DB: {source}')
    with destination.open('xb'):
        pass
    os.chmod(destination, 0o600)
    deadline = time.monotonic() + 60

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('SQLite online backup exceeded 60 seconds')

    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as src:
        with closing(sqlite3.connect(str(destination), timeout=5)) as dst:
            src.backup(dst, pages=128, progress=progress, sleep=0.05)
            dst.execute('PRAGMA journal_mode=DELETE')
    metadata = inspect_db(destination)
    with destination.open('rb') as stream:
        os.fsync(stream.fileno())
    return {**metadata, 'sha256': file_hash(destination), 'bytes': destination.stat().st_size}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(data_dir, backup_root):
    data_dir = data_dir.resolve(strict=True)
    if backup_root.resolve() == data_dir or backup_root.resolve().is_relative_to(data_dir):
        raise ValueError('Backup root must be separate from the live data directory')
    private_directory(backup_root)
    lock = backup_root / '.backup.lock'
    if lock.is_symlink():
        raise ValueError('Lock symlink is not accepted')
    with lock.open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = datetime.now(timezone.utc)
        label = now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        stage = backup_root / ('.incomplete-' + label)
        stage.mkdir(mode=0o700)
        manifest = {
            'format': 1, 'status': 'complete', 'created_utc': now.isoformat(),
            'created_kst': now.astimezone(ZoneInfo('Asia/Seoul')).isoformat(),
            'source_directory': str(data_dir),
            'consistency': 'Each DB is an independent SQLite snapshot, not a cross-DB transaction.',
            'databases': {},
        }
        for name in NAMES:
            source = data_dir / name
            if name == 'ai_quota.sqlite3' and not source.exists():
                manifest['databases'][name] = {'status': 'absent_at_backup'}
                continue
            manifest['databases'][name] = {'status': 'backed_up', **sqlite_copy(source, stage / name)}
        with (stage / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(stage)
        completed = backup_root / label
        stage.rename(completed)
        sync_directory(backup_root)
    return completed


def verify(snapshot):
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError('Snapshot must be a regular directory')
    snapshot = snapshot.resolve(strict=True)
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or manifest.get('status') != 'complete':
        raise ValueError('Incomplete or unsupported snapshot')
    entries = manifest.get('databases', {})
    if set(entries) != set(NAMES) or entries[NAMES[0]].get('status') != 'backed_up':
        raise ValueError('Required DB metadata is missing')
    for name in NAMES:
        entry = entries[name]
        if name == 'ai_quota.sqlite3' and entry.get('status') == 'absent_at_backup':
            continue
        path = snapshot / name
        if entry.get('status') != 'backed_up' or path.is_symlink() or not path.is_file():
            raise ValueError('Invalid snapshot DB entry')
        if file_hash(path) != entry['sha256']:
            raise ValueError('Backup SHA-256 mismatch')
        actual = inspect_db(path)
        if actual['logical_sha256'] != entry['logical_sha256'] or actual['tables'] != entry['tables']:
            raise ValueError('Backup logical verification failed')
    return manifest


def restore_test(snapshot, restore_root, data_dir):
    manifest = verify(snapshot)
    source = Path(manifest['source_directory']).resolve()
    root = restore_root.resolve()
    live = data_dir.resolve()
    if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in (source, live)):
        raise ValueError('Restore tests must be isolated from the live data directory')
    private_directory(restore_root)
    target = restore_root / ('rehearsal-' + uuid.uuid4().hex)
    target.mkdir(mode=0o700)
    restored = []
    for name in NAMES:
        entry = manifest['databases'][name]
        if entry['status'] == 'absent_at_backup':
            continue
        actual = sqlite_copy(snapshot / name, target / name)
        if actual['logical_sha256'] != entry['logical_sha256'] or actual['tables'] != entry['tables']:
            raise ValueError('Restored DB does not match the snapshot')
        restored.append(name)
    return {'restore_test': 'passed', 'directory': str(target), 'databases': restored}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path.home() / 'kirothon-data')
    parser.add_argument('--backup-root', type=Path, default=Path.home() / 'kirothon-backups')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('backup')
    for command in ('verify', 'restore-test'):
        sub = commands.add_parser(command)
        sub.add_argument('--snapshot', type=Path, required=True)
        if command == 'restore-test':
            sub.add_argument('--restore-root', type=Path, default=Path.home() / 'kirothon-restore-tests')
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            snapshot = backup(args.data_dir, args.backup_root)
            manifest = verify(snapshot)
            result = {'backup': 'passed', 'snapshot': str(snapshot), 'databases': {k: v['status'] for k, v in manifest['databases'].items()}}
        elif args.command == 'verify':
            verify(args.snapshot)
            result = {'verification': 'passed', 'snapshot': str(args.snapshot)}
        else:
            result = restore_test(args.snapshot, args.restore_root, args.data_dir)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
