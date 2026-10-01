#!/usr/bin/env python3
"""ISS SSTV event settings and bounded Robot 36 / PD120 image decoding."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import importlib.metadata
import json
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
EVENT_FILE = STATE_DIR / "iss_sstv_event.json"
RECORDINGS_ROOT = (PROJECT_ROOT / "data" / "recordings" / "iss_voice").resolve()
DECODER_VERSION = "0.1.0"
MAX_IMAGES_PER_PASS = 12

MODES = {
    "robot36": "ROBOT_36",
    "pd120": "PD_120",
}

DEFAULT_EVENT = {
    "enabled": True,
    "name": "ISS SSTV Series 33 — Student Education",
    "start_utc": "2026-10-02T09:00:00Z",
    "end_utc": "2026-10-06T15:55:00Z",
    "frequency_hz": 437550000,
    "mode": "robot36",
    "transmission_seconds": 36,
    "pause_seconds": 120,
}


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO date/time with a timezone")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date/time with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("ISS SSTV event settings must be an object")
    name = str(raw.get("name", DEFAULT_EVENT["name"])).strip()
    if not name or len(name) > 100:
        raise ValueError("Event name must contain 1 to 100 characters")
    enabled = raw.get("enabled", DEFAULT_EVENT["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    start = _parse_utc(raw.get("start_utc", DEFAULT_EVENT["start_utc"]), "start_utc")
    end = _parse_utc(raw.get("end_utc", DEFAULT_EVENT["end_utc"]), "end_utc")
    if end <= start:
        raise ValueError("Event end must be later than event start")
    if (end - start).total_seconds() > 31 * 86400:
        raise ValueError("ISS SSTV event cannot be longer than 31 days")
    try:
        frequency = int(round(float(raw.get("frequency_hz", DEFAULT_EVENT["frequency_hz"]))))
    except (TypeError, ValueError) as exc:
        raise ValueError("frequency_hz must be a number") from exc
    if not 140000000 <= frequency <= 450000000:
        raise ValueError("SSTV downlink frequency must be between 140 and 450 MHz")
    mode = str(raw.get("mode", DEFAULT_EVENT["mode"])).strip().lower()
    if mode not in MODES:
        raise ValueError("mode must be robot36 or pd120")
    return {
        "enabled": enabled,
        "name": name,
        "start_utc": _utc_text(start),
        "end_utc": _utc_text(end),
        "frequency_hz": frequency,
        "mode": mode,
        "transmission_seconds": 36 if mode == "robot36" else 120,
        "pause_seconds": 120,
    }


def get_settings() -> dict[str, Any]:
    """Read the persistent operator event or return the shipped Series 33."""
    try:
        payload = json.loads(EVENT_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = DEFAULT_EVENT
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read ISS SSTV event settings: {exc}") from exc
    return _normalize_event(payload)


def set_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically save the operator-configured SSTV event."""
    settings = _normalize_event(payload)
    EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVENT_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, EVENT_FILE)
    return settings


def event_status(settings: dict[str, Any] | None = None, *, now: datetime | None = None) -> str:
    event = _normalize_event(settings or get_settings())
    if not event["enabled"]:
        return "disabled"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = _parse_utc(event["start_utc"], "start_utc")
    end = _parse_utc(event["end_utc"], "end_utc")
    if current < start:
        return "upcoming"
    if current < end:
        return "active"
    return "expired"


def decoder_status(mode: str | None = None) -> dict[str, Any]:
    """Check that the pinned Python decoder and requested mode are usable."""
    try:
        import sstv

        installed = importlib.metadata.version("sstv")
        mode_key = str(mode or "robot36").lower()
        attribute = MODES.get(mode_key)
        if not attribute or not hasattr(sstv.Mode, attribute):
            return {"available": False, "version": installed, "error": f"Unsupported decoder mode: {mode_key}"}
        if installed != DECODER_VERSION:
            return {
                "available": False,
                "version": installed,
                "error": f"Expected sstv=={DECODER_VERSION}",
            }
        return {"available": True, "version": installed, "error": None}
    except Exception as exc:
        return {"available": False, "version": None, "error": str(exc)}


def decode_wav(wav_path: str | Path, *, mode: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decode every complete or partial SSTV frame and save safe PNG results."""
    event_settings = _normalize_event(event or get_settings())
    normalized_mode = str(mode or event_settings["mode"]).strip().lower()
    if normalized_mode not in MODES:
        raise ValueError("Unsupported ISS SSTV mode")
    wav = Path(wav_path).expanduser().resolve()
    try:
        wav.relative_to(RECORDINGS_ROOT)
    except ValueError as exc:
        raise ValueError("SSTV WAV must be inside the ISS recordings directory") from exc
    if not wav.is_file() or wav.suffix.lower() != ".wav":
        raise ValueError("SSTV decoder input must be an existing WAV file")
    status = decoder_status(normalized_mode)
    if not status["available"]:
        raise RuntimeError("ISS SSTV decoder is unavailable: " + str(status.get("error") or "unknown error"))

    import sstv

    decoder_mode = getattr(sstv.Mode, MODES[normalized_mode])
    images = sstv.decode_from_wav(str(wav), mode=decoder_mode)
    output: list[dict[str, Any]] = []
    for index, image in enumerate(images[:MAX_IMAGES_PER_PASS], start=1):
        complete = bool((getattr(image, "info", {}) or {}).get("sstv_complete", True))
        filename = f"sstv_{index:02d}_{normalized_mode}_{'complete' if complete else 'partial'}.png"
        destination = wav.parent / filename
        temporary = destination.with_suffix(".png.tmp")
        image.save(temporary, format="PNG")
        os.replace(temporary, destination)
        output.append({
            "type": "image",
            "format": "png",
            "name": filename,
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
            "mode": normalized_mode,
            "complete": complete,
        })

    result = {
        "ok": True,
        "decoder": "sstv",
        "decoder_version": status["version"],
        "mode": normalized_mode,
        "image_count": len(output),
        "images_truncated": len(images) > MAX_IMAGES_PER_PASS,
        "images": output,
        "wav_path": str(wav),
    }
    metadata = wav.parent / "sstv_decode.json"
    metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["metadata_path"] = str(metadata)
    return result


def pass_is_in_event(target: dict[str, Any], settings: dict[str, Any] | None = None) -> bool:
    """Return true only when the complete planned capture is inside the event."""
    event = _normalize_event(settings or get_settings())
    if not event["enabled"]:
        return False
    try:
        start_epoch = int(target.get("start_epoch") or target["start"].timestamp())
        end_epoch = int(target.get("end_epoch") or target["end"].timestamp())
        event_start = int(_parse_utc(event["start_utc"], "start_utc").timestamp())
        event_end = int(_parse_utc(event["end_utc"], "end_utc").timestamp())
        return start_epoch >= event_start and end_epoch <= event_end and end_epoch > start_epoch
    except (KeyError, TypeError, ValueError, OSError):
        return False
