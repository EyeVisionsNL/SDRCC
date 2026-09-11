#!/usr/bin/env bash
set -euo pipefail

# SDRCC v1.0 clean-machine installer (v0.56.0k provisioning stage)
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="${SUDO_USER:-${USER:-}}"
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
  echo "FAIL: run this installer as the normal SDRCC user (sudo is requested only when needed)."
  exit 1
fi
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
PROJECT_ROOT="${SDRCC_ROOT:-$INSTALL_HOME/SDRCC}"
PROJECT_GROUP="$(id -gn "$INSTALL_USER")"
PYTHON="$PROJECT_ROOT/venv/bin/python"
CHECK_ONLY=0
NON_INTERACTIVE=0
SKIP_THIRD_PARTY=0
AIS_SETUP_ONLY=0
INSTALL_RECEIPT="/var/lib/sdrcc/install-receipt"
[[ "${SDRCC_INSTALL_TEST_MODE:-0}" == 1 ]] && INSTALL_RECEIPT="${SDRCC_INSTALL_RECEIPT:-$INSTALL_RECEIPT}"

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --skip-third-party) SKIP_THIRD_PARTY=1 ;;
    --ais-setup) AIS_SETUP_ONLY=1 ;;
    --destination) shift; PROJECT_ROOT="$1"; PYTHON="$PROJECT_ROOT/venv/bin/python" ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
  shift
done
PROJECT_ROOT="$(realpath -m "$PROJECT_ROOT")"
PYTHON="$PROJECT_ROOT/venv/bin/python"

say(){ printf '\n==> %s\n' "$*"; }
need_sudo(){ sudo -v; }
receipt_set(){ printf '%s=%s\n' "$1" "$2" | sudo tee -a "$INSTALL_RECEIPT" >/dev/null; }
receipt_value(){
  [[ -r "$INSTALL_RECEIPT" ]] || return 0
  awk -F= -v key="$1" '$1 == key { value=substr($0, index($0, "=")+1) } END { print value }' "$INSTALL_RECEIPT"
}
receipt_default(){ [[ -n "$(receipt_value "$1")" ]] || receipt_set "$1" "$2"; }

# Explicit resume path: no reinstall, update, or station configuration rewrite.
if ((AIS_SETUP_ONLY)); then
  ((CHECK_ONLY == 0 && NON_INTERACTIVE == 0)) || { echo "FAIL: --ais-setup requires interactive setup, without --check."; exit 2; }
  [[ -x "$PYTHON" && -f "$PROJECT_ROOT/VERSION" ]] || { echo "FAIL: install FlexGround before resuming AIS setup."; exit 2; }
  need_sudo
  sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/setup_ais.py"
  sudo systemctl enable --now sdrcc.service
  HTTP=000
  for attempt in {1..60}; do
    HTTP="$(curl --max-time 5 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/status || true)"
    [[ "$HTTP" == 200 ]] && break
    sleep 1
  done
  [[ "$HTTP" == 200 ]] || { echo "FAIL: dashboard HTTP $HTTP; inspect journalctl -u sdrcc.service."; exit 4; }
  echo "FlexGround autostart enabled; dashboard HTTP 200 on port 8080."
  exit 0
fi

# Same entry point for a clean Ubuntu station and an existing installation.
if [[ -x "$PYTHON" && -f "$PROJECT_ROOT/VERSION" && "$CHECK_ONLY" == 0 ]]; then
  exec bash "$SOURCE_ROOT/scripts/install/update_existing.sh" "$SOURCE_ROOT" "$PROJECT_ROOT"
fi
say "Preflight"
python3 "$SOURCE_ROOT/scripts/install/preflight.py" || {
  ((CHECK_ONLY)) && exit 2
  echo "Missing dependencies will be installed below."
}
if ((CHECK_ONLY)); then
  "$SOURCE_ROOT/scripts/install/provision_external.sh" --check || true
  exit 0
fi

say "Base Ubuntu dependencies"
need_sudo
sudo install -d -o root -g root -m 0755 "$(dirname "$INSTALL_RECEIPT")"
if [[ ! -f "$INSTALL_RECEIPT" ]]; then
  {
    printf 'receipt_version=1\n'
    printf 'project_root_b64=%s\n' "$(printf '%s' "$PROJECT_ROOT" | base64 -w0)"
    printf 'install_user=%s\n' "$INSTALL_USER"
    printf 'legacy_install=0\n'
  } | sudo tee "$INSTALL_RECEIPT" >/dev/null
fi
sudo chmod 0644 "$INSTALL_RECEIPT"
recorded_root="$(printf '%s' "$(receipt_value project_root_b64)" | base64 -d 2>/dev/null || true)"
[[ "$recorded_root" == "$PROJECT_ROOT" ]] || { echo "FAIL: installation receipt belongs to $recorded_root"; exit 3; }
id -nG "$INSTALL_USER" | tr ' ' '\n' | grep -Fxq plugdev && receipt_default group_plugdev_preexisting 1 || receipt_default group_plugdev_preexisting 0
id -nG "$INSTALL_USER" | tr ' ' '\n' | grep -Fxq dialout && receipt_default group_dialout_preexisting 1 || receipt_default group_dialout_preexisting 0
[[ -e /etc/AIS-catcher ]] && receipt_default ais_config_preexisting 1 || receipt_default ais_config_preexisting 0
[[ -e /etc/default/readsb ]] && receipt_default readsb_config_preexisting 1 || receipt_default readsb_config_preexisting 0
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip git curl ca-certificates rsync \
  build-essential cmake pkg-config rtl-sdr librtlsdr-dev

if ((SKIP_THIRD_PARTY)); then
  say "External runtime dependency check"
  "$SOURCE_ROOT/scripts/install/provision_external.sh" --check
else
  SDRCC_INSTALL_RECEIPT="$INSTALL_RECEIPT" SDRCC_INSTALL_TEST_MODE="${SDRCC_INSTALL_TEST_MODE:-0}" "$SOURCE_ROOT/scripts/install/provision_external.sh"
fi

say "Install SDRCC source"
if [[ "$SOURCE_ROOT" != "$PROJECT_ROOT" ]]; then
  mkdir -p "$PROJECT_ROOT"
  rsync -a --delete \
    --exclude '.git/' --exclude 'venv/' --exclude 'data/' --exclude 'logs/' \
    "$SOURCE_ROOT/" "$PROJECT_ROOT/"
fi
sudo chown -R "$INSTALL_USER:$PROJECT_GROUP" "$PROJECT_ROOT"
mkdir -p "$PROJECT_ROOT/data" "$PROJECT_ROOT/logs"

say "Python environment"
if [[ ! -x "$PYTHON" ]]; then python3 -m venv "$PROJECT_ROOT/venv"; fi
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"

say "Groups"
sudo usermod -a -G plugdev,dialout "$INSTALL_USER"

say "Install privileged receiver helper"
sudo install -o root -g root -m 0755 "$PROJECT_ROOT/scripts/sdrcc_apply_receiver_roles.py" /usr/local/sbin/sdrcc-apply-receiver-roles
sudo install -o root -g root -m 0755 "$PROJECT_ROOT/scripts/sdrcc_disable_ais_autostart.py" /usr/local/sbin/sdrcc-disable-ais-autostart
sudo install -o root -g root -m 0755 "$PROJECT_ROOT/scripts/sdrcc_disable_self_autostart.py" /usr/local/sbin/sdrcc-disable-self-autostart

say "Install sudoers boundaries"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/sdrcc-readsb" <<EOF
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl start readsb.service, /usr/bin/systemctl stop readsb.service, /usr/bin/systemctl is-active readsb.service
EOF
cat >"$tmp/sdrcc-receiver-roles" <<EOF
eyeuser ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-apply-receiver-roles *
EOF
cat >"$tmp/sdrcc-service-handover" <<EOF
# SDRCC controlled receiver-service handover only.
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl stop ais-catcher-control.service
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl stop ais-catcher.service
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl stop readsb.service
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl start ais-catcher.service
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl start ais-catcher-control.service
eyeuser ALL=(root) NOPASSWD: /usr/bin/systemctl start readsb.service
EOF
cat >"$tmp/sdrcc-services" <<EOF
eyeuser ALL=NOPASSWD: /usr/bin/systemctl start ais-catcher.service
eyeuser ALL=NOPASSWD: /usr/bin/systemctl stop ais-catcher.service
eyeuser ALL=NOPASSWD: /usr/bin/systemctl restart ais-catcher.service
eyeuser ALL=NOPASSWD: /usr/bin/systemctl start readsb.service
eyeuser ALL=NOPASSWD: /usr/bin/systemctl stop readsb.service
eyeuser ALL=NOPASSWD: /usr/bin/systemctl restart readsb.service
EOF
cat >"$tmp/sdrcc-traffic-voice" <<EOF
Cmnd_Alias SDRCC_TRAFFIC_VOICE = /usr/bin/systemctl start sdrcc-traffic-voice.service, /usr/bin/systemctl stop sdrcc-traffic-voice.service
eyeuser ALL=(root) NOPASSWD: SDRCC_TRAFFIC_VOICE
EOF
cat >"$tmp/sdrcc-ais-autostart" <<EOF
eyeuser ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-ais-autostart
EOF
cat >"$tmp/sdrcc-self-autostart" <<EOF
eyeuser ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-self-autostart
EOF
for f in "$tmp"/sdrcc-*; do
  sed -i "s/^eyeuser /$INSTALL_USER /" "$f"
  sudo visudo -cf "$f" >/dev/null
  sudo install -o root -g root -m 0440 "$f" "/etc/sudoers.d/$(basename "$f")"
done

say "Install systemd units"
render_unit(){
  local src="$1" dst="$2"
  sed -e "s|@PROJECT_USER@|$INSTALL_USER|g" \
      -e "s|@PROJECT_GROUP@|$PROJECT_GROUP|g" \
      -e "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" \
      -e "s|@PYTHON@|$PYTHON|g" "$src" | sudo tee "$dst" >/dev/null
  sudo chmod 0644 "$dst"
}
render_unit "$PROJECT_ROOT/systemd/sdrcc.service.in" /etc/systemd/system/sdrcc.service
render_unit "$PROJECT_ROOT/systemd/sdrcc-traffic-voice.service.in" /etc/systemd/system/sdrcc-traffic-voice.service
sudo systemctl daemon-reload
sudo systemctl enable sdrcc.service
# Continuous receiver services deliberately remain disabled until SDRCC asks for them.
for svc in readsb.service ais-catcher.service ais-catcher-control.service sdrcc-traffic-voice.service; do
  sudo systemctl disable "$svc" >/dev/null 2>&1 || true
done

say "Station configuration (independent of receiver presence)"
if ((NON_INTERACTIVE)); then
  : "${SDRCC_LOCATION:?Set SDRCC_LOCATION}"
  : "${SDRCC_LATITUDE:?Set SDRCC_LATITUDE}"
  : "${SDRCC_LONGITUDE:?Set SDRCC_LONGITUDE}"
  STATION_NAME="${SDRCC_STATION_NAME:-FlexGround SDR}"
  LOCATION="$SDRCC_LOCATION"; LATITUDE="$SDRCC_LATITUDE"; LONGITUDE="$SDRCC_LONGITUDE"
  ALTITUDE="${SDRCC_ALTITUDE_M:-0}"
else
  echo "The following five values configure this ground station."
  echo "Latitude, longitude and altitude are used for satellite pass planning, Radio View and Doppler correction."
  echo "Use decimal degrees with a dot, for example 51.908401 and 4.351168."
  while true; do
    read -r -p "1/5 Station name (saved identifier) [FlexGround SDR]: " STATION_NAME
    STATION_NAME="${STATION_NAME:-FlexGround SDR}"
    read -r -p "2/5 Location or city (shown in Home Position): " LOCATION
    read -r -p "3/5 Latitude (-90 to 90, decimal degrees): " LATITUDE
    read -r -p "4/5 Longitude (-180 to 180, decimal degrees): " LONGITUDE
    read -r -p "5/5 Altitude above sea level in metres [0]: " ALTITUDE
    ALTITUDE="${ALTITUDE:-0}"
    echo
    echo "Station settings to save:"
    echo "  Name      : $STATION_NAME"
    echo "  Location  : $LOCATION"
    echo "  Latitude  : $LATITUDE"
    echo "  Longitude : $LONGITUDE"
    echo "  Altitude  : $ALTITUDE m ASL"
    read -r -p "Save these station settings? [Y/n] " CONFIRM_STATION
    [[ ! "$CONFIRM_STATION" =~ ^[Nn]$ ]] && break
    echo "Re-enter the station settings."
  done
fi
"$PYTHON" "$PROJECT_ROOT/scripts/install/configure_station.py" \
  --station-name "$STATION_NAME" --location "$LOCATION" \
  --latitude "$LATITUDE" --longitude "$LONGITUDE" --altitude-m "$ALTITUDE" --apply
say "AIS-catcher setup wizard"
ais_setup_args=()
((NON_INTERACTIVE)) && ais_setup_args+=(--non-interactive)
sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/setup_ais.py" "${ais_setup_args[@]}"
sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/initialize_external.py"
"$PYTHON" "$PROJECT_ROOT/scripts/install/detect_receivers.py" || true
echo "Receiver binding is handled by Receiver Manager after startup; no dongles are required."

say "Start and validate SDRCC"
sudo systemctl restart sdrcc.service
"$PYTHON" "$PROJECT_ROOT/scripts/install/validate_install.py"
HTTP=000
for attempt in {1..60}; do
  HTTP="$(curl --max-time 5 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/status || true)"
  [[ "$HTTP" == 200 ]] && break
  sleep 1
done
echo "Dashboard API: HTTP $HTTP"
[[ "$HTTP" == 200 ]] || exit 4

echo
echo "SDRCC clean-machine provisioning stage complete in $PROJECT_ROOT"
if ! sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/setup_ais.py" --check; then
  echo "AIS setup deferred. Resume with: $PROJECT_ROOT/install.sh --ais-setup"
fi
echo "FlexGround starts automatically at boot. Receiver services are started on demand by FlexGround."
