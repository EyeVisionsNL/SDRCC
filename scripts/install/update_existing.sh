#!/usr/bin/env bash
set -euo pipefail
SOURCE_ROOT="$1"
PROJECT_ROOT="$2"
PYTHON="$PROJECT_ROOT/venv/bin/python"
export PYTHONPATH="$PROJECT_ROOT"
CURRENT="$(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION")"
[[ "$CURRENT" == 0.56.0p || "$CURRENT" == 0.56.0q ]] || { echo "FAIL: expected 0.56.0p or 0.56.0q, found $CURRENT"; exit 2; }
[[ "$SOURCE_ROOT" != "$PROJECT_ROOT" ]] || { echo "FAIL: extract the update next to SDRCC (for example in Downloads), then run its install.sh."; exit 2; }
"$PYTHON" "$SOURCE_ROOT/scripts/install/check_update.py" "$SOURCE_ROOT" "$PROJECT_ROOT"
"$PYTHON" "$SOURCE_ROOT/scripts/validate_receiver_flexibility_v0560q.py"
sudo -v
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT_ROOT/.rollback/v0.56.0q-r2-$STAMP"
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
echo "PASS: FlexGround SDR 0.56.0q-r2; dashboard HTTP 200"
echo "Existing station, ISS Voice, Traffic Voice and receiver configuration preserved."
echo "Backup: $BACKUP"
echo "Code rollback (when no receiver activity/recovery is pending):"
echo "  $PYTHON $BACKUP/rollback_code.py $PROJECT_ROOT $BACKUP"
