#!/usr/bin/env bash
set -euo pipefail

# SDRCC v0.56.0k clean-machine third-party provisioning.
# Installs only the established external runtimes SDRCC delegates to.
# Receiver services are left disabled/stopped; SDRCC remains their runtime authority.

MODE="install"
[[ "${1:-}" == "--check" ]] && MODE="check"
[[ "${1:-}" == "--plan" ]] && MODE="plan"

SATDUMP_REPO="https://github.com/SatDump/SatDump.git"
SATDUMP_TAG="1.2.2"
SATDUMP_COMMIT="7aef0fe"
SATDUMP_UBUNTU_2404_AMD64_URL="https://github.com/SatDump/SatDump/releases/download/1.2.2/satdump_1.2.2_ubuntu_24.04_amd64.deb"
READSB_REPO="https://github.com/wiedehopf/readsb.git"
READSB_COMMIT="cc0d099"
AIS_INSTALLER="https://raw.githubusercontent.com/jvde-github/AIS-catcher/v0.70/scripts/aiscatcher-install"
AIS_TAG="v0.70"
AIS_CONTROL_INSTALLER="https://raw.githubusercontent.com/jvde-github/AIS-catcher-control/main/install_ais_catcher_control.sh"
AIS_CONTROL_TAG="v0.1"
AIRBAND_REPO="https://github.com/rtl-airband/RTLSDR-Airband.git"
AIRBAND_TAG="v5.2.0"
AIRBAND_COMMIT="61c5c4061967752da6b491a924664d72184b38fa"
AIRBAND_ROOT="/opt/sdrcc/traffic_voice"
AIRBAND_BIN="$AIRBAND_ROOT/bin/rtl_airband"
AIRBAND_PROVENANCE="$AIRBAND_ROOT/share/BUILD-PROVENANCE"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK=""
INSTALL_RECEIPT="${SDRCC_INSTALL_RECEIPT:-}"
if [[ -n "$INSTALL_RECEIPT" && "$INSTALL_RECEIPT" != /var/lib/sdrcc/install-receipt && "${SDRCC_INSTALL_TEST_MODE:-0}" != 1 ]]; then
  echo "FAIL: non-standard receipt paths are allowed only in installer tests"
  exit 2
fi

say(){ printf '\n==> %s\n' "$*"; }
cleanup(){ if [[ -n "$WORK" ]]; then rm -rf "$WORK"; fi; return 0; }
trap cleanup EXIT
receipt_set(){
  [[ -n "$INSTALL_RECEIPT" ]] || return 0
  printf '%s=%s\n' "$1" "$2" | sudo tee -a "$INSTALL_RECEIPT" >/dev/null
}
receipt_value(){
  [[ -n "$INSTALL_RECEIPT" && -r "$INSTALL_RECEIPT" ]] || return 0
  awk -F= -v key="$1" '$1 == key { value=substr($0, index($0, "=")+1) } END { print value }' "$INSTALL_RECEIPT"
}
receipt_default(){ [[ -n "$(receipt_value "$1")" ]] || receipt_set "$1" "$2"; }
record_service_state(){
  local key="$1" service="$2"
  systemctl is-enabled --quiet "$service" 2>/dev/null && receipt_default "${key}_enabled" 1 || receipt_default "${key}_enabled" 0
  systemctl is-active --quiet "$service" 2>/dev/null && receipt_default "${key}_active" 1 || receipt_default "${key}_active" 0
}

version_line(){ "$1" -v 2>&1 | head -1 || true; }
service_disable(){
  local svc="$1"
  if systemctl list-unit-files "$svc" --no-legend 2>/dev/null | grep -q "$svc"; then
    sudo systemctl disable --now "$svc" >/dev/null 2>&1 || sudo systemctl stop "$svc" >/dev/null 2>&1 || true
  fi
}

install_satdump_official_deb(){
  local arch os_id os_version deb pkg pkg_arch
  arch="$(dpkg --print-architecture 2>/dev/null || true)"
  os_id=""
  os_version=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    os_id="${ID:-}"
    os_version="${VERSION_ID:-}"
  fi

  [[ "$os_id" == "ubuntu" && "$os_version" == "24.04" && "$arch" == "amd64" ]] || return 1

  deb="$WORK/satdump_${SATDUMP_TAG}_ubuntu_24.04_amd64.deb"
  echo "APT SatDump packages unavailable; trying official SatDump ${SATDUMP_TAG} Ubuntu 24.04 amd64 package"
  if ! curl -fL --retry 3 --connect-timeout 20 "$SATDUMP_UBUNTU_2404_AMD64_URL" -o "$deb"; then
    echo "WARN: official SatDump .deb download failed; falling back to pinned source build"
    return 1
  fi

  pkg="$(dpkg-deb -f "$deb" Package 2>/dev/null || true)"
  pkg_arch="$(dpkg-deb -f "$deb" Architecture 2>/dev/null || true)"
  if [[ "$pkg" != "satdump" || "$pkg_arch" != "amd64" ]]; then
    echo "WARN: downloaded SatDump package identity mismatch; falling back to pinned source build"
    return 1
  fi

  if ! sudo apt-get install -y "$deb"; then
    echo "WARN: official SatDump .deb install failed; falling back to pinned source build"
    return 1
  fi

  command -v satdump >/dev/null 2>&1
}

install_satdump_from_source(){
  local src="$WORK/satdump"
  local build="$src/build"
  local got_commit

  echo "Building pinned SatDump ${SATDUMP_TAG} from source"

  sudo apt-get install -y --no-install-recommends \
    g++ libfftw3-dev libpng-dev libtiff-dev libjemalloc-dev \
    libcurl4-openssl-dev libsqlite3-dev libvolk-dev libnng-dev \
    libzstd-dev libhdf5-dev librtlsdr-dev libarmadillo-dev

  git clone --quiet --recursive --depth 1 --branch "$SATDUMP_TAG" "$SATDUMP_REPO" "$src"
  got_commit="$(git -C "$src" rev-parse --short=7 HEAD)"
  [[ "$got_commit" == "$SATDUMP_COMMIT" ]] || {
    echo "FAIL: SatDump commit mismatch: expected $SATDUMP_COMMIT, got $got_commit"
    return 1
  }

  cmake -S "$src" -B "$build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DBUILD_GUI=OFF

  cmake --build "$build" --parallel "$(nproc)"
  sudo cmake --install "$build"
  if [[ -n "$INSTALL_RECEIPT" && -f "$build/install_manifest.txt" ]]; then
    sudo install -o root -g root -m 0600 "$build/install_manifest.txt" "$(dirname "$INSTALL_RECEIPT")/satdump-install-manifest.txt"
  fi
  command -v satdump >/dev/null 2>&1
}

print_plan(){
cat <<EOF
SDRCC external provisioning plan
  SatDump             KEEP existing; Ubuntu apt if available; pinned official/source fallback
  readsb              $READSB_REPO @ $READSB_COMMIT
  AIS-catcher         official installer pinned to $AIS_TAG
  AIS-catcher-control official installer, required release $AIS_CONTROL_TAG
  RTLSDR-Airband      $AIRBAND_REPO $AIRBAND_TAG @ $AIRBAND_COMMIT
  RTLSDR-Airband      SDRCC native Auto Gain patch retained
Policy: readsb/AIS/Traffic Voice services end disabled and stopped.
EOF
}

check_all(){
  local failed=0
  for cmd in satdump readsb AIS-catcher; do
    if command -v "$cmd" >/dev/null 2>&1; then echo "PASS external $cmd: $(command -v "$cmd")"; else echo "MISS external $cmd"; failed=1; fi
  done
  if command -v AIS-catcher-control >/dev/null 2>&1; then echo "PASS external AIS-catcher-control: $(command -v AIS-catcher-control)"; else echo "MISS external AIS-catcher-control"; failed=1; fi
  if [[ -x "$AIRBAND_BIN" ]]; then
    echo "PASS external RTLSDR-Airband: $(version_line "$AIRBAND_BIN")"
    if [[ -f "$AIRBAND_PROVENANCE" ]] && grep -Fq "$AIRBAND_COMMIT" "$AIRBAND_PROVENANCE" && grep -Fq 'SDRCC v0.56.0f auto-gain patch' "$AIRBAND_PROVENANCE"; then
      echo "PASS RTLSDR-Airband provenance and Auto Gain patch"
    else
      echo "FAIL RTLSDR-Airband provenance/Auto Gain patch"; failed=1
    fi
  else echo "MISS external RTLSDR-Airband"; failed=1; fi
  return "$failed"
}

[[ "$MODE" == plan ]] && { print_plan; exit 0; }
[[ "$MODE" == check ]] && { print_plan; check_all; exit $?; }

[[ "$(id -u)" -ne 0 ]] || { echo "FAIL: run as normal user; sudo is requested only for system changes."; exit 2; }
command -v sudo >/dev/null || { echo "FAIL: sudo is required"; exit 2; }
sudo -v
WORK="$(mktemp -d /tmp/sdrcc-v0560k-provision.XXXXXX)"

command -v satdump >/dev/null 2>&1 && receipt_default satdump_preexisting 1 || receipt_default satdump_preexisting 0
command -v readsb >/dev/null 2>&1 && receipt_default readsb_preexisting 1 || receipt_default readsb_preexisting 0
command -v AIS-catcher >/dev/null 2>&1 && receipt_default ais_catcher_preexisting 1 || receipt_default ais_catcher_preexisting 0
command -v AIS-catcher-control >/dev/null 2>&1 && receipt_default ais_control_preexisting 1 || receipt_default ais_control_preexisting 0
[[ -x "$AIRBAND_BIN" ]] && receipt_default airband_preexisting 1 || receipt_default airband_preexisting 0
getent passwd aiscatcher >/dev/null 2>&1 && receipt_default ais_user_preexisting 1 || receipt_default ais_user_preexisting 0
record_service_state readsb_service readsb.service
record_service_state ais_service ais-catcher.service
record_service_state ais_control_service ais-catcher-control.service

say "Ubuntu packages"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl git build-essential cmake pkg-config \
  rtl-sdr librtlsdr-dev \
  debhelper fakeroot help2man libusb-1.0-0-dev libncurses-dev zlib1g-dev libzstd-dev \
  'libconfig++-dev' libfftw3-dev libmp3lame-dev libshout3-dev

say "SatDump"
if command -v satdump >/dev/null 2>&1; then
  receipt_default satdump_installed 0
  echo "KEEP existing SatDump: $(command -v satdump)"
elif apt-cache show satdump >/dev/null 2>&1 && apt-cache show satdump-data >/dev/null 2>&1; then
  echo "Installing SatDump from configured Ubuntu repositories"
  sudo apt-get install -y --no-install-recommends satdump satdump-data
  receipt_set satdump_installed 1
  receipt_set satdump_method apt
elif install_satdump_official_deb; then
  receipt_set satdump_installed 1
  receipt_set satdump_method apt
  echo "Installed SatDump from pinned official release package"
else
  install_satdump_from_source
  receipt_set satdump_installed 1
  receipt_set satdump_method source
fi

command -v satdump >/dev/null 2>&1 || { echo "FAIL: SatDump installation did not provide satdump on PATH"; exit 3; }
echo "PASS external SatDump: $(command -v satdump)"

say "readsb $READSB_COMMIT"
if ! command -v readsb >/dev/null 2>&1; then
  git clone --quiet "$READSB_REPO" "$WORK/readsb"
  git -C "$WORK/readsb" checkout --quiet "$READSB_COMMIT"
  [[ "$(git -C "$WORK/readsb" rev-parse --short=7 HEAD)" == "$READSB_COMMIT" ]] || { echo "FAIL: readsb commit mismatch"; exit 3; }
  (
    cd "$WORK/readsb"
    export DEB_BUILD_OPTIONS=noddebs
    dpkg-buildpackage -b -ui -uc -us --build-profiles=rtlsdr
  )
  mapfile -t debs < <(find "$WORK" -maxdepth 1 -type f -name 'readsb_*.deb' -print)
  ((${#debs[@]})) || { echo "FAIL: readsb package was not produced"; exit 3; }
  sudo apt-get install -y "${debs[@]}"
  receipt_set readsb_installed 1
else
  receipt_default readsb_installed 0
  echo "KEEP existing readsb: $(readsb --version 2>&1 | head -1)"
fi
service_disable readsb.service

say "AIS-catcher $AIS_TAG"
if ! command -v AIS-catcher >/dev/null 2>&1; then
  curl -fL --retry 3 "$AIS_INSTALLER" -o "$WORK/aiscatcher-install"
  grep -q 'aiscatcher' "$WORK/aiscatcher-install" || { echo "FAIL: unexpected AIS-catcher installer content"; exit 3; }
  sudo bash "$WORK/aiscatcher-install" -p
  receipt_set ais_catcher_installed 1
else
  receipt_default ais_catcher_installed 0
  echo "KEEP existing AIS-catcher: $(command -v AIS-catcher)"
fi
service_disable ais-catcher.service

say "AIS-catcher-control $AIS_CONTROL_TAG"
if ! command -v AIS-catcher-control >/dev/null 2>&1; then
  curl -fL --retry 3 "$AIS_CONTROL_INSTALLER" -o "$WORK/ais-control-install"
  grep -Eq 'RELEASE_TAG=.*v0\.1' "$WORK/ais-control-install" || { echo "FAIL: AIS-catcher-control installer no longer pins v0.1"; exit 3; }
  sudo bash "$WORK/ais-control-install"
  receipt_set ais_control_installed 1
else
  receipt_default ais_control_installed 0
  echo "KEEP existing AIS-catcher-control: $(command -v AIS-catcher-control)"
fi
service_disable ais-catcher-control.service

say "RTLSDR-Airband $AIRBAND_TAG with SDRCC Auto Gain"
rebuild_airband=1
if [[ -x "$AIRBAND_BIN" && -f "$AIRBAND_PROVENANCE" ]] \
   && grep -Fq "$AIRBAND_COMMIT" "$AIRBAND_PROVENANCE" \
   && grep -Fq 'SDRCC v0.56.0f auto-gain patch' "$AIRBAND_PROVENANCE"; then
  rebuild_airband=0
  echo "KEEP existing pinned/patched RTLSDR-Airband"
fi
if ((rebuild_airband)); then
  git clone --quiet --branch "$AIRBAND_TAG" --depth 1 "$AIRBAND_REPO" "$WORK/airband"
  [[ "$(git -C "$WORK/airband" rev-parse HEAD)" == "$AIRBAND_COMMIT" ]] || { echo "FAIL: RTLSDR-Airband commit mismatch"; exit 3; }
  python3 "$HERE/patch_rtlsdr_airband_auto_gain.py" "$WORK/airband/src/input-rtlsdr.cpp"
  cmake -S "$WORK/airband" -B "$WORK/airband-build" \
    -DNFM=ON -DRTLSDR=ON -DMIRISDR=OFF -DSOAPYSDR=OFF -DPULSEAUDIO=OFF -DPLATFORM=native
  cmake --build "$WORK/airband-build" -j "$(nproc)"
  NEW_BIN="$(find "$WORK/airband-build" -type f -name rtl_airband -perm -111 -print -quit)"
  [[ -n "$NEW_BIN" ]] || { echo "FAIL: RTLSDR-Airband binary not produced"; exit 3; }
  grep -aFq 'automatic tuner gain enabled' "$NEW_BIN" || { echo "FAIL: patched Auto Gain marker missing"; exit 3; }
  sudo install -d -m 0755 "$AIRBAND_ROOT/bin" "$AIRBAND_ROOT/share"
  sudo install -m 0755 "$NEW_BIN" "$AIRBAND_BIN"
  git -C "$WORK/airband" archive --format=tar.gz --prefix=RTLSDR-Airband-5.2.0/ -o "$WORK/RTLSDR-Airband-5.2.0.tar.gz" HEAD
  sudo install -m 0644 "$WORK/RTLSDR-Airband-5.2.0.tar.gz" "$AIRBAND_ROOT/share/RTLSDR-Airband-5.2.0.tar.gz"
  cat >"$WORK/BUILD-PROVENANCE" <<EOF
RTLSDR-Airband 5.2.0
commit $AIRBAND_COMMIT
source git tag $AIRBAND_TAG
build options NFM=ON RTLSDR=ON MIRISDR=OFF SOAPYSDR=OFF PULSEAUDIO=OFF PLATFORM=native
SDRCC v0.56.0f auto-gain patch
behavior gain<0 => rtlsdr_set_tuner_gain_mode(dev,0); gain>=0 => existing manual path
EOF
  sudo install -m 0644 "$WORK/BUILD-PROVENANCE" "$AIRBAND_PROVENANCE"
  receipt_set airband_installed 1
else
  receipt_default airband_installed 0
fi
service_disable sdrcc-traffic-voice.service

say "External provisioning verification"
check_all

echo
echo "External SDR applications are provisioned. Receiver services remain disabled/stopped for SDRCC-controlled handover."
