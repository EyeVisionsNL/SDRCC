#!/usr/bin/env python3
"""Exercise update shutdown with legacy/current sudo rules and exact restore."""
import ast
import importlib.util
import itertools
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
source = ast.parse((ROOT / 'dashboard/app.py').read_text())
names = {'run_systemctl', 'run_systemctl_for_update', '_update_service_needs_stop',
         '_stop_service_group_for_update', '_write_update_service_plan',
         '_read_update_service_plan', '_restore_update_service_plan',
         '_prepare_receiver_work_for_update'}
module = ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
services = ('readsb.service', 'ais-catcher.service', 'ais-catcher-control.service')
spec = importlib.util.spec_from_file_location('worker', ROOT / 'scripts/sdrcc_update.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

# Validate the actual rules from all three installation paths.
clean = (ROOT / 'install.sh').read_text().split('cat >"$tmp/sdrcc-update-services" <<EOF\n')[1].split('\nEOF')[0]
manual = (ROOT / 'scripts/install/update_existing.sh').read_text().split('cat > "$SUDOERS_TMP" <<EOF\n')[1].split('\nEOF')[0]
expected = {f'eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block {a} {s}'
            for s in (*services, 'sdrcc-traffic-voice.service') for a in ('start', 'stop')}
assert set(clean.splitlines()) == expected
assert set(manual.replace('$INSTALL_USER', 'eyeuser').splitlines()) == expected
with tempfile.TemporaryDirectory() as temp:
    rule = Path(temp) / 'rules'
    rule.write_text(clean + '\n')
    subprocess.run(['/usr/sbin/visudo', '-cf', str(rule)], check=True, capture_output=True)
    writes = {}
    with patch.object(Path, 'write_text', lambda p, text, **k: writes.setdefault(str(p), text)), \
         patch.object(worker.os, 'chmod'), patch.object(worker.os, 'replace'), patch.object(worker, 'run'):
        worker.install_privileged_helpers(ROOT, 'eyeuser')
    assert set(writes['/etc/sudoers.d/sdrcc-update-services.tmp'].splitlines()) == expected
print('PASS: clean, manual and managed installer rules agree; visudo accepts exact rules')

for permitted, flags in itertools.product((False, True), itertools.product((False, True), repeat=3)):
    initial = dict(zip(services, flags))
    states = {s: 'active' if v else 'inactive' for s, v in initial.items()}
    calls = []
    def state(s):
        return {'state': states.get(s, 'inactive'), 'active': states.get(s) == 'active'}
    def run(cmd, **kwargs):
        if '-l' in cmd:
            return SimpleNamespace(returncode=0 if permitted else 1, stdout='', stderr='')
        if 'is-active' in cmd:
            return SimpleNamespace(returncode=0, stdout=states[cmd[-1]], stderr='')
        assert not (cmd[0] == 'sudo' and '--no-block' in cmd and not permitted), 'unauthorized action'
        action, service = cmd[-2:]
        calls.append((action, service))
        states[service] = 'active' if action == 'start' else 'inactive'
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    with tempfile.TemporaryDirectory() as temp:
        project = Path(temp)
        from datetime import datetime
        import json
        ns = dict(datetime=datetime, json=json, UPDATE_RESTORE_SERVICES=services,
                  UPDATE_SERVICE_STATE_FILE=project/'data/state/update_service_state.json',
                  AIS_CONTROL_SERVICE=services[2], run_command=run, service_state=state,
                  wait_for_service=lambda s, wanted, timeout: states[s] == wanted,
                  write_log=lambda msg: None, _update_receiver_runtime_active=lambda: False,
                  hf_monitor_controller=SimpleNamespace(get_session=lambda: None),
                  traffic_voice_controller=SimpleNamespace(VOICE_SERVICE='sdrcc-traffic-voice.service', SESSION_FILE=None),
                  receiver_manager=SimpleNamespace(cancel_service_recovery=lambda p: None, binding_status=lambda: {}, get_status=lambda: {}),
                  get_reconciled_receiver_manager_status=lambda **kw: {},
                  _observe_service_group=lambda p: {s: state(s) for s in (services[1:] if p=='ais' else services[:1])},
                  _service_action_steps=lambda p, a: [(a,s) for s in (tuple(reversed(services[1:])) if p=='ais' else services[:1])])
        exec(compile(module, 'dashboard/app.py', 'exec'), ns)
        result = ns['_prepare_receiver_work_for_update']()
        assert result['ok'], result
        assert all(v == 'inactive' for v in states.values())
        wanted = [s for s, active in initial.items() if active]
        assert set(result['restore_services']) == set(wanted)
        plan_path = ns['UPDATE_SERVICE_STATE_FILE']
        with patch.object(worker, 'run', side_effect=run), patch.object(worker, 'read_update_service_plan', return_value={'active_services': wanted, 'path': plan_path}):
            restored = worker.restore_update_service_plan(project)
        assert restored['ok'] and not plan_path.exists()
        assert all((states[s] == 'active') == initial[s] for s in services)
        before = list(calls)
        ns['_update_receiver_runtime_active'] = lambda: True
        assert not ns['_prepare_receiver_work_for_update']()['ok']
        assert calls == before
print('PASS: 16 legacy/current permission and service-state cases; exact stop/restore; active missions blocked')
