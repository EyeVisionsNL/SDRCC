#!/usr/bin/env python3
"""Deterministic offline validation for Receiver Authority Consolidation.

The validator uses temporary configuration files. It never calls systemctl,
never touches /etc and never changes the project configuration.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import types

import yaml


ROOT = Path(__file__).resolve().parent.parent


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def write_external_configs(readsb: Path, ais: Path, ais_serial: str, adsb_serial: str) -> None:
    readsb.write_text(
        "# readsb configuration\n"
        f'RECEIVER_OPTIONS="--device {adsb_serial} --device-type rtlsdr '
        '--gain auto --ppm 0 --lat 51.9126 --lon 4.3417"\n'
        'DECODER_OPTIONS="--max-range 450 --write-json-every 1"\n',
        encoding="utf-8",
    )
    ais.write_text(
        json.dumps({
            "receiver": [{
                "input": "RTLSDR",
                "active": True,
                "serial": ais_serial,
                "frequency": 162000000,
            }]
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    from core import config, receiver_authority, receiver_registry
    try:
        from core import receiver_monitor
    except ImportError as error:
        # The analysis fixture intentionally contains only relevant source files.
        # The complete target installation has this observer module.
        if "iss_voice_runtime" not in str(error):
            raise
        runtime_stub = types.ModuleType("core.iss_voice_runtime")
        runtime_stub.get_status = lambda: {"active": False}
        sys.modules["core.iss_voice_runtime"] = runtime_stub
        from core import receiver_monitor
    from scripts import migrate_receiver_authority_v0540a as migration
    from scripts import sdrcc_apply_receiver_roles as helper
    original_helper_service_active = helper.service_active
    original_authority_service_state = receiver_authority._service_state
    original_authority_runtime_payloads = receiver_authority._runtime_payloads
    original_authority_run = receiver_authority._run

    # This validator must never mix its temporary service configuration with the
    # host's real systemd/runtime state.  R2 did that during the transaction
    # success test, so an active readsb/AIS installation made the offline fixture
    # appear to have runtime drift.  Keep all runtime observations deterministic
    # and make any accidental host command a hard test failure.
    receiver_authority._service_state = lambda service: {
        "service": service,
        "active": False,
        "state": "inactive",
        "pid": 0,
        "observed": True,
    }
    receiver_authority._runtime_payloads = lambda: ({}, {}, {})

    def reject_host_command(*_args, **_kwargs):
        raise AssertionError("offline validator attempted a host command")

    receiver_authority._run = reject_host_command

    original_station = yaml.safe_load(
        (ROOT / "config/station.yaml").read_text(encoding="utf-8")
    )
    original_registry = yaml.safe_load(
        (ROOT / "config/receivers.yaml").read_text(encoding="utf-8")
    )
    migrated_station, migrated_registry, report = migration.build_migration(
        original_station, original_registry
    )
    check("migration reports one authority", report["assignment_authority"].endswith(":assignments"))
    check("legacy mission mapping removed", "mission_assignments" not in migrated_station)
    check("legacy defaults mapping removed", "receiver_defaults" not in migrated_station)

    before_serials = {
        receiver_id: str((payload.get("hardware") or {}).get("serial"))
        for receiver_id, payload in original_registry["receivers"].items()
    }
    after_serials = {
        receiver_id: str((payload.get("hardware") or {}).get("serial"))
        for receiver_id, payload in migrated_registry["receivers"].items()
    }
    check("registry identities remain immutable", before_serials == after_serials)
    required = {"weather", "ais", "adsb", "iss_voice"}
    check(
        "both receivers support flexible roles",
        all(
            required.issubset(set(payload.get("capabilities") or []))
            for payload in migrated_registry["receivers"].values()
        ),
    )

    previous_paths = {
        "station": config.STATION_CONFIG,
        "registry_config": config.RECEIVERS_CONFIG,
        "registry": receiver_registry.REGISTRY_FILE,
        "readsb": receiver_authority.READSB_CONFIG,
        "ais": receiver_authority.AIS_CONFIG,
        "helper_readsb": helper.READSB_CONFIG,
        "helper_ais": helper.AIS_CONFIG,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="sdrcc-v0540a-") as temporary:
            temp = Path(temporary)
            station_file = temp / "station.yaml"
            registry_file = temp / "receivers.yaml"
            readsb_file = temp / "readsb"
            ais_file = temp / "aiscatcher.json"
            write_yaml(station_file, migrated_station)
            write_yaml(registry_file, migrated_registry)

            config.STATION_CONFIG = station_file
            config.RECEIVERS_CONFIG = registry_file
            receiver_registry.REGISTRY_FILE = registry_file
            receiver_authority.READSB_CONFIG = readsb_file
            receiver_authority.AIS_CONFIG = ais_file
            helper.READSB_CONFIG = readsb_file
            helper.AIS_CONFIG = ais_file

            assignments = config.get_receiver_assignments()
            ais_serial, adsb_serial = receiver_authority.service_serials(assignments)
            write_external_configs(readsb_file, ais_file, ais_serial, adsb_serial)
            inactive = {
                "ais": {"active": False, "state": "inactive", "pid": 0},
                "adsb": {"active": False, "state": "inactive", "pid": 0},
            }
            snapshot = receiver_authority.get_snapshot(
                service_states=inactive,
                mission_status={},
                weather_runtime={},
                iss_runtime={},
                use_cache=False,
            )
            check("aligned external configuration is in sync", snapshot["status"] == "IN_SYNC")
            check("inactive services are configured, not guessed", not snapshot["verified_runtime_assignments"])
            check(
                "actual RECEIVER_OPTIONS form is parsed by observer",
                snapshot["roles"]["adsb"]["service_config_serial"] == adsb_serial,
            )
            helper.service_active = lambda _service: False
            no_op = helper.apply(ais_serial, adsb_serial)
            check(
                "installer adapter accepts aligned actual system form",
                no_op["ok"] is True and no_op["changed"] is False,
            )

            readsb_before = readsb_file.read_text(encoding="utf-8")
            helper.write_readsb_serial("05419737")
            readsb_after = readsb_file.read_text(encoding="utf-8")
            check(
                "actual RECEIVER_OPTIONS form is rewritten by adapter",
                helper.read_readsb_serial() == "05419737",
            )
            check(
                "readsb rewrite preserves all unrelated options",
                readsb_after == readsb_before.replace(
                    f"--device {adsb_serial}", "--device 05419737", 1
                ),
            )
            write_external_configs(readsb_file, ais_file, ais_serial, adsb_serial)

            readsb_file.write_text(
                '# READSB_ARGS="--device COMMENTED"\n'
                f'READSB_ARGS="--net --device={adsb_serial} --gain auto"\n',
                encoding="utf-8",
            )
            check(
                "equals form is parsed and commented device is ignored",
                helper.read_readsb_serial() == adsb_serial,
            )
            helper.write_readsb_serial("05419737")
            check(
                "equals form is rewritten without activating comment",
                helper.read_readsb_serial() == "05419737"
                and "COMMENTED" in readsb_file.read_text(encoding="utf-8"),
            )
            write_external_configs(readsb_file, ais_file, ais_serial, adsb_serial)

            readsb_file.write_text(
                'RECEIVER_OPTIONS="--device WRONG-SERIAL --gain auto"\n', encoding="utf-8"
            )
            drift = receiver_authority.get_snapshot(
                service_states=inactive,
                mission_status={},
                weather_runtime={},
                iss_runtime={},
                use_cache=False,
            )
            check("service configuration drift detected", drift["status"] == "DRIFT")
            check(
                "ADS-B mismatch is explicit",
                any(
                    item["role"] == "adsb" and item["type"] == "service_config_serial_mismatch"
                    for item in drift["drift"]
                ),
            )
            write_external_configs(readsb_file, ais_file, ais_serial, adsb_serial)

            before = deepcopy(config.get_receiver_assignments())
            failed_adapter_calls = []

            def fail_once_then_restore(next_ais: str, next_adsb: str) -> dict:
                failed_adapter_calls.append((next_ais, next_adsb))
                if len(failed_adapter_calls) == 1:
                    return {"ok": False, "message": "simulated adapter failure"}
                write_external_configs(readsb_file, ais_file, next_ais, next_adsb)
                return {"ok": True, "changed": False}

            failed = receiver_authority.apply_assignments(
                {"weather": "sdr2" if before["weather"] == "sdr1" else "sdr1"},
                privileged_apply=fail_once_then_restore,
            )
            check("failed adapter returns failure", failed["ok"] is False)
            check("failed transaction performs rollback", failed["rollback_performed"] is True)
            check("failed transaction re-applies previous service config", len(failed_adapter_calls) == 2)
            check("failed transaction rollback completes", failed["rollback_ok"] is True)
            check("authority restored after failure", config.get_receiver_assignments() == before)
            persisted = yaml.safe_load(station_file.read_text(encoding="utf-8"))
            check("rollback does not recreate mission mapping", "mission_assignments" not in persisted)
            check("rollback does not recreate defaults mapping", "receiver_defaults" not in persisted)

            swapped = {"ais": before["adsb"], "adsb": before["ais"]}

            def fake_apply(next_ais: str, next_adsb: str) -> dict:
                write_external_configs(readsb_file, ais_file, next_ais, next_adsb)
                return {"ok": True, "changed": True, "runtime_verified": {}}

            succeeded = receiver_authority.apply_assignments(
                swapped,
                privileged_apply=fake_apply,
            )
            check("successful transaction commits authority", succeeded["ok"] is True)
            check("successful transaction reports no rollback", succeeded["rollback_performed"] is False)
            check("service configurations follow authority", succeeded["verification"]["status"] == "IN_SYNC")
            check(
                "transaction validation is isolated from host runtime",
                all(
                    not succeeded["verification"]["roles"][role]["runtime_active"]
                    for role in ("ais", "adsb")
                ),
            )

            helper.write_readsb_serial("24006572")
            helper.write_ais_serial("05419737")
            check("standalone helper rewrites readsb safely", helper.read_readsb_serial() == "24006572")
            check("standalone helper rewrites AIS safely", helper.read_ais_serial() == "05419737")
    finally:
        config.STATION_CONFIG = previous_paths["station"]
        config.RECEIVERS_CONFIG = previous_paths["registry_config"]
        receiver_registry.REGISTRY_FILE = previous_paths["registry"]
        receiver_authority.READSB_CONFIG = previous_paths["readsb"]
        receiver_authority.AIS_CONFIG = previous_paths["ais"]
        helper.READSB_CONFIG = previous_paths["helper_readsb"]
        helper.AIS_CONFIG = previous_paths["helper_ais"]
        helper.service_active = original_helper_service_active
        receiver_authority._service_state = original_authority_service_state
        receiver_authority._runtime_payloads = original_authority_runtime_payloads
        receiver_authority._run = original_authority_run
        receiver_authority.invalidate_cache()

    app_source = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    monitor_source = (ROOT / "core/receiver_monitor.py").read_text(encoding="utf-8")
    check("dashboard transaction uses existing privileged boundary", "/usr/local/sbin/sdrcc-apply-receiver-roles" in app_source)
    check(
        "dashboard leaves service PID observation to Assignment Authority",
        'service_states={"ais": ais, "adsb": adsb}' not in app_source,
    )
    check("Receiver Monitor consumes authority snapshot", "authority_snapshot" in monitor_source)
    check("Receiver Monitor exposes drift", "configuration_drift" in monitor_source)

    original_ais_metrics = receiver_monitor.get_ais_metrics
    original_adsb_metrics = receiver_monitor.get_adsb_metrics
    original_iss_status = receiver_monitor.iss_voice_runtime.get_status
    try:
        receiver_monitor.get_ais_metrics = lambda active: {
            "available": active,
            "service_active": active,
            "detail": "fixture AIS",
        }
        receiver_monitor.get_adsb_metrics = lambda active: {
            "available": active,
            "service_active": active,
            "detail": "fixture ADS-B",
        }
        receiver_monitor.iss_voice_runtime.get_status = lambda: {"active": False}
        devices = [
            {"id": "sdr1", "name": "SDR1", "serial": "05419737"},
            {"id": "sdr2", "name": "SDR2", "serial": "24006572"},
        ]
        role_template = {
            "runtime_active": False,
            "runtime_verified": False,
            "verified_runtime_receiver": None,
            "configuration_drift": False,
        }
        synthetic_authority = {
            "assignment_authority": "config/station.yaml:assignments",
            "status": "UNVERIFIED",
            "configuration_drift": False,
            "drift": [],
            "roles": {
                "weather": {**role_template, "role": "weather", "configured_receiver": "sdr1"},
                "ais": {**role_template, "role": "ais", "configured_receiver": "sdr1"},
                "adsb": {
                    **role_template,
                    "role": "adsb",
                    "configured_receiver": "sdr2",
                    "runtime_active": True,
                    "service_active": True,
                },
                "iss_voice": {**role_template, "role": "iss_voice", "configured_receiver": "sdr2"},
            },
        }
        monitor = receiver_monitor.get_snapshot(
            devices=devices,
            assignments={"weather": "sdr1", "ais": "sdr1", "adsb": "sdr2", "iss_voice": "sdr2"},
            ais_service={"active": False},
            adsb_service={"active": True},
            mission={},
            live_rf={},
            authority_snapshot=synthetic_authority,
        )
        row = next(item for item in monitor["receivers"] if item["id"] == "sdr2")
        check("unverified active service claims no receiver role", row["role"] == "IDLE")
        check("unverified active service is explicit", row["status"] == "UNVERIFIED")

        synthetic_authority["status"] = "DRIFT"
        synthetic_authority["configuration_drift"] = True
        synthetic_authority["roles"]["adsb"].update({
            "verified_runtime_receiver": "sdr1",
            "configuration_drift": True,
        })
        synthetic_authority["drift"] = [{"role": "adsb", "type": "runtime_receiver_mismatch"}]
        monitor = receiver_monitor.get_snapshot(
            devices=devices,
            assignments={"weather": "sdr1", "ais": "sdr1", "adsb": "sdr2", "iss_voice": "sdr2"},
            ais_service={"active": False},
            adsb_service={"active": True},
            mission={},
            live_rf={},
            authority_snapshot=synthetic_authority,
        )
        actual = next(item for item in monitor["receivers"] if item["id"] == "sdr1")
        check("verified mismatch is attributed to actual receiver", actual["role"] == "ADS-B")
        check("verified mismatch remains drift", actual["status"] == "DRIFT")
    finally:
        receiver_monitor.get_ais_metrics = original_ais_metrics
        receiver_monitor.get_adsb_metrics = original_adsb_metrics
        receiver_monitor.iss_voice_runtime.get_status = original_iss_status
    print("VALIDATION PASS: SDRCC v0.54.0a Receiver Authority Consolidation")


if __name__ == "__main__":
    main()
