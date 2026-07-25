#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.plugin_manager as pm

def req(c,m):
    if not c: raise AssertionError(m)
    print('PASS:',m)

snap=pm.get_snapshot()
req(snap['manager_version']=='0.45.0','Plugin Manager-versie is v0.45.0')
req(snap['summary']['execution_enabled_plugins']==['weather','ais','adsb'],'Weather, AIS en ADS-B zijn execution-enabled')
w=next(p for p in snap['plugins'] if p['plugin_id']=='weather')
req(w['control']['enabled'] is True,'Weather-control is ingeschakeld')
req(w['control']['actions']==['start','stop'],'Weather-acties zijn begrensd tot start/stop')
req(w['execution']['executable'] is True,'Weather execution is uitvoerbaar')
req(w['execution']['execution_mode']=='delegated_mission_scheduler_autopilot','Weather gebruikt scheduler/autopilot-delegatie')
req(w['control']['authority']=='existing_mission_scheduler_autopilot_path','Weather behoudt bestaande missie-authority')
source=Path('dashboard/app.py').read_text()
block=source[source.index('def api_plugin_manager_action'):source.index('@app.route("/api/plugin-capabilities"')]
req('core.satdump' not in block and 'satdump.' not in block,'Plugin Manager-route bevat geen directe SatDump-call')
req('run_systemctl(' not in block,'Weather-route bevat geen eigen systemctl-call')
req('mission_scheduler_core.set_scheduler_mode("AUTO")' in block,'Weather Start activeert bestaande AUTO-scheduler')
req('_stop_active_mission()' in block,'Weather Stop hergebruikt bestaande Stop Mission-keten')
req('immediate_recording": False' in block,'Weather Start begint niet direct met opnemen')
req('next_pass' in block,'Weather Start vereist een eerstvolgende passage')
print({'status':'ok','version':'0.45.0','enabled_plugins':['weather','ais','adsb'],'authority':'existing_mission_scheduler_autopilot_path'})
