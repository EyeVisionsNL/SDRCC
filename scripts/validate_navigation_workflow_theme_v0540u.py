#!/usr/bin/env python3
"""Validate SDRCC v0.54.0u workflow order and navigation-only theme."""

from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ORDER = [
    "system",
    "radio",
    "radio-view",
    "traffic-voice",
    "hf-monitor",
    "mission",
    "mission-planner",
    "images",
    "history",
    "mission-analytics",
    "logs",
]


class DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tabs = False
        self.buttons: list[tuple[str, set[str]]] = []
        self.pages: list[tuple[str, set[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "nav" and "tabs" in classes:
            self.in_tabs = True
        elif tag == "button" and self.in_tabs and "tab-button" in classes:
            tab = values.get("data-tab")
            if tab:
                self.buttons.append((tab, classes))
        elif tag == "section" and "tab-page" in classes:
            page_id = values.get("id") or ""
            if page_id.startswith("tab-"):
                self.pages.append((page_id[4:], classes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav" and self.in_tabs:
            self.in_tabs = False


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    if os.environ.get("FAKE_NAVIGATION_THEME_FAIL") == "1":
        raise RuntimeError("injected navigation theme validation failure")

    template = read("dashboard/templates/index.html")
    theme = read("dashboard/static/css/navigation_theme.css")
    tabs_js = read("dashboard/static/js/tabs.js")

    parser = DashboardParser()
    parser.feed(template)

    check([tab for tab, _classes in parser.buttons] == EXPECTED_ORDER, "tab buttons follow the approved operator workflow")
    check(len(parser.buttons) == len(EXPECTED_ORDER), "all eleven tab buttons remain unique")
    check(
        [tab for tab, classes in parser.buttons if "active" in classes] == ["system"],
        "System is the only initially active tab button",
    )
    check(
        [page for page, classes in parser.pages if "active" in classes] == ["system"],
        "System is the only initially visible tab page",
    )
    check(set(page for page, _classes in parser.pages) == set(EXPECTED_ORDER), "every tab button retains its matching page")
    check('/static/css/navigation_theme.css?v=0.56.0b' in template, "navigation theme uses the v0.56.0b cache key")

    for token, label in (
        ("grid-template-columns: repeat(11, minmax(0, 1fr))", "wide navigation uses eleven equal columns"),
        ('.tab-button[data-tab="system"]', "System has a scoped accent"),
        ('.tab-button[data-tab="mission"]', "Mission Control has a scoped accent"),
        ('.tab-button[data-tab="images"]', "Mission Operations has a scoped accent"),
        ('.tab-button[data-tab="traffic-voice"]', "Traffic Voice has a scoped accent"),
        ('.tab-button[data-tab="hf-monitor"]', "HF Monitor has a scoped accent"),
        (".tab-button.active", "active tab state is explicit"),
        (".tab-button:focus-visible", "keyboard focus state is explicit"),
        ("@media (max-width: 1100px)", "navigation has a narrow-screen grid"),
    ):
        check(token in theme, label)

    check(".topbar" not in theme, "navigation theme does not alter the banner")
    check(".tab-page" not in theme, "navigation theme does not alter page visibility")
    check(not any(token in theme for token in ("/api/", "fetch(", "systemctl")), "navigation theme contains no runtime coupling")
    check(
        'const tab = button.dataset.tab;' in tabs_js
        and 'document.getElementById(`tab-${tab}`)' in tabs_js
        and 'button.classList.add("active")' in tabs_js,
        "existing tab switching path is retained",
    )
    check("SDRCC – Flexible Ground Station" in template and "Listen · Decode · Analyze · Share" in template, "current banner content remains present")

    print("PASS: v0.54.0u workflow navigation theme validation complete")


if __name__ == "__main__":
    main()
