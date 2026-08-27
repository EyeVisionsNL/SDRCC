#!/usr/bin/env python3
"""Validate the presentation-only SDRCC v0.54.0v-r2 compact header and startup splash."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PROJECT_URL = "https://github.com/EyeVisionsNL/SDRCC"


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.github_links: list[dict[str, str | None]] = []
        self.logo_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "a" and values.get("href") == PROJECT_URL:
            self.github_links.append(values)
        if tag == "img" and values.get("src") == "/static/assets/flexground-sdr.png":
            self.logo_sources.append(values.get("src") or "")


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
    if os.environ.get("FAKE_HEADER_SPLASH_FAIL") == "1":
        raise RuntimeError("injected header splash validation failure")

    template = read("dashboard/templates/index.html")
    header_css = read("dashboard/static/css/header_theme.css")
    splash_js = read("dashboard/static/js/startup_splash.js")
    navigation_css = read("dashboard/static/css/navigation_theme.css")

    parser = ContractParser()
    parser.feed(template)

    check("FlexGround SDR" in template and "Flexible SDR Ground Station" in template, "approved FlexGround SDR identity is present")
    check("Single Screen Ground Station" not in template, "retired Single Screen Ground Station copy is absent")
    check("Mission Control · Satellite Reception · Air Traffic · Maritime" not in template, "old generic banner subtitle is removed")
    check(len(parser.logo_sources) >= 2, "FlexGround SDR logo is reused in splash and banner")
    check('id="sdrcc-startup-splash"' in template and " hidden" in template, "startup splash defaults to hidden")
    check('/static/css/header_theme.css?v=0.56.0n' in template, "header theme uses the current branding cache key")
    check('/static/js/startup_splash.js?v=0.54.0v-r1' in template, "startup behavior uses the v0.54.0v cache key")

    check(len(parser.github_links) == 1, "one canonical project link is present")
    github = parser.github_links[0]
    check(github.get("target") == "_blank", "GitHub project opens in a new tab")
    check(set((github.get("rel") or "").split()) == {"noopener", "noreferrer"}, "GitHub project link isolates the new tab")
    check(bool(github.get("aria-label")), "GitHub project link has an accessible label")
    check("github-project-icon" in template, "GitHub icon is visibly included")
    check("topbar-status" in template and "LIVE" in template, "existing LIVE identity remains present")

    topbar = css_rule(header_css, ".topbar")
    brand = css_rule(header_css, ".topbar .brand-block")
    logo = css_rule(header_css, ".topbar .brand-logo")
    actions = css_rule(header_css, ".topbar-actions")
    check("min-height: 88px" in topbar and "padding: 10px 26px" in topbar, "desktop header height is compact")
    check("flex-direction: row" in brand and "align-items: center" in brand, "title copy sits beside the logo")
    check("width: 72px" in logo and "height: 72px" in logo, "banner logo remains prominent without forcing extra height")
    check("flex-direction: row" in actions and "align-items: center" in actions, "GitHub and LIVE controls share one row")

    for token, label in (
        ("linear-gradient(112deg, #061b38 0%, #083d68 48%, #0b6e9e 100%)", "header has a brighter blue space gradient"),
        (".topbar-space-art", "responsive satellite artwork is styled"),
        (".topbar-satellite", "satellite artwork remains scoped to the header"),
        (".github-project-link:focus-visible", "project link has keyboard focus styling"),
        (".startup-splash.is-visible", "splash entrance state is explicit"),
        (".startup-splash.is-leaving", "splash exit state is explicit"),
        ("@media (max-width: 760px)", "header has a narrow-screen layout"),
        ("@media (prefers-reduced-motion: reduce)", "reduced-motion preference is respected"),
    ):
        check(token in header_css, label)

    check("sdrcc-startup-splash-v0540v" in splash_js, "splash is scoped to the browser session")
    check("window.sessionStorage" in splash_js, "browser-session storage controls repeat display")
    check('document.getElementById("system-cpu")' in splash_js, "splash observes the existing System readiness value")
    check("MutationObserver" in splash_js, "readiness observation creates no polling loop")
    check("window.setTimeout(dismiss, 4500)" in splash_js, "splash has a failure-safe timeout")
    check(not any(token in splash_js for token in ("fetch(", "/api/", "XMLHttpRequest", "systemctl")), "splash creates no API or service authority")
    check(not any(token in header_css for token in (".tabs", ".tab-button", ".tab-page")), "header theme does not alter navigation")
    check(".topbar" not in navigation_css, "navigation theme remains independent from the header")

    duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
    check(not duplicates, "header release introduces no duplicate element IDs")

    print("PASS: v0.54.0v-r2 compact header and startup splash validation complete")


if __name__ == "__main__":
    main()
