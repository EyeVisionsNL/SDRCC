#!/usr/bin/env python3
"""Exercise version discovery against a URL-keyed stale CDN response."""
from io import BytesIO
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import update_manager as manager


def main():
    requests = []
    cache = {}
    remote_version = "0.60.4"

    def cached_response(request, timeout):
        requests.append(request)
        body = cache.setdefault(request.full_url, remote_version.encode())
        return BytesIO(body)

    for channel in ("main", "develop"):
        remote_version = "0.60.4"
        with (
            patch.object(manager, "_read_channel_state", return_value={"selected": channel, "installed": channel}),
            patch.object(manager, "installed_version", return_value="0.60.4"),
            patch.object(manager, "_read_worker_status", return_value={}),
            patch.object(manager, "audio_setup_required", return_value=False),
            patch.object(manager, "urlopen", side_effect=cached_response),
            patch.dict(manager._CHECK),
        ):
            first = manager.check_remote_version()
            assert first["same_version"] and not first["update_available"]
            remote_version = "0.60.5"
            second = manager.check_remote_version()
            assert second["latest_version"] == "0.60.5" and second["update_available"]
            assert requests[-1].full_url != requests[-2].full_url
            url = urlsplit(requests[-1].full_url)
            assert url.path.endswith(f"/{channel}/VERSION")
            assert parse_qs(url.query).get("check")
            assert requests[-1].get_header("Cache-control") == "no-cache, no-store"
            with patch.object(manager, "urlopen", side_effect=URLError("offline")):
                failed = manager.check_remote_version()
            assert failed["latest_version"] is None and not failed["update_available"]
            assert failed["check_error"]
        print(f"PASS: {channel} fresh version, availability and network failure")


if __name__ == "__main__":
    main()
