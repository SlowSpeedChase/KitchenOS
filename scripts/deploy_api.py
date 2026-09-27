#!/usr/bin/env python3
"""Stage a reviewed API release outside Git checkouts; switch/restore only its job.

No source checkout is updated, cleaned or copied. No database migration runs.
Command output is captured and never printed (dependency/config errors may hold secrets).
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import tarfile
import time
import uuid

LABEL = 'com.kitchenos.api'
UNLOAD_WAIT_ATTEMPTS = 50
UNLOAD_WAIT_SECONDS = 0.2


def run(args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True)


def checked(runner, args):
    result = runner([str(a) for a in args])
    if result.returncode:
        raise RuntimeError('deployment command failed; prior state retained')
    return result.stdout


def atomic(path, data):
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save(root, state):
    atomic(root / 'activation-state.json', json.dumps(state, indent=2).encode())


def stage(source, sha, root, python, env_file, runner=run):
    source, root, env_file = source.resolve(), root.resolve(), env_file.resolve()
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('use the exact reviewed 40-character commit SHA')
    common = Path(checked(runner, ['git', '-C', source, 'rev-parse', '--path-format=absolute', '--git-common-dir']).strip())
    if root.is_relative_to(common.parent) or source.is_relative_to(root):
        raise ValueError('runtime must be outside the primary and feature checkouts')
    if not env_file.is_file() or env_file.stat().st_mode & 0o077 or env_file.is_relative_to(root):
        raise ValueError('use a private external environment file with mode 0600')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = root / 'releases' / sha
    if release.exists():
        raise ValueError('release exists; retain it and use another reviewed SHA')
    release.mkdir(parents=True, mode=0o700)
    archive = release / '.source.tar'
    try:
        checked(runner, ['git', '-C', source, 'archive', '--format=tar', '--output', archive, sha])
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                if not (member.isfile() or member.isdir()) or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                    raise ValueError('archive contains an unsafe entry')
            bundle.extractall(release, filter='data')
        archive.unlink()
        (release / '.env').symlink_to(env_file)
        checked(runner, [python, '-m', 'venv', release / '.venv'])
        executable = release / '.venv/bin/python'
        checked(runner, [executable, '-m', 'pip', 'install', '-r', release / 'requirements.txt'])
        checked(runner, [executable, '-m', 'compileall', '-q', release / 'api_server.py', release / 'lib'])
        logs = root / 'logs'
        logs.mkdir(exist_ok=True, mode=0o700)
        launcher = release / 'ops/agents/KitchenOS · API'
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text('#!/bin/bash\nexec ' + shlex.quote(str(executable)) + ' ' + shlex.quote(str(release / 'api_server.py')) + ' "$@"\n')
        launcher.chmod(0o700)
        candidate = {
            'Label': LABEL, 'ProgramArguments': [str(launcher)],
            'WorkingDirectory': str(release), 'KeepAlive': True, 'RunAtLoad': True,
            'EnvironmentVariables': {'PORT': '5001', 'KITCHENOS_RELEASE_SHA': sha,
                'PATH': '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
            'StandardOutPath': str(logs / 'api.log'), 'StandardErrorPath': str(logs / 'api.err.log'),
        }
        atomic(release / 'api.plist', plistlib.dumps(candidate))
        checked(runner, ['plutil', '-lint', release / 'api.plist'])
        atomic(release / 'release.json', json.dumps({'sha': sha}).encode())
        return release
    except Exception:
        shutil.rmtree(release)
        raise


# Evaluated by the release's own Python; no config values are returned or logged.
CONFIG_CHECK = '''from dotenv import dotenv_values
from pathlib import Path
import sys
v = dotenv_values(sys.argv[1], interpolate=False)
valid = bool(v.get('KITCHENOS_API_TOKEN', '').strip())
for key in ('KITCHENOS_DB', 'KITCHENOS_VAULT', 'KITCHENOS_STORAGE_TABLE', 'KITCHENOS_ITEM_ALIASES'):
    value = v.get(key, '')
    valid = valid and bool(value) and Path(value).is_absolute() and Path(value).exists()
    valid = valid and not Path(value).resolve().is_relative_to(Path(sys.argv[2]).resolve())
sys.exit(0 if valid else 1)
'''


def loaded(uid, runner):
    result = runner(['launchctl', 'print', f'gui/{uid}/{LABEL}'])
    if result.returncode not in (0, 113):
        raise RuntimeError('cannot establish previous service state')
    return result.returncode == 0


def wait_for_unload(uid, label, runner, sleeper=time.sleep):
    for attempt in range(UNLOAD_WAIT_ATTEMPTS):
        result = runner(['launchctl', 'print', f'gui/{uid}/{label}'])
        if result.returncode == 113:
            return
        if result.returncode != 0:
            raise RuntimeError('cannot establish service unload state')
        if attempt + 1 < UNLOAD_WAIT_ATTEMPTS:
            sleeper(UNLOAD_WAIT_SECONDS)
    raise RuntimeError('service did not unload before timeout')


def probe(sha, runner):
    for path, status in (('/health', '200'), ('/api/recipes', '401')):
        # Header capture proves this process is the reviewed release, not another
        # process that kept port 5001 open. Auth probe uses no secret.
        args = ['curl', '-q', '--silent', '--show-error', '--noproxy', '*', '--include',
                '--retry', '4', '--retry-connrefused', '--retry-delay', '1', '--retry-max-time', '20',
                '--connect-timeout', '5', '--max-time', '15', '--write-out', '\n%{http_code}',
                '--header', 'X-Forwarded-For: 192.0.2.1', 'http://127.0.0.1:5001' + path]
        result = runner(args)
        payload, _, actual = result.stdout.rpartition('\n')
        if result.returncode or actual.strip() != status:
            raise RuntimeError('release acceptance probe failed')
        if path == '/health' and f'x-kitchenos-release: {sha}' not in payload.lower():
            raise RuntimeError('running API does not identify the reviewed release')
        if path == '/api/recipes' and 'Unauthorized' not in payload:
            raise RuntimeError('API authentication probe failed')


def activate(root, release, agents, uid, runner=run, sleeper=time.sleep):
    root, release = root.resolve(), release.resolve()
    if release.parent != root / 'releases':
        raise ValueError('release must belong to selected runtime')
    sha = json.loads((release / 'release.json').read_text())['sha']
    if release.name != sha or not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('invalid release identity')
    state_file = root / 'activation-state.json'
    if state_file.exists() and json.loads(state_file.read_text())['status'] != 'rolled-back':
        raise RuntimeError('roll back existing activation before another deployment')
    checked(runner, [release / '.venv/bin/python', '-c', CONFIG_CHECK, release / '.env', root])
    checked(runner, ['plutil', '-lint', release / 'api.plist'])
    destination = agents / (LABEL + '.plist')
    if not destination.is_file() or destination.is_symlink():
        raise ValueError('existing regular API plist required for rollback')
    backup = root / 'backups' / uuid.uuid4().hex
    backup.mkdir(parents=True, mode=0o700)
    atomic(backup / 'api.plist', destination.read_bytes())
    state = {'status': 'pending', 'uid': uid, 'destination': str(destination),
             'backup': str(backup / 'api.plist'), 'was_loaded': loaded(uid, runner), 'sha': sha}
    save(root, state)
    try:
        if state['was_loaded']:
            checked(runner, ['launchctl', 'bootout', f'gui/{uid}/{LABEL}'])
            wait_for_unload(uid, LABEL, runner, sleeper)
        atomic(destination, (release / 'api.plist').read_bytes())
        checked(runner, ['launchctl', 'bootstrap', f'gui/{uid}', destination])
        probe(sha, runner)
        state['status'] = 'active'
        save(root, state)
    except Exception:
        try:
            rollback(root, runner, sleeper)
        except Exception:
            raise RuntimeError('activation failed; rollback incomplete, retry saved rollback') from None
        raise RuntimeError('activation failed; previous service restored') from None


def rollback(root, runner=run, sleeper=time.sleep):
    state = json.loads((root / 'activation-state.json').read_text())
    if state['status'] == 'rolled-back':
        return
    uid = state['uid']
    if loaded(uid, runner):
        checked(runner, ['launchctl', 'bootout', f'gui/{uid}/{LABEL}'])
        wait_for_unload(uid, LABEL, runner, sleeper)
    destination = Path(state['destination'])
    atomic(destination, Path(state['backup']).read_bytes())
    if state['was_loaded']:
        checked(runner, ['launchctl', 'bootstrap', f'gui/{uid}', destination])
    state['status'] = 'rolled-back'
    save(root, state)


@contextmanager
def lock(root):
    if root.is_symlink():
        raise ValueError('runtime must not be a symlink')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.deploy.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('stage', 'activate', 'rollback'))
    parser.add_argument('--runtime-root', type=Path, default=Path.home() / 'Library/Application Support/KitchenOS API')
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--sha')
    parser.add_argument('--python', type=Path)
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'stage' and not (args.sha and args.python and args.env_file):
            raise ValueError('stage requires --sha, --python and --env-file')
        if args.command == 'activate' and not args.sha:
            raise ValueError('activate requires --sha')
        common = Path(checked(run, ['git', '-C', args.source, 'rev-parse', '--path-format=absolute', '--git-common-dir']).strip())
        if args.runtime_root.resolve().is_relative_to(common.parent):
            raise ValueError('runtime must be outside all checkouts')
        with lock(args.runtime_root):
            if args.command == 'stage':
                stage(args.source, args.sha, args.runtime_root, args.python, args.env_file)
            elif args.command == 'activate':
                activate(args.runtime_root, args.runtime_root / 'releases' / args.sha,
                         Path.home() / 'Library/LaunchAgents', os.getuid())
            else:
                rollback(args.runtime_root)
    except (OSError, ValueError, RuntimeError, KeyError):
        print('FAIL: API deployment incomplete; retained release and activation-state.json support recovery')
        return 1
    print('PASS: ' + args.command)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
