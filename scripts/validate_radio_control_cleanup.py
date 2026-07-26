#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('/home/eyevisions/SDRCC')
html = (ROOT / 'dashboard/templates/index.html').read_text(encoding='utf-8')
radio_css = (ROOT / 'dashboard/static/css/radio.css').read_text(encoding='utf-8')
system_css = (ROOT / 'dashboard/static/css/system.css').read_text(encoding='utf-8')
controls_js = (ROOT / 'dashboard/static/js/controls.js').read_text(encoding='utf-8')
api_js = (ROOT / 'dashboard/static/js/api.js').read_text(encoding='utf-8')
services_js = (ROOT / 'dashboard/static/js/services.js').read_text(encoding='utf-8')

system_start = html.index('<section class="tab-page" id="tab-system">')
radio_start = html.index('<section class="tab-page" id="tab-radio">')
radio_view_start = html.index('<section class="tab-page" id="tab-radio-view">')
system_html = html[system_start:radio_start]
radio_html = html[radio_start:radio_view_start]

actions = ('start_ais', 'stop_ais', 'start_adsb', 'stop_adsb')
checks = [
    ('System contains Service Control', 'id="system-service-control-title"' in system_html and 'Service Control' in system_html),
    ('System contains all service actions', all(f'data-action="{action}"' in system_html for action in actions)),
    ('Radio no longer contains service actions', all(f'data-action="{action}"' not in radio_html for action in actions)),
    ('old runtime service card removed', 'Receiver Runtime & Service Control' not in html),
    ('service status ids are unique', html.count('id="ais-status-radio"') == 1 and html.count('id="adsb-status-radio"') == 1),
    ('service actions are unique', all(html.count(f'data-action="{action}"') == 1 for action in actions)),
    ('Mission Assignments retained', 'Mission Assignments & Receiver Defaults' in radio_html and 'mission-assignment-weather' in radio_html),
    ('Receiver Defaults retained', 'receiver-default-sdr1' in radio_html and 'receiver-default-sdr2' in radio_html),
    ('RF settings retained', 'id="weather-rf-form"' in radio_html),
    ('assignment card widened', '.mission-assignment-card{grid-column:span 2}' in radio_css),
    ('System service CSS present', '.system-service-controls' in system_css and '.system-service-row' in system_css),
    ('service dispatcher unchanged', 'button.dataset.action' in controls_js and 'runActionApi(actionId)' in controls_js),
    ('service API unchanged', 'fetch("/api/action"' in api_js and 'JSON.stringify({action: actionId})' in api_js),
    ('service status handlers unchanged', 'setPair("start_ais", "stop_ais"' in services_js and 'setPair("start_adsb", "stop_adsb"' in services_js),
]
for label, ok in checks:
    if not ok:
        raise SystemExit(f'FAIL: {label}')
    print(f'PASS: {label}')
print('VALIDATION PASS: v0.47.1c Radio Control Cleanup')
