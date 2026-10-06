#!/usr/bin/env python3

from pathlib import Path
import base64
import json
import math
import os
import subprocess
import threading
import zlib
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

STATION_CONFIG = CONFIG_DIR / "station.yaml"
READSB_POSITION_HELPER = Path("/usr/local/sbin/sdrcc-sync-readsb-position")
SATELLITES_CONFIG = CONFIG_DIR / "satellites.yaml"
SCHEDULER_CONFIG = CONFIG_DIR / "scheduler.yaml"
RECEIVERS_CONFIG = CONFIG_DIR / "receivers.yaml"
TRAFFIC_VOICE_CONFIG = CONFIG_DIR / "traffic_voice.yaml"
HF_MONITOR_CONFIG = CONFIG_DIR / "hf_monitor.yaml"
_station_write_lock = threading.RLock()
_traffic_voice_write_lock = threading.RLock()

TRAFFIC_VOICE_CHANNEL_CATALOG_VERSION = 2
_TRAFFIC_VOICE_MARINE_CATALOG_ZLIB_B64 = (
    "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"
)

RTL_SDR_VALID_GAINS = (
    0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4,
    15.7, 16.6, 19.7, 20.7, 22.9, 25.4, 28.0, 29.7,
    32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4,
    43.9, 44.5, 48.0, 49.6,
)


def load_yaml(path: Path):
    """Laad een YAML-bestand."""
    if not path.exists():
        raise FileNotFoundError(f"Configuratiebestand niet gevonden: {path}")

    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def load():
    """Backward compatible: laad station.yaml."""
    return load_station()


def load_station():
    """Laad algemene SDRCC-configuratie."""
    return load_yaml(STATION_CONFIG)


def load_satellites():
    """Laad satellietconfiguratie."""
    return load_yaml(SATELLITES_CONFIG)


def load_scheduler():
    """Laad Mission Scheduler-configuratie."""
    return load_yaml(SCHEDULER_CONFIG)


def load_receivers():
    """Laad de statische Receiver Registry."""
    return load_yaml(RECEIVERS_CONFIG)


def _traffic_voice_marine_catalog():
    raw = zlib.decompress(
        base64.b64decode(_TRAFFIC_VOICE_MARINE_CATALOG_ZLIB_B64)
    ).decode("utf-8")
    catalog = json.loads(raw)
    if not isinstance(catalog, list):
        raise ValueError("Traffic Voice marine channel catalog is invalid")
    return catalog


def _migrate_traffic_voice_channel_catalog(data):
    """Merge the current SDRCC marine catalog once without erasing user tuning choices."""
    if not isinstance(data, dict):
        return data, False
    settings = data.get("traffic_voice")
    if not isinstance(settings, dict):
        return data, False
    try:
        current_version = int(settings.get("channel_catalog_version", 0) or 0)
    except (TypeError, ValueError):
        current_version = 0
    if current_version >= TRAFFIC_VOICE_CHANNEL_CATALOG_VERSION:
        return data, False

    modes = settings.get("modes")
    marine = modes.get("marine_ais") if isinstance(modes, dict) else None
    existing = marine.get("channels") if isinstance(marine, dict) else None
    if not isinstance(existing, list):
        return data, False

    existing_by_id = {}
    existing_by_frequency = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("id") or "").strip()
        if channel_id:
            existing_by_id[channel_id] = item
        try:
            frequency = round(float(item.get("frequency_mhz")), 6)
        except (TypeError, ValueError):
            continue
        existing_by_frequency[frequency] = item

    merged = []
    catalog_ids = set()
    catalog_frequencies = set()
    for item in _traffic_voice_marine_catalog():
        channel = dict(item)
        channel_id = str(channel.get("id") or "").strip()
        frequency = round(float(channel["frequency_mhz"]), 6)
        previous = existing_by_id.get(channel_id) or existing_by_frequency.get(frequency)
        if isinstance(previous, dict) and "scan_enabled" in previous:
            channel["scan_enabled"] = bool(previous["scan_enabled"])
        merged.append(channel)
        catalog_ids.add(channel_id)
        catalog_frequencies.add(frequency)

    # Preserve unique user-added channels after the maintained SDRCC catalog.
    for item in existing:
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("id") or "").strip()
        try:
            frequency = round(float(item.get("frequency_mhz")), 6)
        except (TypeError, ValueError):
            continue
        if channel_id in catalog_ids or frequency in catalog_frequencies:
            continue
        merged.append(item)

    marine["channels"] = merged
    valid_ids = {str(item.get("id") or "") for item in merged if isinstance(item, dict)}
    selected = str(marine.get("selected_channel_id") or "")
    if selected not in valid_ids and merged:
        replacement = next(
            (
                str(item.get("id") or "")
                for item in merged
                if isinstance(item, dict) and item.get("scan_enabled") is True
            ),
            str(merged[0].get("id") or ""),
        )
        marine["selected_channel_id"] = replacement

    settings["channel_catalog_version"] = TRAFFIC_VOICE_CHANNEL_CATALOG_VERSION
    return data, True


def load_traffic_voice():
    """Load Traffic Voice and apply one-time maintained channel catalog migrations."""
    with _traffic_voice_write_lock:
        data = load_yaml(TRAFFIC_VOICE_CONFIG)
        data, changed = _migrate_traffic_voice_channel_catalog(data)
        if changed:
            save_traffic_voice(data)
        return data


def load_hf_monitor():
    """Load the HF Amateur Monitor configuration."""
    return load_yaml(HF_MONITOR_CONFIG)


def get_traffic_voice_config():
    """Return the configured Traffic Voice section without runtime state."""
    data = load_traffic_voice()
    traffic_voice = data.get("traffic_voice", {}) if isinstance(data, dict) else {}
    if not isinstance(traffic_voice, dict):
        raise ValueError("traffic_voice must be a YAML mapping")
    return traffic_voice


def save_traffic_voice(data):
    """Write traffic_voice.yaml atomically without creating another authority."""
    if not isinstance(data, dict):
        raise ValueError("Traffic Voice-configuratie moet een YAML mapping zijn")
    with _traffic_voice_write_lock:
        temp_path = TRAFFIC_VOICE_CONFIG.with_suffix(".yaml.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                yaml.safe_dump(data, file, sort_keys=False)
                file.flush()
                os.fsync(file.fileno())
            if TRAFFIC_VOICE_CONFIG.exists():
                os.chmod(temp_path, TRAFFIC_VOICE_CONFIG.stat().st_mode & 0o777)
            temp_path.replace(TRAFFIC_VOICE_CONFIG)
            directory_fd = os.open(TRAFFIC_VOICE_CONFIG.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def get_rtl_sdr_valid_gains():
    """Return the shared tuner-gain vocabulary for the station RTL-SDRs."""
    return list(RTL_SDR_VALID_GAINS)


def get_scheduler_config():
    """Geef schedulerinstellingen met veilige standaardwaarden."""
    data = load_scheduler()
    scheduler = data.get("scheduler", {})

    return {
        "preflight_seconds": int(
            scheduler.get("preflight_seconds", 300)
        ),
        "prepare_seconds": int(
            scheduler.get("prepare_seconds", 90)
        ),
        "lock_seconds": int(
            scheduler.get("lock_seconds", 30)
        ),
        "restore_delay_seconds": int(
            scheduler.get("restore_delay_seconds", 0)
        ),
    }


def get_enabled_satellites():
    """Geef alleen ingeschakelde satellieten terug."""
    data = load_satellites()
    satellites = data.get("satellites", {})

    enabled = {}

    for name, config in satellites.items():
        if config.get("enabled", False):
            enabled[name] = config

    return enabled



HOME_POSITION_ALTITUDE_MIN_M = -500.0
HOME_POSITION_ALTITUDE_MAX_M = 10000.0


def _home_position_number(value, field_name):
    """Normalize one finite numeric home-position value."""
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def normalize_home_position(payload):
    """Validate operator-supplied station location without creating new authority."""
    if not isinstance(payload, dict):
        raise ValueError("Home Position payload must be an object")

    location = str(payload.get("location") or "").strip()
    if not location:
        location = "Home"
    if len(location) > 80:
        raise ValueError("Location name must be 80 characters or fewer")

    latitude = _home_position_number(payload.get("latitude"), "Latitude")
    longitude = _home_position_number(payload.get("longitude"), "Longitude")
    altitude_m = _home_position_number(payload.get("altitude_m", 0.0), "Altitude")

    if not -90.0 <= latitude <= 90.0:
        raise ValueError("Latitude must be between -90 and 90 degrees")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Longitude must be between -180 and 180 degrees")
    if not HOME_POSITION_ALTITUDE_MIN_M <= altitude_m <= HOME_POSITION_ALTITUDE_MAX_M:
        raise ValueError(
            f"Altitude must be between {HOME_POSITION_ALTITUDE_MIN_M:g} and "
            f"{HOME_POSITION_ALTITUDE_MAX_M:g} metres"
        )

    return {
        "location": location,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "altitude_m": round(altitude_m, 1),
    }


def get_home_position():
    """Return the station location used by planning, Radio View and Doppler."""
    data = load_station() or {}
    station = data.get("station", {})
    if not isinstance(station, dict):
        raise ValueError("station must be a YAML mapping")
    return normalize_home_position({
        "location": station.get("location") or "Home",
        "latitude": station.get("latitude"),
        "longitude": station.get("longitude"),
        "altitude_m": station.get("altitude_m", 0.0),
    })


def _sync_readsb_home_position(position):
    """Synchronise the derived readsb position through the bounded root helper."""
    if not READSB_POSITION_HELPER.exists():
        raise OSError(f"readsb position helper is missing: {READSB_POSITION_HELPER}")

    result = subprocess.run(
        [
            "sudo",
            "-n",
            str(READSB_POSITION_HELPER),
            f"{position['latitude']:.6f}",
            f"{position['longitude']:.6f}",
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise OSError(
            (result.stderr or result.stdout or "readsb position sync failed").strip()
        )


def set_home_position(payload):
    """Update station authority and keep the derived readsb position synchronized."""
    position = normalize_home_position(payload)
    data = load_station() or {}
    if not isinstance(data, dict):
        raise ValueError("station.yaml must contain a YAML mapping")

    previous = yaml.safe_load(yaml.safe_dump(data, sort_keys=False)) or {}

    station = data.setdefault("station", {})
    if not isinstance(station, dict):
        raise ValueError("station must be a YAML mapping")

    station["location"] = position["location"]
    station["latitude"] = position["latitude"]
    station["longitude"] = position["longitude"]
    station["altitude_m"] = position["altitude_m"]

    save_station(data)
    try:
        _sync_readsb_home_position(position)
    except Exception:
        save_station(previous)
        raise

    return position


def save_station(data):
    """Schrijf station.yaml atomisch weg."""
    with _station_write_lock:
        temp_path = STATION_CONFIG.with_suffix(".yaml.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                yaml.safe_dump(data, file, sort_keys=False)
                file.flush()
                os.fsync(file.fileno())
            if STATION_CONFIG.exists():
                os.chmod(temp_path, STATION_CONFIG.stat().st_mode & 0o777)
            temp_path.replace(STATION_CONFIG)
            directory_fd = os.open(STATION_CONFIG.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def get_assignment_roles():
    """Return the supported receiver-assignment roles in stable UI order."""
    return (
        "weather",
        "ais",
        "adsb",
        "iss_voice",
        "traffic_voice",
        "hf_monitor",
    )


def _configured_receiver_ids():
    """Return enabled compatibility IDs from the central registry."""
    from core.receiver_registry import get_receiver_ids
    return tuple(get_receiver_ids(compatibility=True))


def get_assignment_defaults():
    """Return safe defaults based on the configured receivers."""
    receiver_ids = _configured_receiver_ids()
    first = receiver_ids[0] if receiver_ids else None
    second = receiver_ids[1] if len(receiver_ids) > 1 else first
    return {
        "weather": first,
        "ais": first,
        "adsb": second,
        "iss_voice": None,
        "traffic_voice": second,
        "hf_monitor": None,
    }


def _validate_assignment_role(role):
    normalized = str(role or "").strip().lower()
    if normalized not in get_assignment_roles():
        raise ValueError(f"Onbekende receiverrol: {role}")
    return normalized


def _validate_assignment_device(device_id, *, allow_none=False):
    if device_id is None and allow_none:
        return None
    normalized = str(device_id or "").strip().lower()
    if normalized not in set(_configured_receiver_ids()):
        raise ValueError("Onbekende of uitgeschakelde receiver")
    return normalized


def get_receiver_assignments():
    """Return the single persistent role-assignment authority.

    Missing roles retain safe defaults for old installations. Explicit invalid
    values fail closed instead of being silently replaced, because silently
    changing the effective receiver would hide configuration drift.
    """
    data = load_station()
    configured = data.get("assignments", {}) or {}
    if not isinstance(configured, dict):
        raise ValueError("assignments moet een YAML mapping zijn")
    defaults = get_assignment_defaults()
    assignments = {}

    for role in get_assignment_roles():
        raw_value = configured.get(role, defaults.get(role))
        if raw_value in (None, "", "none", "null"):
            assignments[role] = None
            continue
        assignments[role] = _validate_assignment_device(raw_value, allow_none=True)

    return assignments


def get_assignment(role):
    """Return the receiver assigned to one role, or None when unassigned."""
    role = _validate_assignment_role(role)
    return get_receiver_assignments().get(role)


def set_assignment(role, device_id):
    """Persist one role assignment without touching services or runtime state."""
    return set_plugin_assignments({role: device_id})


def validate_assignment_changes(changes):
    """Return normalized changes and the complete candidate authority."""
    if not isinstance(changes, dict):
        raise ValueError("Toewijzingen moeten als mapping worden aangeleverd")

    normalized = {}
    for role, device_id in changes.items():
        normalized_role = _validate_assignment_role(role)
        normalized_device = _validate_assignment_device(
            device_id,
            allow_none=True,
        )
        if normalized_device is not None:
            from core.receiver_registry import get_receiver
            receiver = get_receiver(normalized_device)
            capabilities = set((receiver or {}).get("capabilities") or [])
            if normalized_role not in capabilities:
                raise ValueError(
                    f"{normalized_device.upper()} ondersteunt rol {normalized_role} niet"
                )
        normalized[normalized_role] = normalized_device

    current = get_receiver_assignments()
    candidate = {**current, **normalized}
    if candidate.get("ais") and candidate.get("ais") == candidate.get("adsb"):
        raise ValueError("AIS en ADS-B kunnen niet dezelfde receiver gebruiken")
    return normalized, candidate


def set_plugin_assignments(changes):
    """Persist validated changes to the only assignment authority."""
    normalized, _candidate = validate_assignment_changes(changes)

    data = load_station()
    # v0.54.0a: assignments is the only persistent role mapping. The legacy
    # sections remain readable through compatibility functions below, but may
    # never be written as independent policy again.
    data.pop("mission_assignments", None)
    data.pop("receiver_defaults", None)
    assignments = data.setdefault("assignments", {})
    if not isinstance(assignments, dict):
        raise ValueError("assignments moet een YAML mapping zijn")
    assignments.update(normalized)
    save_station(data)
    return get_receiver_assignments()


def set_weather_receiver(device_id):
    """Backward-compatible wrapper for the generic assignment API."""
    return set_assignment("weather", device_id)


def set_receiver_roles(roles):
    """Backward-compatible fixed AIS/ADS-B assignment editor."""
    allowed = {"ais", "adsb", "manual"}
    normalized = {}
    for receiver_id in _configured_receiver_ids():
        role = str((roles or {}).get(receiver_id, "manual")).strip().lower()
        if role not in allowed:
            raise ValueError(f"Ongeldige rol voor {receiver_id}: {role}")
        normalized[receiver_id] = role

    for exclusive_role in ("ais", "adsb"):
        selected = [
            receiver_id
            for receiver_id, role in normalized.items()
            if role == exclusive_role
        ]
        if len(selected) > 1:
            raise ValueError(
                f"{exclusive_role.upper()} kan maar aan één receiver worden toegewezen"
            )

    changes = {
        "ais": next(
            (receiver_id for receiver_id, role in normalized.items() if role == "ais"),
            None,
        ),
        "adsb": next(
            (receiver_id for receiver_id, role in normalized.items() if role == "adsb"),
            None,
        ),
    }
    return set_plugin_assignments(changes)

def get_weather_rf_config():
    """Geef Weather RF-instellingen met veilige standaardwaarden."""
    data = load_station()
    rf = data.get("weather_rf", {})
    mode = str(rf.get("gain_mode", "auto")).lower()
    if mode not in {"auto", "smart", "manual"}:
        mode = "auto"
    raw_gain = rf.get("gain_db")
    try:
        gain = float(raw_gain) if raw_gain is not None else 38.6
    except (TypeError, ValueError):
        gain = 38.6
    valid_gains = get_rtl_sdr_valid_gains()
    if gain not in valid_gains:
        gain = min(valid_gains, key=lambda value: abs(value - gain))
    lna_agc = bool(rf.get("lna_agc", mode == "auto"))
    if mode == "smart":
        # A Smart measurement must use the same repeatable tuner gain for its
        # probe and the complete SatDump recording.
        lna_agc = False
    return {
        "gain_mode": mode,
        "gain_db": gain,
        "dc_block": bool(rf.get("dc_block", True)),
        "iq_swap": bool(rf.get("iq_swap", False)),
        "lna_agc": lna_agc,
        "fill_missing": bool(rf.get("fill_missing", True)),
        "rs_usecheck": bool(rf.get("rs_usecheck", True)),
        "valid_gains": valid_gains,
    }


def set_weather_rf_config(settings):
    """Sla gevalideerde Weather RF-instellingen op."""
    current = get_weather_rf_config()
    mode = str(settings.get("gain_mode", current["gain_mode"])).lower()
    if mode not in {"auto", "smart", "manual"}:
        raise ValueError("Gain-modus moet auto, smart of manual zijn")
    try:
        gain = float(settings.get("gain_db", current["gain_db"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Ongeldige gainwaarde") from exc
    if gain not in current["valid_gains"]:
        raise ValueError("Deze gainwaarde wordt niet door de RTL-SDR ondersteund")
    data = load_station()
    rf = data.setdefault("weather_rf", {})
    rf["gain_mode"] = mode
    rf["gain_db"] = gain
    rf["dc_block"] = bool(settings.get("dc_block", current["dc_block"]))
    rf["iq_swap"] = bool(settings.get("iq_swap", current["iq_swap"]))
    rf["lna_agc"] = (
        False if mode == "smart"
        else bool(settings.get("lna_agc", current["lna_agc"]))
    )
    rf["fill_missing"] = bool(settings.get("fill_missing", current["fill_missing"]))
    rf["rs_usecheck"] = bool(settings.get("rs_usecheck", current["rs_usecheck"]))
    save_station(data)
    return get_weather_rf_config()


# v0.47.1a Mission Assignment & Restore Policy Foundation
MISSION_ASSIGNMENT_ROLES = ("weather", "iss_voice")
DEFAULT_CONTEXT_PLUGINS = ("ais", "adsb")
def get_mission_assignment_roles():
    """Return mission-capable roles in stable UI order."""
    return MISSION_ASSIGNMENT_ROLES


def get_mission_assignments():
    """Compatibility projection derived from ``assignments`` only."""
    authority = get_receiver_assignments()
    return {role: authority.get(role) for role in MISSION_ASSIGNMENT_ROLES}


def set_mission_assignments(changes):
    """Compatibility writer routed to the single assignment authority."""
    if not isinstance(changes, dict):
        raise ValueError("Mission assignments moeten als mapping worden aangeleverd")
    unknown = set(changes) - set(MISSION_ASSIGNMENT_ROLES)
    if unknown:
        raise ValueError("Onbekend missietype: " + ", ".join(sorted(unknown)))

    set_plugin_assignments(changes)
    return get_mission_assignments()


def get_receiver_defaults():
    """Compatibility projection derived from ``assignments`` only."""
    receiver_ids = _configured_receiver_ids()
    authority = get_receiver_assignments()
    result = {receiver_id: [] for receiver_id in receiver_ids}
    for plugin_id in DEFAULT_CONTEXT_PLUGINS:
        receiver_id = authority.get(plugin_id)
        if receiver_id in result:
            result[receiver_id].append(plugin_id)
    return result


def set_receiver_defaults(defaults):
    """Compatibility writer routed to the single assignment authority."""
    if not isinstance(defaults, dict):
        raise ValueError("Receiver defaults moeten als mapping worden aangeleverd")
    receiver_ids = _configured_receiver_ids()
    unknown_receivers = set(defaults) - set(receiver_ids)
    if unknown_receivers:
        raise ValueError("Onbekende receiver: " + ", ".join(sorted(unknown_receivers)))

    normalized = {receiver_id: [] for receiver_id in receiver_ids}
    seen = set()
    for receiver_id in receiver_ids:
        raw_plugins = defaults.get(receiver_id, []) or []
        if isinstance(raw_plugins, str):
            raw_plugins = [] if raw_plugins in {"", "none", "manual"} else [raw_plugins]
        for raw_plugin in raw_plugins:
            plugin_id = str(raw_plugin or "").strip().lower()
            if plugin_id not in DEFAULT_CONTEXT_PLUGINS:
                raise ValueError(f"Ongeldige default plugin voor {receiver_id}: {raw_plugin}")
            if plugin_id in seen:
                raise ValueError(f"{plugin_id.upper()} kan maar één default receiver hebben")
            seen.add(plugin_id)
            normalized[receiver_id].append(plugin_id)

    changes = {}
    for plugin_id in DEFAULT_CONTEXT_PLUGINS:
        changes[plugin_id] = next(
            (rid for rid, plugins in normalized.items() if plugin_id in plugins),
            None,
        )
    set_plugin_assignments(changes)
    return get_receiver_defaults()


def get_assignment_restore_policy():
    """Return compatibility views backed by one persistent authority."""
    return {
        "version": "0.54.0a",
        "assignment_authority": "config/station.yaml:assignments",
        "persistent_assignment_keys": ["assignments"],
        "assignments": get_receiver_assignments(),
        "mission_assignments": get_mission_assignments(),
        "receiver_defaults": get_receiver_defaults(),
        "mission_assignment_roles": list(MISSION_ASSIGNMENT_ROLES),
        "default_context_plugins": list(DEFAULT_CONTEXT_PLUGINS),
        "receiver_ids": list(_configured_receiver_ids()),
        "execution_enabled": True,
        "restore_enabled": True,
        "compatibility_views_only": True,
    }
