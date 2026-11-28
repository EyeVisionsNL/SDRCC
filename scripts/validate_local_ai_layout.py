#!/usr/bin/env python3
"""Render the actual Intelligence HTML/CSS in headless Chrome, without RF or AI."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "dashboard/templates/index.html").read_text()
SECTION = TEMPLATE.split('<section class="tab-page" id="tab-intelligence">', 1)[1].split('<script defer src="{{ url_for(\'static\', filename=\'js/local_ai.js\') }}', 1)[0]
CHROME = next((p for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if (p := shutil.which(name))), None)
assert CHROME, "Headless Chrome required for layout regression"

styles = []
for name in re.findall(r'href="/static/css/([^?"\s]+)(?:\?[^"]*)?"', TEMPLATE):
    css = ROOT / "dashboard/static/css" / name
    assert css.is_file(), name
    styles.append(f'<link rel="stylesheet" href="{css.as_uri()}">')

JS = """
const by = id => document.getElementById(id);
const assert = (condition, message) => { if (!condition) throw Error(message); };
const rect = node => node.getBoundingClientRect();
try {
    const ai = by("tab-intelligence"), answer = by("local-ai-answer");
    const source = by("local-ai-evidence"), settings = document.querySelector(".ai-settings");
    const chat = document.querySelector(".ai-chat");
    for (const b of ai.querySelectorAll("button,textarea,select")) b.disabled = false;
    by("local-ai-status").textContent = "Model and engine installed. · 15.4 GiB RAM · 9.1 GiB available · x86_64";
    by("local-ai-badge").textContent = "ENABLED";
    by("local-ai-toggle").textContent = "Disable Local AI";
    answer.textContent = Array.from({length: 7}, (_, i) => "Reception result " + (i + 1) + ": validated observations from the selected period.").join("\\n");
    source.hidden = false;
    assert(!source.open, "Evidence must be collapsed by default");
    assert(getComputedStyle(by("local-ai-transfer")).display === "none", "Inactive download should not occupy space");
    assert(getComputedStyle(by("local-ai-install")).display === "none", "Hidden install button occupies space");
    assert(rect(by("local-ai-send")).height <= 38, "Ask button too tall");
    assert(rect(by("local-ai-send")).width < 150, "Ask button too wide");
    assert(rect(answer).top < innerHeight * .78, "Answer begins below usable viewport: " + rect(answer).top + " / " + innerHeight);
    assert(rect(answer).top < rect(source).top, "Source data precedes answer");
    assert(answer.scrollHeight <= answer.clientHeight + 2, "Typical answer needs internal scrolling");
    if (innerWidth > 850) {
        assert(rect(settings).left > rect(chat).left, "Desktop settings not beside chat");
        assert(rect(answer).bottom <= innerHeight, "Typical desktop answer below fold: " + rect(answer).bottom + " / " + innerHeight);
    } else {
        assert(rect(settings).top >= rect(chat).bottom, "Narrow layout settings must follow chat");
    }
    assert(document.documentElement.scrollWidth <= innerWidth + 2, "Horizontal overflow");
    source.querySelector("summary").click();
    assert(source.open, "Evidence cannot be expanded");
    const observer = by("local-ai-inspect-view");
    assert(observer.hidden && getComputedStyle(observer).display === "none", "Observer must not enlarge Ask AI");
    assert(ai.querySelectorAll("[data-ai-view]").length === 3, "Missing Intelligence subviews");
    by("local-ai-ask-view").hidden = true;
    observer.hidden = false;
    assert(rect(by("local-ai-inspect-answer")).top < innerHeight * .85, "Observer answer starts too low");
    assert(document.documentElement.scrollWidth <= innerWidth + 2, "Observer horizontal overflow");
    document.body.dataset.result = "PASS";
} catch (error) {
    document.body.dataset.result = "FAIL";
    document.body.dataset.error = error.message;
}
"""
with tempfile.TemporaryDirectory() as temp:
    fixture = Path(temp) / "intelligence.html"
    fixture.write_text('<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + "".join(styles) + '</head><body><div style="height:180px"></div><main><section class="tab-page active" id="tab-intelligence">' + SECTION + '</main><script>' + JS + '</script></body></html>')
    for width, height in ((1649, 928), (1280, 800), (600, 900)):
        run = subprocess.run([CHROME, "--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--allow-file-access-from-files", "--no-first-run", f"--window-size={width},{height}", "--dump-dom", fixture.as_uri()], capture_output=True, text=True, timeout=30)
        result = re.search(r'<body[^>]*>', run.stdout)
        assert run.returncode == 0 and result and 'data-result="PASS"' in result.group(0), (width, height, result.group(0) if result else run.stderr[-1500:])
        print(f"PASS: {width}x{height} Intelligence layout")
