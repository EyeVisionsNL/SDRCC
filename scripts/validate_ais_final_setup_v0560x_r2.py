#!/usr/bin/env python3
"""Validate final-step AIS setup design without touching live services."""

from pathlib import Path
import importlib.util
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load("setup_ais", ROOT / "scripts/install/setup_ais.py")
initializer = load("initialize_external", ROOT / "scripts/install/initialize_external.py")

failed = False


def check(name, condition):
    global failed
    print(("PASS" if condition else "FAIL") + ": " + name)
    failed |= not condition


# ------------------------------------------------------------
# Installer order
# ------------------------------------------------------------
install = (ROOT / "install.sh").read_text()

markers = [
    "Initialise external service configs",
    "Detect receivers",
    "Start and validate SDRCC",
    "Final AIS-catcher setup",
    "SDRCC clean-machine provisioning stage complete",
]

positions = [install.index(marker) for marker in markers]

check(
    "AIS wizard is final configuration step",
    positions == sorted(positions),
)

check(
    "RTL-SDR choices shown for AIS setup",
    "show_rtlsdr_choices" in install,
)

check(
    "--ais-setup also shows RTL-SDR choices",
    "if ((AIS_SETUP_ONLY)); then" in install
    and "show_rtlsdr_choices" in install[
        install.index("if ((AIS_SETUP_ONLY)); then"):
        install.index("# Same entry point")
    ],
)


# ------------------------------------------------------------
# initialize_external must never create AIS config
# ------------------------------------------------------------
init_source = (ROOT / "scripts/install/initialize_external.py").read_text()

check(
    "initialize_external contains no UNBOUND_AIS",
    "UNBOUND_AIS" not in init_source,
)

check(
    "initialize_external does not reference aiscatcher.json",
    "aiscatcher.json" not in init_source,
)

with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)

    readsb = directory / "readsb"
    readsb.write_text(
        'RECEIVER_OPTIONS="--device-type rtlsdr --gain auto"\n'
    )

    ais = directory / "aiscatcher.json"
    ais.write_text('{"sentinel":"must-stay-untouched"}\n')

    before = ais.read_text()
    initializer.initialize(readsb=readsb)

    check(
        "readsb still receives UNBOUND_ADSB placeholder",
        "--device UNBOUND_ADSB" in readsb.read_text(),
    )

    check(
        "AIS sentinel untouched by initializer",
        ais.read_text() == before,
    )


# ------------------------------------------------------------
# AIS validation rules
# ------------------------------------------------------------
def cfg(serial="05419737", wizard=False, engine="on", receivers=None):
    if receivers is None:
        receivers = [{
            "active": True,
            "input": "RTLSDR",
            "serial": serial,
        }]
    return {
        "engine": engine,
        "control": {"wizard": wizard},
        "receiver": receivers,
    }


check(
    "one real RTL-SDR is configured",
    setup.configured(cfg()) is True,
)

check(
    "lingering wizard flag detected after Save & Close",
    setup.configured(cfg(wizard=True)) is False
    and setup.wizard_saved(cfg(wizard=True)) is True,
)

check(
    "UNBOUND receiver rejected",
    setup.receiver_configured(cfg(serial="UNBOUND_AIS")) is False,
)

check(
    "empty serial rejected",
    setup.receiver_configured(cfg(serial="")) is False,
)

check(
    "real receiver plus empty second input rejected",
    setup.receiver_configured(cfg(receivers=[
        {"active": True, "input": "RTLSDR", "serial": "05419737"},
        {"active": True, "input": "RTLSDR", "serial": ""},
    ])) is False,
)

check(
    "two real active RTL-SDR inputs rejected",
    setup.receiver_configured(cfg(receivers=[
        {"active": True, "input": "RTLSDR", "serial": "05419737"},
        {"active": True, "input": "RTLSDR", "serial": "24006572"},
    ])) is False,
)

raise SystemExit(1 if failed else 0)
