#!/usr/bin/env python3
"""Code-only deployment. No DB/schema/dependency rollback and no AWS changes."""
import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

PROJECT = Path('/home/ubuntu/kirothon')
WEB = Path('/var/www/kirothon-preview')
ROOT = Path('/home/ubuntu/kirothon-deployments')
SERVICE = 'kirothon-api.service'
FRONT = {'package.json', 'package-lock.json', 'index.html', 'vite.config.ts',
         'tsconfig.json', 'tsconfig.app.json', 'tsconfig.node.json', 'components.json',
         'eslint.config.js', 'eslint.config.mjs', 'oxlint.config.json', '.oxlintrc.json'}
MAX_BYTES = 100 * 1024 * 1024


def allowed(name):
    p = PurePosixPath(name)
    if not name or '\\' in name or p.is_absolute() or '..' in p.parts or name != str(p):
        return False
    if any(x in {'.git', 'node_modules', '.venv', '__pycache__', 'dist', 'data', 'uploads'}
           or x.startswith('.env') for x in p.parts):
        return False
    if p.suffix.lower() in {'.pem', '.key', '.pfx', '.p12', '.db', '.sqlite', '.sqlite3', '.pyc'}:
        return False
    if p.parts[:2] == ('backend', 'app'):
        return len(p.parts) > 2 and p.suffix == '.py'
    if name == 'backend/requirements.lock':
        return True
    if p.parts[:2] in {('frontend', 'src'), ('frontend', 'public')}:
        return len(p.parts) > 2 and not any(x.startswith('.') for x in p.parts[2:])
    if len(p.parts) == 2 and p.parts[0] == 'frontend' and p.name in FRONT:
        return True
    return p.parts[:2] in {('.kiro', 'steering'), ('.kiro', 'specs')} and p.suffix == '.md'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_files(project):
    for folder in ('backend/app', 'frontend/src', 'frontend/public', '.kiro/steering', '.kiro/specs'):
        base = project / folder
        if base.is_symlink():
            raise ValueError('Source directory symlinks are not accepted')
        if base.exists():
            for path in sorted(base.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Source symlinks are not accepted')
                if path.is_file() and allowed(path.relative_to(project).as_posix()):
                    yield path
    for name in ('backend/requirements.lock', *(f'frontend/{n}' for n in sorted(FRONT))):
        path = project / name
        if path.is_symlink():
            raise ValueError('Source symlinks are not accepted')
        if path.is_file():
            yield path


def pack(project, output):
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(project):
            content = path.read_bytes()
            if re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[A-Z0-9]{16}', content):
                raise ValueError('Potential embedded credential found; source packaging refused')
            archive.write(path, path.relative_to(project).as_posix())


def extract(archive, target):
    total = 0
    seen = set()
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 3000:
            raise ValueError('Too many archive entries')
        for entry in bundle.infolist():
            name = entry.filename
            mode = entry.external_attr >> 16
            if not allowed(name) or entry.is_dir() or stat.S_ISLNK(mode) or name in seen:
                raise ValueError('Disallowed or duplicate archive path')
            seen.add(name)
            total += entry.file_size
            if total > MAX_BYTES:
                raise ValueError('Source archive exceeds 100 MiB')
        for required in ('backend/app/main.py', 'backend/requirements.lock',
                         'frontend/src/App.tsx', 'frontend/package.json',
                         'frontend/package-lock.json', 'frontend/index.html'):
            if required not in seen:
                raise ValueError('Incomplete source archive: ' + required)
        for entry in bundle.infolist():
            path = target / entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as src, path.open('xb') as dst:
                shutil.copyfileobj(src, dst)


def execute(args, cwd=None, timeout=180, env=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, env=env)
    if result.returncode:
        # Keep build output in the private release folder, not in chat/terminal.
        error = RuntimeError('Command failed: ' + Path(args[0]).name)
        error.output = result.stdout
        raise error
    return result.stdout


def prepare(stage, project, run=execute):
    for name in ('backend/requirements.lock', 'frontend/package-lock.json'):
        if sha(stage / name) != sha(project / name):
            raise ValueError('Dependency lock change requires separate mentor preparation: ' + name)
    for name in ('models.py', 'database.py'):
        old, new = project / 'backend/app' / name, stage / 'backend/app' / name
        if old.exists() and (not new.is_file() or sha(old) != sha(new)):
            raise ValueError('DB model/config changes require a separate reviewed change: ' + name)
    for path in (stage / 'backend/app').rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    # r1 archives remain rollback-compatible. r2 checks importability and the
    # existing SQLite column shape before any live code or data is modified.
    if (stage / 'backend/app/schema_check.py').is_file():
        python = project / 'backend/.venv/bin/python'
        if not python.is_file():
            raise ValueError('Preinstalled backend virtual environment is missing')
        database = project.parent / 'kirothon-data/records.sqlite3'
        check_env = dict(os.environ, KIROTHON_AI_MODE='mock',
                         KIROTHON_DB_PATH=str(stage / '.check-data/records.sqlite3'),
                         AWS_EC2_METADATA_DISABLED='true')
        run([str(python), '-m', 'app.schema_check', '--database', str(database)],
            cwd=stage / 'backend', env=check_env)
    modules = project / 'frontend/node_modules'
    if not modules.is_dir():
        raise ValueError('Preinstalled frontend dependencies are missing')
    (stage / 'frontend/node_modules').symlink_to(modules, target_is_directory=True)
    node = '/usr/local/bin/node'
    run([node, str(modules / 'typescript/bin/tsc'), '-b'], cwd=stage / 'frontend')
    run([node, str(modules / 'vite/bin/vite.js'), 'build'], cwd=stage / 'frontend')
    if not (stage / 'frontend/dist/index.html').is_file():
        raise ValueError('Frontend build did not produce index.html')


def atomic_copy(source, target):
    missing = []
    parent = target.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    if parent.is_symlink():
        raise ValueError('Target parent symlinks are not accepted')
    for parent in reversed(missing):
        parent.mkdir()
        os.chmod(parent, 0o755)
    if target.is_symlink():
        raise ValueError('Target symlinks are not accepted')
    temp = target.with_name('.deploy-' + uuid.uuid4().hex)
    shutil.copyfile(source, temp)
    os.chmod(temp, 0o644)
    os.replace(temp, target)


def publish(source, target):
    files = sorted(source.rglob('*'), key=lambda p: (p.name == 'index.html', str(p)))
    for path in files:
        if path.is_symlink():
            raise ValueError('Published tree symlinks are not accepted')
        if path.is_file():
            relative = path.relative_to(source)
            if any(part.startswith('.') for part in relative.parts):
                raise ValueError('Hidden files must not be published')
            atomic_copy(path, target / relative)


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(15):
        try:
            with opener.open('http://127.0.0.1:8000/api/health', timeout=2) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    return False


def apply(stage, project, web, release, run=execute, check_health=health):
    swaps, configs = [], []
    if web.is_symlink() or any(p.is_symlink() for p in web.rglob('*')):
        raise ValueError('Published web tree contains a symlink')
    previous = release / 'previous'
    previous.mkdir(mode=0o700)
    shutil.copytree(web, previous / 'web')
    # Refuse moving any non-code files out of the three managed source trees.
    for name in ('backend/app', 'frontend/src', 'frontend/public'):
        live = project / name
        if live.is_symlink():
            raise ValueError('Managed source tree is a symlink')
        if live.exists():
            for path in live.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Managed source contains a symlink')
                if path.is_file() and '__pycache__' not in path.parts and not allowed(path.relative_to(project).as_posix()):
                    raise ValueError('Protected or unsupported file in managed source tree')
        if not (stage / name).exists():
            (stage / name).mkdir(parents=True)
    # Existing operational .env files stay outside the managed trees, untouched.
    for name in sorted(FRONT):
        new, live, saved = stage / 'frontend' / name, project / 'frontend' / name, previous / 'config' / name
        if new.is_file():
            if live.is_symlink():
                raise ValueError('Frontend config symlinks are not accepted')
            if live.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live, saved)
            configs.append((new, live, saved, live.exists()))
    stopped = False
    try:
        run(['sudo', '-n', 'systemctl', 'stop', SERVICE])
        stopped = True
        for name in ('backend/app', 'frontend/src', 'frontend/public'):
            live, saved = project / name, previous / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            existed = live.exists()
            if existed:
                live.rename(saved)
            swaps.append((live, saved, existed))
            (stage / name).rename(live)
        for new, live, saved, existed in configs:
            atomic_copy(new, live)
        publish(stage / 'frontend/dist', web)
        run(['sudo', '-n', 'systemctl', 'start', SERVICE])
        if not check_health():
            raise RuntimeError('New API failed health check')
        return {'deployment': 'passed', 'release': release.name, 'database_restored': False}
    except BaseException as original:
        if not stopped:
            raise
        try:
            run(['sudo', '-n', 'systemctl', 'stop', SERVICE])
            failed = release / 'failed-code'
            for live, saved, existed in reversed(swaps):
                if live.exists():
                    target = failed / live.relative_to(project)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    live.rename(target)
                if existed:
                    saved.rename(live)
            for new, live, saved, existed in configs:
                if existed:
                    atomic_copy(saved, live)
                elif live.exists():
                    live.rename(release / ('failed-config-' + live.name))
            publish(previous / 'web', web)
            run(['sudo', '-n', 'systemctl', 'start', SERVICE])
            if not check_health():
                raise RuntimeError('Previous API health check failed')
        except BaseException:
            raise RuntimeError('ROLLBACK_FAILED: preserve this release and inspect manually') from original
        raise RuntimeError('DEPLOY_FAILED_ROLLED_BACK: previous code restored, DB untouched') from original


def main():
    os.umask(0o077)
    def interrupted(signum, frame):
        raise InterruptedError('Deployment interrupted; attempting code rollback')
    signal.signal(signal.SIGHUP, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('pack')
    p.add_argument('--project', type=Path, default=PROJECT)
    p.add_argument('--output', type=Path, required=True)
    for name in ('check', 'deploy'):
        p = sub.add_parser(name)
        p.add_argument('--archive', type=Path, required=True)
        p.add_argument('--sha256', required=True)
    p = sub.add_parser('rollback')
    p.add_argument('--release', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'pack':
            pack(args.project, args.output)
            print(json.dumps({'archive': str(args.output), 'sha256': sha(args.output)}))
            return 0
        if os.getuid() != PROJECT.stat().st_uid or PROJECT.is_symlink() or WEB.is_symlink():
            raise ValueError('Project ownership or path mismatch')
        ROOT.mkdir(mode=0o700, exist_ok=True)
        if ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
            raise ValueError('Deployment root must be a private regular directory')
        if (ROOT / '.lock').is_symlink():
            raise ValueError('Deployment lock symlinks are not accepted')
        with (ROOT / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == 'rollback':
                if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', args.release):
                    raise ValueError('Invalid release ID')
                archive = ROOT / args.release / 'previous-source.zip'
                expected = sha(archive)
            else:
                archive, expected = args.archive, args.sha256.lower()
            if archive.is_symlink() or archive.stat().st_size > MAX_BYTES or sha(archive) != expected:
                raise ValueError('Archive hash or size check failed')
            label = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
            release = ROOT / label
            release.mkdir(mode=0o700)
            staged_archive = release / 'candidate.zip'
            shutil.copyfile(archive, staged_archive)
            stage = release / 'candidate'
            stage.mkdir()
            extract(staged_archive, stage)
            prepare(stage, PROJECT)
            if args.command == 'check':
                print(json.dumps({'check': 'passed', 'release': label, 'live_code_changed': False}))
                return 0
            execute(['sudo', '-n', 'true'])
            if not health() and args.command != 'rollback':
                raise RuntimeError('Current API is unhealthy; deployment refused')
            pack(PROJECT, release / 'previous-source.zip')
            db_backup = execute([str(PROJECT / 'backend/.venv/bin/python'),
                                 '/home/ubuntu/kirothon-tools/backup_db.py', 'backup'])
            (release / 'db-backup.json').write_text(db_backup, encoding='utf-8')
            result = apply(stage, PROJECT, WEB, release)
            if args.command == 'rollback':
                result['rollback_of'] = args.release
            (release / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
        return 0
    except Exception as error:
        if 'release' in locals() and hasattr(error, 'output'):
            (release / 'command.log').write_text(error.output, encoding='utf-8')
        print(json.dumps({'status': 'failed', 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
