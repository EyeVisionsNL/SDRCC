#!/usr/bin/env python3
"""SDRCC local graphical installer, wrapping the supported Bash installation.

Python standard library only. All radio provisioning is still performed by
install.sh; this module manages UI, live progress and AIS wizard confirmation.
"""
from __future__ import annotations

import argparse
import codecs
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The installed GUI lives in scripts/install/, but --preview is also
# distributed as a standalone file in /tmp. Resolve safely in both cases.
SCRIPT_FILE = Path(__file__).resolve()
ROOT = SCRIPT_FILE.parents[2] if len(SCRIPT_FILE.parents) >= 3 else SCRIPT_FILE.parent
PROMPT = "Enter = check saved configuration; d = defer AIS setup:"
MARKERS = {
    "==> Preflight": ("Checking the system", 5),
    "==> Base Ubuntu dependencies": ("Installing Ubuntu dependencies", 15),
    "==> Optional SDRCC features": ("Preparing your feature selection", 29),
    "==> External runtime dependency check": ("Preparing radio applications", 31),
    "==> Install SDRCC source": ("Installing SDRCC", 46),
    "==> Python environment": ("Installing Python dependencies", 51),
    "==> Audio processing and ISS SSTV decoder": ("Preparing audio and SSTV decoding", 57),
    "==> Groups": ("Configuring hardware access", 63),
    "==> Install systemd units": ("Registering system services", 72),
    "==> Station setup": ("Preparing station settings", 78),
    "==> Detect receivers": ("Detecting RTL-SDR receivers", 83),
    "==> Start and validate SDRCC": ("Checking the dashboard", 87),
    "==> Final AIS-catcher setup": ("AIS-catcher web wizard", 94),
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>SDRCC — Installer</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif;background:#081625;color:#e8f4ff}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at top right,#123a5a 0,#081625 70%)}
main{max-width:930px;margin:35px auto;padding:0 18px}
header{display:flex;align-items:center;gap:15px;margin-bottom:22px}
.logo{height:56px;width:56px;background:#193b5b;border:1px solid #37789d;border-radius:15px;display:grid;place-items:center;font-size:30px}
h1{margin:0;font-size:1.8rem}
.subtitle{color:#9db8cf;margin-top:5px}
.panel{background:#0e243a;border:1px solid #2b5570;border-radius:16px;padding:24px;box-shadow:0 12px 35px #0003}
h2{margin:0 0 10px;font-size:1.25rem}
p,.hint{color:#b9ccde;line-height:1.6}
.choices{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:22px 0}
.choice{display:flex;gap:11px;align-items:start;cursor:pointer;border:1px solid #355d7b;background:#122e46;border-radius:12px;padding:16px;min-height:110px}
.choice:has(input:checked){border-color:#43c0e9;background:#173d59}
.choice input{width:20px;height:20px;accent-color:#41b9e5;flex:none;margin-top:1px}
.choice strong{display:block;margin-bottom:5px}
.choice small{display:block;color:#abc3d4;line-height:1.45}
button{border:0;border-radius:10px;background:#37bee6;color:#082337;font-weight:750;padding:13px 19px;font-size:.95rem;cursor:pointer}
button:hover{background:#78ddf7}
button:disabled{opacity:.45;cursor:not-allowed}
button.secondary{background:#204762;color:#ecf8ff;border:1px solid #48718b}
.preview-label{display:inline-block;background:#12334d;color:#7fe0ff;border:1px solid #42afd2;padding:5px 10px;border-radius:8px;font-size:.8rem;font-weight:750;margin-top:8px}
.preview-panel{background:#172f49;border-color:#3e8aab}
.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}
.hidden{display:none!important}
.track{height:12px;border-radius:99px;background:#23435b;overflow:hidden;margin:18px 0 8px}
.fill{height:100%;width:0;background:#3cbce7;transition:width .2s}
pre{background:#061522;border:1px solid #2a4860;border-radius:10px;padding:14px;overflow:auto;height:240px;color:#c3dbea;font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.note{padding:13px 15px;border:1px solid #446b81;border-radius:10px;background:#123049;color:#d3e7f5}
.note strong{color:#f7c782}
.status{font-size:1.08rem;color:#75ddfb;font-weight:700;min-height:1.5em}
.row{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
footer{margin:17px 0;text-align:center;color:#87a7be;font-size:.84rem}
@media(max-width:540px){main{margin:16px auto}.panel{padding:18px}}
</style></head>
<body><main>
<header><div class="logo">📡</div><div><h1>SDRCC Installer</h1>
<div class="subtitle">Listen · Decode · Analyze · Share</div>
<div class="preview-label hidden" id="modeBadge">PREVIEW MODE · NO CHANGES</div></div></header>
<section class="panel" id="selection">
<h2>Choose your SDRCC features</h2>
<p>Select the functions you want. Home Position and receiver assignments can
be configured later in SDRCC.</p>
<div class="choices">
<label class="choice"><input id="satellite" type="checkbox" checked><span>
<strong>🛰 Satellites</strong><small>SatDump, satellite reception and missions</small></span></label>
<label class="choice"><input id="traffic_voice" type="checkbox" checked><span>
<strong>🎙 Traffic Voice</strong><small>Marine VHF, ATIS and aviation audio</small></span></label>
<label class="choice"><input id="radio_receiver" type="checkbox" checked><span>
<strong>📻 Radio Receiver</strong><small>Direct tuning, spectrum and waterfall</small></span></label>
</div>
<div class="note" id="introNote">The existing AIS-catcher wizard opens automatically near the end
of installation. <strong>Keep this terminal open</strong>: Ubuntu might ask for your
sudo password there.</div>
<div class="actions"><button id="start">Install SDRCC</button></div>
</section>
<section class="panel hidden" id="progress">
<div class="row"><h2>Installation progress</h2><span id="pct">0%</span></div>
<div class="status" id="stage">Preparing…</div>
<div class="track"><div class="fill" id="bar"></div></div>
<p class="hint" id="progressHint">Live installer output. Progress is based on installation stages,
not a precise time estimate.</p>
<div id="aisPanel" class="note hidden">
<div id="aisExplanation"><strong>Finish setup in the AIS-catcher browser tab</strong>.
Choose one RTL-SDR input and save with <strong>Save &amp; Close</strong>.
<strong>An SDR serial number is optional</strong>; you can assign or change the
receiver binding later in SDRCC. Then click <strong>Verify AIS setup</strong> here.</div>
<div class="actions">
<button id="verify" disabled>Verify AIS setup</button>
<button class="secondary" id="defer" disabled>Finish without AIS setup</button>
</div>
<p id="aisHelp" class="hint">The wizard is starting…</p>
</div>
<pre id="logs" role="log" aria-live="off"></pre>
<div class="actions"><button id="finish" class="secondary hidden">Close installer</button></div>
</section>
<footer>SDRCC · Local installer · 127.0.0.1 only</footer>
</main>
<script>
"use strict";
const token = __SDRCC_TOKEN__;
const preview = __SDRCC_PREVIEW__;
if (preview) {
 byPreviewSetup();
}
function byPreviewSetup() {
 const el = id => document.getElementById(id);
 el("modeBadge").classList.remove("hidden");
 el("start").textContent = "Start preview";
 el("introNote").textContent = "Safe preview: no software is installed, no services are started or stopped, and no settings are changed. All progress and AIS steps are simulated.";
 el("introNote").classList.add("preview-panel");
 el("progressHint").textContent = "Simulation only — this progress is not a real SDRCC installation.";
 el("aisExplanation").textContent = "Simulation only: this is a preview of the AIS-catcher confirmation step. No actual wizard opens, and no receiver or AIS configuration is changed.";
 el("verify").textContent = "Simulate AIS confirmed";
 el("defer").textContent = "Simulate AIS deferred";
}
const api = async (path, data) => {
 const opts = {headers: {"X-SDRCC-Token": token}, cache: "no-store"};
 if (data !== undefined) {
   opts.method = "POST";
   opts.headers["Content-Type"] = "application/json";
   opts.body = JSON.stringify(data);
 }
 const res = await fetch(path, opts);
 const body = await res.json();
 if (!res.ok) throw new Error(body.error || "Request failed");
 return body;
};
const by = id => document.getElementById(id);
let lastLogs = "";
let finished = false;
let closing = false;
async function refresh() {
 if (closing) return;
 try {
  const s = await api("/api/status");
  if (!s.started) return;
  by("selection").classList.add("hidden");
  by("progress").classList.remove("hidden");
  by("stage").textContent = s.stage;
  by("pct").textContent = String(s.percent) + "%";
  by("bar").style.width = String(s.percent) + "%";
  const newLogs = s.lines.join("\\n");
  if (lastLogs !== newLogs) {
   const log = by("logs");
   const bottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 35;
   log.textContent = newLogs;
   if (bottom) log.scrollTop = log.scrollHeight;
   lastLogs = newLogs;
  }
  by("aisPanel").classList.toggle("hidden", !s.ais_stage || s.finished);
  by("verify").disabled = !s.awaiting_ais;
  by("defer").disabled = !s.awaiting_ais;
  by("aisHelp").textContent = preview ?
   (s.awaiting_ais ? "Test either button; this will not read or write AIS settings." : "Previewing the AIS step…") :
   (s.awaiting_ais ? "After Save & Close, click Verify. No SDR serial number is required." :
    "Preparing the AIS-catcher wizard or checking the saved configuration…");
  finished = s.finished;
  by("finish").classList.toggle("hidden", !finished);
 } catch (error) {
  by("stage").textContent = "Connection lost: " + error.message;
 }
}
by("start").onclick = async () => {
 by("start").disabled = true;
 try {
  await api("/api/start", {
   satellite: by("satellite").checked,
   traffic_voice: by("traffic_voice").checked,
   radio_receiver: by("radio_receiver").checked
  });
  by("selection").classList.add("hidden");
  by("progress").classList.remove("hidden");
  await refresh();
 } catch (error) { alert(error.message); by("start").disabled = false; }
};
by("verify").onclick = async () => {
 try { await api("/api/ais/check", {}); await refresh(); }
 catch (error) { alert(error.message); }
};
by("defer").onclick = async () => {
 if (!preview && !confirm("Continue without finishing AIS-catcher setup? You can resume it later.")) return;
 try { await api("/api/ais/defer", {}); await refresh(); }
 catch (error) { alert(error.message); }
};
by("finish").onclick = async () => {
 try { await api("/api/close", {}); closing = true; by("stage").textContent = "Installer closed. You can close this tab."; }
 catch (error) { alert(error.message); }
};
setInterval(refresh, 750);
refresh();
</script></body></html>
"""


class InstallState:
    def __init__(self, preview=False):
        self.preview = preview
        self.lock = threading.RLock()
        self.started = False
        self.finished = False
        self.awaiting_ais = False
        self.ais_stage = False
        self.exit_code = None
        self.percent = 0
        self.stage = "Choose features"
        self.lines = deque(maxlen=420)
        self.process = None

    def snapshot(self):
        with self.lock:
            return {
                "preview": self.preview,
                "started": self.started,
                "finished": self.finished,
                "awaiting_ais": self.awaiting_ais,
                "ais_stage": self.ais_stage,
                "exit_code": self.exit_code,
                "percent": self.percent,
                "stage": self.stage,
                "lines": list(self.lines),
            }

    def add_line(self, line):
        clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line).rstrip()
        if not clean:
            return
        with self.lock:
            self.lines.append(clean[-5000:])
            for marker, (stage, pct) in MARKERS.items():
                if marker in clean:
                    self.stage = stage
                    self.percent = max(self.percent, pct)
                    if marker == "==> Final AIS-catcher setup":
                        self.ais_stage = True

    def start(self, choices):
        if not isinstance(choices, dict) or any(type(choices.get(key)) is not bool for key in
                                                 ("satellite", "traffic_voice", "radio_receiver")):
            raise ValueError("Select the three installer options.")
        with self.lock:
            if self.started:
                raise ValueError("The installation has already started.")
            self.started = True
            self.stage = "Starting preview" if self.preview else "Starting Bash installer"
            self.lines.append("Selected options: " + ", ".join(
                k + "=" + ("yes" if choices[k] else "no")
                for k in ("satellite", "traffic_voice", "radio_receiver")))
        runner = self._simulate if self.preview else self._run
        thread = threading.Thread(target=runner, args=(choices,), daemon=True)
        thread.start()

    def _simulate(self, choices):
        """Purely in-memory preview. No shell, filesystem writes or service changes."""
        self.add_line("[PREVIEW] Demo only — your SDRCC installation stays untouched.")
        for marker in (
            "==> Preflight",
            "==> Base Ubuntu dependencies",
            "==> Optional SDRCC features",
            "==> Install SDRCC source",
            "==> Python environment",
            "==> Install systemd units",
            "==> Station setup",
            "==> Detect receivers",
            "==> Start and validate SDRCC",
            "==> Final AIS-catcher setup",
        ):
            with self.lock:
                if self.finished:
                    return
            self.add_line("[PREVIEW] " + marker)
            time.sleep(0.38)
        self.add_line("[PREVIEW] AIS wizard would open here during a real installation.")
        self.add_line("[PREVIEW] Try Simulate AIS confirmed or Simulate AIS deferred.")
        with self.lock:
            self.awaiting_ais = True
            self.stage = "Simulated AIS-catcher confirmation"

    def _run(self, choices):
        if self.preview:
            raise RuntimeError("Preview mode must never execute the real installer.")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        for key, value in choices.items():
            env["SDRCC_FEATURE_" + key.upper()] = "1" if value else "0"
        try:
            process = subprocess.Popen(
                ["bash", str(ROOT / "install.sh"), "--gui-choices"],
                cwd=ROOT, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0)
            with self.lock:
                self.process = process
            partial = ""
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                for char in decoder.decode(chunk):
                    if char == "\r":
                        continue
                    if char == "\n":
                        self.add_line(partial)
                        partial = ""
                    else:
                        partial += char
                        if partial.endswith(PROMPT):
                            self.add_line(partial)
                            partial = ""
                            with self.lock:
                                self.awaiting_ais = True
                        elif len(partial) > 10000:
                            self.add_line(partial)
                            partial = ""
            if partial:
                self.add_line(partial)
            result = process.wait()
        except (OSError, ValueError) as error:
            self.add_line("FAIL: " + str(error))
            result = 1
        with self.lock:
            self.finished = True
            self.awaiting_ais = False
            self.exit_code = result
            if result == 0:
                self.percent = 100
                if any("AIS setup deferred." in line or "DEFERRED: AIS is not ready" in line
                       for line in self.lines):
                    self.stage = "SDRCC installed · AIS setup deferred"
                    self.lines.append("Resume AIS later with: bash install.sh --ais-setup")
                else:
                    self.stage = "Installation completed"
                self.lines.append("Open http://127.0.0.1:8080/ for SDRCC.")
            else:
                self.stage = "Installation failed (exit " + str(result) + ")"
                self.lines.append("Installation stopped. Check the output above; do not remove files manually.")

    def ais_reply(self, answer):
        with self.lock:
            if self.preview:
                if self.finished or not self.awaiting_ais:
                    raise ValueError("The simulated AIS step is not ready.")
                self.awaiting_ais = False
                self.finished = True
                self.exit_code = 0
                self.percent = 100
                self.stage = "Preview complete — nothing was changed"
                result = "simulated AIS deferred" if answer == "d" else "simulated AIS confirmed"
                self.lines.append("[PREVIEW] " + result + "; no AIS configuration was inspected or modified.")
                return
            if self.finished or not self.awaiting_ais or not self.process or not self.process.stdin:
                raise ValueError("The AIS-catcher wizard is not waiting for confirmation.")
            self.process.stdin.write((answer + "\n").encode("utf-8"))
            self.process.stdin.flush()
            self.awaiting_ais = False
            self.stage = "Verifying AIS-catcher setup" if not answer else "Deferring AIS-catcher setup"


def main(argv=None):
    parser = argparse.ArgumentParser(description="SDRCC local installer interface")
    parser.add_argument("--preview", action="store_true",
                        help="Safe UI simulation with no installation or configuration changes")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        print("Run the installer as your normal Ubuntu account, not root.", file=sys.stderr)
        return 2
    if not args.preview and not (ROOT / "install.sh").is_file():
        print("Full installation requires the SDRCC repository. Use --preview "
              "for the standalone GUI demonstration.", file=sys.stderr)
        return 2
    if not args.preview and (ROOT / "venv/bin/python").exists() and (ROOT / "VERSION").exists():
        print("SDRCC is already installed. Use System → Advanced Maintenance for updates.", file=sys.stderr)
        print("For a new GUI installation use a clean install; the installer never overwrites it.", file=sys.stderr)
        return 2
    state = InstallState(preview=args.preview)
    token = secrets.token_urlsafe(32)
    httpd = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def allowed_host(self):
            return self.headers.get("Host", "") == "127.0.0.1:" + str(httpd.server_port)

        def authorized(self):
            origin = self.headers.get("Origin")
            return (self.allowed_host()
                    and self.headers.get("X-SDRCC-Token") == token
                    and (not origin or origin == "http://127.0.0.1:" + str(httpd.server_port)))

        def json_reply(self, code, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.allowed_host():
                self.send_error(403)
                return
            if self.path == "/":
                page = (PAGE.replace("__SDRCC_TOKEN__", json.dumps(token))
                        .replace("__SDRCC_PREVIEW__", "true" if args.preview else "false")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/api/status" and self.authorized():
                self.json_reply(200, state.snapshot())
            else:
                self.send_error(404)

        def do_POST(self):
            if not self.authorized():
                self.json_reply(403, {"error": "Access denied."})
                return
            size = self.headers.get("Content-Length", "0")
            if not size.isdecimal() or int(size) > 4096:
                self.json_reply(400, {"error": "Invalid request size."})
                return
            try:
                data = json.loads(self.rfile.read(int(size)) or b"{}")
                if self.path == "/api/start":
                    state.start(data)
                elif self.path == "/api/ais/check":
                    state.ais_reply("")
                elif self.path == "/api/ais/defer":
                    state.ais_reply("d")
                elif self.path == "/api/close":
                    if not state.snapshot()["finished"]:
                        raise ValueError("Installation is still running.")
                    threading.Thread(target=httpd.shutdown, daemon=True).start()
                else:
                    self.json_reply(404, {"error": "Unknown action."})
                    return
                self.json_reply(200, {"ok": True})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.json_reply(400, {"error": str(error)})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:" + str(httpd.server_port) + "/"
    print(("SDRCC SAFE PREVIEW: " if args.preview else "SDRCC graphical installer: ") + url, flush=True)
    if args.preview:
        print("PREVIEW ONLY: no installation, no sudo, no services, no settings changes.", flush=True)
    else:
        print("Keep this terminal open for any Ubuntu sudo password prompts.", flush=True)
    if shutil.which("xdg-open"):
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            print("Open the local address above manually in your browser.", flush=True)
    else:
        print("Open the local address above manually in your browser.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        with state.lock:
            process = state.process
        if process and process.poll() is None:
            print("\nInterrupting the active installer. Check system state before retrying.")
            # Keep the installer in our terminal's process group so sudo
            # retains /dev/tty access for interactive password prompts.
            # Ctrl+C from the terminal is already delivered to the child.
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
    finally:
        httpd.server_close()
    return state.exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
