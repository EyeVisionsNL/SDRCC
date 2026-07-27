#!/usr/bin/env python3

"""Static receiver registry.

The registry is the single source of truth for receiver identity and hardware.
Runtime ownership, reservations and service state deliberately remain outside
this module.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import re

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = PROJECT_ROOT / "config" / "receivers.yaml"

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
KNOWN_CAPABILITIES = {
    "weather",
    "ais",
    "adsb",
    "iss_voice",
    "meshcore",
    "recording",
    "live_rf",
}


def _load_raw() -> dict[str, Any]:
    if not REGISTRY_FILE.is_file():
        raise FileNotFoundError(f"Receiver registry niet gevonden: {REGISTRY_FILE}")
    with REGISTRY_FILE.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Receiver registry moet een YAML mapping zijn")
    return data


def _normalise_receiver(receiver_id: str, raw: Any, order: int) -> dict[str, Any]:
    if not _ID_RE.fullmatch(receiver_id):
        raise ValueError(f"Ongeldige neutrale receiver-id: {receiver_id}")
    if not isinstance(raw, dict):
        raise ValueError(f"Receiver {receiver_id} moet een mapping zijn")

    hardware = raw.get("hardware") or {}
    if not isinstance(hardware, dict):
        raise ValueError(f"hardware van {receiver_id} moet een mapping zijn")

    driver = str(hardware.get("driver") or "rtlsdr").strip().lower()
    serial = str(hardware.get("serial") or "").strip()
    if not serial:
        raise ValueError(f"Receiver {receiver_id} heeft geen serienummer")

    aliases_raw = raw.get("aliases") or []
    if isinstance(aliases_raw, str):
        aliases_raw = [aliases_raw]
    if not isinstance(aliases_raw, list):
        raise ValueError(f"aliases van {receiver_id} moet een lijst zijn")
    aliases = []
    for alias in aliases_raw:
        value = str(alias or "").strip().lower()
        if not value or not _ID_RE.fullmatch(value):
            raise ValueError(f"Ongeldige alias voor {receiver_id}: {alias}")
        if value not in aliases:
            aliases.append(value)

    capabilities_raw = raw.get("capabilities") or []
    if isinstance(capabilities_raw, str):
        capabilities_raw = [capabilities_raw]
    if not isinstance(capabilities_raw, list):
        raise ValueError(f"capabilities van {receiver_id} moet een lijst zijn")
    capabilities = []
    for capability in capabilities_raw:
        value = str(capability or "").strip().lower()
        if value not in KNOWN_CAPABILITIES:
            raise ValueError(f"Onbekende capability voor {receiver_id}: {capability}")
        if value not in capabilities:
            capabilities.append(value)

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"defaults van {receiver_id} moet een mapping zijn")

    runtime_id = aliases[0] if aliases else receiver_id
    return {
        "id": receiver_id,
        "registry_id": receiver_id,
        "runtime_id": runtime_id,
        "number": str(raw.get("number") or f"RX{order:02d}"),
        "name": str(raw.get("name") or receiver_id),
        "description": str(raw.get("description") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "hardware": {"driver": driver, "serial": serial},
        "driver": driver,
        "serial": serial,
        "aliases": aliases,
        "capabilities": capabilities,
        "locked": bool(defaults.get("locked", False)),
        "defaults": deepcopy(defaults),
    }


def get_registry(*, include_disabled: bool = False) -> dict[str, dict[str, Any]]:
    raw = _load_raw()
    receivers = raw.get("receivers") or {}
    if not isinstance(receivers, dict) or not receivers:
        raise ValueError("Receiver registry bevat geen receivers")

    result: dict[str, dict[str, Any]] = {}
    serial_owner: dict[str, str] = {}
    alias_owner: dict[str, str] = {}

    for order, (raw_id, value) in enumerate(receivers.items(), start=1):
        receiver_id = str(raw_id or "").strip().lower()
        item = _normalise_receiver(receiver_id, value, order)

        serial_key = item["serial"].casefold()
        if serial_key in serial_owner:
            raise ValueError(
                f"Dubbel serienummer bij {receiver_id} en {serial_owner[serial_key]}"
            )
        serial_owner[serial_key] = receiver_id

        for identity in [receiver_id, *item["aliases"]]:
            if identity in alias_owner:
                raise ValueError(
                    f"Dubbele receiver-id/alias {identity}: "
                    f"{receiver_id} en {alias_owner[identity]}"
                )
            alias_owner[identity] = receiver_id

        if include_disabled or item["enabled"]:
            result[receiver_id] = item

    return result


def get_receivers(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    return [deepcopy(item) for item in get_registry(include_disabled=include_disabled).values()]


def get_receiver_ids(*, compatibility: bool = True) -> tuple[str, ...]:
    """Return enabled receiver identities in stable registry order.

    compatibility=True preserves the existing runtime aliases used by older
    callers. compatibility=False returns canonical registry identities.
    """
    receivers = get_receivers()
    key = "runtime_id" if compatibility else "id"
    return tuple(str(item[key]) for item in receivers)


def resolve_runtime_id(receiver_id: str | None) -> str | None:
    """Resolve a canonical ID or alias to the compatibility runtime ID."""
    item = get_receiver(receiver_id, include_disabled=True)
    return str(item["runtime_id"]) if item else None


def identity(receiver_id: str | None, *, include_disabled: bool = False) -> dict[str, Any] | None:
    """Return the shared identity contract used by core runtime components."""
    item = get_receiver(receiver_id, include_disabled=include_disabled)
    if item is None:
        return None
    return {
        "id": item["id"],
        "registry_id": item["id"],
        "canonical_id": item["id"],
        "runtime_id": item["runtime_id"],
        "aliases": deepcopy(item["aliases"]),
        "number": item["number"],
        "name": item["name"],
        "serial": item["serial"],
        "driver": item["driver"],
        "enabled": item["enabled"],
    }


def resolve_id(receiver_id: str | None) -> str | None:
    requested = str(receiver_id or "").strip().lower()
    if not requested:
        return None
    for item in get_receivers(include_disabled=True):
        if requested == item["id"] or requested in item["aliases"]:
            return item["id"]
    return None


def get_receiver(receiver_id: str | None, *, include_disabled: bool = False) -> dict[str, Any] | None:
    canonical = resolve_id(receiver_id)
    if canonical is None:
        return None
    item = get_registry(include_disabled=True).get(canonical)
    if not item or (not include_disabled and not item["enabled"]):
        return None
    return deepcopy(item)


def public_snapshot() -> dict[str, Any]:
    receivers = get_receivers(include_disabled=True)
    return {
        "ok": True,
        "version": "0.49.0c1",
        "authority": "static_identity_only",
        "registry_file": str(REGISTRY_FILE),
        "receiver_count": len(receivers),
        "enabled_count": sum(1 for item in receivers if item["enabled"]),
        "receivers": receivers,
        "runtime_state_in_registry": False,
    }
