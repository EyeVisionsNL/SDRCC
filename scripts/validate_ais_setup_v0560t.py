#!/usr/bin/env python3
"""Exercise AIS setup with real files; systemd/browser/hardware are simulated."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_ais', ROOT / 'scripts/install/setup_ais.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def ready():
    return {'config': 'aiscatcher', 'version': 1, 'engine': 'off',
            'control': {'wizard': False, 'password': 'preserved-test-hash'},
            'receiver': [{'input': 'RTLSDR', 'serial': 'TEST123'}],
            'sharing': False, 'udp': [{'host': '127.0.0.1', 'port': 10110}]}


class WizardFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / 'ais/aiscatcher.json'
        self.dropin = self.root / 'systemd/ais-catcher.service.d/90-flexground-managed.conf'
        self.services = {s: {'active': 'active', 'enabled': 'enabled'}
                         for s in (*setup.SERVICES, 'sdrcc.service')}
        self.exec_start = '/usr/bin/AIS-catcher -C /etc/AIS-catcher/config.json'
        self.calls = []
        self.fail_disable = None
        self.supports_managed = True
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.temp.cleanup)
        for name, value in [('ROOT', self.root), ('CONFIG', self.config), ('DROPIN', self.dropin)]:
            self.stack.enter_context(patch.object(setup, name, value))
        self.stack.enter_context(patch.object(setup, 'run', self.run_command))
        self.stack.enter_context(patch.object(setup.shutil, 'which', return_value='/usr/bin/AIS-catcher'))
        self.stack.enter_context(patch.object(setup, 'wait_for_http'))
        self.stack.enter_context(patch.object(setup.os, 'chown'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def put(self, value):
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o640)

    def run_command(self, *args, check=True):
        self.calls.append(args)
        out, code = '', 0
        if args[0] == 'hostname':
            out = '192.0.2.10'
        elif args[0] == '/usr/bin/AIS-catcher':
            out = '\t[-E [config file] [bind address:port] - managed mode]' if self.supports_managed else '[-h help]'
        else:
            self.assertEqual(args[0], 'systemctl')
            action = args[1]
            if action == 'daemon-reload':
                self.exec_start = '/usr/bin/AIS-catcher -E /etc/AIS-catcher/aiscatcher.json 0.0.0.0:8118'
            elif action == 'show':
                service, prop = args[2], args[3].split('=')[1]
                out = {'LoadState': 'loaded', 'User': 'root',
                       'ActiveState': self.services[service]['active'],
                       'ExecStart': self.exec_start}[prop]
            elif action == 'is-enabled':
                out = self.services[args[2]]['enabled']
                code = int(out != 'enabled')
            elif action == 'disable':
                service = args[-1]
                if service == self.fail_disable:
                    raise RuntimeError('simulated disable failure')
                self.services[service].update(enabled='disabled', active='inactive')
            elif action in ('start', 'stop'):
                self.services[args[2]]['active'] = 'active' if action == 'start' else 'inactive'
            else:
                self.fail(f'unexpected command {args}')
        return subprocess.CompletedProcess(args, code, out, '')

    def assert_final_state(self):
        for service in setup.SERVICES:
            self.assertEqual(self.services[service], {'active': 'inactive', 'enabled': 'disabled'})
        self.assertEqual(self.services['sdrcc.service'], {'active': 'active', 'enabled': 'enabled'})

    def test_fresh_wizard_and_engine_handover(self):
        def finish(prompt):
            self.assertTrue(json.loads(self.config.read_text())['control']['wizard'])
            self.assertEqual(self.services['sdrcc.service']['active'], 'inactive')
            self.put(ready())
            return ''
        with patch('builtins.input', finish):
            self.assertTrue(setup.setup())
        self.assert_final_state()
        value = json.loads(self.config.read_text())
        self.assertEqual(value['engine'], 'on')
        self.assertEqual(value['udp'], ready()['udp'])
        self.assertFalse(value['sharing'])
        self.assertEqual(value['control']['password'], 'preserved-test-hash')
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertTrue(self.dropin.exists())

    def test_existing_managed_config_is_preserved_without_wizard(self):
        self.put(ready())
        self.exec_start = '/usr/bin/AIS-catcher -E /etc/AIS-catcher/aiscatcher.json 127.0.0.1:8118'
        with patch('builtins.input', side_effect=AssertionError('must not prompt')):
            self.assertTrue(setup.setup())
        self.assertFalse(self.dropin.exists())
        self.assert_final_state()

    def test_incomplete_input_is_not_success_and_can_defer(self):
        incomplete = ready()
        incomplete['receiver'][0]['serial'] = 'UNBOUND_AIS'
        self.put(incomplete)
        with patch('builtins.input', side_effect=['', 'd']):
            self.assertFalse(setup.setup())
        self.assert_final_state()
        self.assertFalse(setup.configured(json.loads(self.config.read_text())))

    def test_non_interactive_deferred_has_no_config_or_override_mutation(self):
        with patch('builtins.input', side_effect=AssertionError('must not prompt')):
            self.assertFalse(setup.setup(non_interactive=True))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.dropin.exists())
        self.assert_final_state()

    def test_interrupt_and_eof_cleanup(self):
        for exception in (KeyboardInterrupt, EOFError):
            with self.subTest(exception=exception):
                with patch('builtins.input', side_effect=exception):
                    with self.assertRaises(exception):
                        setup.setup()
                self.assert_final_state()

    def test_http_failure_cleanup(self):
        with patch.object(setup, 'wait_for_http', side_effect=RuntimeError('unreachable')):
            with self.assertRaisesRegex(RuntimeError, 'unreachable'):
                setup.setup()
        self.assert_final_state()

    def test_old_binary_has_explicit_failure_without_config_rewrite(self):
        self.supports_managed = False
        with self.assertRaisesRegex(RuntimeError, 'lacks managed mode'):
            setup.setup()
        self.assertFalse(self.dropin.exists())
        self.assertFalse(self.config.exists())
        self.assert_final_state()

    def test_corrupt_config_does_not_touch_services(self):
        self.config.parent.mkdir()
        self.config.write_text('{broken')
        with self.assertRaises(ValueError):
            setup.setup()
        self.assertEqual(self.calls, [])

    def test_active_reservation_does_not_touch_services(self):
        p = self.root / 'data/state/receiver_manager.json'
        p.parent.mkdir(parents=True)
        p.write_text('{"reservations": {"sdr1": "mission"}}')
        with self.assertRaisesRegex(RuntimeError, 'Stop active missions'):
            setup.setup()
        self.assertEqual(self.calls, [])

    def test_reservation_race_does_not_stop_receivers(self):
        with patch.object(setup, 'check_reservations', side_effect=[None, RuntimeError('reservation race')]):
            with self.assertRaisesRegex(RuntimeError, 'reservation race'):
                setup.setup()
        for service in setup.SERVICES:
            self.assertEqual(self.services[service]['active'], 'active')
        self.assertEqual(self.services['sdrcc.service']['active'], 'active')

    def test_failed_cleanup_is_failure_and_does_not_restart_flexground(self):
        self.fail_disable = 'ais-catcher.service'
        with self.assertRaisesRegex(RuntimeError, 'disable failure'):
            setup.setup()
        self.assertEqual(self.services['sdrcc.service']['active'], 'inactive')
        self.assertEqual(self.services['readsb.service']['active'], 'inactive')

    def test_clean_install_does_not_start_flexground_before_return(self):
        self.services['sdrcc.service']['active'] = 'inactive'
        self.put(ready())
        self.assertTrue(setup.setup())
        self.assertEqual(self.services['sdrcc.service']['active'], 'inactive')

    def test_dismissal_empty_serial_and_multiple_devices_not_ready(self):
        for receiver in ([], [{'input': 'RTLSDR', 'serial': ''}],
                         [{'input': 'RTLSDR', 'serial': 'UNBOUND_AIS'}],
                         [{'input': 'SERIALPORT', 'serial': 'TEST'}],
                         ready()['receiver'] * 2):
            value = ready()
            value['receiver'] = receiver
            self.assertFalse(setup.configured(value))


class InstallerEntryPoint(unittest.TestCase):
    def test_resume_runs_setup_without_update_or_station_rewrite(self):
        with tempfile.TemporaryDirectory(prefix='flexground-entry-') as directory:
            root = Path(directory)
            project = root / 'SDRCC'
            binary = root / 'bin'
            (project / 'venv/bin').mkdir(parents=True)
            (project / 'scripts/install').mkdir(parents=True)
            (project / 'config').mkdir()
            binary.mkdir()
            (project / 'VERSION').write_text('0.56.0t\n')
            station = project / 'config/station.yaml'
            station.write_text('station: keep-my-settings\n')
            shutil.copy2(ROOT / 'install.sh', project / 'install.sh')
            (project / 'venv/bin/python').symlink_to(sys.executable)
            # The helper's real behavior is exercised by WizardFlow; here test
            # the actual shell dispatcher and its error propagation.
            helper = project / 'scripts/install/setup_ais.py'
            helper.write_text("from pathlib import Path\nPath(__file__).with_suffix('.called').touch()\n")
            log = root / 'commands'
            wrappers = {
                'sudo': '#!/bin/bash\n[[ "${1:-}" == -v ]] && exit 0\nexec "$@"\n',
                'systemctl': '#!/bin/bash\nprintf "%s\\n" "$*" >> "$TEST_COMMAND_LOG"\n',
                'curl': '#!/bin/bash\nprintf "200"\n',
                'getent': '#!/bin/bash\nprintf "tester:x:1000:1000::/tmp:/bin/bash\\n"\n',
                'id': '#!/bin/bash\nprintf "tester\\n"\n',
            }
            for name, content in wrappers.items():
                path = binary / name
                path.write_text(content)
                path.chmod(0o755)
            env = dict(os.environ, USER='tester', SUDO_USER='tester',
                       SDRCC_ROOT=str(project), TEST_COMMAND_LOG=str(log),
                       PATH=str(binary) + ':' + os.environ['PATH'])
            command = ['bash', str(project / 'install.sh'), '--ais-setup']
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(helper.with_suffix('.called').exists())
            self.assertIn('enable --now sdrcc.service', log.read_text())
            self.assertEqual(station.read_text(), 'station: keep-my-settings\n')
            log.unlink()
            helper.write_text('raise SystemExit(7)\n')
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertFalse(log.exists(), 'failed setup must not enable/start FlexGround')


if __name__ == '__main__':
    unittest.main(verbosity=2)
