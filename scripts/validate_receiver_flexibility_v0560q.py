#!/usr/bin/env python3
"""Behavior tests against real Registry/Manager; only USB and service boundaries simulated."""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import receiver_registry as registry, receiver_manager as manager, receiver_hardware as hardware
from core import config, event_bus

class Flexibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.usb = self.root/'usb'; self.usb.mkdir()
        self.registry = self.root/'receivers.yaml'
        self.state = self.root/'manager.json'
        original = yaml.safe_load((ROOT/'config/receivers.yaml').read_text())
        for item in original['receivers'].values(): item['hardware']['serial'] = ''
        self.registry.write_text(yaml.safe_dump(original))
        self.patches = [patch.object(registry, 'REGISTRY_FILE', self.registry),
                        patch.object(manager, 'STATE_FILE', self.state),
                        patch.object(hardware, 'SYSFS', self.usb),
                        patch.object(event_bus, 'publish_receiver'),
                        patch.object(config, 'get_receiver_assignments', return_value={'ais':'sdr1','adsb':'sdr2','weather':'sdr2','hf_monitor':'sdr2','traffic_voice':'sdr2'})]
        for p in self.patches: p.start()
        hardware._cache=(0,None); manager._previous_active={}
        self.services={}; self.calls=[]; self.synced=[]
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()
    def usb_add(self, serial, port=None):
        port=port or ('1-'+str(len(list(self.usb.iterdir()))+1))
        p=self.usb/port; p.mkdir()
        for key,value in {'idVendor':'0bda','idProduct':'2838','product':'RTL2838UHIDIR','serial':serial}.items(): (p/key).write_text(value)
        hardware._cache=(0,None)
    def usb_clear(self):
        import shutil
        for p in self.usb.iterdir(): shutil.rmtree(p)
        hardware._cache=(0,None)
    def observe(self, name): return {'state': 'active' if self.services.get(name) else 'inactive','active': bool(self.services.get(name))}
    def action(self, action, name):
        self.calls.append((action,name)); self.services[name] = action=='start'; return True
    def wait(self,name,state,timeout): return self.services.get(name,False)==(state=='active')
    def sync(self,a,b): self.synced.append((a,b)); return {'ok':True}
    def bind(self,**kwargs): return manager.bind_hardware(privileged_apply=self.sync,service_state=self.observe,**kwargs)
    def tick(self, stop=None):
        manager.hardware_tick(service_state=self.observe,service_action=self.action,wait_for_service=self.wait,
                              stop_receiver=stop or (lambda *a:None),privileged_apply=self.sync)
    def serials(self): return [r['serial'] for r in registry.get_receivers()]
    def bound(self):
        self.usb_add('A');self.usb_add('B');self.bind()
    def test_empty_valid_and_unavailable(self):
        self.assertEqual(self.serials(),['',''])
        self.assertFalse(manager.is_available('sdr1'))
        with self.assertRaises(RuntimeError): manager.reserve('sdr1',mission_key='test')
        self.tick();self.assertEqual(self.serials(),['',''])
    def test_initial_binding_stable_by_serial(self):
        self.usb_add('B');self.usb_add('A');self.bind()
        self.assertEqual(self.serials(),['A','B']);self.assertEqual(self.synced,[('A','B')])
        self.assertTrue(manager.is_available('sdr1'))
    def test_missing_bindings_retained(self):
        self.bound();self.usb_clear();before=self.registry.read_bytes();self.tick()
        self.assertEqual(self.registry.read_bytes(),before)
        self.assertFalse(manager.is_available('sdr1'))
        self.assertFalse(manager.get_status()['receivers']['sdr1']['available'])
    def test_unknown_does_not_modify(self):
        self.bound();before=self.registry.read_bytes()
        with patch.object(hardware,'SYSFS',self.root/'missing'):
            hardware._cache=(0,None);self.tick()
            self.assertEqual(hardware.presence('A'),'UNKNOWN')
            self.assertFalse(manager.is_available('sdr1'))
        self.assertEqual(self.registry.read_bytes(),before)
    def test_duplicate_serial_rejected(self):
        self.usb_add('DUP');self.usb_add('DUP')
        self.assertTrue(hardware.scan(refresh=True)['ambiguous'])
        with self.assertRaises(RuntimeError):self.bind()
        self.assertEqual(self.serials(),['',''])
    def test_missing_serial_rejected(self):
        self.usb_add('');self.usb_add('B')
        with self.assertRaises(RuntimeError):self.bind()
    def test_ambiguous_count_manual_binding(self):
        self.usb_add('A')
        self.assertFalse(self.bind()['ok'])
        self.bind(mapping={'receiver01':'A'})
        self.assertEqual(self.serials(),['A',''])
    def test_extra_device_requires_choice(self):
        for s in ('A','B','C'):self.usb_add(s)
        self.assertFalse(self.bind()['ok']);self.assertEqual(self.serials(),['',''])
    def test_replace_two(self):
        self.bound();self.usb_clear();self.usb_add('C');self.usb_add('D');self.tick()
        self.assertEqual(self.serials(),['C','D'])
        self.assertEqual(self.synced[-1],('C','D'))
    def test_replace_one_preserves_other(self):
        self.bound();self.usb_clear();self.usb_add('B');self.usb_add('C');self.tick()
        self.assertEqual(self.serials(),['C','B'])
    def test_live_services_stop_sync_restart(self):
        self.bound();self.services['ais-catcher.service']=True;self.tick()
        self.usb_clear();self.usb_add('B');self.usb_add('C');self.tick()
        self.assertIn(('stop','ais-catcher.service'),self.calls)
        self.assertIn(('start','ais-catcher.service'),self.calls)
        self.assertTrue(self.services['ais-catcher.service'])
        self.assertEqual(self.synced[-1],('C','B'))
    def test_reservation_not_force_released(self):
        self.bound();manager.reserve('sdr1',mission_key='owner')
        self.usb_clear();self.usb_add('B');self.usb_add('C')
        with self.assertRaises(RuntimeError):self.tick()
        self.assertEqual(self.serials(),['A','B'])
        self.assertIn('receiver01',manager._load_state()['reservations'])
    def test_existing_executor_cleanup_defers_services(self):
        self.bound();self.services['ais-catcher.service']=True
        manager.begin_handover('sdr1',mission_key='test-mission',services=['ais-catcher.service'],
                               service_state=self.observe,service_action=self.action,wait_for_service=self.wait,
                               release_delay_seconds=0)
        self.usb_clear();self.usb_add('B');self.usb_add('C')
        def stop(key,reservation):
            if reservation:
                result=manager.restore_handover(mission_key=reservation['mission_key'],service_state=self.observe,
                    service_action=self.action,wait_for_service=self.wait)
                self.assertTrue(result['deferred'])
        self.tick(stop)
        self.assertEqual(self.serials(),['C','B'])
        self.assertTrue(self.services['ais-catcher.service'])
        self.assertFalse(manager._load_state()['reservations'])
    def test_external_failure_blocks_and_retries(self):
        self.usb_add('A');self.usb_add('B')
        with self.assertRaises(RuntimeError):
            manager.bind_hardware(privileged_apply=lambda *a:{'ok':False,'message':'adapter failed'},service_state=self.observe)
        self.assertEqual(self.serials(),['','']);self.assertTrue(manager.binding_status()['transaction'])
        self.bind();self.assertEqual(self.serials(),['A','B']);self.assertFalse(manager.binding_status()['transaction'])
    def test_atomic_registry_failure_replays_intent(self):
        self.usb_add('A');self.usb_add('B')
        with patch.object(registry,'write_bindings',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.bind()
        self.assertEqual(self.serials(),['','']);self.assertTrue(manager.binding_status()['transaction'])
        self.bind();self.assertEqual(self.serials(),['A','B'])
    def test_manual_change_busy_is_rejected(self):
        self.bound();self.usb_add('C');self.services['ais-catcher.service']=True
        with self.assertRaises(RuntimeError):self.bind(mapping={'receiver01':'C'})
        self.assertEqual(self.serials(),['A','B'])
    def test_snapshot_read_only(self):
        self.usb_add('A');self.usb_add('B');before=self.registry.read_bytes()
        for _ in range(3):manager.get_status()
        self.assertEqual(self.registry.read_bytes(),before)
    def test_duplicate_mapping_rejected(self):
        self.usb_add('A');self.usb_add('B')
        with self.assertRaises(ValueError):self.bind(mapping={'receiver01':'A','receiver02':'A'})
    def test_recovery_survives_restart(self):
        self.bound();self.services['ais-catcher.service']=True;self.tick()
        self.usb_clear();self.tick()
        manager._previous_active={}
        self.usb_add('A');self.usb_add('B');self.tick()
        self.assertTrue(self.services['ais-catcher.service'])
    def test_explicit_stop_cancels_recovery(self):
        self.bound();self.services['ais-catcher.service']=True;self.tick()
        self.usb_clear();self.tick();manager.cancel_service_recovery('ais')
        self.usb_add('A');self.usb_add('B');self.tick()
        self.assertFalse(self.services['ais-catcher.service'])
    def test_ais_restores_main_before_control(self):
        self.bound()
        self.services.update({'ais-catcher.service':True,'ais-catcher-control.service':True})
        self.tick();self.usb_clear();self.tick();self.usb_add('A');self.usb_add('B');self.tick()
        starts=[name for action,name in self.calls if action=='start']
        self.assertEqual(starts,['ais-catcher.service','ais-catcher-control.service'])
    def test_service_start_blocked_when_missing(self):
        self.bound();self.usb_clear()
        self.assertIsNotNone(manager.service_action_block('ais','start'))
        self.assertIsNone(manager.service_action_block('ais','stop'))
    def test_activation_checks_disappearance(self):
        self.bound();manager.reserve('sdr1',mission_key='owner');self.usb_clear()
        with self.assertRaises(RuntimeError):manager.activate(mission_key='owner')
        self.assertIn('receiver01',manager._load_state()['reservations'])
    def test_service_restart_failure_keeps_intent(self):
        self.bound();self.services['ais-catcher.service']=True;self.tick();self.usb_clear();self.tick()
        self.usb_add('A');self.usb_add('B')
        with self.assertRaises(RuntimeError):
            manager.hardware_tick(service_state=self.observe,service_action=lambda *args:False,
                wait_for_service=self.wait,stop_receiver=lambda *args:None,privileged_apply=self.sync)
        self.assertTrue(manager.binding_status()['recovery'])
        self.assertFalse(manager.is_available('sdr1'))
    def test_blank_config_can_update_station_location(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('configure_station',ROOT/'scripts/install/configure_station.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        station=self.root/'station.yaml';station.write_text('station: {}\n')
        args=['configure_station','--location','Test','--latitude','1','--longitude','2','--apply']
        with patch.object(module,'STATION',station),patch.object(module,'RECEIVERS',self.registry),patch.object(sys,'argv',args):
            module.main()
        self.assertEqual(yaml.safe_load(station.read_text())['station']['location'],'Test')
        self.assertEqual(self.serials(),['',''])
    def test_clean_external_placeholders_then_existing_helper(self):
        import importlib.util
        def module(name,path):
            spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
        initial=module('initial',ROOT/'scripts/install/initialize_external.py')
        helper=module('helper',ROOT/'scripts/sdrcc_apply_receiver_roles.py')
        ais=self.root/'ais.json';readsb=self.root/'readsb'
        ais.write_text(json.dumps({'config':'aiscatcher','viewer':{'lat':1}}))
        readsb.write_text('RECEIVER_OPTIONS="--device-type rtlsdr --gain auto"\n')
        initial.initialize(ais,readsb)
        with patch.object(helper,'AIS_CONFIG',ais),patch.object(helper,'READSB_CONFIG',readsb):
            helper.write_ais_serial('NEW-A');helper.write_readsb_serial('NEW-B')
            self.assertEqual(helper.read_ais_serial(),'NEW-A');self.assertEqual(helper.read_readsb_serial(),'NEW-B')
        before=(ais.read_bytes(),readsb.read_bytes());initial.initialize(ais,readsb)
        self.assertEqual(before,(ais.read_bytes(),readsb.read_bytes()))
        self.assertEqual(json.loads(ais.read_text())['viewer'],{'lat':1})
    def test_controller_defers_only_missing_service(self):
        self.bound();self.assertFalse(manager.defer_missing_service('ais-catcher.service'))
        self.usb_clear();self.assertTrue(manager.defer_missing_service('ais-catcher.service'))
        self.assertEqual(manager.binding_status()['recovery']['receiver01']['services'],['ais-catcher.service'])
    def test_dashboard_hf_loss_uses_existing_controller(self):
        from types import SimpleNamespace
        tree=ast.parse((ROOT/'dashboard/app.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stop_receiver_for_hardware_loss')
        calls=[]
        controller=SimpleNamespace(get_session=lambda:{'receiver':{'registry_id':'receiver01'}},stop=lambda **kwargs:calls.append('stop'))
        namespace={'hf_monitor_controller':controller,'receiver_registry':registry,
                   'service_state':self.observe,'run_systemctl':self.action,'wait_for_service':self.wait,
                   '_active_mission_receiver':lambda:None}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'dashboard-hf-stop','exec'),namespace)
        namespace['stop_receiver_for_hardware_loss']('receiver01',{'mission_key':'hf'})
        self.assertEqual(calls,['stop'])
    def test_operator_can_recover_pending_with_different_replacement(self):
        self.usb_add('A');self.usb_add('B')
        with self.assertRaises(RuntimeError):
            manager.bind_hardware(privileged_apply=lambda *args:{'ok':False},service_state=self.observe)
        self.usb_clear();self.usb_add('B');self.usb_add('C')
        self.bind(mapping={'receiver01':'C','receiver02':'B'})
        self.assertEqual(self.serials(),['C','B']);self.assertFalse(manager.binding_status()['transaction'])
    def test_no_service_resurrection_on_idle_receiver(self):
        self.bound();self.usb_clear();self.tick()
        self.usb_add('A');self.usb_add('B');self.tick()
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
