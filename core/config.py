#!/usr/bin/env python3

from pathlib import Path
import os
import threading
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

STATION_CONFIG = CONFIG_DIR / "station.yaml"
SATELLITES_CONFIG = CONFIG_DIR / "satellites.yaml"
SCHEDULER_CONFIG = CONFIG_DIR / "scheduler.yaml"
RECEIVERS_CONFIG = CONFIG_DIR / "receivers.yaml"
_station_write_lock = threading.RLock()


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
    return ("weather", "ais", "adsb", "iss_voice", "meshcore")


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
        "meshcore": None,
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
    if mode not in {"auto", "manual"}:
        mode = "auto"
    raw_gain = rf.get("gain_db")
    try:
        gain = float(raw_gain) if raw_gain is not None else 38.6
    except (TypeError, ValueError):
        gain = 38.6
    valid_gains = [
        0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4,
        15.7, 16.6, 19.7, 20.7, 22.9, 25.4, 28.0, 29.7,
        32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4,
        43.9, 44.5, 48.0, 49.6,
    ]
    if gain not in valid_gains:
        gain = min(valid_gains, key=lambda value: abs(value - gain))
    return {
        "gain_mode": mode,
        "gain_db": gain,
        "dc_block": bool(rf.get("dc_block", True)),
        "iq_swap": bool(rf.get("iq_swap", False)),
        "lna_agc": bool(rf.get("lna_agc", mode == "auto")),
        "fill_missing": bool(rf.get("fill_missing", True)),
        "rs_usecheck": bool(rf.get("rs_usecheck", True)),
        "valid_gains": valid_gains,
    }


def set_weather_rf_config(settings):
    """Sla gevalideerde Weather RF-instellingen op."""
    current = get_weather_rf_config()
    mode = str(settings.get("gain_mode", current["gain_mode"])).lower()
    if mode not in {"auto", "manual"}:
        raise ValueError("Gain-modus moet auto of manual zijn")
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
    rf["lna_agc"] = bool(settings.get("lna_agc", current["lna_agc"]))
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
