#!/usr/bin/env python3
"""Run the dashboard assignment workflow with real voice cleanup and fake services."""
import ast
from contextlib import ExitStack
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import traffic_voice_controller as voice


class AssignmentVoice(unittest.TestCase):
    def scenario(self, mode, fail=False, previous_voice=False):
        assignments = {'ais': 'sdr1', 'adsb': 'sdr2', 'traffic_voice': 'sdr2'}
        states = {voice.VOICE_SERVICE: True, voice.AIS_SERVICE: True, voice.ADSB_SERVICE: False}
        actions = []
        def state(service):
            return {'active': states[service], 'state': 'active' if states[service] else 'inactive'}
        def action(operation, service):
            actions.append((operation, service))
            if fail and service == voice.VOICE_SERVICE:
                return NS(returncode=1, stderr='stop failed')
            states[service] = operation == 'start'
            return NS(returncode=0)
        def reserve():
            self.assertFalse(states[voice.VOICE_SERVICE])
            self.assertFalse(voice.SESSION_FILE.exists())
            actions.append(('reserve', 'receivers'))
            return ['reservation']
        def apply(changes, **kwargs):
            self.assertFalse(states[voice.VOICE_SERVICE])
            actions.append(('apply', 'assignments'))
            assignments.update(changes)
            return {'ok': True, 'assignments': dict(assignments)}
        authority = NS(service_serials=Mock(), apply_assignments=Mock(side_effect=apply))
        manager = NS(cancel_service_recovery=Mock())
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(voice, 'SESSION_FILE', Path(directory)/'session.json'))
            stack.enter_context(patch.object(voice.config, 'get_receiver_assignments', side_effect=lambda:dict(assignments)))
            stack.enter_context(patch.object(voice.config, 'set_plugin_assignments', side_effect=assignments.update))
            stack.enter_context(patch.object(voice.receiver_manager, 'get_status', return_value={}))
            stack.enter_context(patch.object(voice.receiver_manager, 'defer_missing_service', return_value=False))
            stack.enter_context(patch.object(voice.receiver_registry, 'resolve_id', side_effect=lambda value:value))
            stack.enter_context(patch.object(voice.traffic_voice, 'get_receiver_settings', return_value={'open_squelch':False}))
            previous = {s:{'active':True, 'state':'active'} for s in states}
            previous[voice.VOICE_SERVICE]['active'] = previous_voice
            voice._write_session(previous, assignments, mode=mode, voice_receiver='sdr2')
            tree = ast.parse((ROOT/'dashboard/app.py').read_text())
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='_apply_receiver_assignment_changes')
            function.decorator_list = []
            namespace = dict(_receiver_assignment_block_reason=lambda:None,
                config_core=NS(validate_assignment_changes=lambda c:(c,{**assignments,**c}), get_receiver_assignments=lambda:dict(assignments)),
                receiver_authority=authority, receiver_manager=manager,
                traffic_voice_controller=voice, service_state=state, run_systemctl=action,
                wait_for_service=lambda s, expected, timeout:states[s]==(expected=='active'),
                _reserve_assignment_transaction_receivers=reserve,
                _release_assignment_transaction_receivers=lambda keys:[],
                apply_receiver_service_configuration=Mock(),write_log=Mock(),
                event_bus=NS(publish_receiver=Mock()))
            exec(compile(ast.Module(body=[function],type_ignores=[]), 'dashboard/app.py','exec'),namespace)
            result, status = namespace[function.name]({'ais':'sdr2','adsb':'sdr1'})
            if fail:
                self.assertEqual(status,409)
                authority.apply_assignments.assert_not_called()
                self.assertEqual(assignments['ais'],'sdr1')
                self.assertTrue(voice.SESSION_FILE.exists())
            else:
                self.assertEqual(status,200)
                self.assertEqual(assignments['ais'],'sdr2')
                self.assertFalse(states[voice.VOICE_SERVICE])
                self.assertLess(actions.index(('stop',voice.VOICE_SERVICE)),actions.index(('reserve','receivers')))
                self.assertNotIn(('start',voice.VOICE_SERVICE),actions)
            manager.cancel_service_recovery.assert_called_once_with('traffic_voice')
    def test_marine_swap(self): self.scenario('marine_ais')
    def test_airband_swap(self): self.scenario('airband_adsb')
    def test_stop_failure_aborts_swap(self): self.scenario('marine_ais',fail=True)
    def test_old_session_cannot_restart_voice(self): self.scenario('marine_ais',previous_voice=True)

if __name__=='__main__': unittest.main(verbosity=2)
