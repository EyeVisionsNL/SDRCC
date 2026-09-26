#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$1"
PYTHON="$PROJECT_ROOT/venv/bin/python"
[[ -t 0 ]] || { echo 'FAIL: HTTPS setup requires an interactive terminal.'; exit 2; }
[[ -x "$PYTHON" && -f "$PROJECT_ROOT/core/web_security.py" ]] || { echo 'FAIL: update SDRCC before HTTPS setup.'; exit 2; }
echo 'HTTPS + wachtwoord en authenticator voor SDRCC.'
echo 'Stuur in je router TCP 80 en 443 door naar deze pc. Verwijder forwarding van 8080.'
echo 'Poort 80 dient alleen voor certificaatcontrole. De setup herstart SDRCC.'
echo 'Stop actieve ontvangsttaken voordat je doorgaat.'
read -r -p 'Publiek IPv4-adres: ' PUBLIC_IP
read -r -p 'E-mailadres voor het certificaat: ' CERT_EMAIL
"$PYTHON" - "$PUBLIC_IP" <<'PY'
import ipaddress, sys
ip = ipaddress.ip_address(sys.argv[1])
if ip.version != 4 or not ip.is_global:
    raise SystemExit('Gebruik een publiek IPv4-adres, niet het lokale adres van de pc.')
PY
"$PYTHON" - "$PROJECT_ROOT" <<'PYCODE'
import json, sys
from pathlib import Path
state = Path(sys.argv[1]) / 'data/state/receiver_manager.json'
if state.exists():
    value = json.loads(state.read_text())
    if any(value.get(key) for key in ('reservations', 'reservation', 'binding_transaction', 'hardware_recovery')):
        raise SystemExit('Stop eerst de actieve ontvangsttaken of herstel de ontvangerstatus in SDRCC.')
PYCODE
sudo -v
sudo apt-get update
sudo apt-get install -y nginx python3-venv
"$PYTHON" -m pip install 'flask>=3.1,<4' 'waitress>=3.0.2,<4' 'qrcode>=8,<9'
sudo python3 -m venv /opt/sdrcc-certbot
sudo /opt/sdrcc-certbot/bin/pip install 'certbot>=5.4,<6'
"$PYTHON" "$PROJECT_ROOT/scripts/install/configure_web_account.py" "$PROJECT_ROOT" "$PUBLIC_IP"
sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/provision_https.py" prepare "$PUBLIC_IP" --email "$CERT_EMAIL"
mv "$PROJECT_ROOT/data/security/account.pending.json" "$PROJECT_ROOT/data/security/account.json"
sudo "$PYTHON" "$PROJECT_ROOT/scripts/install/provision_https.py" activate "$PUBLIC_IP"
