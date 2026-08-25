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

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --skip-third-party) SKIP_THIRD_PARTY=1 ;;
    --destination) shift; PROJECT_ROOT="$1"; PYTHON="$PROJECT_ROOT/venv/bin/python" ;;
    *) echo "Unknown option: $1"; exit 2 ;;
  esac
  shift
done

say(){ printf '\n==> %s\n' "$*"; }
need_sudo(){ sudo -v; }

say "Preflight"
python3 "$SOURCE_ROOT/scripts/install/preflight.py"
if ((CHECK_ONLY)); then
  "$SOURCE_ROOT/scripts/install/provision_external.sh" --check || true
  exit 0
fi

say "Base Ubuntu dependencies"
need_sudo
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip git curl ca-certificates rsync \
  build-essential cmake pkg-config rtl-sdr librtlsdr-dev

if ((SKIP_THIRD_PARTY)); then
  say "External runtime dependency check"
  "$SOURCE_ROOT/scripts/install/provision_external.sh" --check
else
  "$SOURCE_ROOT/scripts/install/provision_external.sh"
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

say "Receiver detection and initial station configuration"
DETECTED_JSON="$("$PYTHON" "$PROJECT_ROOT/scripts/install/detect_receivers.py" --json || true)"
mapfile -t DETECTED_SERIALS < <(printf '%s' "$DETECTED_JSON" | "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); [print(x["serial"]) for x in d.get("receivers",[])]')
if ((${#DETECTED_SERIALS[@]} < 2)); then
  echo "FAIL: SDRCC v1.0 currently requires at least two detected RTL-SDR receivers."
  exit 4
fi
"$PYTHON" "$PROJECT_ROOT/scripts/install/detect_receivers.py" || true
serial_detected(){ local wanted="$1" item; for item in "${DETECTED_SERIALS[@]}"; do [[ "$item" == "$wanted" ]] && return 0; done; return 1; }
if ((NON_INTERACTIVE)); then
  : "${SDRCC_LOCATION:?Set SDRCC_LOCATION for --non-interactive}"
  : "${SDRCC_LATITUDE:?Set SDRCC_LATITUDE for --non-interactive}"
  : "${SDRCC_LONGITUDE:?Set SDRCC_LONGITUDE for --non-interactive}"
  : "${SDRCC_SDR1_SERIAL:?Set SDRCC_SDR1_SERIAL for --non-interactive}"
  : "${SDRCC_SDR2_SERIAL:?Set SDRCC_SDR2_SERIAL for --non-interactive}"
  STATION_NAME="${SDRCC_STATION_NAME:-SDRCC}"; ALTITUDE="${SDRCC_ALTITUDE_M:-0}"
  LOCATION="$SDRCC_LOCATION"; LATITUDE="$SDRCC_LATITUDE"; LONGITUDE="$SDRCC_LONGITUDE"
  SDR1_SERIAL="$SDRCC_SDR1_SERIAL"; SDR2_SERIAL="$SDRCC_SDR2_SERIAL"
else
  echo
  read -r -p "Station name [SDRCC]: " STATION_NAME; STATION_NAME="${STATION_NAME:-SDRCC}"
  read -r -p "Location/city: " LOCATION
  read -r -p "Latitude: " LATITUDE
  read -r -p "Longitude: " LONGITUDE
  read -r -p "Altitude metres [0]: " ALTITUDE; ALTITUDE="${ALTITUDE:-0}"
  read -r -p "Serial to use as SDR1: " SDR1_SERIAL
  read -r -p "Serial to use as SDR2: " SDR2_SERIAL
fi
serial_detected "$SDR1_SERIAL" || { echo "FAIL: SDR1 serial was not detected"; exit 4; }
serial_detected "$SDR2_SERIAL" || { echo "FAIL: SDR2 serial was not detected"; exit 4; }
"$PYTHON" "$PROJECT_ROOT/scripts/install/configure_station.py" \
  --station-name "$STATION_NAME" --location "$LOCATION" \
  --latitude "$LATITUDE" --longitude "$LONGITUDE" --altitude-m "$ALTITUDE" \
  --sdr1-serial "$SDR1_SERIAL" --sdr2-serial "$SDR2_SERIAL" --apply

say "Start and validate SDRCC"
sudo systemctl restart sdrcc.service
sleep 2
"$PYTHON" "$PROJECT_ROOT/scripts/install/validate_install.py"
HTTP="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/status || true)"
echo "Dashboard API: HTTP $HTTP"
[[ "$HTTP" == 200 ]] || exit 4

echo
echo "SDRCC clean-machine provisioning stage complete in $PROJECT_ROOT"
echo "AIS-catcher managed input may still require its first-run setup before SDRCC can transactionally swap AIS/readsb roles."
