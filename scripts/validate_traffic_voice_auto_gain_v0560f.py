#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path('/home/eyevisions/SDRCC')
sys.path.insert(0, str(ROOT))

def check(ok, label):
    if not ok:
        raise AssertionError(label)
    print('PASS:', label)

check((ROOT/'VERSION').read_text().strip() == '0.56.0f', 'release version is 0.56.0f')
source = (ROOT/'core/traffic_voice.py').read_text(encoding='utf-8')
js = (ROOT/'dashboard/static/js/traffic_voice.js').read_text(encoding='utf-8')
html = (ROOT/'dashboard/templates/index.html').read_text(encoding='utf-8')
check('gain_mode' in source and "-1.0 if receiver_settings['gain_mode'] == 'auto'" in source,
      'SDRCC renders the bounded -1.0 Auto Gain sentinel')
check('traffic-voice-auto-gain' in html and 'traffic-voice-auto-gain' in js,
      'Traffic Voice Auto Gain checkbox is wired')
check('gainSelect.disabled' in js, 'manual gain is disabled while Auto Gain is selected')

cfg = yaml.safe_load((ROOT/'config/traffic_voice.yaml').read_text(encoding='utf-8')) or {}
backend = ((cfg.get('traffic_voice') or {}).get('backend') or {})
check(backend.get('gain_mode') in {'auto','manual'}, 'Traffic Voice gain mode is persisted')

from core import traffic_voice
validation = traffic_voice.validate_configuration(cfg)
check(validation.get('ok') is True, 'Traffic Voice configuration validates with gain mode')
settings = traffic_voice.get_receiver_settings(cfg)
check(settings.get('gain_mode') in {'auto','manual'}, 'receiver settings expose gain mode')
auto = traffic_voice.normalize_receiver_settings({'auto_gain': True}, payload=cfg)
manual = traffic_voice.normalize_receiver_settings({'auto_gain': False}, payload=cfg)
check(auto['gain_mode'] == 'auto' and manual['gain_mode'] == 'manual',
      'bounded settings normalize Auto and Manual gain')

binary = Path('/opt/sdrcc/traffic_voice/bin/rtl_airband')
check(binary.exists(), 'patched RTLSDR-Airband binary exists')
strings = subprocess.run(['strings', str(binary)], text=True, capture_output=True, check=True).stdout
check('automatic tuner gain enabled' in strings, 'installed native backend contains Auto Gain path')
prov = Path('/opt/sdrcc/traffic_voice/share/BUILD-PROVENANCE').read_text(encoding='utf-8')
check('SDRCC v0.56.0f auto-gain patch' in prov, 'backend provenance records SDRCC Auto Gain patch')
print('VALIDATION PASS: SDRCC v0.56.0f Traffic Voice native Auto Gain')
