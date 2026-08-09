#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'dashboard/templates/index.html').read_text(encoding='utf-8')
controls_js = (ROOT / 'dashboard/static/js/controls.js').read_text(encoding='utf-8')
api_js = (ROOT / 'dashboard/static/js/api.js').read_text(encoding='utf-8')
services_js = (ROOT / 'dashboard/static/js/services.js').read_text(encoding='utf-8')
app = (ROOT / 'dashboard/app.py').read_text(encoding='utf-8')

system_start = html.index('id="tab-system"')
radio_start = html.index('id="tab-radio"')
system_html = html[system_start:radio_start]

checks = [
    ('service control moved to System', 'id="system-service-control-title"' in system_html),
    ('service controls remain present', all(token in system_html for token in (
        'data-action="start_ais"', 'data-action="stop_ais"',
        'data-action="start_adsb"', 'data-action="stop_adsb"'))),
    ('legacy role form removed', 'id="receiver-roles-form"' not in html),
    ('legacy role dropdowns removed', 'id="receiver-role-sdr1"' not in html and 'id="receiver-role-sdr2"' not in html),
    ('service click dispatcher retained', 'button.dataset.action' in controls_js and 'runActionApi(actionId)' in controls_js),
    ('service action API retained', 'fetch("/api/action"' in api_js and 'JSON.stringify({action: actionId})' in api_js),
    ('service button state handlers retained', 'setPair("start_ais", "stop_ais"' in services_js and 'setPair("start_adsb", "stop_adsb"' in services_js),
    ('receiver assignment UI retained', 'Receiver Assignments' in html and 'receiver-assignment-weather' in html),
    ('current assignment selectors retained', all(token in html for token in (
        'receiver-assignment-weather', 'receiver-assignment-ais',
        'receiver-assignment-adsb', 'receiver-assignment-iss-voice'))),
    ('legacy APIs retained for compatibility', '@app.route("/api/receiver-roles", methods=["POST"])' in app and '@app.route("/api/receiver-roles/apply", methods=["POST"])' in app),
]
for label, ok in checks:
    if not ok:
        raise SystemExit(f'FAIL: {label}')
    print(f'PASS: {label}')
print('VALIDATION PASS: v0.47.1c Receiver Runtime & Service Control')
