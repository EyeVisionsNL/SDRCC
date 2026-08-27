#!/usr/bin/env python3
"""Validate the presentation-only FlexGround SDR branding migration."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cli = (ROOT / "scripts/sdrcc.py").read_text(encoding="utf-8")
    main_unit = (ROOT / "systemd/sdrcc.service.in").read_text(encoding="utf-8")
    voice_unit = (ROOT / "systemd/sdrcc-traffic-voice.service.in").read_text(encoding="utf-8")
    log_sources = (ROOT / "core/log_sources.py").read_text(encoding="utf-8")

    check(version == "0.56.0n", "branding release version is 0.56.0n")
    check("FlexGround SDR – Flexible SDR Ground Station" in template, "dashboard title uses the new identity")
    check(template.count("/static/assets/flexground-sdr.png") >= 2, "header and startup splash use the new logo")
    check("/static/assets/flexground-sdr-favicon.png" in template, "dashboard uses the dedicated favicon")
    check("SDRCC – Flexible Ground Station" not in template, "old visible dashboard title is absent")
    check("<h1 align=\"center\">FlexGround SDR</h1>" in readme, "README uses the new project name")
    check("previously presented as **SDR Control Center (SDRCC)**" in readme, "README documents the legacy identity")
    check('print(f"\\nFlexGround SDR v{VERSION}")' in cli, "CLI banner uses the new identity")
    check("Description=FlexGround SDR" in main_unit, "main systemd description uses the new identity")
    check("Description=FlexGround SDR" in voice_unit, "Traffic Voice systemd description uses the new identity")
    check('"label": "FlexGround SDR"' in log_sources, "log viewer presents the new identity")

    # Compatibility boundary: presentation changes must not rename runtime contracts.
    check((ROOT / "systemd/sdrcc.service.in").exists(), "legacy systemd unit filename is retained")
    check((ROOT / "scripts/sdrcc.py").exists(), "legacy CLI filename is retained")
    check('data-log-source="sdrcc"' in template, "legacy log source API identifier is retained")
    check("https://github.com/EyeVisionsNL/SDRCC" in template, "existing repository URL is retained")

    for asset in ("flexground-sdr.png", "flexground-sdr-favicon.png"):
        path = ROOT / "dashboard/static/assets" / asset
        check(path.is_file() and path.stat().st_size > 0, f"{asset} is present and non-empty")

    print("VALIDATION PASS: FlexGround SDR v0.56.0n Branding Foundation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
