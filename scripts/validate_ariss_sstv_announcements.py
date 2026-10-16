#!/usr/bin/env python3
"""Regression checks for official ARISS SSTV announcement parsing."""
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.iss_sstv_announcements import parse_notice


NEW_AND_OLD = """<h2>Upcoming SSTV events</h2>
<p><strong>2026-10-14 Expedition 75 Series 34 &quot;ARISS Hardware&quot;</strong><br>
Begins Thursday October 22 time TBD (will be updated here)<br>
Concludes Sunday October 25 time TBD (will be updated here)<br>
Images will be transmitted at 437.55 MHz (+/- Doppler shift), decode with Robot 36 mode,
transmission 36 seconds on, two minutes off.</p>
<p>2026-09-23 SSTV Expedition 75 Series 33 featuring "Student Education"<br>
Begins Friday October 2, 2026 9:00 UTC.<br>
Concludes Tuesday October 6, 2026 at 15:55 UTC.</p>"""

latest = parse_notice(NEW_AND_OLD)
assert latest["published"] == "2026-10-14", latest
assert "Expedition 75 Series 34" in latest["excerpt"], latest
assert "ARISS Hardware" in latest["excerpt"], latest
assert "Series 33" not in latest["excerpt"], latest
assert latest["end_utc"] is None, "TBD must not be treated as a confirmed end time"

older = parse_notice("""<h2>Upcoming SSTV events</h2>
<p>2026-09-23 SSTV Expedition 75 Series 33 featuring "Student Education"<br>
Begins Friday October 2, 2026 9:00 UTC.<br>
Concludes Tuesday October 6, 2026 at 15:55 UTC.</p>""")
assert older["published"] == "2026-09-23", older
assert older["end_utc"] == datetime(2026, 10, 6, 15, 55, tzinfo=timezone.utc).isoformat(), older

try:
    parse_notice("<p>No announcement currently available.</p>")
except ValueError:
    pass
else:
    raise AssertionError("Missing dated announcement must fail clearly")

print("PASS: ARISS latest Expedition notice, TBD handling, historical SSTV notice")
