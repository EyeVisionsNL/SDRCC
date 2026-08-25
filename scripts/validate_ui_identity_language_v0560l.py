#!/usr/bin/env python3
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
def check(ok,msg):
    if not ok:
        print(f"FAIL: {msg}"); raise SystemExit(1)
    print(f"PASS: {msg}")
check((ROOT/'VERSION').read_text().strip()=='0.56.0l','release version is 0.56.0l')
for rel in ['dashboard/app.py','core/mission_scheduler.py','core/mission_preflight.py','core/mission_engine.py','core/receiver_manager.py','core/mission_simulator.py','core/satdump.py','core/mission_queue.py']:
    ast.parse((ROOT/rel).read_text()); check(True,f'parseable {rel}')
inv=(ROOT/'dashboard/static/js/receiver_inventory.js').read_text(); ana=(ROOT/'dashboard/static/js/mission_analytics.js').read_text(); tim=(ROOT/'dashboard/static/js/timeline.js').read_text(); app=(ROOT/'dashboard/app.py').read_text()
check('receiver.name || receiver.number || receiver.id' in inv,'System inventory prefers SDR display name')
check('analyticsReceiverLabel' in ana,'Analytics has display-only receiver normalizer')
for token in ('RECEIVER01','RX01','RECEIVER02','RX02'): check(token in ana,f'Analytics normalizer covers {token}')
for phrase in ('Nog geen operator-events.','Geen events binnen dit filter.','Details tonen','Details verbergen','Event Timeline tijdelijk niet bereikbaar.'):
    check(phrase not in tim,f'Timeline UI no longer contains Dutch: {phrase}')
for phrase in ('Passage geselecteerd','Event Bus gestart','SDRCC operator-eventopslag en API zijn actief.'):
    check(phrase not in app,f'active dashboard Event Bus producer is English: {phrase}')
check((ROOT/'docs/ui-identity-language-consistency-v0560l.md').exists(),'v0.56.0l documentation is present')
print('VALIDATION PASS: SDRCC v0.56.0l UI Identity & Language Consistency')
