#!/usr/bin/env python3
"""Observer-only plugin execution lifecycle foundation for SDRCC v0.50.0a.

This module defines a uniform lifecycle contract and composes current plugin
observations. It never executes plugins, controls services, reserves receivers,
or changes Mission Engine state. Existing authorities remain unchanged.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from typing import Any
from core import plugin_runtime

VERSION = "0.50.0a"
SCHEMA_VERSION = 1
LIFECYCLE = (
    "INITIALIZED", "PREPARED", "EXECUTING", "MONITORING",
    "COMPLETED", "FAILED", "CLEANED_UP",
)
TERMINAL_STATES = ("COMPLETED", "FAILED", "CLEANED_UP")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _observed_phase(plugin: dict[str, Any]) -> str:
    state = str(plugin.get("runtime_state") or "").upper()
    if state == "MISSION_ACTIVE":
        return "EXECUTING"
    if state == "SERVICE_ACTIVE":
        return "MONITORING"
    if state == "RECEIVER_RESERVED":
        return "PREPARED"
    return "INITIALIZED"


def get_contract() -> dict[str, Any]:
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "foundation_only": True,
        "read_only": True,
        "behavior_changed": False,
        "execution_authority": "existing_authorities_only",
        "receiver_authority": "receiver_manager",
        "identity_authority": "receiver_registry",
        "mission_authority": "mission_engine",
        "service_authority": "existing_dashboard_systemctl_path",
        "lifecycle": list(LIFECYCLE),
        "terminal_states": list(TERMINAL_STATES),
        "operations": {
            "initialize": "describe runtime context",
            "prepare": "observe readiness and dependencies",
            "execute": "delegate to existing authority",
            "monitor": "observe existing runtime state",
            "complete": "observe successful terminal result",
            "fail": "observe non-success terminal result",
            "cleanup": "observe release and restoration",
        },
        "prohibited_authorities": [
            "direct_systemctl", "direct_process_start", "receiver_reservation",
            "mission_state_transition", "runtime_state_persistence",
        ],
    }


def get_snapshot(*, include_planned: bool = True) -> dict[str, Any]:
    observed = plugin_runtime.get_snapshot(include_planned=include_planned)
    plugins=[]
    for item in observed.get("plugins", []):
        plugin=deepcopy(item)
        plugin["lifecycle_phase"]=_observed_phase(plugin)
        plugin["lifecycle_contract_version"]=VERSION
        plugin["execution_mode"]="delegation_only"
        plugin["behavior_changed"]=False
        plugins.append(plugin)
    return {
        "ok": bool(observed.get("ok", True)),
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "source": "plugin_execution_runtime",
        "foundation_only": True,
        "read_only": True,
        "behavior_changed": False,
        "authority": "observation_and_delegation_contract_only",
        "contract": get_contract(),
        "plugin_count": len(plugins),
        "plugins": plugins,
        "observed_at": _now(),
    }
