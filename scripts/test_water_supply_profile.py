import unittest
from core import traffic_map

class WaterSupplyTests(unittest.TestCase):
    def test_numbered_fleet_names(self):
        for name in ('DWS 15', 'DWS15', 'D.W.S. 15', 'DWS 15 - WATERMAN', 'WATERMAN-DWS 15', 'DRINKWATER 1', 'Drinkwaterboot 2', 'WATERBOOT 15'):
            with self.subTest(name=name):
                self.assertEqual(traffic_map.display_profile(name,8000,0),'water_supply')
        for name in ('WATERMAN','DWS','DWS 15 CARGO','MY WATERBOOT','DRINKWATER','OTHER'):
            self.assertNotEqual(traffic_map.display_profile(name,8000,0),'water_supply')

    def test_protected_types_and_fixed_targets(self):
        for kind in (55,30,60,70,81,8400):
            self.assertNotEqual(traffic_map.display_profile('DWS 15',kind,0),'water_supply')
        for cls in (9,10,11,12):
            self.assertNotEqual(traffic_map.display_profile('DWS 15',8000,cls),'water_supply')
        self.assertNotEqual(traffic_map.display_profile('DWS 15',8000,0,mmsi='992440001'),'water_supply')

    def test_screenshot_vessel_keeps_ais_dimensions(self):
        ship=traffic_map.vessels({'ships':[{'mmsi':244700532,'shipname':'DWS 15',
            'shiptype':8000,'shipclass':0,'lat':51.9,'lon':4.4,'length':25,'width':6,
            'cog':177.1,'sog':3,'callsign':'PG7871','eni':'02009392'}]})[0]
        self.assertEqual(ship['render_profile'],'water_supply')
        self.assertTrue(ship['hull_available'])
        self.assertEqual(ship['length_m'],25)
        self.assertEqual(ship['beam_m'],6)
        self.assertEqual(ship['shiptype'],8000)
