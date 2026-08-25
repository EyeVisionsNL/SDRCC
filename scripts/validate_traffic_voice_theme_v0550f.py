#!/usr/bin/env python3
"""Validate the presentation-only v0.55.0f-r3 Traffic Voice theme alignment."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def css_rule(stylesheet: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet, re.DOTALL)
    if not match:
        raise AssertionError(f"missing CSS rule: {selector}")
    return match.group(1)


def main() -> None:
    required = (
        "VERSION",
        "dashboard/templates/index.html",
        "dashboard/static/css/traffic_voice.css",
        "dashboard/static/js/traffic_voice.js",
        "docs/traffic-voice-theme-v0550f.md",
    )
    for relative_path in required:
        check((ROOT / relative_path).is_file(), f"required file present: {relative_path}")

    check(read("VERSION").strip() == "0.56.0c", "current release version is 0.56.0c")
    template = read("dashboard/templates/index.html")
    stylesheet = read("dashboard/static/css/traffic_voice.css")
    javascript = read("dashboard/static/js/traffic_voice.js")

    check(
        '/static/css/traffic_voice.css?v=0.55.0f-r3' in template,
        "Traffic Voice uses the v0.55.0f-r3 stylesheet cache key",
    )
    check('data-traffic-mode="marine_ais"' in template, "Marine mode card remains present")
    check('data-traffic-mode="airband_adsb"' in template, "Aviation mode card remains present")
    check('class="card traffic-voice-shared-workspace"' in template, "Active Receiver card remains present")

    tab = css_rule(stylesheet, "#tab-traffic-voice")
    check("--traffic-accent: #fb7185" in tab, "rose Traffic Voice identity remains defined")
    check("--traffic-cyan: #22d3ee" in tab, "cyan Marine identity is defined")
    check("--traffic-purple: #a78bfa" in tab, "purple Aviation identity is defined")

    marine = css_rule(stylesheet, '.traffic-voice-mode[data-traffic-mode="marine_ais"]')
    aviation = css_rule(stylesheet, '.traffic-voice-mode[data-traffic-mode="airband_adsb"]')
    shared = css_rule(stylesheet, ".traffic-voice-shared-workspace")
    check("var(--traffic-cyan)" in marine, "Marine card uses the cyan panel accent")
    check("var(--traffic-purple)" in aviation, "Aviation card uses the purple panel accent")
    check("var(--traffic-accent)" in shared, "Active Receiver card uses the rose panel accent")

    corner_selector = (
        ".traffic-voice-header::after,\n"
        ".traffic-voice-mode::after,\n"
        ".traffic-voice-shared-workspace::after"
    )
    corner = css_rule(stylesheet, corner_selector)
    for token, label in (
        ("width: 76px", "corner ornament keeps the shared 76px width"),
        ("height: 76px", "corner ornament keeps the shared 76px height"),
        ("top: -45px", "corner ornament keeps the shared vertical offset"),
        ("right: -23px", "corner ornament keeps the shared horizontal offset"),
        ("border-radius: 50%", "corner ornament remains circular"),
        ("pointer-events: none", "corner ornament cannot intercept controls"),
    ):
        check(token in corner, label)

    themed_panels = css_rule(
        stylesheet,
        ".traffic-voice-header,\n.traffic-voice-shared-workspace",
    )
    check("inset 3px 0 0 var(--panel-accent)" in themed_panels, "Active Receiver and header receive the neon accent rail")
    check("overflow: hidden" in themed_panels, "panel corner ornaments remain clipped to their cards")

    mode_rail = css_rule(stylesheet, ".traffic-voice-mode::before")
    check("background: var(--panel-accent)" in mode_rail, "mode rails follow their panel identity")
    check("box-shadow: 0 0 12px" in mode_rail, "mode rails retain a restrained neon glow")
    selected_rail = css_rule(stylesheet, ".traffic-voice-mode.is-selected::before")
    check("var(--panel-accent)" in selected_rail, "selected mode retains its Marine or Aviation identity rail")
    selected_card = css_rule(stylesheet, ".traffic-voice-mode.is-selected")
    check("var(--panel-accent) 72%" in selected_card, "selected border retains the mode identity colour")
    check("var(--traffic-accent)" not in selected_card, "selected Maritime border is no longer forced rose")
    mode_label = css_rule(stylesheet, "#tab-traffic-voice .traffic-voice-mode-heading > div > span")
    check("var(--panel-accent)" in mode_label, "mode label follows the Maritime or Aviation identity")
    mode_icon = css_rule(stylesheet, ".traffic-voice-mode-icon")
    check(mode_icon.count("var(--panel-accent)") >= 3, "mode icon follows its panel identity")

    check("fetch(" in javascript and "/api/traffic-voice" in javascript, "existing Traffic Voice API consumer is unchanged")
    check(not any(token in stylesheet for token in ("systemctl", "subprocess", "/api/")), "theme CSS creates no runtime authority")

    print("VALIDATION PASS: v0.55.0f-r3 Traffic Voice mode identity")


if __name__ == "__main__":
    main()
