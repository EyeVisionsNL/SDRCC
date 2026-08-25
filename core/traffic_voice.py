#!/usr/bin/env python3
"""Traffic Voice configuration, runtime projection and backend rendering."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

from core import config as config_core
from core import plugin_registry, receiver_registry


VERSION = "0.56.0e"
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
MODE_FREQUENCY_RANGES = {
    "marine_ais": (156.0, 162.3),
    "airband_adsb": (118.0, 144.0),
}
_METRIC_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)\{(?P<labels>[^}]*)\}\s+(?P<value>[-+0-9.eE]+)$'
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')


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
        item["id"] for item in receiver_registry.get_receivers()
        if item["id"] != context
    ]
    return candidates[0] if len(candidates) == 1 else None


def validate_configuration(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    raw = config_core.load_traffic_voice() if payload is None else deepcopy(payload)
    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["configuration root must be a mapping"]}
    if raw.get("version") != SCHEMA_VERSION:
        errors.append(f"version must be {SCHEMA_VERSION}")
    settings = raw.get("traffic_voice")
    if not isinstance(settings, dict):
        return {"ok": False, "errors": [*errors, "traffic_voice must be a mapping"]}
    if settings.get("foundation_only") is not False:
        errors.append("foundation_only must be false")
    if settings.get("execution_enabled") is not True:
        errors.append("execution_enabled must be true")
    if settings.get("selected_mode") not in MODE_ORDER:
        errors.append("selected_mode must be marine_ais or airband_adsb")
    if settings.get("receiver_policy") != "opposite_context_receiver":
        errors.append("receiver_policy must be opposite_context_receiver")
    if not str(settings.get("channel_source") or "").strip():
        errors.append("channel_source is required")

    backend = settings.get("backend")
    if not isinstance(backend, dict):
        errors.append("backend must be a mapping")
    else:
        exact = {
            "name": "rtlsdr_airband",
            "version": "5.2.0",
            "service": "sdrcc-traffic-voice.service",
            "audio_transport": "local_udp_pcm",
            "activity_source": "channel_statistics",
        }
        for field, expected in exact.items():
            if backend.get(field) != expected:
                errors.append(f"backend.{field} must be {expected}")
        if backend.get("commit") != "61c5c4061967752da6b491a924664d72184b38fa":
            errors.append("backend.commit is not the pinned v5.2.0 commit")
        try:
            port = int(backend.get("audio_port"))
        except (TypeError, ValueError):
            port = 0
        if port <= 0 or port > 65535:
            errors.append("backend.audio_port is invalid")
        if int(backend.get("audio_sample_rate_hz") or 0) != 16000:
            errors.append("backend.audio_sample_rate_hz must be 16000 for the pinned AM/NFM build")
        valid_gains = config_core.get_rtl_sdr_valid_gains()
        try:
            gain_db = float(backend.get("gain_db"))
        except (TypeError, ValueError):
            gain_db = -1.0
        if gain_db not in valid_gains:
            errors.append("backend.gain_db is not a supported RTL-SDR gain")
        try:
            squelch_snr_db = float(backend.get("squelch_snr_db"))
        except (TypeError, ValueError):
            squelch_snr_db = -1.0
        if squelch_snr_db < 1.0 or squelch_snr_db > 30.0:
            errors.append("backend.squelch_snr_db must be between 1.0 and 30.0 dB")
        if not isinstance(backend.get("open_squelch"), bool):
            errors.append("backend.open_squelch must be a boolean")

    spectrum = settings.get("spectrum") or {}
    if spectrum.get("mode") != "channel_activity" or spectrum.get("fft_enabled") is not False:
        errors.append("spectrum must remain channel_activity with fft_enabled false")
    speaker = settings.get("speaker_context") or {}
    if speaker.get("label") != "possible_speaker" or speaker.get("certainty") != "probabilistic":
        errors.append("speaker context must remain explicitly probabilistic")
    if speaker.get("asr_enabled") is not False:
        errors.append("speaker_context.asr_enabled must remain false")

    modes = settings.get("modes")
    if not isinstance(modes, dict) or set(modes) != set(MODE_ORDER):
        errors.append("modes must contain exactly marine_ais and airband_adsb")
        modes = modes if isinstance(modes, dict) else {}
    for mode_id in MODE_ORDER:
        mode = modes.get(mode_id)
        if not isinstance(mode, dict):
            errors.append(f"modes.{mode_id} must be a mapping")
            continue
        for field, expected in MODE_CONTRACTS[mode_id].items():
            if str(mode.get(field) or "").strip().lower() != expected:
                errors.append(f"modes.{mode_id}.{field} must be {expected}")
        if mode.get("execution_enabled") is not True:
            errors.append(f"modes.{mode_id}.execution_enabled must be true")
        channels = mode.get("channels")
        if not isinstance(channels, list):
            errors.append(f"modes.{mode_id}.channels must be a list")
            continue
        if not channels:
            errors.append(f"modes.{mode_id}.channels must not be empty")
        tuning_mode = str(mode.get("tuning_mode") or "").strip().lower()
        if tuning_mode not in {"scan", "fixed"}:
            errors.append(f"modes.{mode_id}.tuning_mode must be scan or fixed")
        selected_channel_id = str(mode.get("selected_channel_id") or "").strip()
        ids: set[str] = set()
        frequencies: set[float] = set()
        minimum_frequency, maximum_frequency = MODE_FREQUENCY_RANGES[mode_id]
        for index, channel in enumerate(channels):
            prefix = f"modes.{mode_id}.channels[{index}]"
            if not isinstance(channel, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            channel_id = str(channel.get("id") or "").strip()
            label = str(channel.get("label") or "").strip()
            try:
                frequency = round(float(channel.get("frequency_mhz")), 6)
            except (TypeError, ValueError):
                frequency = 0.0
            if not channel_id or channel_id in ids:
                errors.append(f"{prefix}.id is missing or duplicate")
            if not label:
                errors.append(f"{prefix}.label is required")
            if (
                frequency < minimum_frequency
                or frequency > maximum_frequency
                or frequency in frequencies
            ):
                errors.append(f"{prefix}.frequency_mhz is invalid or duplicate")
            if mode_id == "airband_adsb":
                try:
                    channel_frequency = round(float(channel.get("channel_mhz")), 6)
                except (TypeError, ValueError):
                    channel_frequency = 0.0
                if channel_frequency < minimum_frequency or channel_frequency > maximum_frequency:
                    errors.append(f"{prefix}.channel_mhz is invalid")
            scan_enabled = channel.get("scan_enabled", True)
            if not isinstance(scan_enabled, bool):
                errors.append(f"{prefix}.scan_enabled must be a boolean when present")
            ids.add(channel_id)
            frequencies.add(frequency)
        if selected_channel_id not in ids:
            errors.append(f"modes.{mode_id}.selected_channel_id is unknown")
    return {"ok": not errors, "schema_version": SCHEMA_VERSION, "errors": errors}


def get_receiver_settings(
    payload: dict[str, Any] | None = None,
    *,
    mode_id: str | None = None,
) -> dict[str, Any]:
    """Return the editable settings projection for one Traffic Voice mode."""
    raw = config_core.load_traffic_voice() if payload is None else deepcopy(payload)
    settings = raw.get("traffic_voice", {}) if isinstance(raw, dict) else {}
    backend = settings.get("backend", {}) if isinstance(settings, dict) else {}
    selected_mode = str(mode_id or settings.get("selected_mode") or "").strip()
    if selected_mode not in MODE_ORDER:
        raise ValueError("Onbekende Traffic Voice-modus")
    mode = (settings.get("modes", {}) or {}).get(selected_mode, {})
    channels = deepcopy(mode.get("channels") or [])
    return {
        "mode_id": selected_mode,
        "tuning_mode": str(mode.get("tuning_mode") or "scan").lower(),
        "selected_channel_id": str(mode.get("selected_channel_id") or ""),
        "gain_db": float(backend.get("gain_db") or 0.0),
        "squelch_snr_db": float(backend.get("squelch_snr_db") or 0.0),
        "open_squelch": backend.get("open_squelch") is True,
        "valid_gains": config_core.get_rtl_sdr_valid_gains(),
        "channels": channels,
        "scan_channel_ids": [
            str(item.get("id") or "") for item in channels
            if item.get("scan_enabled", True) is not False
        ],
    }


def normalize_receiver_settings(
    changes: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
    mode_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("Traffic Voice-instellingen moeten een mapping zijn")
    current = get_receiver_settings(payload, mode_id=mode_id)
    tuning_mode = str(changes.get("tuning_mode", current["tuning_mode"])).strip().lower()
    if tuning_mode not in {"scan", "fixed"}:
        raise ValueError("Afstemmodus moet scan of fixed zijn")
    selected_channel_id = str(
        changes.get("selected_channel_id", current["selected_channel_id"])
    ).strip()
    channel_ids = {str(item.get("id") or "") for item in current["channels"]}
    if selected_channel_id not in channel_ids:
        raise ValueError("Onbekend kanaal voor de geselecteerde Traffic Voice-modus")
    try:
        gain_db = float(changes.get("gain_db", current["gain_db"]))
    except (TypeError, ValueError) as error:
        raise ValueError("Ongeldige Traffic Voice-gain") from error
    if gain_db not in current["valid_gains"]:
        raise ValueError("Deze gain wordt niet door de RTL-SDR ondersteund")
    try:
        squelch_snr_db = float(
            changes.get("squelch_snr_db", current["squelch_snr_db"])
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Ongeldige Traffic Voice-squelch") from error
    if squelch_snr_db < 1.0 or squelch_snr_db > 30.0:
        raise ValueError("Squelch moet tussen 1,0 en 30,0 dB liggen")
    open_squelch = changes.get("open_squelch", current["open_squelch"])
    if not isinstance(open_squelch, bool):
        raise ValueError("Open squelch moet true of false zijn")
    raw_scan_ids = changes.get("scan_channel_ids", current["scan_channel_ids"])
    if not isinstance(raw_scan_ids, list):
        raise ValueError("Scan channel selection must be a list")
    scan_channel_ids = []
    seen_scan_ids = set()
    for raw_id in raw_scan_ids:
        channel_id = str(raw_id or "").strip()
        if channel_id not in channel_ids:
            raise ValueError("Onbekend kanaal in de Traffic Voice scanselectie")
        if channel_id not in seen_scan_ids:
            seen_scan_ids.add(channel_id)
            scan_channel_ids.append(channel_id)
    if tuning_mode == "scan" and not scan_channel_ids:
        raise ValueError("Selecteer minimaal één kanaal voor Scan all channels")
    return {
        "mode_id": current["mode_id"],
        "tuning_mode": tuning_mode,
        "selected_channel_id": selected_channel_id,
        "gain_db": gain_db,
        "squelch_snr_db": squelch_snr_db,
        "open_squelch": open_squelch,
        "scan_channel_ids": scan_channel_ids,
    }


def save_receiver_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Persist validated controls in config/traffic_voice.yaml only."""
    raw = config_core.load_traffic_voice()
    normalized = normalize_receiver_settings(changes, payload=raw)
    candidate = deepcopy(raw)
    settings = candidate["traffic_voice"]
    backend = settings["backend"]
    mode = settings["modes"][normalized["mode_id"]]
    backend["gain_db"] = normalized["gain_db"]
    backend["squelch_snr_db"] = normalized["squelch_snr_db"]
    backend["open_squelch"] = normalized["open_squelch"]
    mode["tuning_mode"] = normalized["tuning_mode"]
    mode["selected_channel_id"] = normalized["selected_channel_id"]
    enabled_scan_ids = set(normalized["scan_channel_ids"])
    for channel in mode.get("channels") or []:
        channel["scan_enabled"] = str(channel.get("id") or "") in enabled_scan_ids
    validation = validate_configuration(candidate)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    config_core.save_traffic_voice(candidate)
    return get_receiver_settings()


def save_selected_mode(mode_id: str) -> dict[str, Any]:
    """Persist the selected mode in the existing Traffic Voice authority."""
    selected_mode = str(mode_id or "").strip()
    if selected_mode not in MODE_ORDER:
        raise ValueError("Onbekende Traffic Voice-modus")
    raw = config_core.load_traffic_voice()
    candidate = deepcopy(raw)
    candidate["traffic_voice"]["selected_mode"] = selected_mode
    validation = validate_configuration(candidate)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    config_core.save_traffic_voice(candidate)
    return get_receiver_settings(candidate)


def _service_state(service_name: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            text=True, capture_output=True, timeout=5, check=False,
        )
        state = result.stdout.strip() or result.stderr.strip() or "unknown"
        return {"service": service_name, "active": state == "active", "state": state}
    except (OSError, subprocess.SubprocessError) as error:
        return {"service": service_name, "active": False, "state": "unknown", "error": str(error)}


def parse_statistics(
    text: str,
    *,
    possible_active_snr_db: float = 6.0,
) -> list[dict[str, Any]]:
    channels: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_RE.match(line)
        if not match:
            continue
        labels = {
            key: value.replace(r"\"", '"').replace(r"\\", "\\")
            for key, value in _LABEL_RE.findall(match.group("labels"))
        }
        frequency = str(labels.get("freq") or labels.get("frequency") or "")
        label = str(labels.get("label") or frequency)
        if not frequency:
            continue
        try:
            value = float(match.group("value"))
            frequency_value = float(frequency)
        except ValueError:
            continue
        if frequency_value < 1_000_000:
            frequency_mhz = round(frequency_value, 6)
            frequency_hz = int(round(frequency_mhz * 1_000_000.0))
        else:
            frequency_hz = int(round(frequency_value))
            frequency_mhz = round(frequency_hz / 1_000_000.0, 6)
        item = channels.setdefault((frequency, label), {
            "frequency_hz": frequency_hz,
            "frequency_mhz": frequency_mhz,
            "label": label,
        })
        item[match.group("name")] = value

    result = []
    for item in channels.values():
        signal = item.get("channel_dbfs_signal_level")
        noise = item.get("channel_dbfs_noise_level")
        snr = signal - noise if signal is not None and noise is not None else None
        item["signal_dbfs"] = round(signal, 2) if signal is not None else None
        item["noise_dbfs"] = round(noise, 2) if noise is not None else None
        item["snr_db"] = round(snr, 2) if snr is not None else None
        item["activity_count"] = int(item.get("channel_activity_counter") or 0)
        item["squelch_count"] = int(item.get("channel_squelch_counter") or 0)
        item["possible_active"] = bool(
            snr is not None and snr >= float(possible_active_snr_db)
        )
        result.append(item)
    return sorted(result, key=lambda item: item["frequency_hz"])


def read_statistics(
    path: str | Path,
    *,
    possible_active_snr_db: float = 6.0,
) -> dict[str, Any]:
    stats_path = Path(path)
    try:
        text = stats_path.read_text(encoding="utf-8")
        age = max(0.0, datetime.now().timestamp() - stats_path.stat().st_mtime)
        channels = parse_statistics(
            text,
            possible_active_snr_db=possible_active_snr_db,
        )
        return {
            "available": True,
            "fresh": age <= 35.0,
            "age_seconds": round(age, 2),
            "channels": channels,
            "error": None,
        }
    except OSError as error:
        return {"available": False, "fresh": False, "age_seconds": None, "channels": [], "error": str(error)}


def _libconfig_string(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_rtlsdr_airband_config() -> str:
    raw = config_core.load_traffic_voice()
    validation = validate_configuration(raw)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    settings = raw["traffic_voice"]
    backend = settings["backend"]
    assignments = config_core.get_receiver_assignments()
    selected_mode = str(settings.get("selected_mode") or "")
    mode = settings["modes"][selected_mode]
    context_plugin = str(mode["context_plugin"])
    context_receiver = assignments.get(context_plugin)
    voice_receiver = _other_receiver(context_receiver)
    assigned_voice = receiver_registry.resolve_id(assignments.get("traffic_voice"))
    if voice_receiver is None or assigned_voice != voice_receiver:
        raise RuntimeError("Traffic Voice assignment wijkt af van opposite_context_receiver")
    receiver = receiver_registry.get_receiver(voice_receiver)
    receiver_settings = get_receiver_settings(raw)
    channels = mode["channels"]
    selected_channel = next(
        item for item in channels
        if item["id"] == receiver_settings["selected_channel_id"]
    )
    if receiver_settings["tuning_mode"] == "fixed" or receiver_settings["open_squelch"]:
        channels = [selected_channel]
    else:
        enabled_scan_ids = set(receiver_settings["scan_channel_ids"])
        channels = [item for item in channels if str(item.get("id") or "") in enabled_scan_ids]
        if not channels:
            raise RuntimeError("Traffic Voice scan heeft geen ingeschakelde kanalen")
    freqs = ", ".join(f"{float(item['frequency_mhz']):.6f}" for item in channels)
    labels = ", ".join(_libconfig_string(item["label"]) for item in channels)
    squelch_snr_db = (
        0.0 if receiver_settings["open_squelch"]
        else receiver_settings["squelch_snr_db"]
    )
    return "\n".join((
        "# Generated by SDRCC v0.56.0e; do not edit runtime output.",
        "log_scan_activity = true;",
        f"stats_filepath = {_libconfig_string(backend['stats_file'])};",
        "tau = 75;",
        "devices:",
        "({",
        '  type = "rtlsdr";',
        f"  serial = {_libconfig_string(receiver['serial'])};",
        f"  gain = {receiver_settings['gain_db']:.1f};",
        f"  correction = {int(backend['correction_ppm'])};",
        '  mode = "scan";',
        "  channels:",
        "  (",
        "    {",
        f"      modulation = {_libconfig_string(mode['modulation'])};",
        f"      freqs = ( {freqs} );",
        f"      labels = ( {labels} );",
        f"      squelch_snr_threshold = {squelch_snr_db:.1f};",
        "      outputs: (",
        "        {",
        '          type = "udp_stream";',
        f"          dest_address = {_libconfig_string(backend['audio_host'])};",
        f"          dest_port = {int(backend['audio_port'])};",
        "          continuous = true;",
        "        }",
        "      );",
        "    }",
        "  );",
        " }",
        ");",
        "",
    ))


def get_snapshot(
    *,
    service_reader: Callable[[str], dict[str, Any]] | None = None,
    audio_reader: Callable[[], dict[str, Any]] | None = None,
    atis_reader: Callable[[], dict[str, Any]] | None = None,
    ais_matcher: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = config_core.load_traffic_voice()
    validation = validate_configuration(raw)
    settings = raw.get("traffic_voice", {}) if isinstance(raw, dict) else {}
    modes_config = settings.get("modes", {}) if isinstance(settings, dict) else {}
    assignments = config_core.get_receiver_assignments()
    plugin = plugin_registry.get_plugin("traffic_voice")
    errors = list(validation["errors"])
    if not plugin or plugin.get("status") != "active" or plugin.get("executor") != "service":
        errors.append("traffic_voice plugin must be an active service plugin")
    if (plugin or {}).get("services") != ["sdrcc-traffic-voice.service"]:
        errors.append("traffic_voice service metadata is invalid")
    receivers = receiver_registry.get_receivers()
    if len(receivers) != 2:
        errors.append("Traffic Voice requires exactly two enabled receivers")

    mode_snapshots: list[dict[str, Any]] = []
    selected_assignment = None
    selected_assignment_matches = False
    selected_mode = str(settings.get("selected_mode") or "")
    for mode_id in MODE_ORDER:
        mode = deepcopy(modes_config.get(mode_id) or {})
        context_plugin = str(mode.get("context_plugin") or "")
        context_receiver_id = assignments.get(context_plugin)
        derived_voice_id = _other_receiver(context_receiver_id)
        selected = mode_id == selected_mode
        item = {
            "id": mode_id,
            "label": mode.get("label") or mode_id,
            "voice_profile": mode.get("voice_profile"),
            "modulation": str(mode.get("modulation") or "").upper(),
            "context_plugin": context_plugin,
            "inactive_plugin": mode.get("inactive_plugin"),
            "channel_bank": mode.get("channel_bank"),
            "channel_count": len(mode.get("channels") or []),
            "channels": deepcopy(mode.get("channels") or []),
            "selected": selected,
            "execution_enabled": mode.get("execution_enabled") is True,
            "context_receiver": _receiver_projection(context_receiver_id),
            "derived_voice_receiver": _receiver_projection(derived_voice_id),
        }
        mode_snapshots.append(item)
        if selected:
            assigned_voice_id = receiver_registry.resolve_id(assignments.get("traffic_voice"))
            matches = bool(derived_voice_id and assigned_voice_id == derived_voice_id)
            selected_assignment_matches = matches
            selected_assignment = {
                "voice_role": "traffic_voice",
                "voice_receiver": _receiver_projection(assignments.get("traffic_voice")),
                "context_plugin": context_plugin,
                "context_receiver": _receiver_projection(context_receiver_id),
                "separated": bool(
                    assigned_voice_id
                    and assigned_voice_id != receiver_registry.resolve_id(context_receiver_id)
                ),
                "matches_policy": matches,
            }

    backend = deepcopy(settings.get("backend") or {})
    receiver_settings = get_receiver_settings(raw)
    backend["valid_gains"] = receiver_settings["valid_gains"]
    service = (service_reader or _service_state)(
        str(backend.get("service") or "sdrcc-traffic-voice.service")
    )
    if service.get("active") and not selected_assignment_matches:
        errors.append("traffic_voice assignment does not match opposite_context_receiver policy")
    activity = read_statistics(
        str(backend.get("stats_file") or "/run/sdrcc-traffic-voice/channel-stats.prom"),
        possible_active_snr_db=float(backend.get("squelch_snr_db") or 6.0),
    )
    if audio_reader is None:
        from core import traffic_voice_audio
        audio_reader = traffic_voice_audio.get_status
    audio = audio_reader()
    if atis_reader is None:
        from core import traffic_voice_atis
        atis_reader = traffic_voice_atis.get_status
    atis = atis_reader()
    latest_atis = atis.get("latest") or {}
    ais_match = {
        "matched": False,
        "status": "not_applicable" if selected_mode != "marine_ais" else "no_validated_atis",
        "callsign": None,
    }
    possible_speaker = None
    if selected_mode == "marine_ais" and latest_atis.get("fresh"):
        identity = latest_atis.get("callsign") or latest_atis.get("atis_code")
        if identity:
            possible_speaker = f"{identity} · ATIS VALIDATED"
        callsign = latest_atis.get("callsign")
        if callsign:
            if ais_matcher is None:
                from core import receiver_monitor
                ais_matcher = receiver_monitor.match_ais_callsign
            ais_match = ais_matcher(callsign)
            if ais_match.get("matched"):
                vessel = ais_match.get("shipname") or callsign
                possible_speaker = f"{vessel} · {callsign} · AIS MATCHED"
    strongest = max(
        activity["channels"],
        key=lambda item: item.get("snr_db") if item.get("snr_db") is not None else -999.0,
        default=None,
    )
    return {
        "ok": not errors,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "source": "traffic_voice",
        "read_only": False,
        "foundation_only": False,
        "execution_enabled": True,
        "selected_mode": selected_mode,
        "receiver_policy": settings.get("receiver_policy"),
        "channel_source": settings.get("channel_source"),
        "assignment": selected_assignment,
        "modes": mode_snapshots,
        "backend": backend,
        "receiver_settings": receiver_settings,
        "service": service,
        "audio": audio,
        "atis": atis,
        "ais_match": ais_match,
        "activity": activity,
        "strongest_channel": strongest,
        "spectrum": deepcopy(settings.get("spectrum") or {}),
        "speaker_context": deepcopy(settings.get("speaker_context") or {}),
        "possible_speaker": possible_speaker,
        "authorities": {
            "configuration": "config/traffic_voice.yaml",
            "plugin_metadata": "plugin_registry",
            "receiver_identity": "receiver_registry",
            "receiver_assignment": "config/station.yaml:assignments",
            "receiver_runtime": "receiver_manager",
            "service_control": "existing_dashboard_systemctl_path",
            "sdr_owner": "rtlsdr_airband",
            "audio_bridge": "localhost_udp_observer",
            "atis_decoder": "audio_bridge_read_only_observer",
            "ais_correlation": "receiver_monitor_read_only_ships_json",
            "ais_map": "existing_ais_catcher_viewer",
        },
        "validation": {"ok": not errors, "configuration": validation, "errors": errors},
        "updated_at": _now(),
    }
