"""Read-only, cached official ARISS SSTV announcements."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from threading import RLock
import time
from urllib.request import Request, urlopen

SOURCE = "https://www.ariss.org/upcoming-sstv-events.html"
_LOCK = RLock()
_cache = {}
_checked = 0.0

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("br", "p", "div", "h2"):
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def parse_notice(document):
    parser = _Text()
    parser.feed(document)
    text = " ".join(" ".join(parser.parts).split())
    matches = list(re.finditer(r"\b(20\d{2}-\d{2}-\d{2})\s+SSTV\b", text))
    if not matches:
        raise ValueError("No dated SSTV announcement found on ARISS.")
    first = matches[0]
    end = matches[1].start() if len(matches) > 1 else first.start() + 1600
    notice = text[first.start():end].strip()
    # Keep the displayed source excerpt short; never render third-party HTML.
    excerpt = " ".join(notice.split()[:90])
    end_utc = None
    match = re.search(r"Concludes\s+\w+\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})\s+(?:at\s+)?(\d{1,2}):(\d{2})\s+UTC", notice, re.I)
    if match:
        try:
            end_utc = datetime.strptime(" ".join(match.groups()), "%B %d %Y %H %M").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return {"published": first.group(1), "excerpt": excerpt, "end_utc": end_utc}

def get_announcements():
    global _cache, _checked
    with _LOCK:
        now = time.monotonic()
        if _checked and now - _checked < (3600 if _cache.get("ok") else 300):
            return dict(_cache)
        try:
            request = Request(SOURCE, headers={"User-Agent": "SDRCC-ARISS-SSTV/0.65"})
            with urlopen(request, timeout=8) as response:
                if response.geturl() != SOURCE:
                    raise ValueError("Unexpected ARISS redirect")
                raw = response.read(1000001)
            if len(raw) > 1000000:
                raise ValueError("ARISS response too large")
            notice = parse_notice(raw.decode("utf-8", "replace"))
            _cache = {"ok": True, "source_url": SOURCE, **notice,
                      "checked_at": datetime.now(timezone.utc).isoformat()}
        except (OSError, ValueError, TimeoutError) as error:
            _cache = {**_cache, "ok": False, "source_url": SOURCE,
                      "error": "ARISS announcements temporarily unavailable."}
        _checked = now
        return dict(_cache)
