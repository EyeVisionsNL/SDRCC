#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AIRBAND_REPO="https://github.com/rtl-airband/RTLSDR-Airband.git"
AIRBAND_TAG="v5.2.0"
AIRBAND_COMMIT="61c5c4061967752da6b491a924664d72184b38fa"
AIRBAND_ROOT="/opt/sdrcc/traffic_voice"
AIRBAND_BIN="$AIRBAND_ROOT/bin/rtl_airband"
AIRBAND_PROVENANCE="$AIRBAND_ROOT/share/BUILD-PROVENANCE"
WORK="$(mktemp -d /tmp/sdrcc-airband-scan-speed.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

[[ "$(id -u)" -ne 0 ]] || { echo "FAIL: run as normal user; sudo is requested only for install"; exit 2; }
for cmd in git cmake python3; do command -v "$cmd" >/dev/null || { echo "FAIL: missing $cmd"; exit 2; }; done
sudo -v

echo "==> Rebuild pinned RTLSDR-Airband with SDRCC patches"
git clone --quiet --branch "$AIRBAND_TAG" --depth 1 "$AIRBAND_REPO" "$WORK/airband"
[[ "$(git -C "$WORK/airband" rev-parse HEAD)" == "$AIRBAND_COMMIT" ]] || { echo "FAIL: RTLSDR-Airband commit mismatch"; exit 3; }
python3 "$ROOT/scripts/install/patch_rtlsdr_airband_auto_gain.py" "$WORK/airband/src/input-rtlsdr.cpp"
python3 "$ROOT/scripts/install/patch_rtlsdr_airband_scan_interval.py" "$WORK/airband/src/rtl_airband.cpp"
cmake -S "$WORK/airband" -B "$WORK/build" \
  -DNFM=ON -DRTLSDR=ON -DMIRISDR=OFF -DSOAPYSDR=OFF -DPULSEAUDIO=OFF -DPLATFORM=native
cmake --build "$WORK/build" -j "$(nproc)"
NEW_BIN="$(find "$WORK/build" -type f -name rtl_airband -perm -111 -print -quit)"
[[ -n "$NEW_BIN" ]] || { echo "FAIL: RTLSDR-Airband binary not produced"; exit 3; }
grep -aFq 'automatic tuner gain enabled' "$NEW_BIN" || { echo "FAIL: Auto Gain patch marker missing"; exit 3; }
grep -aFq 'scan_interval_ms must be 100..500 ms' "$NEW_BIN" || { echo "FAIL: scan interval patch marker missing"; exit 3; }

sudo systemctl stop sdrcc-traffic-voice.service 2>/dev/null || true
sudo install -d -m 0755 "$AIRBAND_ROOT/bin" "$AIRBAND_ROOT/share"
sudo install -m 0755 "$NEW_BIN" "$AIRBAND_BIN"
cat >"$WORK/BUILD-PROVENANCE" <<EOF
RTLSDR-Airband 5.2.0
commit $AIRBAND_COMMIT
source git tag $AIRBAND_TAG
build options NFM=ON RTLSDR=ON MIRISDR=OFF SOAPYSDR=OFF PULSEAUDIO=OFF PLATFORM=native
SDRCC v0.56.0f auto-gain patch
behavior gain<0 => rtlsdr_set_tuner_gain_mode(dev,0); gain>=0 => existing manual path
SDRCC v0.56.0w scan-interval patch
behavior scan_interval_ms=100..500 in 50 ms steps; default 200 ms
EOF
sudo install -m 0644 "$WORK/BUILD-PROVENANCE" "$AIRBAND_PROVENANCE"

echo "PASS: installed $AIRBAND_BIN"
grep -F 'SDRCC v0.56.0w scan-interval patch' "$AIRBAND_PROVENANCE"
