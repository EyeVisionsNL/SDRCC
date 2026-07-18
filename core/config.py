#!/usr/bin/env python3

from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

STATION_CONFIG = CONFIG_DIR / "station.yaml"
SATELLITES_CONFIG = CONFIG_DIR / "satellites.yaml"
SCHEDULER_CONFIG = CONFIG_DIR / "scheduler.yaml"


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
    temp_path = STATION_CONFIG.with_suffix(".yaml.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)
    temp_path.replace(STATION_CONFIG)


def get_receiver_assignments():
    """Geef receiver-toewijzingen met veilige defaults."""
    data = load_station()
    assignments = data.get("assignments", {})
    return {
        "weather": assignments.get("weather", "sdr1"),
        "ais": assignments.get("ais", "sdr1"),
        "adsb": assignments.get("adsb", "sdr2"),
    }


def set_weather_receiver(device_id):
    """Sla de gekozen Weather-ontvanger persistent op."""
    if device_id not in {"sdr1", "sdr2"}:
        raise ValueError("Weather-ontvanger moet sdr1 of sdr2 zijn")
    data = load_station()
    assignments = data.setdefault("assignments", {})
    assignments.setdefault("ais", "sdr1")
    assignments.setdefault("adsb", "sdr2")
    assignments["weather"] = device_id
    save_station(data)
    return get_receiver_assignments()


def set_receiver_roles(roles):
    """Sla vaste receiverrollen op zonder services te wijzigen."""
    allowed = {"ais", "adsb", "manual"}
    normalized = {}
    for receiver_id in ("sdr1", "sdr2"):
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

    data = load_station()
    assignments = data.setdefault("assignments", {})
    assignments.setdefault("weather", "sdr1")
    assignments["ais"] = next(
        (receiver_id for receiver_id, role in normalized.items() if role == "ais"),
        None,
    )
    assignments["adsb"] = next(
        (receiver_id for receiver_id, role in normalized.items() if role == "adsb"),
        None,
    )
    save_station(data)
    return get_receiver_assignments()


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
        "spectrum_span_hz": int(rf.get("spectrum_span_hz", 1000000)),
        "spectrum_bin_hz": int(rf.get("spectrum_bin_hz", 10000)),
        "valid_gains": valid_gains,
    }




def get_mission_recommendation_config():
    """Geef instellingen voor historische RF-aanbevelingen."""
    data = load_station()
    automation = data.get("automation", {})
    return {
        "auto_apply_rf_recommendation": bool(
            automation.get("auto_apply_rf_recommendation", False)
        ),
    }


def set_mission_recommendation_config(settings):
    """Sla de automatische RF-aanbevelingsinstelling op."""
    current = get_mission_recommendation_config()
    enabled = settings.get(
        "auto_apply_rf_recommendation",
        current["auto_apply_rf_recommendation"],
    )
    data = load_station()
    automation = data.setdefault("automation", {})
    automation["auto_apply_rf_recommendation"] = bool(enabled)
    save_station(data)
    return get_mission_recommendation_config()

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
    rf.setdefault("spectrum_span_hz", current["spectrum_span_hz"])
    rf.setdefault("spectrum_bin_hz", current["spectrum_bin_hz"])
    save_station(data)
    return get_weather_rf_config()
