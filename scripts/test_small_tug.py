import unittest
from core import traffic_map

class SmallTugTests(unittest.TestCase):
    def ship(self, **extra):
        raw=dict(mmsi=244039187,shipname='KRVE 83',shiptype=52,shipclass=5,
                 lat=51.9,lon=4.4,length=11,width=4,speed=0)
        raw.update(extra)
        return traffic_map.vessels({'ships':[raw]})[0]

    def test_moored_unknown_bearing(self):
        s=self.ship()
        self.assertEqual(s['render_profile'],'tug')
        self.assertTrue(s['hull_available'])
        self.assertTrue(s['hull_bearing_approximate'])
        self.assertEqual(s['hull_heading'],0)
        self.assertEqual(s['length_m'],11)
        self.assertEqual(s['beam_m'],4)

    def test_true_heading_and_offsets(self):
        s=self.ship(heading=123,to_bow=7,to_stern=4,to_port=2,to_starboard=2)
        self.assertEqual(s['hull_heading'],123)
        self.assertFalse(s['hull_bearing_approximate'])
        self.assertEqual(s['to_bow'],7)

    def test_missing_size_stays_icon(self):
        self.assertFalse(self.ship(length=None,width=None)['hull_available'])

    def test_station_and_other_types_unchanged(self):
        self.assertFalse(self.ship(shipclass=12)['hull_available'])
        self.assertFalse(self.ship(shiptype=70)['hull_available'])

    def test_eight_metre_threshold(self):
        self.assertTrue(self.ship(length=8)['hull_available'])
        self.assertFalse(self.ship(length=7.9)['hull_available'])
