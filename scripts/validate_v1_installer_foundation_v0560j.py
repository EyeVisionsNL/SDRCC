#!/usr/bin/env python3
from pathlib import Path
import ast, re
ROOT=Path(__file__).resolve().parents[1]

def check(ok,msg):
    if not ok: raise SystemExit('FAIL: '+msg)
    print('PASS: '+msg)
version=(ROOT/'VERSION').read_text().strip(); check(version in {'0.56.0j','0.56.0k'},f'release {version} retains v0.56.0j installer foundation')
for rel in ['install.sh','update.sh','uninstall.sh','systemd/sdrcc.service.in','systemd/sdrcc-traffic-voice.service.in','scripts/install/preflight.py','scripts/install/detect_receivers.py','scripts/install/configure_station.py','scripts/install/validate_install.py']:
    check((ROOT/rel).exists(),f'required installer file present: {rel}')
for rel in ['scripts/install/preflight.py','scripts/install/detect_receivers.py','scripts/install/configure_station.py','scripts/install/validate_install.py']:
    ast.parse((ROOT/rel).read_text()); print('PASS: parseable '+rel)
install=(ROOT/'install.sh').read_text(); detect=(ROOT/'scripts/install/detect_receivers.py').read_text(); config=(ROOT/'scripts/install/configure_station.py').read_text()
check('$HOME/SatStation' not in install and '/home/eyevisions' not in install,'installer has no legacy/user-specific project path')
check('serial' in detect.lower() and "'index'" in detect,'receiver detection exposes serial plus presentation index')
check("hardware',{})['serial']" in config,'station configurator persists receiver serial identity')
check('/etc/sudoers.d/' in install and 'sdrcc-readsb' in install and 'visudo -cf' in install,'sudoers boundaries are generated and syntax-checked')
check('sdrcc_apply_receiver_roles.py' in install and '/usr/local/sbin/sdrcc-apply-receiver-roles' in install,'existing receiver-role helper is installed, not reimplemented')
check('systemctl enable sdrcc.service' in install,'SDRCC service is enabled')
check('enable readsb' not in install and 'enable ais-catcher' not in install,'external receiver services are not auto-enabled')
check('provision_external.sh' in install,'later installer retains explicit third-party boundary')
check('--purge-data' in (ROOT/'uninstall.sh').read_text(),'uninstall preserves data unless purge is explicit')
check((ROOT/'docs/v1-installer-foundation-v0560j.md').exists(),'installer foundation documentation is present')
print('VALIDATION PASS: SDRCC v0.56.0j v1.0 Installer Foundation')
