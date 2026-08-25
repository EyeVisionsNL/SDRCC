\
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -d "$ROOT/.git" ]] || { echo "Update requires a Git checkout; release-tar updates will be added with v1.0 packaging."; exit 2; }
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || { echo "FAIL: working tree is not clean"; exit 3; }
BACKUP="$HOME/sdrcc-backups/update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP/config"
cp -a "$ROOT/config/." "$BACKUP/config/"
git -C "$ROOT" pull --ff-only
"$ROOT/venv/bin/pip" install -r "$ROOT/requirements.txt"
sudo systemctl restart sdrcc.service
"$ROOT/venv/bin/python" "$ROOT/scripts/install/validate_install.py"
echo "Update complete. Config backup: $BACKUP"
