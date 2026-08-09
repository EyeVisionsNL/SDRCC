#!/usr/bin/env python3
"""Read-only Traffic Voice Monitor foundation for SDRCC v0.55.0a.

The module validates configuration and projects existing receiver assignments.
It never opens an SDR, starts a process, controls a service, changes an
assignment, reserves a receiver, or persists runtime state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from core import config as config_core
from core import plugin_registry
from core import receiver_registry


VERSION = "0.55.0a"
SCHEMA_VERSION = 1
MODE_ORDER = ("marine_ais", "airband_adsb")
MODE_CONTRACTS = {
    "marine_ais": {
        "voice_profile": "marine_voice",
        "modulation": "nfm",
        "context_plugin": "ais",
        "inactive_plugin": "adsb",
    },
    "airband_adsb": {
        "voice_profile": "airband_voice",
        "modulation": "am",
        "context_plugin": "adsb",
        "inactive_plugin": "ais",
    },
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _receiver_projection(receiver_id: str | None) -> dict[str, Any] | None:
    receiver = receiver_registry.get_receiver(receiver_id)
    if receiver is None:
        return None
    return {
        "canonical_id": receiver["id"],
        "runtime_id": receiver["runtime_id"],
        "name": receiver["name"],
        "number": receiver["number"],
        "serial": receiver["serial"],
    }


def _other_receiver(receiver_id: str | None) -> str | None:
    context = receiver_registry.resolve_id(receiver_id)
    if context is None:
        return None
    candidates = [
        item["id"]
        for item in receiver_registry.get_receivers()
        if item["id"] != context
    ]
    return candidates[0] if len(candidates) == 1 else None


def validate_configuration(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate the static foundation schema and non-execution contract."""
    errors: list[str] = []
    if payload is None:
        raw = config_core.load_traffic_voice()
    else:
        raw = deepcopy(payload)

    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["configuration root must be a mapping"]}
    if raw.get("version") != SCHEMA_VERSION:
        errors.append(f"version must be {SCHEMA_VERSION}")

    settings = raw.get("traffic_voice")
    if not isinstance(settings, dict):
        return {"ok": False, "errors": [*errors, "traffic_voice must be a mapping"]}

    if settings.get("foundation_only") is not True:
        errors.append("foundation_only must remain true")
    if settings.get("execution_enabled") is not False:
        errors.append("execution_enabled must remain false")
    if settings.get("receiver_policy") != "opposite_context_receiver":
        errors.append("receiver_policy must be opposite_context_receiver")

    selected_mode = str(settings.get("selected_mode") or "").strip().lower()
    if selected_mode not in MODE_ORDER:
        errors.append("selected_mode must be marine_ais or airband_adsb")

    backend = settings.get("backend")
    if not isinstance(backend, dict):
        errors.append("backend must be a mapping")
    else:
        expected_backend = {
            "name": "rtlsdr_airband",
            "audio_transport": "local_udp_pcm",
            "activity_source": "channel_statistics",
        }
        for field, expected in expected_backend.items():
            if backend.get(field) != expected:
                errors.append(f"backend.{field} must be {expected}")

    spectrum = settings.get("spectrum")
    if not isinstance(spectrum, dict):
        errors.append("spectrum must be a mapping")
    else:
        if spectrum.get("mode") != "channel_activity":
            errors.append("spectrum.mode must be channel_activity")
        if spectrum.get("fft_enabled") is not False:
            errors.append("spectrum.fft_enabled must remain false")

    speaker = settings.get("speaker_context")
    if not isinstance(speaker, dict):
        errors.append("speaker_context must be a mapping")
    else:
        if speaker.get("label") != "possible_speaker":
            errors.append("speaker_context.label must be possible_speaker")
        if speaker.get("certainty") != "probabilistic":
            errors.append("speaker_context.certainty must be probabilistic")
        if speaker.get("asr_enabled") is not False:
            errors.append("speaker_context.asr_enabled must remain false")

    modes = settings.get("modes")
    if not isinstance(modes, dict):
        errors.append("modes must be a mapping")
        modes = {}
    if set(modes) != set(MODE_ORDER):
        errors.append("modes must contain exactly marine_ais and airband_adsb")

    for mode_id in MODE_ORDER:
        mode = modes.get(mode_id)
        if not isinstance(mode, dict):
            errors.append(f"modes.{mode_id} must be a mapping")
            continue
        if not str(mode.get("label") or "").strip():
            errors.append(f"modes.{mode_id}.label is required")
        for field, expected in MODE_CONTRACTS[mode_id].items():
            if str(mode.get(field) or "").strip().lower() != expected:
                errors.append(f"modes.{mode_id}.{field} must be {expected}")
        if not str(mode.get("channel_bank") or "").strip():
            errors.append(f"modes.{mode_id}.channel_bank is required")
        if not isinstance(mode.get("channels"), list):
            errors.append(f"modes.{mode_id}.channels must be a list")

    return {
        "ok": not errors,
        "schema_version": SCHEMA_VERSION,
        "errors": errors,
    }


def get_snapshot() -> dict[str, Any]:
    """Return the complete read-only foundation snapshot."""
    raw = config_core.load_traffic_voice()
    validation = validate_configuration(raw)
    settings = raw.get("traffic_voice", {}) if isinstance(raw, dict) else {}
    modes_config = settings.get("modes", {}) if isinstance(settings, dict) else {}
    assignments = config_core.get_receiver_assignments()
    plugin = plugin_registry.get_plugin("traffic_voice")

    contract_errors: list[str] = []
    if plugin is None:
        contract_errors.append("traffic_voice plugin metadata is missing")
    else:
        if plugin.get("status") != "planned":
            contract_errors.append("traffic_voice plugin status must remain planned")
        if plugin.get("executor") is not None:
            contract_errors.append("traffic_voice executor must remain disabled")
        if plugin.get("services") != [] or plugin.get("handover_services") != []:
            contract_errors.append("traffic_voice must not declare services in v0.55.0a")
        if plugin.get("assignment_role") != "traffic_voice":
            contract_errors.append("traffic_voice assignment role is invalid")

    receivers = receiver_registry.get_receivers()
    if len(receivers) != 2:
        contract_errors.append("Traffic Voice foundation requires exactly two enabled receivers")
    for receiver in receivers:
        if "traffic_voice" not in set(receiver.get("capabilities") or []):
            contract_errors.append(
                f"{receiver.get('runtime_id')}: traffic_voice capability is missing"
            )

    selected_mode = str(settings.get("selected_mode") or "").strip().lower()
    voice_receiver_id = assignments.get("traffic_voice")
    mode_snapshots: list[dict[str, Any]] = []
    selected_assignment: dict[str, Any] | None = None

    for mode_id in MODE_ORDER:
        mode = deepcopy(modes_config.get(mode_id) or {})
        context_plugin = str(mode.get("context_plugin") or "").strip().lower()
        context_receiver_id = assignments.get(context_plugin)
        derived_voice_id = _other_receiver(context_receiver_id)
        item = {
            "id": mode_id,
            "label": mode.get("label") or mode_id,
            "voice_profile": mode.get("voice_profile"),
            "modulation": str(mode.get("modulation") or "").upper(),
            "context_plugin": context_plugin,
            "inactive_plugin": mode.get("inactive_plugin"),
            "channel_bank": mode.get("channel_bank"),
            "channel_count": len(mode.get("channels") or []),
            "selected": mode_id == selected_mode,
            "context_receiver": _receiver_projection(context_receiver_id),
            "derived_voice_receiver": _receiver_projection(derived_voice_id),
        }
        mode_snapshots.append(item)
        if item["selected"]:
            separated = bool(
                voice_receiver_id
                and context_receiver_id
                and receiver_registry.resolve_id(voice_receiver_id)
                != receiver_registry.resolve_id(context_receiver_id)
            )
            matches_policy = bool(
                derived_voice_id
                and receiver_registry.resolve_id(voice_receiver_id) == derived_voice_id
            )
            selected_assignment = {
                "voice_role": "traffic_voice",
                "voice_receiver": _receiver_projection(voice_receiver_id),
                "context_plugin": context_plugin,
                "context_receiver": _receiver_projection(context_receiver_id),
                "separated": separated,
                "matches_policy": matches_policy,
            }
            if not separated:
                contract_errors.append(
                    "selected voice and context roles must use different receivers"
                )
            if not matches_policy:
                contract_errors.append(
                    "traffic_voice assignment does not match opposite_context_receiver policy"
                )

    if selected_assignment is None:
        contract_errors.append("selected mode has no assignment projection")

    all_errors = [*validation["errors"], *contract_errors]
    return {
        "ok": not all_errors,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "source": "traffic_voice_foundation",
        "read_only": True,
        "foundation_only": True,
        "execution_enabled": False,
        "behavior_changed": False,
        "selected_mode": selected_mode,
        "receiver_policy": settings.get("receiver_policy"),
        "assignment": selected_assignment,
        "modes": mode_snapshots,
        "backend": deepcopy(settings.get("backend") or {}),
        "spectrum": deepcopy(settings.get("spectrum") or {}),
        "speaker_context": deepcopy(settings.get("speaker_context") or {}),
        "authorities": {
            "configuration": "config/traffic_voice.yaml",
            "plugin_metadata": "plugin_registry",
            "receiver_identity": "receiver_registry",
            "receiver_assignment": "config/station.yaml:assignments",
            "receiver_runtime": "receiver_manager",
            "service_control": "existing_dashboard_systemctl_path",
        },
        "prohibited_in_v0550a": [
            "sdr_open",
            "process_start",
            "systemctl",
            "receiver_reservation",
            "assignment_write",
            "runtime_persistence",
        ],
        "validation": {
            "ok": not all_errors,
            "configuration": validation,
            "contract_errors": contract_errors,
            "errors": all_errors,
        },
        "updated_at": _now(),
    }
