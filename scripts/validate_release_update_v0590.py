#!/usr/bin/env python3
"""Isolated release checks: no packages, services or remote writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import update_manager as dashboard

spec = importlib.util.spec_from_file_location('worker', ROOT / 'scripts/sdrcc_update.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
for module in (dashboard, worker):
    for version in ('0.56.0x-r10', '0.57.0', '0.58.0', '0.58.0-r3'):
        assert module.compare_versions(version, '0.59.0') == -1
    assert module.compare_versions('0.59.0', '0.59.0') == 0
    assert module.compare_versions('0.60.0', '0.59.0') == 1

with patch.object(dashboard, 'installed_version', return_value='0.59.0'), \
     patch.object(dashboard, '_read_worker_status', return_value={}), \
     patch.dict(dashboard._CHECK, latest_version='0.59.0', check_error=None):
    for missing in (True, False):
        with patch.object(dashboard, 'audio_setup_required', return_value=missing):
            status = dashboard.get_status()
            assert status['can_complete_audio_setup'] == missing
            assert not status['update_available']

def check_worker(current, setup_ok):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        project = base / 'project'
        project.mkdir()
        (project / 'VERSION').write_text(current)
        def run(args, **kwargs):
            if 'clone' in args:
                source = Path(args[-1])
                source.mkdir()
                (source / 'VERSION').write_text('0.59.0')
            return subprocess.CompletedProcess(args, 0, 'test-commit', '')
        with patch.multiple(worker, LOCK_FILE=base/'lock', STATUS_FILE=base/'status', LOG_FILE=base/'log'), \
             patch.object(worker, 'installation', return_value=(project, 'test', 'test')), \
             patch.object(worker, 'run', side_effect=run), \
             patch.object(worker, 'verify_source_manifest'), \
             patch.object(worker, 'source_preflight') as preflight, \
             patch.object(worker, 'prepare_audio_dependencies', return_value=setup_ok) as prepare, \
             patch.object(worker, 'deploy_manifest') as deploy:
            result = worker.worker()
            status = json.loads((base/'status').read_text())
            assert not deploy.called
            if current == '0.59.0':
                preflight.assert_called_once()
                prepare.assert_called_once()
                assert result == (0 if setup_ok else 1)
                assert status['state'] == ('success' if setup_ok else 'failed')
                if setup_ok:
                    assert status['audio_setup_attempted']
                    assert status['current_version'] == status['target_version']
            else:
                assert result == 0 and status['state'] == 'up_to_date'
                assert not prepare.called

check_worker('0.59.0', True)
check_worker('0.59.0', False)
check_worker('0.60.0', True)
print('PASS: release version ordering, completion availability, repair success/failure and downgrade prevention')
