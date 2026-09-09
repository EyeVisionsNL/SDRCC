#!/usr/bin/env python3
"""Run the destructive uninstaller in an isolated fake system tree."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {message}")
    print(f"PASS: {message}")


with tempfile.TemporaryDirectory(prefix="sdrcc-uninstall-test-") as temporary:
    test_root = Path(temporary)
    project = test_root / "SDRCC"
    system = test_root / "system"
    state = test_root / "state"
    fake_bin = test_root / "bin"
    command_log = test_root / "commands.log"

    project.mkdir()
    (project / "core").mkdir()
    (project / "dashboard").mkdir()
    (project / "VERSION").write_text("0.56.0q\n")
    (project / "install.sh").write_text("#!/usr/bin/env bash\n")
    shutil.copy2(ROOT / "uninstall.sh", project / "uninstall.sh")

    installed_paths = [
        "/etc/systemd/system/sdrcc.service",
        "/etc/systemd/system/sdrcc-traffic-voice.service",
        "/etc/sudoers.d/sdrcc-services",
        "/usr/local/sbin/sdrcc-apply-receiver-roles",
        "/usr/bin/AIS-catcher",
        "/usr/bin/AIS-catcher-control",
        "/usr/bin/satdump",
        "/etc/default/readsb",
    ]
    for relative in installed_paths:
        path = system / relative.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n")
    for relative in ["/etc/AIS-catcher", "/usr/lib/ais-catcher", "/opt/sdrcc/traffic_voice"]:
        path = system / relative.lstrip("/")
        path.mkdir(parents=True, exist_ok=True)
        (path / "installed").write_text("test\n")

    state.mkdir()
    receipt = state / "install-receipt"
    encoded_root = base64.b64encode(str(project).encode()).decode()
    receipt.write_text(
        "receipt_version=1\n"
        f"project_root_b64={encoded_root}\n"
        f"install_user={os.environ.get('USER', 'tester')}\n"
        "satdump_installed=1\nreadsb_installed=1\nais_catcher_installed=1\n"
        "ais_control_installed=1\nairband_installed=1\n"
        "ais_config_preexisting=0\nreadsb_config_preexisting=0\n"
        "group_plugdev_preexisting=1\ngroup_dialout_preexisting=1\n"
    )

    fake_bin.mkdir()
    wrappers = {
        "sudo": '#!/usr/bin/env bash\n[[ "${1:-}" == -v ]] && exit 0\nexec "$@"\n',
        "systemctl": f'#!/usr/bin/env bash\nprintf "%s\\n" "systemctl $*" >> "{command_log}"\nexit 0\n',
        "apt-get": f'#!/usr/bin/env bash\nprintf "%s\\n" "apt-get $*" >> "{command_log}"\nexit 0\n',
        "dpkg-query": "#!/usr/bin/env bash\nexit 1\n",
        "userdel": f'#!/usr/bin/env bash\nprintf "%s\\n" "userdel $*" >> "{command_log}"\n',
        "groupdel": f'#!/usr/bin/env bash\nprintf "%s\\n" "groupdel $*" >> "{command_log}"\n',
        "gpasswd": f'#!/usr/bin/env bash\nprintf "%s\\n" "gpasswd $*" >> "{command_log}"\n',
    }
    for name, text in wrappers.items():
        path = fake_bin / name
        path.write_text(text)
        path.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        PATH=f"{fake_bin}:{environment['PATH']}",
        SDRCC_INSTALL_RECEIPT=str(receipt),
        SDRCC_SYSTEM_ROOT=str(system),
        SDRCC_INSTALL_TEST_MODE="1",
    )
    completed = subprocess.run(
        [str(project / "uninstall.sh"), "--yes"],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    check(completed.returncode == 0, f"isolated uninstall exits successfully: {completed.stderr.strip()}")
    check(not project.exists(), "project source, configuration, data and logs are removed")
    check(not receipt.exists(), "root-owned installation receipt is removed")
    check(not (system / "etc/systemd/system/sdrcc.service").exists(), "systemd integration is removed")
    check(not (system / "usr/local/sbin/sdrcc-apply-receiver-roles").exists(), "privileged helper is removed")
    check(not (system / "etc/AIS-catcher").exists(), "installer-owned AIS configuration is removed")
    check(not (system / "opt/sdrcc/traffic_voice").exists(), "installer-owned RTLSDR-Airband build is removed")
    logged = command_log.read_text()
    check("apt-get purge -y satdump satdump-data" in logged, "installer-owned SatDump packages are purged")
    check("apt-get purge -y readsb" in logged, "installer-owned readsb package is purged")

with tempfile.TemporaryDirectory(prefix="sdrcc-uninstall-preserve-test-") as temporary:
    test_root = Path(temporary)
    project = test_root / "SDRCC"
    system = test_root / "system"
    state = test_root / "state"
    fake_bin = test_root / "bin"
    command_log = test_root / "commands.log"

    (project / "core").mkdir(parents=True)
    (project / "dashboard").mkdir()
    (project / "VERSION").write_text("0.56.0q\n")
    (project / "install.sh").write_text("#!/usr/bin/env bash\n")
    shutil.copy2(ROOT / "uninstall.sh", project / "uninstall.sh")
    for relative in ["/usr/bin/satdump", "/usr/bin/AIS-catcher", "/usr/bin/AIS-catcher-control", "/opt/sdrcc/traffic_voice/bin/rtl_airband"]:
        path = system / relative.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pre-existing\n")
    for relative in ["/etc/default/readsb", "/etc/AIS-catcher/aiscatcher.json"]:
        path = system / relative.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed by FlexGround\n")
        path.with_name(path.name + ".before-flexground-initialization").write_text("original\n")

    state.mkdir()
    receipt = state / "install-receipt"
    encoded_root = base64.b64encode(str(project).encode()).decode()
    receipt.write_text(
        "receipt_version=1\n"
        f"project_root_b64={encoded_root}\n"
        "satdump_installed=0\nreadsb_installed=0\nais_catcher_installed=0\n"
        "ais_control_installed=0\nairband_installed=0\n"
        "ais_config_preexisting=1\nreadsb_config_preexisting=1\n"
        "readsb_service_enabled=1\nreadsb_service_active=1\n"
        "ais_service_enabled=1\nais_service_active=1\n"
        "ais_control_service_enabled=1\nais_control_service_active=1\n"
    )
    fake_bin.mkdir()
    wrappers = {
        "sudo": '#!/usr/bin/env bash\n[[ "${1:-}" == -v ]] && exit 0\nexec "$@"\n',
        "systemctl": f'#!/usr/bin/env bash\nprintf "%s\\n" "systemctl $*" >> "{command_log}"\nexit 0\n',
        "apt-get": f'#!/usr/bin/env bash\nprintf "%s\\n" "apt-get $*" >> "{command_log}"\nexit 0\n',
    }
    for name, text in wrappers.items():
        path = fake_bin / name
        path.write_text(text)
        path.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        PATH=f"{fake_bin}:{environment['PATH']}",
        SDRCC_INSTALL_RECEIPT=str(receipt),
        SDRCC_SYSTEM_ROOT=str(system),
        SDRCC_INSTALL_TEST_MODE="1",
    )
    completed = subprocess.run(
        [str(project / "uninstall.sh"), "--yes"],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    check(completed.returncode == 0, "receipt-aware preservation uninstall exits successfully")
    check(not project.exists(), "FlexGround is removed when external applications are preserved")
    check((system / "usr/bin/satdump").exists(), "pre-existing SatDump is preserved")
    check((system / "usr/bin/AIS-catcher").exists(), "pre-existing AIS-catcher is preserved")
    check((system / "opt/sdrcc/traffic_voice/bin/rtl_airband").exists(), "pre-existing RTLSDR-Airband is preserved")
    check((system / "etc/default/readsb").read_text() == "original\n", "pre-existing readsb configuration is restored")
    check((system / "etc/AIS-catcher/aiscatcher.json").read_text() == "original\n", "pre-existing AIS configuration is restored")
    logged = command_log.read_text()
    check("apt-get purge" not in logged, "no pre-existing external package is purged")
    check("systemctl enable readsb.service" in logged and "systemctl start readsb.service" in logged, "pre-existing service state is restored")

print("VALIDATION PASS: complete and receipt-aware FlexGround SDR uninstall")
