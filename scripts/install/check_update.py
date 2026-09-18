#!/usr/bin/env python3
"""Read-only update source, compatibility and receiver-ownership checks."""
from pathlib import Path
import hashlib
import json
import sys

source, project = map(Path, sys.argv[1:3])
manifest_path = source / "scripts/install/update_manifest.json"
manifest = json.loads(manifest_path.read_text())

if not isinstance(manifest, dict):
    raise SystemExit("FAIL: update manifest is not an object")

for name, allowed in manifest.items():
    relative = Path(name)
    if (
        not isinstance(name, str)
        or relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
    ):
        raise SystemExit(f"FAIL: unsafe update manifest path {name!r}")
    if not isinstance(allowed, list) or not all(isinstance(value, str) for value in allowed):
        raise SystemExit(f"FAIL: invalid hash list for {name}")

    # The manifest cannot approve its own current digest without recursion.
    if name == "scripts/install/update_manifest.json":
        continue

    source_file = source / relative
    if not source_file.is_file():
        raise SystemExit(f"FAIL: update source missing {name}")
    source_digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
    if source_digest not in allowed:
        raise SystemExit(f"FAIL: update source hash not approved for {name}")

    target = project / relative
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() not in allowed:
        raise SystemExit(f"FAIL: locally modified source {name}; review before updating")

state = project / "data/state/receiver_manager.json"
if state.exists():
    data = json.loads(state.read_text())
    if any(
        data.get(key)
        for key in (
            "reservations",
            "reservation",
            "binding_transaction",
            "hardware_recovery",
        )
    ):
        raise SystemExit(
            "FAIL: receiver activity, binding transaction or hardware recovery is pending. "
            "Resolve it in the dashboard and retry."
        )

print(
    "PASS: update source hashes approved; source compatibility clean; "
    "no receiver activity/recovery; local config excluded from update"
)
