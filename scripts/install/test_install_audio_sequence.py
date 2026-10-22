#!/usr/bin/env python3
"""Read-only installer-order regression checks; does not install packages."""
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT / "install.sh"


class FreshInstallAudioTests(unittest.TestCase):
    def test_venv_and_requirements_precede_audio_dependencies(self):
        bash = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(bash.index('say "Python environment"'),
                        bash.index('say "Audio processing and ISS SSTV decoder"'))
        self.assertLess(bash.index('"$PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"'),
                        bash.index('say "Audio processing and ISS SSTV decoder"'))

    def test_satellite_only_install_also_attempts_sstv_setup(self):
        bash = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if ((FEATURE_TRAFFIC_VOICE || FEATURE_SATELLITE)); then', bash)
        self.assertIn('prepare_audio_comparison.sh" "$PROJECT_ROOT" --install', bash)

    def test_audio_failure_warns_without_aborting_core(self):
        bash = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("WARNING: Audio processing or ISS SSTV setup is incomplete.", bash)
        self.assertIn("Complete audio setup.", bash)


if __name__ == "__main__":
    unittest.main()
