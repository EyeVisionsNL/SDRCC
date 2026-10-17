"""Optional read-only SDRCC Emergency Monitor (v0.67.5).

Consumes local readsb/AIS-catcher observations without touching receiver ownership.
P2000 MQTT input and outbound Home Assistant notifications are opt-in.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

from core import config as station_config, event_bus, receiver_monitor

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "data" / "config" / "emergency_monitor.json"
STATE_FILE = ROOT / "data" / "state" / "emergency_monitor.json"
_lock = threading.RLock()
_worker: threading.Thread | None = None
_stop: threading.Event | None = None
_runtime: dict[str, Any] = {"mqtt": "OFF", "adsb": "OFF", "ais": "OFF", "p2000": "OFF", "last_error": ""}
_recent: dict[str, float] = {}
_presence: dict[str, int] = {}
_attributes: dict[str, tuple[float, dict]] = {}
_mqtt_client: Any = None
_last_settings = None
_DEFAULT = {
    "enabled": False,
    "radius_km": 20,
    "categories": {"lifeliner": True, "police_helicopter": True, "knrm": True,
                   "waterpolitie": True, "p2000": True},
    "p2000_input": False,
    "ha_notifications": False,
    "mqtt_host": "",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "mqtt_tls": False,
    "aircraft_hex": {"lifeliner": [], "police_helicopter": []},
    "vessel_mmsi": {"knrm": [], "waterpolitie": []},
}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic(path: Path, data: dict, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600 if private else 0o644)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def settings() -> dict:
    data = deepcopy(_DEFAULT)
    stored = _read_json(SETTINGS_FILE)
    for key in data:
        if key in ("categories", "aircraft_hex", "vessel_mmsi"):
            if isinstance(stored.get(key), dict):
                data[key].update(stored[key])
        elif key in stored:
            data[key] = stored[key]
    return data


def public_settings() -> dict:
    data = settings()
    data["mqtt_password_set"] = bool(data.pop("mqtt_password", ""))
    return data


def _identifiers(source: Any, pattern: str) -> list[str]:
    if isinstance(source, str):
        values = re.split(r"[\s,;]+", source.strip())
    elif isinstance(source, list):
        values = source
    else:
        raise ValueError("Identifiers must be a list or comma-separated string.")
    output = []
    for raw in values:
        value = str(raw).strip().upper()
        if not value:
            continue
        if not re.fullmatch(pattern, value):
            raise ValueError("Invalid monitored identifier: " + value[:30])
        if value not in output:
            output.append(value)
    if len(output) > 200:
        raise ValueError("Too many identifiers (maximum 200).")
    return output


def validate(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Settings must be a JSON object.")
    previous = settings()
    data = deepcopy(previous)
    for field in ("enabled", "p2000_input", "ha_notifications", "mqtt_tls"):
        if field in payload:
            if not isinstance(payload[field], bool):
                raise ValueError(field + " must be a boolean.")
            data[field] = payload[field]
    if "radius_km" in payload:
        radius = payload["radius_km"]
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or not 1 <= radius <= 100:
            raise ValueError("Detection radius must be between 1 and 100 km.")
        data["radius_km"] = int(radius)
    if "categories" in payload:
        value = payload["categories"]
        if not isinstance(value, dict) or set(value) - set(_DEFAULT["categories"]):
            raise ValueError("Unknown monitoring category.")
        for key, flag in value.items():
            if not isinstance(flag, bool):
                raise ValueError("Category selection must be true or false.")
            data["categories"][key] = flag
    if "mqtt_host" in payload:
        host = str(payload["mqtt_host"]).strip()
        if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9_.:-]*", host):
            raise ValueError("Invalid MQTT hostname.")
        data["mqtt_host"] = host
    if "mqtt_port" in payload:
        port = payload["mqtt_port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Invalid MQTT port.")
        data["mqtt_port"] = port
    if "mqtt_user" in payload:
        user = str(payload["mqtt_user"]).strip()
        if len(user) > 128:
            raise ValueError("MQTT username is too long.")
        data["mqtt_user"] = user
    if payload.get("clear_mqtt_password") is True:
        data["mqtt_password"] = ""
    elif payload.get("mqtt_password"):
        password = str(payload["mqtt_password"])
        if len(password) > 512:
            raise ValueError("MQTT password is too long.")
        data["mqtt_password"] = password
    for field, categories, pattern in (
        ("aircraft_hex", ("lifeliner", "police_helicopter"), r"[0-9A-F]{6}"),
        ("vessel_mmsi", ("knrm", "waterpolitie"), r"[0-9]{9}"),
    ):
        if field in payload:
            supplied = payload[field]
            if not isinstance(supplied, dict) or set(supplied) - set(categories):
                raise ValueError("Unknown identity category.")
            for name, value in supplied.items():
                data[field][name] = _identifiers(value, pattern)
    return data


def save(payload: Any) -> dict:
    data = validate(payload)
    with _lock:
        _atomic(SETTINGS_FILE, data, private=True)
    sync_worker()
    return public_settings()


def distance_km(a: float, b: float, c: float, d: float) -> float:
    radius = 6371.0088
    x, y = math.radians(float(a)), math.radians(float(c))
    delta = math.radians(float(d) - float(b))
    h = math.sin((y-x)/2)**2 + math.cos(x)*math.cos(y)*math.sin(delta/2)**2
    return 2*radius*math.asin(min(1.0, math.sqrt(max(0.0, h))))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def classify_aircraft(item: dict, data: dict) -> str | None:
    hex_id = str(item.get("hex") or "").strip().upper()
    callsign = str(item.get("flight") or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{6}", hex_id):
        return None
    if hex_id in data["aircraft_hex"]["lifeliner"] or re.fullmatch(r"LIFELN[1-9]", callsign):
        return "lifeliner"
    if hex_id in data["aircraft_hex"]["police_helicopter"]:
        return "police_helicopter"
    return None


def classify_vessel(item: dict, data: dict) -> str | None:
    mmsi = str(item.get("mmsi") or "").strip()
    if mmsi.endswith(".0"):
        mmsi = mmsi[:-2]
    if not re.fullmatch(r"[0-9]{9}", mmsi):
        return None
    if mmsi in data["vessel_mmsi"]["knrm"]:
        return "knrm"
    if mmsi in data["vessel_mmsi"]["waterpolitie"]:
        return "waterpolitie"
    return None


def _load_history() -> dict:
    state = _read_json(STATE_FILE)
    return {
        "history": (state.get("history") or [])[-50:],
        "last_sent": state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {},
    }


def _store_event(event: dict, *, send_mqtt: bool = True) -> None:
    with _lock:
        state = _load_history()
        state["history"] = ([event] + state["history"])[:50]
        state["last_sent"] = {key: val for key, val in _recent.items() if time.time()-val < 86400}
        _atomic(STATE_FILE, state)
        client = _mqtt_client
        cfg = settings()
    try:
        event_bus.publish_info("EMERGENCY", event["title"], event.get("detail", ""), data={
            "source": event["source"], "category": event["category"], "distance_km": event.get("distance_km")})
    except Exception:
        pass
    if send_mqtt and cfg["ha_notifications"] and client is not None:
        try:
            client.publish("sdrcc/emergency/events", json.dumps(event), qos=1, retain=False)
        except Exception as error:
            with _lock:
                _runtime["last_error"] = "MQTT publish failed: " + str(error)[:160]


def _target_event(source: str, category: str, identity: str, label: str, distance: float, data: dict) -> None:
    key = source + ":" + identity
    now = time.time()
    if distance > float(data["radius_km"]) + 2:
        _presence.pop(key, None)
        return
    if distance > float(data["radius_km"]):
        return
    _presence[key] = min(_presence.get(key, 0) + 1, 3)
    if _presence[key] < 2 or now - _recent.get(key, 0) < 1800:
        return
    _recent[key] = now
    event = {
        "id": hashlib.sha256((key + ":" + str(now)).encode()).hexdigest()[:16],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source, "category": category, "kind": "nearby_detected",
        "title": category.replace("_", " ").title() + " nearby",
        "detail": label + " detected within " + str(data["radius_km"]) + " km.",
        "identity": identity, "label": label,
        "distance_km": round(distance, 1), "radius_km": data["radius_km"],
    }
    _store_event(event)


def _poll_positions(data: dict) -> None:
    home = station_config.get_home_position()
    home_lat, home_lon = home["latitude"], home["longitude"]
    payload, source = receiver_monitor._read_json_file(receiver_monitor.READSB_AIRCRAFT_FILES)
    fresh = False
    if source:
        try:
            fresh = time.time() - Path(source).stat().st_mtime <= 5
        except OSError:
            pass
    with _lock:
        _runtime["adsb"] = "LIVE" if fresh else "UNAVAILABLE"
    if fresh and isinstance(payload, dict):
        for item in payload.get("aircraft", []):
            if not isinstance(item, dict):
                continue
            category = classify_aircraft(item, data)
            if not category or not data["categories"].get(category):
                continue
            lat, lon = _number(item.get("lat")), _number(item.get("lon"))
            age = _number(item.get("seen_pos"))
            if lat is None or lon is None or age is None or not 0 <= age <= 30 or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                continue
            identity = str(item["hex"]).strip().upper()
            flight = str(item.get("flight") or identity).strip()
            _target_event("adsb", category, identity, flight, distance_km(home_lat, home_lon, lat, lon), data)

    ships, _ = receiver_monitor._read_ais_ships()
    with _lock:
        _runtime["ais"] = "LIVE" if ships is not None else "UNAVAILABLE"
    if ships is None:
        return
    for item in receiver_monitor._extract_list(ships, ("ships", "vessels", "targets", "data")):
        category = classify_vessel(item, data)
        if not category or not data["categories"].get(category):
            continue
        age = receiver_monitor._first_number(item, ("last_signal", "last_signal_seconds", "age"))
        validated = item.get("validated")
        lat = receiver_monitor._first_number(item, ("lat", "latitude"))
        lon = receiver_monitor._first_number(item, ("lon", "longitude"))
        if age is None or not 0 <= age <= 120 or (validated is not None and str(validated) not in ("1", "True", "true")):
            continue
        if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        mmsi = str(item.get("mmsi")).replace(".0", "")
        label = str(item.get("shipname") or item.get("name") or mmsi).strip()[:80]
        _target_event("ais", category, mmsi, label, distance_km(home_lat, home_lon, lat, lon), data)


def _p2000_event(sensor: str, payload: str) -> None:
    data = settings()
    if not data["enabled"] or not data["p2000_input"] or not data["categories"]["p2000"]:
        return
    info = _attributes.get(sensor)
    if info is None or time.monotonic() - info[0] > 90:
        return
    attributes = info[1]
    received = str(attributes.get("time received") or "")[:32]
    digest = hashlib.sha256((sensor + received + payload).encode("utf-8")).hexdigest()[:16]
    key = "p2000:" + digest
    now = time.time()
    if now - _recent.get(key, 0) < 86400:
        return
    _recent[key] = now
    name = {"2002": "GRIP", "2003": "Lifeliner", "2004": "Regional", "2005": "KNRM"}.get(sensor, "P2000")
    event = {
        "id": digest, "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "p2000", "category": "p2000", "kind": "dispatch",
        "title": "P2000 " + name,
        "detail": "Dispatch received by the existing P2000 RTL-SDR receiver.",
        "identity": sensor, "priority": str(attributes.get("priority") or "")[:20],
    }
    _store_event(event, send_mqtt=False)  # Existing HA alerts already consume P2000; no duplicate HA push.


def _start_mqtt(data: dict) -> None:
    global _mqtt_client
    if not (data["p2000_input"] or data["ha_notifications"]):
        with _lock:
            _runtime["mqtt"] = "OFF"
            _runtime["p2000"] = "OFF"
        return
    if not data["mqtt_host"]:
        with _lock:
            _runtime["mqtt"] = "NOT CONFIGURED"
            _runtime["p2000"] = "NOT CONFIGURED"
        return
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        with _lock:
            _runtime["mqtt"] = "DEPENDENCY MISSING (paho-mqtt)"
        return
    client = mqtt.Client(client_id="sdrcc-emergency-" + str(os.getpid()), protocol=mqtt.MQTTv311)
    if data["mqtt_user"]:
        client.username_pw_set(data["mqtt_user"], data["mqtt_password"] or None)
    if data["mqtt_tls"]:
        client.tls_set()
    def connected(client, userdata, flags, rc, *args):
        with _lock:
            _runtime["mqtt"] = "CONNECTED" if rc == 0 else "ERROR " + str(rc)
            _runtime["p2000"] = "LISTENING" if rc == 0 and data["p2000_input"] else "OFF"
        if rc == 0:
            if data["p2000_input"]:
                for sid in ("2002", "2003", "2004", "2005"):
                    for suffix in ("attributes", "state"):
                        client.subscribe("homeassistant/sensor/p2000_rtlsdr/" + sid + "/" + suffix, qos=0)
            if data["ha_notifications"]:
                client.publish("sdrcc/emergency/status", "online", qos=1, retain=True)
    def disconnected(client, userdata, rc, *args):
        with _lock:
            _runtime["mqtt"] = "DISCONNECTED"
            _runtime["p2000"] = "UNAVAILABLE" if data["p2000_input"] else "OFF"
    def message(client, userdata, msg):
        try:
            segments = msg.topic.split("/")
            if len(segments) != 5 or segments[:3] != ["homeassistant", "sensor", "p2000_rtlsdr"]:
                return
            sensor, field = segments[-2:]
            if sensor not in {"2002", "2003", "2004", "2005"}:
                return
            decoded = msg.payload.decode("utf-8", "replace")
            if field == "attributes":
                parsed = json.loads(decoded)
                if isinstance(parsed, dict):
                    _attributes[sensor] = (time.monotonic(), parsed)
            elif field == "state":
                _p2000_event(sensor, decoded[:1200])
        except (ValueError, TypeError):
            return
    client.on_connect = connected
    client.on_disconnect = disconnected
    client.on_message = message
    if data["ha_notifications"]:
        client.will_set("sdrcc/emergency/status", "offline", qos=1, retain=True)
    try:
        client.connect(data["mqtt_host"], data["mqtt_port"], keepalive=60)
        _mqtt_client = client
        client.loop_start()
        with _lock:
            _runtime["last_error"] = ""
    except Exception as error:
        with _lock:
            _runtime["mqtt"] = "ERROR"
            _runtime["last_error"] = str(error)[:160]


def _close_mqtt() -> None:
    global _mqtt_client
    client = _mqtt_client
    _mqtt_client = None
    if client is not None:
        try:
            if settings()["ha_notifications"]:
                client.publish("sdrcc/emergency/status", "offline", qos=1, retain=True).wait_for_publish(timeout=2)
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass


def _loop(cancel: threading.Event) -> None:
    _presence.clear()
    try:
        state = _load_history()
        now = time.time()
        _recent.clear()
        _recent.update({str(k): float(v) for k, v in state["last_sent"].items()
                        if isinstance(v, (int, float)) and now - v < 86400})
        data = settings()
        try:
            _start_mqtt(data)
        except Exception as error:
            with _lock:
                _runtime["mqtt"] = "ERROR"
                _runtime["last_error"] = "Optional MQTT failed: " + str(error)[:140]
        # Warm up to avoid firing for all aircraft already in range during startup.
        cancel.wait(60)
        reconnect_after = time.monotonic() + 30
        while not cancel.is_set():
            if (data["p2000_input"] or data["ha_notifications"]) and _mqtt_client is None and time.monotonic() >= reconnect_after:
                _start_mqtt(data)
                reconnect_after = time.monotonic() + 30
            try:
                _poll_positions(data)
            except Exception as error:
                with _lock:
                    _runtime["last_error"] = str(error)[:160]
            cancel.wait(5)
    finally:
        _close_mqtt()
        with _lock:
            _runtime["adsb"] = "OFF"
            _runtime["ais"] = "OFF"
            _runtime["mqtt"] = "OFF"
            _runtime["p2000"] = "OFF"


def sync_worker() -> None:
    global _worker, _stop
    with _lock:
        if _stop is not None:
            _stop.set()
        previous = _worker
    if previous is not None and previous.is_alive():
        previous.join(timeout=8)
        if previous.is_alive():
            raise RuntimeError("Emergency Monitor worker did not stop cleanly.")
    with _lock:
        _worker, _stop = None, None
        if not settings()["enabled"]:
            _runtime.update({"adsb": "OFF", "ais": "OFF", "mqtt": "OFF", "p2000": "OFF"})
            return
        _stop = threading.Event()
        _worker = threading.Thread(target=_loop, args=(_stop,), daemon=True, name="sdrcc-emergency")
        _worker.start()


def snapshot() -> dict:
    with _lock:
        data = public_settings()
        state = _load_history()
        return {"ok": True, "settings": data, "runtime": dict(_runtime),
                "events": state["history"][:20], "running": bool(_worker and _worker.is_alive())}


def test_ha() -> dict:
    data = settings()
    if not data["enabled"] or not data["ha_notifications"]:
        raise ValueError("Enable Emergency Monitor and Home Assistant notifications first.")
    with _lock:
        client = _mqtt_client
        status = _runtime["mqtt"]
    if client is None or status != "CONNECTED":
        raise ValueError("MQTT broker is not connected.")
    event = {
        "id": "test-" + str(int(time.time() * 1000)),
        "timestamp": datetime.now(timezone.utc).isoformat(), "source": "test",
        "category": "test", "kind": "test", "title": "SDRCC Emergency Monitor test",
        "detail": "Test message from SDRCC, not a real emergency.", "test": True,
    }
    result = client.publish("sdrcc/emergency/events", json.dumps(event), qos=1, retain=False)
    if result.rc != 0:
        raise ValueError("MQTT publish failed with code " + str(result.rc))
    return {"ok": True, "message": "Test event sent to MQTT."}
