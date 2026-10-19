"""Focused regressions for the System > Advanced Maintenance disclosure layout."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dashboard/templates/index.html"
JS = ROOT / "dashboard/static/js/emergency_monitor.js"
CSS = ROOT / "dashboard/static/css/emergency_monitor.css"


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.element_parent = {}
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get("id")
        if name:
            self.element_parent[name] = list(self.stack)
            self.elements[name] = (tag, attrs)
        if tag not in {"input", "img", "link", "meta", "br", "hr", "source", "area", "wbr"}:
            self.stack.append((tag, name))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                break


class AdvancedMaintenanceLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.tags = Tags()
        cls.tags.feed(cls.html)

    def test_emergency_monitor_is_independently_collapsible(self):
        tag, attrs = self.tags.elements["em-monitor"]
        self.assertEqual(tag, "details")
        self.assertNotIn("open", attrs)
        self.assertIn(("details", None), self.tags.element_parent["em-monitor"])
        self.assertIn(("details", "em-monitor"), self.tags.element_parent["em-form"])
        self.assertIn("em-summary", self.html)
        self.assertIn('id="em-state"', self.html)

    def test_unused_autostart_test_card_is_absent(self):
        self.assertNotIn('data-action="disable_sdrcc_autostart"', self.html)
        self.assertNotIn('id="sdrcc-autostart-result"', self.html)
        self.assertNotIn("SDRCC test mode", self.html)

    def test_runtime_source_cards_not_concatenated(self):
        for source in ("adsb", "ais", "mqtt"):
            self.assertIn('id="em-source-' + source + '"', self.html)
            self.assertIn('data-source="' + source + '"', self.html)
            self.assertIn('renderSourceStatus("' + source + '"', self.js)
        self.assertIn('data-state="ok"', self.css)
        self.assertIn('data-state="error"', self.css)
        self.assertIn('data-state="warning"', self.css)
        self.assertNotIn('"ADS-B: " + (runtime.adsb', self.js)

    def test_control_ids_survive_maintenance_refactor(self):
        for name in ("em-enabled", "em-form", "em-test", "em-save",
                     "em-cat-lifeliner", "em-radius", "em-mqtt-config",
                     "home-position-form", "sdrcc-update-install",
                     "ais-autostart-result", "mission-sounds-enabled"):
            self.assertIn(name, self.tags.elements)

    def test_category_radius_inputs_for_all_aircraft_and_vessel_categories(self):
        for name in ("lifeliner", "police_helicopter", "knrm", "waterpolitie"):
            tag, attrs = self.tags.elements["em-range-" + name]
            self.assertEqual(tag, "input")
            self.assertEqual(attrs.get("type"), "number")
            self.assertEqual(attrs.get("min"), "1")
            self.assertEqual(attrs.get("max"), "100")
        self.assertIn("category_radius_km: Object.fromEntries", self.js)
        self.assertIn(".em-category-radii", self.css)

    def test_audio_ui_sounds_panel_is_full_width_and_compact(self):
        self.assertIn('id="mission-sounds-title"', self.html)
        self.assertIn("Audio &amp; UI sounds", self.html)
        self.assertIn('mission-sounds-options', self.html)
        self.assertIn("mission_sounds.css?v=0.67.24", self.html)
        for name in ("mission-sounds-enabled", "mission-sounds-volume",
                     "mission-tab-sounds-enabled", "mission-control-sounds-enabled",
                     "mission-interface-clicks-enabled", "mission-startup-sound-enabled",
                     "mission-sounds-test", "mission-tab-sounds-test",
                     "mission-control-sounds-test-start", "mission-control-sounds-test-stop",
                     "mission-interface-clicks-test", "mission-startup-sound-test"):
            self.assertIn(name, self.tags.elements)

        sound_css = (ROOT / "dashboard/static/css/mission_sounds.css").read_text(encoding="utf-8")
        self.assertIn("#tab-system .system-maintenance-body-v0540f > .mission-sounds-panel {", sound_css)
        self.assertIn("grid-column: 1 / -1;", sound_css)
        self.assertIn(".mission-sounds-options {", sound_css)
        self.assertIn(".mission-sounds-test-actions {", sound_css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", sound_css)
        self.assertIn("@media (max-width: 700px)", sound_css)
        self.assertIn("grid-template-columns: 1fr;", sound_css)

    def test_distinct_maintenance_identity_colors(self):
        for color in ("#38bdf8", "#a78bfa", "#f59e0b"):
            self.assertIn(color, self.css)


if __name__ == "__main__":
    unittest.main()
