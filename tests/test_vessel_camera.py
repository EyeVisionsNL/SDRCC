"""Curated identity and active Marine Traffic snapshot regression."""
import unittest
from pathlib import Path
import yaml
from unittest.mock import patch
from core import vessel_camera, traffic_voice


class VesselCameraTests(unittest.TestCase):
    def test_catalog(self):
        for mmsi, (name, _) in vessel_camera.CAMERAS.items():
            match = dict(matched=True, mmsi=mmsi, shipname=name)
            result = vessel_camera.for_match(match)
            self.assertEqual(result['mmsi'], mmsi)
            self.assertTrue(result['page_url'].startswith('https://webcam-binnenvaart.nl/pages/cam-'))
            self.assertIsNone(vessel_camera.for_match({**match, 'matched': False}))
            self.assertIsNone(vessel_camera.for_match({**match, 'shipname': 'OTHER VESSEL'}))
            self.assertIsNone(vessel_camera.for_match({**match, 'mmsi': '999999999'}))
        self.assertIsNone(vessel_camera.for_match(None))
        self.assertIsNone(vessel_camera.for_match(dict(matched=True, shipname='SAYONARA')))

    def test_snapshot(self):
        raw = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config/traffic_voice.yaml').read_text())
        match = dict(matched=True, mmsi='244010927', shipname='CARISMA')
        for mode, active, expected in [('marine_ais', True, True), ('marine_ais', False, False), ('airband_adsb', True, False)]:
            raw['traffic_voice']['selected_mode'] = mode
            with patch.object(traffic_voice.config_core, 'load_traffic_voice', return_value=raw), patch.object(traffic_voice, '_log_atis_ais_result_once'):
                result = traffic_voice.get_snapshot(
                    service_reader=lambda _: dict(active=active),
                    audio_reader=lambda: dict(ok=True, available=False),
                    atis_reader=lambda: dict(latest=dict(fresh=True, atis_code='9244010927')),
                    ais_matcher=lambda _: match)
            self.assertEqual(bool(result['vessel_camera']), expected)
            if mode == 'marine_ais':
                self.assertEqual(result['ais_match'], match)
