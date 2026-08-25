#!/usr/bin/env python3
from pathlib import Path
import ast, subprocess
ROOT=Path(__file__).resolve().parents[1]
def check(ok,msg):
    if not ok: raise SystemExit('FAIL: '+msg)
    print('PASS: '+msg)
check((ROOT/'VERSION').read_text().strip()=='0.56.0k','release version is 0.56.0k')
required=['install.sh','update.sh','uninstall.sh','scripts/install/provision_external.sh','scripts/install/patch_rtlsdr_airband_auto_gain.py','scripts/install/preflight.py','scripts/install/detect_receivers.py','scripts/install/configure_station.py','scripts/install/validate_install.py','systemd/sdrcc.service.in','systemd/sdrcc-traffic-voice.service.in','docs/v1-installer-provisioning-v0560k.md']
for rel in required: check((ROOT/rel).exists(),f'required installer file present: {rel}')
for rel in ['scripts/install/preflight.py','scripts/install/detect_receivers.py','scripts/install/configure_station.py','scripts/install/validate_install.py','scripts/install/patch_rtlsdr_airband_auto_gain.py']:
    ast.parse((ROOT/rel).read_text()); print('PASS: parseable '+rel)
for rel in ['install.sh','update.sh','uninstall.sh','scripts/install/provision_external.sh']:
    text=(ROOT/rel).read_text(); check(text.startswith('#!/usr/bin/env bash\n'),f'{rel} starts with a valid shebang')
    done=subprocess.run(['bash','-n',str(ROOT/rel)],capture_output=True,text=True); check(done.returncode==0,f'{rel} shell syntax')
install=(ROOT/'install.sh').read_text(); provision=(ROOT/'scripts/install/provision_external.sh').read_text()
check('/api/status' in install and '/api/system-status' not in install,'installer uses the stable SDRCC status endpoint')
check('provision_external.sh' in install,'project installer invokes the external provisioning boundary')
check('--skip-third-party' in install,'existing complete third-party stack can be retained explicitly')
check('satdump satdump-data' in provision,'SatDump is provisioned from Ubuntu packages')
check('READSB_COMMIT="cc0d099"' in provision,'readsb source is commit-pinned')
check('AIS_INSTALLER="https://raw.githubusercontent.com/jvde-github/AIS-catcher/v0.70/' in provision,'AIS-catcher installer URL is release-tag pinned')
check('AIS_CONTROL_TAG="v0.1"' in provision and 'RELEASE_TAG=' in provision,'AIS-catcher-control release pin is verified before execution')
check('AIRBAND_TAG="v5.2.0"' in provision and 'AIRBAND_COMMIT="61c5c4061967752da6b491a924664d72184b38fa"' in provision,'RTLSDR-Airband is tag and commit pinned')
check('patch_rtlsdr_airband_auto_gain.py' in provision and 'automatic tuner gain enabled' in (ROOT/'scripts/install/patch_rtlsdr_airband_auto_gain.py').read_text(),'existing native Auto Gain patch is retained')
check('service_disable readsb.service' in provision and 'service_disable ais-catcher.service' in provision and 'service_disable ais-catcher-control.service' in provision,'external receiver services finish policy-disabled')
check('systemctl enable readsb' not in install+provision and 'systemctl enable ais-catcher' not in install+provision,'installer never enables continuous external receiver services')
check('curl -fsSL' not in provision or '| bash' not in provision,'remote installers are downloaded before execution rather than piped directly to shell')
check('--check' in provision and '--plan' in provision,'external provisioning has read-only check and plan modes')
check((ROOT/'docs/v1-installer-provisioning-v0560k.md').exists(),'v0.56.0k provisioning documentation is present')
print('VALIDATION PASS: SDRCC v0.56.0k v1.0 External Provisioning')
