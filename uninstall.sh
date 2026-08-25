#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURGE=0
[[ "${1:-}" == "--purge-data" ]] && PURGE=1
read -r -p "Remove SDRCC services and privileged integration? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
sudo systemctl disable --now sdrcc.service 2>/dev/null || true
sudo systemctl stop sdrcc-traffic-voice.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/sdrcc.service /etc/systemd/system/sdrcc-traffic-voice.service
sudo rm -f /etc/sudoers.d/sdrcc-readsb /etc/sudoers.d/sdrcc-receiver-roles /etc/sudoers.d/sdrcc-service-handover /etc/sudoers.d/sdrcc-services /etc/sudoers.d/sdrcc-traffic-voice
sudo rm -f /usr/local/sbin/sdrcc-apply-receiver-roles
sudo systemctl daemon-reload
rm -rf "$ROOT/venv"
if ((PURGE)); then rm -rf "$ROOT/data" "$ROOT/logs"; echo "Runtime data purged."; else echo "Runtime data/config/source preserved in $ROOT."; fi
echo "Third-party packages (SatDump, readsb, AIS-catcher, RTLSDR-Airband) are preserved by default because they are independent upstream software."
