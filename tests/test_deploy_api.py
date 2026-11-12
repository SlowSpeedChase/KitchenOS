"""Deployment uses only a temporary git repo, synthetic config and fake launchd."""
import json
import plistlib
import subprocess
from pathlib import Path

import pytest

from scripts import deploy_api as deploy


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "test@example.invalid"],
                 ["config", "user.name", "Test"]):
        subprocess.run(["git", "-C", str(source), *args], check=True)
    (source / "api_server.py").write_text("reviewed = True\n")
    (source / "requirements.txt").write_text("")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
    sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    (source / "api_server.py").write_text("dirty = True\n")
    (source / "untracked").write_text("keep me")
    config = tmp_path / "private.env"
    config.write_text("fixture")
    config.chmod(0o600)
    root = tmp_path / "runtime"
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    plist = agents / "com.kitchenos.api.plist"
    old = plistlib.dumps({"Label": "com.kitchenos.api", "ProgramArguments": [str(source / "old launcher")]})
    plist.write_bytes(old)
    state = {"loaded": True, "fail": None, "calls": []}

    def runner(args):
        state["calls"].append(args)
        if args[0] == "git":
            return subprocess.run(args, capture_output=True, text=True)
        if args[1:3] == ["-m", "venv"]:
            python = Path(args[-1]) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("fixture")
        if args[0] == "launchctl":
            if args[1] == "print":
                return subprocess.CompletedProcess(args, 0 if state["loaded"] else 113, "state = running", "")
            if args[1] == "bootout":
                state["loaded"] = False
            elif args[1] == "bootstrap":
                state["loaded"] = True
                if state["fail"] == "bootstrap" and str(root) in plist.read_text():
                    return subprocess.CompletedProcess(args, 1, "", "secret")
        if args[0] == "curl":
            output = 'HTTP/1.1 200 OK\nX-KitchenOS-Release: ' + sha + '\n\n{"status":"ok"}\n200' if args[-1].endswith('/health') else '{"error":"Unauthorized"}\n401'
            if state["fail"] == "auth":
                output = '[]\n200'
            return subprocess.CompletedProcess(args, 0, output, "")
        code = 1 if state["fail"] == "build" and "pip" in args else 0
        return subprocess.CompletedProcess(args, code, "", "secret")

    return source, sha, config, root, agents, plist, old, state, runner


def delayed_unload_runner(state, runner, unload_results):
    bootout_seen = False

    def delayed_unload(args):
        nonlocal bootout_seen
        if args[:2] == ['launchctl', 'bootout']:
            state['calls'].append(args)
            bootout_seen = True
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[:2] == ['launchctl', 'print'] and bootout_seen and unload_results:
            state['calls'].append(args)
            code = unload_results.pop(0)
            if code == 113:
                state['loaded'] = False
            return subprocess.CompletedProcess(args, code, '', '')
        if args[:2] == ['launchctl', 'bootstrap']:
            assert unload_results == []
        return runner(args)

    return delayed_unload


def test_staging_archives_only_reviewed_commit_and_does_not_switch_service(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    assert (release / 'api_server.py').read_text() == 'reviewed = True\n'
    assert not (release / 'untracked').exists()
    assert (source / 'api_server.py').read_text() == 'dirty = True\n'
    assert (source / 'untracked').read_text() == 'keep me'
    assert plist.read_bytes() == old
    assert not any(c[0] == 'launchctl' for c in state['calls'])
    candidate = plistlib.loads((release / 'api.plist').read_bytes())
    assert Path(candidate['ProgramArguments'][0]).name == 'KitchenOS · API'
    assert str(release / '.venv/bin/python') in Path(candidate['ProgramArguments'][0]).read_text()
    assert (release / '.env').resolve() == config


@pytest.mark.parametrize('failure', ['auth', 'bootstrap'])
def test_activation_failure_restores_exact_prior_plist_and_service(deployment, failure):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    state['fail'] = failure
    with pytest.raises(RuntimeError, match='restored'):
        deploy.activate(root, release, agents, 501, runner)
    assert plist.read_bytes() == old
    assert state['loaded'] is True
    assert json.loads((root / 'activation-state.json').read_text())['status'] == 'rolled-back'
    assert (source / 'api_server.py').read_text() == 'dirty = True\n'


def test_activation_waits_until_launchd_reports_old_job_gone(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    state['calls'].clear()
    unload_results = [0, 0, 113]
    sleeps = []
    delayed_unload = delayed_unload_runner(state, runner, unload_results)

    deploy.activate(root, release, agents, 501, delayed_unload, sleeps.append)

    launchctl_actions = [call[1] for call in state['calls'] if call[0] == 'launchctl']
    assert launchctl_actions == ['print', 'bootout', 'print', 'print', 'print', 'bootstrap']
    assert len(sleeps) == 2
    assert state['loaded'] is True


def test_wait_for_unload_times_out_while_job_remains_loaded(monkeypatch):
    calls = []
    sleeps = []

    def still_loaded(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'state = running', '')

    monkeypatch.setattr(deploy, 'UNLOAD_WAIT_ATTEMPTS', 3, raising=False)
    with pytest.raises(RuntimeError, match='unload'):
        deploy.wait_for_unload(501, deploy.LABEL, still_loaded, sleeps.append)

    assert calls == [['launchctl', 'print', 'gui/501/com.kitchenos.api']] * 3
    assert len(sleeps) == 2


def test_rollback_waits_until_launchd_reports_new_job_gone(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    deploy.activate(root, release, agents, 501, runner)
    state['calls'].clear()
    unload_results = [0, 0, 113]
    sleeps = []
    delayed_unload = delayed_unload_runner(state, runner, unload_results)

    deploy.rollback(root, delayed_unload, sleeps.append)

    launchctl_actions = [call[1] for call in state['calls'] if call[0] == 'launchctl']
    assert launchctl_actions == ['print', 'bootout', 'print', 'print', 'print', 'bootstrap']
    assert len(sleeps) == 2
    assert plist.read_bytes() == old
    assert state['loaded'] is True


def test_success_and_explicit_rollback_preserve_source_and_original_load_state(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    state['loaded'] = False
    deploy.activate(root, release, agents, 501, runner)
    assert str(release) in plist.read_text()
    assert state['loaded'] is True
    deploy.rollback(root, runner)
    assert plist.read_bytes() == old
    assert state['loaded'] is False
    deploy.rollback(root, runner)
    assert (source / 'api_server.py').read_text() == 'dirty = True\n'


def test_failed_build_leaves_old_service_and_no_activatable_release(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    state['fail'] = 'build'
    with pytest.raises(RuntimeError):
        deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    assert plist.read_bytes() == old
    assert not (root / 'releases' / sha).exists()
    assert state['loaded'] is True


def test_runtime_inside_source_is_rejected_before_writes(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    with pytest.raises(ValueError):
        deploy.stage(source, sha, source / 'runtime', Path('/test/python'), config, runner)
    assert not (source / 'runtime').exists()


def test_mismatched_running_release_rolls_back(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)

    def stale_process(args):
        result = runner(args)
        if args[0] == 'curl':
            result.stdout = result.stdout.replace(sha, '0' * 40)
        return result

    with pytest.raises(RuntimeError, match='restored'):
        deploy.activate(root, release, agents, 501, stale_process)
    assert plist.read_bytes() == old
    assert state['loaded'] is True


def test_invalid_runtime_config_aborts_before_stopping_service(deployment):
    source, sha, config, root, agents, plist, old, state, runner = deployment
    release = deploy.stage(source, sha, root, Path('/test/python'), config, runner)
    state['calls'].clear()

    def invalid_config(args):
        if '-c' in args:
            return subprocess.CompletedProcess(args, 1, '', 'secret')
        return runner(args)

    with pytest.raises(RuntimeError):
        deploy.activate(root, release, agents, 501, invalid_config)
    assert not any(c[0] == 'launchctl' for c in state['calls'])
    assert plist.read_bytes() == old


def test_config_validation_requires_existing_external_data_and_token(tmp_path):
    import sys
    root = tmp_path / 'runtime'
    root.mkdir()
    config = tmp_path / 'private.env'
    db = tmp_path / 'existing.db'
    table = tmp_path / 'storage.json'
    db.touch()
    table.write_text('{}')
    values = {'KITCHENOS_API_TOKEN': 'fixture', 'KITCHENOS_DB': str(db),
              'KITCHENOS_VAULT': str(tmp_path), 'KITCHENOS_STORAGE_TABLE': str(table),
              'KITCHENOS_ITEM_ALIASES': str(table)}
    for missing in [None, *values]:
        selected = {k: v for k, v in values.items() if k != missing}
        config.write_text('\n'.join(f'{k}={v}' for k, v in selected.items()))
        result = subprocess.run([sys.executable, '-c', deploy.CONFIG_CHECK, str(config), str(root)], capture_output=True)
        assert result.returncode == (0 if missing is None else 1)
        assert b'fixture' not in result.stdout
