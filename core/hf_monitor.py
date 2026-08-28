#!/usr/bin/env python3
"""Configuration and dashboard projection for the live HF Amateur Monitor.

Lifecycle, receiver handover and hardware access stay in their dedicated
controller/backend modules.  This module validates operator input and combines
their observed state for the dashboard.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core import config as config_core
from core import plugin_registry, receiver_registry

VERSION = "0.56.0d"
BAND_ORDER = (
    "80m", "40m", "20m", "15m", "10m",
    "shortwave", "airband", "marine", "2m",
    "fm_broadcast", "70cm", "pmr446", "adsb", "custom",
)
MODE_ORDER = ("LSB", "USB", "CW", "AM", "NFM", "FM", "WFM")
MIN_FREQUENCY_HZ = 500_000
MAX_FREQUENCY_HZ = 1_766_000_000
CONTINUOUS_CONTEXTS = (
    ("ais", "AIS", "ais-catcher.service"),
    ("adsb", "ADS-B", "readsb.service"),
)


def _settings(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = config_core.load_hf_monitor() if payload is None else deepcopy(payload)
    if not isinstance(raw, dict):
        raise ValueError("HF Monitor configuration must be a YAML mapping")
    settings = raw.get("hf_monitor")
    if not isinstance(settings, dict):
        raise ValueError("hf_monitor must be a YAML mapping")
    return settings


def validate_configuration(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate the executable HF Monitor configuration."""
    errors: list[str] = []
    try:
        settings = _settings(payload)
    except (FileNotFoundError, ValueError) as error:
        return {"ok": False, "errors": [str(error)]}

    if str(settings.get("version") or "") != VERSION:
        errors.append(f"version must be {VERSION}")
    if settings.get("foundation_only") is not False:
        errors.append("foundation_only must be false")
    if settings.get("execution_enabled") is not True:
        errors.append("execution_enabled must be true")
    if settings.get("receiver_policy") != "operator_selected_handover":
        errors.append("receiver_policy must be operator_selected_handover")

    backend = settings.get("backend")
    if not isinstance(backend, dict):
        errors.append("backend must be a mapping")
        backend = {}
    if backend.get("selected") != "librtlsdr_qbranch_dsp":
        errors.append("backend.selected must be librtlsdr_qbranch_dsp")
    if backend.get("status") != "validated":
        errors.append("backend.status must be validated")
    if int(backend.get("sample_rate_hz") or 0) != 240000:
        errors.append("backend.sample_rate_hz must be 240000")
    if int(backend.get("audio_sample_rate_hz") or 0) != 16000:
        errors.append("backend.audio_sample_rate_hz must be 16000")
    required = backend.get("required_capabilities")
    if not isinstance(required, list) or set(required) != {
        "hf_direct_sampling", "ssb_demodulation", "spectrum_stream", "pcm_audio",
        "fm_demodulation", "live_gain_control", "audio_squelch",
    }:
        errors.append("backend.required_capabilities is incomplete")

    modes = settings.get("modes")
    if tuple(modes or ()) != MODE_ORDER:
        errors.append("modes must use the stable LSB/USB/CW/AM/NFM/FM/WFM order")

    bands = settings.get("bands")
    if not isinstance(bands, dict) or tuple(bands) != BAND_ORDER:
        errors.append("bands/presets must use the stable Radio Receiver preset order")
        bands = {}
    for band_id in BAND_ORDER:
        band = bands.get(band_id)
        if not isinstance(band, dict):
            errors.append(f"{band_id} band is missing")
            continue
        try:
            minimum = int(band.get("minimum_hz"))
            maximum = int(band.get("maximum_hz"))
            default = int(band.get("default_hz"))
        except (TypeError, ValueError):
            errors.append(f"{band_id} frequencies must be integers")
            continue
        if not minimum < default < maximum:
            errors.append(f"{band_id} default frequency must be inside the band")
        if str(band.get("default_mode") or "").upper() not in MODE_ORDER:
            errors.append(f"{band_id} default mode is invalid")

    if settings.get("selected_band") not in BAND_ORDER:
        errors.append("selected_band is invalid")
    if str(settings.get("selected_mode") or "").upper() not in MODE_ORDER:
        errors.append("selected_mode is invalid")
    gain_mode = str(settings.get("gain_mode") or "auto").strip().lower()
    if gain_mode not in {"auto", "manual"}:
        errors.append("gain_mode must be auto or manual")
    valid_gains = config_core.get_rtl_sdr_valid_gains()
    try:
        gain_db = float(settings.get("gain_db"))
    except (TypeError, ValueError):
        gain_db = float("nan")
    if gain_db not in valid_gains:
        errors.append("gain_db is not a supported RTL-SDR gain")
    if not isinstance(settings.get("squelch_enabled"), bool):
        errors.append("squelch_enabled must be a boolean")
    try:
        squelch_threshold = float(settings.get("squelch_threshold_dbfs"))
    except (TypeError, ValueError):
        squelch_threshold = -999.0
    if not -65.0 <= squelch_threshold <= -10.0:
        errors.append("squelch_threshold_dbfs must be between -65 and -10 dBFS")
    if receiver_registry.resolve_runtime_id(settings.get("default_receiver")) is None:
        errors.append("default_receiver is unknown")

    plugin = plugin_registry.get_plugin("hf_monitor")
    if not plugin or plugin.get("status") != "active":
        errors.append("hf_monitor must be an active bounded-controller plugin")

    return {"ok": not errors, "errors": errors}


def _receiver_options(assignments: dict[str, str | None]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for receiver in receiver_registry.get_receivers():
        runtime_id = str(receiver["runtime_id"])
        pause_plugin = None
        pause_label = None
        pause_service = None
        for plugin_id, label, service in CONTINUOUS_CONTEXTS:
            assigned = receiver_registry.resolve_runtime_id(assignments.get(plugin_id))
            if assigned == runtime_id:
                pause_plugin = plugin_id
                pause_label = label
                pause_service = service
                break
        display_name = str(receiver.get("name") or runtime_id.upper())
        side_effect = f"pauses {pause_label}" if pause_label else "no continuous context assigned"
        options.append({
            "id": runtime_id,
            "canonical_id": receiver["id"],
            "name": display_name,
            "serial": receiver["serial"],
            "label": f"{display_name} · {side_effect}",
            "pause_plugin": pause_plugin,
            "pause_label": pause_label,
            "pause_service": pause_service,
            "handover_required": pause_plugin is not None,
            "restore_contract": "exact_pre_start_service_state",
        })
    return options


def validate_selection(selection: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(selection, dict):
        raise ValueError("HF-selectie ontbreekt")
    settings = _settings()
    receiver_id = receiver_registry.resolve_runtime_id(selection.get("receiver_id"))
    if receiver_id is None:
        raise ValueError("Kies een geldige HF-ontvanger")
    band_id = str(selection.get("band") or "").strip().lower()
    band = (settings.get("bands") or {}).get(band_id)
    if band_id not in BAND_ORDER or not isinstance(band, dict):
        raise ValueError("Kies een geldige frequentie-preset")
    mode = str(selection.get("mode") or "").strip().upper()
    if mode not in MODE_ORDER:
        raise ValueError("Kies LSB, USB, CW, AM, NFM, FM of WFM")
    try:
        frequency_hz = int(selection.get("frequency_hz"))
    except (TypeError, ValueError) as error:
        raise ValueError("Frequentie moet in Hz worden opgegeven") from error
    if not MIN_FREQUENCY_HZ <= frequency_hz <= MAX_FREQUENCY_HZ:
        raise ValueError(
            "Frequentie moet tussen "
            f"{MIN_FREQUENCY_HZ / 1_000_000:.3f} en "
            f"{MAX_FREQUENCY_HZ / 1_000_000:.3f} MHz liggen"
        )
    return {
        "receiver_id": receiver_id,
        "band": band_id,
        "mode": mode,
        "frequency_hz": frequency_hz,
    }


def validate_rf_controls(controls: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize operator gain/squelch without creating hardware authority."""
    settings = _settings()
    source = controls if isinstance(controls, dict) else {}
    gain_mode = str(source.get("gain_mode", settings.get("gain_mode", "auto"))).strip().lower()
    if gain_mode not in {"auto", "manual"}:
        raise ValueError("Gain mode must be auto or manual")
    try:
        gain_db = float(source.get("gain_db", settings.get("gain_db", 28.0)))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid HF tuner gain") from error
    valid_gains = config_core.get_rtl_sdr_valid_gains()
    if gain_db not in valid_gains:
        raise ValueError("This tuner gain is not supported by the RTL-SDR")
    enabled = source.get("squelch_enabled", settings.get("squelch_enabled", False))
    if not isinstance(enabled, bool):
        raise ValueError("squelch_enabled must be true or false")
    try:
        threshold = float(source.get(
            "squelch_threshold_dbfs", settings.get("squelch_threshold_dbfs", -42.0)
        ))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid HF squelch threshold") from error
    if not -65.0 <= threshold <= -10.0:
        raise ValueError("Squelch threshold must be between -65 and -10 dBFS")
    return {
        "gain_mode": gain_mode,
        "gain_db": gain_db,
        "squelch_enabled": enabled,
        "squelch_threshold_dbfs": threshold,
        "valid_gains": valid_gains,
    }


def get_snapshot(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return configuration plus observed live backend/session state."""
    from core import hf_monitor_backend, hf_monitor_controller

    validation = validate_configuration(payload)
    settings = _settings(payload)
    assignments = config_core.get_receiver_assignments()
    receivers = _receiver_options(assignments)
    default_receiver = receiver_registry.resolve_runtime_id(settings.get("default_receiver"))
    selected_band = str(settings.get("selected_band"))
    bands = []
    for band_id in BAND_ORDER:
        band = deepcopy(settings["bands"][band_id])
        band["id"] = band_id
        bands.append(band)

    backend_runtime = hf_monitor_backend.get_status()
    session = hf_monitor_controller.get_session()
    active_selection = session.get("selection") if isinstance(session, dict) else None
    if not isinstance(active_selection, dict):
        active_selection = {
            "receiver_id": default_receiver,
            "band": selected_band,
            "mode": str(settings.get("selected_mode") or ""),
            "frequency_hz": int(settings["bands"][selected_band]["default_hz"]),
        }
    rf_controls = validate_rf_controls()
    runtime_state = str(backend_runtime.get("state") or "STOPPED")
    runtime_rf = (
        (backend_runtime.get("rf_controls") or {})
        if isinstance(backend_runtime, dict) and runtime_state in {"STARTING", "LISTENING"}
        else {}
    )
    session_status = str((session or {}).get("status") or "")
    if session_status == "ATTENTION":
        runtime_state = "ATTENTION"
    backend_available = bool(backend_runtime.get("available"))
    start_allowed = bool(
        validation["ok"] and backend_available and session is None
        and runtime_state == "STOPPED"
    )
    if not validation["ok"]:
        start_block_reason = "; ".join(validation["errors"])
    elif not backend_available:
        start_block_reason = str(backend_runtime.get("error") or "librtlsdr is niet beschikbaar")
    elif session is not None:
        start_block_reason = "HF Monitor heeft al een actieve of te herstellen sessie."
    elif runtime_state != "STOPPED":
        start_block_reason = f"HF backend is {runtime_state.lower()}."
    else:
        start_block_reason = None

    return {
        "ok": validation["ok"],
        "version": VERSION,
        "source": "hf_monitor",
        "read_only": False,
        "foundation_only": False,
        "execution_enabled": True,
        "runtime_state": runtime_state,
        "status": (
            "LISTENING" if runtime_state == "LISTENING" else
            "ATTENTION" if runtime_state in {"ATTENTION", "ERROR"} else
            "READY" if validation["ok"] and backend_available else
            "BACKEND_UNAVAILABLE" if validation["ok"] else "CONFIGURATION_ERROR"
        ),
        "start_allowed": start_allowed,
        "start_block_reason": start_block_reason,
        "retune_allowed": bool(
            session is not None and session_status == "LISTENING"
            and runtime_state == "LISTENING"
        ),
        "stop_allowed": session is not None or runtime_state in {"STARTING", "LISTENING", "ERROR", "ATTENTION"},
        "receiver_policy": settings.get("receiver_policy"),
        "default_receiver": default_receiver,
        "receivers": receivers,
        "bands": bands,
        "modes": list(settings.get("modes") or []),
        "selected_receiver": active_selection["receiver_id"],
        "selected_band": active_selection["band"],
        "selected_mode": active_selection["mode"],
        "selected_frequency_hz": int(active_selection["frequency_hz"]),
        "rf_controls": {
            **rf_controls,
            **runtime_rf,
        },
        "backend": {
            **deepcopy(settings.get("backend") or {}),
            "runtime": backend_runtime,
        },
        "spectrum": deepcopy(backend_runtime.get("spectrum") or {}),
        "audio": deepcopy(backend_runtime.get("audio") or {}),
        "session": deepcopy(session),
        "authorities": {
            "configuration": "config/hf_monitor.yaml",
            "receiver_handover": "receiver_manager",
            "service_control": "existing_dashboard_systemctl_path",
            "backend": "single_owner_librtlsdr",
            "dashboard": "bounded_lifecycle_endpoint",
        },
        "restore_contract": {
            "restore_exact_pre_start_state": True,
            "restart_previously_inactive_services": False,
            "durable_session_required_before_execution": True,
        },
        "validation": validation,
    }
