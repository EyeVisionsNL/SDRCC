#!/usr/bin/env python3
"""Run the upstream managed-mode wizard, then return receivers to FlexGround.

This is an explicit install/setup operation, never part of ordinary updates.
The browser owns all device, password and sharing choices.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path('/etc/AIS-catcher/aiscatcher.json')
DROPIN = Path('/etc/systemd/system/ais-catcher.service.d/90-flexground-managed.conf')
SERVICES = ('ais-catcher-control.service', 'ais-catcher.service',
            'readsb.service', 'sdrcc-traffic-voice.service')


def run(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(args)}: {result.stderr.strip()}")
    return result


def state(service, prop):
    return run('systemctl', 'show', service, '--property=' + prop, '--value').stdout.strip()


def exists(service):
    return state(service, 'LoadState') not in ('', 'not-found')


def read_config():
    if not CONFIG.exists():
        return {}
    value = json.loads(CONFIG.read_text())
    if not isinstance(value, dict):
        raise RuntimeError('AIS configuration must be a JSON object; existing file preserved.')
    return value


def configured(value):
    """A dismissed wizard or UNBOUND placeholder is not a configured receiver."""
    control = value.get('control', {})
    if not isinstance(control, dict) or control.get('wizard') not in (False, 'off', 'false'):
        return False
    receivers = value.get('receiver')
    if not isinstance(receivers, list):
        return False
    active = [r for r in receivers if isinstance(r, dict)
              and r.get('active', True) not in (False, 'off', 'false')]
    if len(active) != 1:
        return False
    receiver = active[0]
    serial = str(receiver.get('serial') or '').strip()
    return (str(receiver.get('input', '')).upper() == 'RTLSDR'
            and bool(serial) and not serial.startswith('UNBOUND'))


def save_config(value):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    previous = CONFIG.stat() if CONFIG.exists() else None
    if previous:
        backup = CONFIG.with_name(CONFIG.name + '.before-flexground-initialization')
        if not backup.exists():
            shutil.copy2(CONFIG, backup)
            os.chown(backup, previous.st_uid, previous.st_gid)
    fd, name = tempfile.mkstemp(dir=CONFIG.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        if previous:
            os.chmod(name, previous.st_mode & 0o777)
            os.chown(name, previous.st_uid, previous.st_gid)
        else:
            owner = pwd.getpwnam(state('ais-catcher.service', 'User') or 'root')
            os.chmod(name, 0o640)
            os.chown(name, owner.pw_uid, owner.pw_gid)
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def quiet_receivers():
    errors = []
    for service in SERVICES:
        try:
            if not exists(service):
                continue
            run('systemctl', 'disable', '--now', service)
            if state(service, 'ActiveState') not in ('inactive', 'failed'):
                raise RuntimeError(f'{service} did not stop')
            enabled = run('systemctl', 'is-enabled', service, check=False).stdout.strip()
            if enabled not in ('disabled', 'masked'):
                raise RuntimeError(f'{service} autostart is still {enabled or "unknown"}')
        except (RuntimeError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    if errors:
        raise RuntimeError('; '.join(errors))


def check_reservations():
    path = ROOT / 'data/state/receiver_manager.json'
    if path.exists():
        value = json.loads(path.read_text())
        if value.get('reservations') or value.get('reservation'):
            raise RuntimeError('Stop active missions/Radio Receiver sessions in FlexGround before AIS setup.')


def prepare_managed_service():
    command = state('ais-catcher.service', 'ExecStart')
    if re.search(r'(?:^|\s)-E\s+/etc/AIS-catcher/aiscatcher\.json\s+', command):
        # Keep the site's existing managed listener and service options.
        return
    if re.search(r'(?:^|\s)-E(?:\s|$)', command):
        raise RuntimeError('AIS managed service uses another config path; preserved for manual review.')
    if DROPIN.exists():
        raise RuntimeError(f'Existing managed override is ineffective; inspect {DROPIN}.')
    binary = shutil.which('AIS-catcher')
    if not binary or not re.fullmatch(r'/[A-Za-z0-9_./-]+', binary):
        raise RuntimeError('AIS-catcher executable is missing or has an unsupported path.')
    help_result = run(binary, '-h', check=False)
    if not re.search(r'(?:^|\s|\[)-E(?:\s|,)', help_result.stdout + help_result.stderr):
        raise RuntimeError('Installed AIS-catcher lacks managed mode (-E). Update AIS-catcher before setup.')
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    DROPIN.write_text('[Service]\nExecStart=\n'
                      f'ExecStart={binary} -E /etc/AIS-catcher/aiscatcher.json 0.0.0.0:8118\n')
    DROPIN.chmod(0o644)
    run('systemctl', 'daemon-reload')
    if '-E /etc/AIS-catcher/aiscatcher.json 0.0.0.0:8118' not in state('ais-catcher.service', 'ExecStart'):
        raise RuntimeError('Managed service override was not applied; inspect systemctl cat ais-catcher.service.')


def listener():
    command = state('ais-catcher.service', 'ExecStart')
    match = re.search(r'-E\s+/etc/AIS-catcher/aiscatcher\.json\s+([^\s;]+)', command)
    if not match:
        raise RuntimeError('Cannot determine the AIS managed listener.')
    address = match[1]
    match = re.fullmatch(r'(?:(\d+\.\d+\.\d+\.\d+):)?(\d+)', address)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise RuntimeError(f'Unsupported managed listener {address}; existing service preserved.')
    host, port = match[1] or '0.0.0.0', match[2]
    local = '127.0.0.1' if host == '0.0.0.0' else host
    print(f'AIS setup on this machine: http://{local}:{port}', flush=True)
    if host == '0.0.0.0':
        addresses = run('hostname', '-I', check=False).stdout.split()
        for ip in addresses:
            if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', ip):
                print(f'AIS setup from your browser: http://{ip}:{port}', flush=True)
    elif host.startswith('127.'):
        print(f'Remote SSH: reconnect with ssh -L {port}:127.0.0.1:{port} USER@STATION, '
              f'then open http://127.0.0.1:{port} on your own computer.', flush=True)
    return f'http://{local}:{port}/'


def wait_for_http(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.URLError:
            pass
        time.sleep(1)
    raise RuntimeError('AIS wizard did not become reachable; inspect journalctl -u ais-catcher.service.')


def setup(non_interactive=False):
    check_reservations()
    # Fail before changing services if a stored config cannot be read safely.
    value = read_config()
    was_active = state('sdrcc.service', 'ActiveState') == 'active'
    run('systemctl', 'stop', 'sdrcc.service')
    try:
        check_reservations()
    except BaseException:
        if was_active:
            run('systemctl', 'start', 'sdrcc.service')
        raise
    try:
        quiet_receivers()
        value = read_config()
        if non_interactive and not configured(value):
            print('DEFERRED: AIS wizard requires a browser. Resume with ./install.sh --ais-setup.')
            return False
        prepare_managed_service()
        if not configured(value):
            value.setdefault('config', 'aiscatcher')
            value.setdefault('version', 1)
            value['engine'] = 'off'
            control = value.setdefault('control', {})
            if not isinstance(control, dict):
                raise RuntimeError('AIS control section is not an object; existing configuration preserved.')
            control['wizard'] = True
            control.setdefault('legacy_config', '/etc/AIS-catcher/config.json')
            save_config(value)
            run('systemctl', 'start', 'ais-catcher.service')
            url = listener()
            wait_for_http(url)
            print('Complete the AIS-catcher wizard: choose one RTL-SDR, your password and desired outputs.\n'
                  'Use Save & Close. If necessary reopen Setup Wizard in the System panel.\n'
                  'Return here after saving. A skipped wizard or UNBOUND input is not completion.', flush=True)
            while True:
                answer = input('Enter = check saved configuration; d = defer AIS setup: ').strip().lower()
                if answer == 'd':
                    print('DEFERRED: AIS is not ready. Resume with ./install.sh --ais-setup.')
                    return False
                value = read_config()
                if configured(value):
                    break
                print('AIS setup is incomplete: save one active RTL-SDR with a real serial in the wizard.')
        # Stop before saving engine=on: systemd start/stop must control reception.
        quiet_receivers()
        value = read_config()
        if not configured(value):
            raise RuntimeError('AIS configuration changed before final verification; rerun --ais-setup.')
        value['engine'] = 'on'
        save_config(value)
        print('PASS: AIS configured. Receiver services stopped, autostart disabled.')
        return True
    finally:
        # Also executed on browser failure, EOF, Ctrl-C and a normal termination.
        # Do not restart FlexGround if service cleanup could not be verified.
        quiet_receivers()
        if was_active:
            run('systemctl', 'start', 'sdrcc.service')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--check', action='store_true', help='read-only configuration check')
    args = parser.parse_args()
    if args.check:
        ready = configured(read_config())
        print('PASS: AIS configured' if ready else 'DEFERRED: AIS setup incomplete')
        return 0 if ready else 2
    if os.geteuid() != 0:
        parser.error('run through install.sh --ais-setup, or use sudo')
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        setup(args.non_interactive)
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError, EOFError) as error:
        print(f'FAIL: {error}')
        return 1
    except KeyboardInterrupt:
        print('\nAIS setup interrupted. Resume with ./install.sh --ais-setup.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
