#!/usr/bin/env python3
"""Optional CPU-only Local AI foundation. No receiver control or cloud inference."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request

import yaml
from flask import Blueprint, jsonify, request
from core import features

ROOT = features.PROJECT_ROOT
AI_DIR = ROOT / "data" / "local_ai"
MODEL = "Qwen3-4B-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/a9a60d0/Qwen3-4B-Q4_K_M.gguf"
MODEL_SHA = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
ENGINE = "b12711"
ARCHIVES = {
    "x86_64": ("x64", "ba1b86ce6e6ac6e8c850fcc35cad1683b3d6e21d4f1de472d289df42119652d8"),
    "aarch64": ("arm64", "b5e7679762942bb9f34482cd8e69b719b26546ed2d16a005cf31119fea8676c2"),
}
GIB = 1024 ** 3
MEMORY_LIMIT = 5 * GIB
LOCK = threading.Lock()
_progress = ""
_error = ""
bp = Blueprint("local_ai", __name__)


def enabled():
    return features.get_features().get("local_ai", False) is True


def set_enabled(value):
    path = features.FEATURES_CONFIG
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict) or not isinstance(data.setdefault("features", {}), dict):
        raise RuntimeError("Invalid feature configuration.")
    data["features"]["local_ai"] = bool(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".features-", delete=False) as f:
        temp = Path(f.name)
        try:
            yaml.safe_dump(data, f, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def receipt():
    return {"engine": ENGINE, "model_sha256": MODEL_SHA, "architecture": platform.machine()}


def binary():
    candidates = list((AI_DIR / "engine").rglob("llama-server"))
    if len(candidates) != 1 or not candidates[0].is_file():
        raise RuntimeError("Local AI engine not installed.")
    return candidates[0]


def installed():
    if AI_DIR.is_symlink():
        return False
    try:
        return (json.loads((AI_DIR / "receipt.json").read_text()) == receipt()
                and (AI_DIR / MODEL).is_file() and os.access(binary(), os.X_OK))
    except (OSError, ValueError, RuntimeError):
        return False


def hardware():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return values.get("MemTotal", 0), values.get("MemAvailable", 0)


def preflight(install=False):
    if platform.system() != "Linux" or platform.machine() not in ARCHIVES:
        raise RuntimeError("Local AI requires a supported Linux x86-64 or arm64 system.")
    total, available = hardware()
    if total < 7 * GIB or (os.cpu_count() or 1) < 2:
        raise RuntimeError("Local AI requires at least 8 GB RAM and two CPU threads.")
    if available < 6 * GIB:
        raise RuntimeError("Local AI paused: less than 6 GiB RAM available.")
    if os.getloadavg()[0] >= (os.cpu_count() or 1) * 0.75:
        raise RuntimeError("Local AI paused: system load is high. Try again later.")
    if not shutil.which("prlimit") or not shutil.which("nice"):
        raise RuntimeError("Local AI requires prlimit and nice.")
    if install and shutil.disk_usage(ROOT).free < 5 * GIB:
        raise RuntimeError("At least 5 GiB free disk space is required.")


def download(url, dest, expected, maximum):
    digest = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": "SDRCC-Local-AI/0.80"})
    with urllib.request.urlopen(req, timeout=45) as response, dest.open("xb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise RuntimeError("Unexpected download size.")
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError("Local AI download SHA-256 verification failed.")


def install_assets():
    global _progress
    if AI_DIR.is_symlink():
        raise RuntimeError("Refusing a symbolic Local AI directory.")
    if installed():
        set_enabled(True)
        return
    preflight(install=True)
    if AI_DIR.exists():
        raise RuntimeError("Incomplete or outdated AI installation. Remove it before reinstalling.")
    AI_DIR.parent.mkdir(parents=True, exist_ok=True)
    arch, engine_hash = ARCHIVES[platform.machine()]
    asset = f"llama-{ENGINE}-bin-ubuntu-{arch}.tar.gz"
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE}/{asset}"
    with tempfile.TemporaryDirectory(prefix=".local-ai-", dir=AI_DIR.parent) as temp:
        stage = Path(temp) / "ready"
        stage.mkdir()
        archive = Path(temp) / asset
        _progress = "Downloading and verifying llama.cpp..."
        download(url, archive, engine_hash, 512 * 1024 ** 2)
        _progress = "Extracting verified AI engine..."
        engine_dir = stage / "engine"
        engine_dir.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(engine_dir, filter="data")
        servers = list(engine_dir.rglob("llama-server"))
        if len(servers) != 1 or not os.access(servers[0], os.X_OK):
            raise RuntimeError("Verified engine archive did not contain an executable llama-server.")
        _progress = "Downloading and verifying Qwen3-4B (approximately 2.5 GB)..."
        download(MODEL_URL, stage / MODEL, MODEL_SHA, 3 * GIB)
        (stage / "receipt.json").write_text(json.dumps(receipt()), encoding="utf-8")
        os.replace(stage, AI_DIR)
    set_enabled(True)


def _worker():
    global _progress, _error
    try:
        install_assets()
    except Exception as exc:
        _error = str(exc)[:400]
    finally:
        _progress = ""
        LOCK.release()


def start_install():
    global _progress, _error
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("Local AI is busy.")
    _error = ""
    _progress = "Preparing Local AI..."
    try:
        threading.Thread(target=_worker, daemon=True, name="sdrcc-local-ai-install").start()
    except Exception:
        _progress = ""
        LOCK.release()
        raise


def local_request(port, key, path, payload=None, timeout=2):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Authorization": "Bearer " + key}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        conn.request("GET" if body is None else "POST", path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or response.status != 200:
            raise RuntimeError("Local AI engine is not ready or returned an error.")
        return json.loads(raw)
    finally:
        conn.close()


def infer(question):
    if not enabled() or not installed():
        raise RuntimeError("Install and enable Local AI first.")
    preflight()
    server = binary()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    key = secrets.token_hex(32)
    cmd = ["nice", "-n", "15", "prlimit", f"--as={MEMORY_LIMIT}", "--cpu=180:190", "--",
           str(server), "--model", str(AI_DIR / MODEL), "--host", "127.0.0.1",
           "--port", str(port), "--api-key", key, "--threads", "2",
           "--threads-batch", "2", "--ctx-size", "4096", "--parallel", "1",
           "--n-gpu-layers", "0", "--batch-size", "128", "--ubatch-size", "128",
           "--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}']
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LD_LIBRARY_PATH": str(server.parent)}
    process = subprocess.Popen(cmd, cwd=server.parent, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local AI engine exited during startup (possibly resource limits).")
            try:
                local_request(port, key, "/health")
                break
            except (OSError, ValueError, RuntimeError, http.client.HTTPException):
                time.sleep(0.5)
        else:
            raise RuntimeError("Local AI engine startup timed out.")
        result = local_request(port, key, "/v1/chat/completions", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are SDRCC Local AI. This foundation release has no access to live reception, history, system data, tools or receiver controls. Never claim otherwise. Answer in the user's language and say when you cannot verify something."},
                {"role": "user", "content": question},
            ],
            "max_tokens": 384, "temperature": 0.6, "stream": False,
        }, timeout=100)
        return result["choices"][0]["message"]["content"]
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def status():
    total, available = hardware()
    return {"enabled": enabled(), "installed": installed(), "busy": LOCK.locked(),
            "progress": _progress, "error": _error, "model": MODEL,
            "has_assets": AI_DIR.exists() or AI_DIR.is_symlink(),
            "engine": ENGINE, "ram_gib": round(total / GIB, 1),
            "available_gib": round(available / GIB, 1),
            "architecture": platform.machine()}


def change_allowed():
    # A JSON-only API prevents simple cross-origin HTML form submissions.
    # Do not grant CORS access; match the dashboard origin when supplied.
    origin = request.headers.get("Origin")
    return request.is_json and (not origin or origin == request.host_url.rstrip("/"))


@bp.get("/api/local-ai/status")
def api_status():
    return jsonify(status())


@bp.post("/api/local-ai/action")
def api_action():
    global _error
    if not change_allowed():
        return jsonify(error="Invalid request origin or format."), 403
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Invalid request."), 400
    action = body.get("action")
    try:
        if action == "install":
            start_install()
            return jsonify(status()), 202
        if action not in ("enable", "disable", "remove"):
            return jsonify(error="Unknown action."), 400
        if not LOCK.acquire(blocking=False):
            return jsonify(error="Local AI is busy."), 409
        try:
            if action == "enable":
                if not installed():
                    raise RuntimeError("Install Local AI first.")
                set_enabled(True)
            else:
                set_enabled(False)
                if action == "remove":
                    if AI_DIR.is_symlink():
                        raise RuntimeError("Refusing a symbolic Local AI directory.")
                    if AI_DIR.exists():
                        shutil.rmtree(AI_DIR)
            _error = ""
        finally:
            LOCK.release()
        return jsonify(status())
    except (OSError, RuntimeError, ValueError) as exc:
        return jsonify(error=str(exc)[:400]), 409


@bp.post("/api/local-ai/chat")
def api_chat():
    if not change_allowed():
        return jsonify(error="Invalid request origin or format."), 403
    body = request.get_json(silent=True)
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not 0 < len(question.strip()) <= 2000:
        return jsonify(error="Enter a question of 1–2000 characters."), 400
    if not LOCK.acquire(blocking=False):
        return jsonify(error="Local AI is busy."), 409
    try:
        return jsonify(answer=infer(question.strip()))
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, http.client.HTTPException) as exc:
        return jsonify(error=str(exc)[:400]), 503
    finally:
        LOCK.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", required=True)
    parser.parse_args()
    try:
        install_assets()
    except Exception as exc:
        print(f"Local AI installation incomplete: {exc}")
        raise SystemExit(1)
    print("Local AI installed and enabled.")
