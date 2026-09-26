#!/usr/bin/env bash
set -euo pipefail
SOURCE_ROOT="$1"
PROJECT_ROOT="$2"
PYTHON="$PROJECT_ROOT/venv/bin/python"
export PYTHONPATH="$PROJECT_ROOT"
CURRENT="$(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION")"
[[ "$CURRENT" == 0.56.0p || "$CURRENT" == 0.56.0q || "$CURRENT" == 0.56.0r || "$CURRENT" == 0.56.0s || "$CURRENT" == 0.56.0t || "$CURRENT" == 0.56.0x || "$CURRENT" == 0.56.0x-r1 || "$CURRENT" == 0.56.0x-r2 || "$CURRENT" == 0.56.0x-r3 || "$CURRENT" == 0.56.0x-r4 || "$CURRENT" == 0.56.0x-r5 || "$CURRENT" == 0.56.0x-r6 || "$CURRENT" == 0.56.0x-r7 || "$CURRENT" == 0.56.0x-r8 || "$CURRENT" == 0.56.0x-r9 || "$CURRENT" == 0.56.0x-r10 || "$CURRENT" =~ ^0\.(57|58|59)\.[0-9]+(-r[0-9]+)?$ ]] || { echo "FAIL: unsupported installed version $CURRENT"; exit 2; }
[[ "$SOURCE_ROOT" != "$PROJECT_ROOT" ]] || { echo "FAIL: extract the update next to SDRCC (for example in Downloads), then run its install.sh."; exit 2; }
"$PYTHON" "$SOURCE_ROOT/scripts/install/check_update.py" "$SOURCE_ROOT" "$PROJECT_ROOT"
"$PYTHON" "$SOURCE_ROOT/scripts/validate_receiver_flexibility_v0560q.py"
sudo -v
# Install/maintain Traffic Voice audio helpers only when that feature is enabled.
TRAFFIC_VOICE_ENABLED="$("$PYTHON" - <<'PYFEATURE'
from pathlib import Path
import yaml
path = Path("config/features.yaml")
if not path.exists():
    print("1")
else:
    data = yaml.safe_load(path.read_text()) or {}
    print("1" if bool((data.get("features") or {}).get("traffic_voice", True)) else "0")
PYFEATURE
)"
if [[ "$TRAFFIC_VOICE_ENABLED" == 1 ]] && ! sudo bash "$SOURCE_ROOT/scripts/install/prepare_audio_comparison.sh" "$PROJECT_ROOT" --install; then
  echo "WARNING: audio comparison dependencies unavailable; existing speech filter remains usable."
fi
INSTALL_RECEIPT="/var/lib/sdrcc/install-receipt"
[[ "${SDRCC_INSTALL_TEST_MODE:-0}" == 1 ]] && INSTALL_RECEIPT="${SDRCC_INSTALL_RECEIPT:-$INSTALL_RECEIPT}"
INSTALL_USER="$(stat -c %U "$PROJECT_ROOT")"
[[ "$INSTALL_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
  echo "FAIL: unsafe project owner: $INSTALL_USER"; exit 3;
}
if [[ ! -f "$INSTALL_RECEIPT" ]]; then
  sudo install -d -o root -g root -m 0755 "$(dirname "$INSTALL_RECEIPT")"
  {
    printf 'receipt_version=1\n'
    printf 'project_root_b64=%s\n' "$(printf '%s' "$PROJECT_ROOT" | base64 -w0)"
    printf 'install_user=%s\n' "$INSTALL_USER"
    printf 'legacy_install=1\n'
    printf 'airband_installed=1\n'
  } | sudo tee "$INSTALL_RECEIPT" >/dev/null
  sudo chmod 0644 "$INSTALL_RECEIPT"
else
  [[ "$(stat -c %u "$INSTALL_RECEIPT")" == 0 || "${SDRCC_INSTALL_TEST_MODE:-0}" == 1 ]] || {
    echo "FAIL: installation receipt is not owned by root: $INSTALL_RECEIPT"; exit 3;
  }
  RECORDED_ROOT="$(awk -F= '$1 == "project_root_b64" { value=substr($0, index($0, "=")+1) } END { print value }' "$INSTALL_RECEIPT" | base64 -d 2>/dev/null || true)"
  [[ "$RECORDED_ROOT" == "$PROJECT_ROOT" ]] || {
    echo "FAIL: installation receipt belongs to $RECORDED_ROOT"; exit 3;
  }
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT_ROOT/.rollback/${CURRENT}-$STAMP"
mkdir -p "$BACKUP/files"
cp -a "$PROJECT_ROOT/config" "$BACKUP/config"
cp -a "$SOURCE_ROOT/scripts/install/rollback_code.py" "$BACKUP/rollback_code.py"
if [[ -f "$PROJECT_ROOT/data/state/receiver_manager.json" ]]; then
  cp -a "$PROJECT_ROOT/data/state/receiver_manager.json" "$BACKUP/receiver_manager.json"
fi
WAS_ACTIVE=0
systemctl is-active --quiet sdrcc.service && WAS_ACTIVE=1
sudo systemctl stop sdrcc.service
# Recheck ownership after shutdown: a new reservation may have been made while
# preflight ran. Do not install over a persisted active task.
if ! "$PYTHON" "$SOURCE_ROOT/scripts/install/check_update.py" "$SOURCE_ROOT" "$PROJECT_ROOT"; then
  ((WAS_ACTIVE)) && sudo systemctl start sdrcc.service
  exit 3
fi
SOURCE_ROOT="$SOURCE_ROOT" PROJECT_ROOT="$PROJECT_ROOT" BACKUP="$BACKUP" "$PYTHON" - <<'PY'
import json,os,shutil
from pathlib import Path
source=Path(os.environ['SOURCE_ROOT']); project=Path(os.environ['PROJECT_ROOT']); backup=Path(os.environ['BACKUP'])
manifest=json.loads((source/'scripts/install/update_manifest.json').read_text())
created=[]
for relative in manifest:
    src=source/relative; dst=project/relative; old=backup/'files'/relative
    if dst.exists():
        old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,old)
    else:created.append(relative)
    dst.parent.mkdir(parents=True,exist_ok=True)
    temp=dst.with_name(dst.name+'.update-tmp');shutil.copy2(src,temp);os.replace(temp,dst)
(backup/'created.json').write_text(json.dumps(created))
PY
sudo install -o root -g root -m 0755 \
  "$PROJECT_ROOT/scripts/sdrcc_disable_ais_autostart.py" \
  /usr/local/sbin/sdrcc-disable-ais-autostart
sudo install -o root -g root -m 0755 \
  "$PROJECT_ROOT/scripts/sdrcc_disable_self_autostart.py" \
  /usr/local/sbin/sdrcc-disable-self-autostart
sudo install -o root -g root -m 0755 \
  "$PROJECT_ROOT/scripts/sdrcc_sync_readsb_position.py" \
  /usr/local/sbin/sdrcc-sync-readsb-position
sudo install -o root -g root -m 0755 \
  "$PROJECT_ROOT/scripts/sdrcc_update.py" \
  /usr/local/sbin/sdrcc-update
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-ais-autostart\n' \
  "$INSTALL_USER" > "$SUDOERS_TMP"
sudo visudo -cf "$SUDOERS_TMP" >/dev/null
sudo install -o root -g root -m 0440 \
  "$SUDOERS_TMP" /etc/sudoers.d/sdrcc-ais-autostart
rm -f "$SUDOERS_TMP"
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-self-autostart\n' \
  "$INSTALL_USER" > "$SUDOERS_TMP"
sudo visudo -cf "$SUDOERS_TMP" >/dev/null
sudo install -o root -g root -m 0440 \
  "$SUDOERS_TMP" /etc/sudoers.d/sdrcc-self-autostart
rm -f "$SUDOERS_TMP"
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-sync-readsb-position *\n' \
  "$INSTALL_USER" > "$SUDOERS_TMP"
sudo visudo -cf "$SUDOERS_TMP" >/dev/null
sudo install -o root -g root -m 0440 \
  "$SUDOERS_TMP" /etc/sudoers.d/sdrcc-readsb-position
rm -f "$SUDOERS_TMP"
SUDOERS_TMP="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-update ""\n' \
  "$INSTALL_USER" > "$SUDOERS_TMP"
sudo visudo -cf "$SUDOERS_TMP" >/dev/null
sudo install -o root -g root -m 0440 \
  "$SUDOERS_TMP" /etc/sudoers.d/sdrcc-update
rm -f "$SUDOERS_TMP"

HOME_POSITION="$("$PYTHON" - <<'PYHOME'
from core.config import get_home_position
position = get_home_position()
print(f"{position['latitude']}\t{position['longitude']}")
PYHOME
)"
IFS=$'\t' read -r HOME_LAT HOME_LON <<< "$HOME_POSITION"
sudo /usr/local/sbin/sdrcc-sync-readsb-position "$HOME_LAT" "$HOME_LON"
# On failure retain the backup and report diagnostics; do not reverse a completed
# hardware transaction by restoring old receiver configuration.
if ! "$PYTHON" -m compileall -q "$PROJECT_ROOT/core" "$PROJECT_ROOT/dashboard"; then
  echo "FAIL: compilation; backup available at $BACKUP"; exit 4
fi
sudo systemctl start sdrcc.service
HTTP=000
for attempt in {1..60}; do
  HTTP="$(curl --max-time 5 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/status || true)"
  [[ "$HTTP" == 200 ]] && break
  sleep 1
done
if [[ "$HTTP" != 200 ]]; then
  echo "FAIL: dashboard HTTP $HTTP; inspect sudo journalctl -u sdrcc.service -n 80 --no-pager"
  echo "Backup: $BACKUP"
  exit 4
fi
echo "PASS: SDRCC $(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION"); dashboard HTTP 200"
echo "Existing station, ISS Voice, Traffic Voice and receiver configuration preserved."
echo "This update did not replace the existing Home Position."
echo "To change it: System -> Advanced Maintenance -> Home Position."
echo "Backup: $BACKUP"
echo "Code rollback (when no receiver activity/recovery is pending):"
echo "  $PYTHON $BACKUP/rollback_code.py $PROJECT_ROOT $BACKUP"
