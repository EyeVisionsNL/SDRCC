#!/usr/bin/env python3
"""Local terminal enrollment. Never transmit the authenticator seed off the host."""
import argparse
import base64
import getpass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.web_security import matching_counter
from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('public_ip')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.public_ip)
    if address.version != 4 or not address.is_global:
        parser.error('Use your public IPv4 address')
    if not sys.stdin.isatty():
        parser.error('Account setup requires a local interactive terminal')
    directory = args.project / 'data/security'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if (directory/'account.json').exists():
        if input('Dit vervangt je login en authenticator. Doorgaan? [ja/N] ').strip().lower() != 'ja':
            return 1
    username = input('Gebruikersnaam [admin]: ').strip() or 'admin'
    if len(username) > 80:
        raise SystemExit('Gebruikersnaam te lang')
    password = getpass.getpass('Nieuw wachtwoord (minimaal 12 tekens): ')
    if not 12 <= len(password) <= 1024:
        raise SystemExit('Gebruik 12 tot 1024 tekens')
    if password != getpass.getpass('Herhaal wachtwoord: '):
        raise SystemExit('Wachtwoorden verschillen')
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    uri = 'otpauth://totp/' + quote('SDRCC:' + username, safe='') + '?' + urlencode({
        'secret': secret, 'issuer': 'SDRCC', 'algorithm': 'SHA1', 'digits': 6, 'period': 30})
    import qrcode
    qr = qrcode.QRCode(border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    print('\nScan deze QR-code met je authenticator-app:')
    qr.print_ascii(invert=True)
    print('Handmatig invoeren kan ook. Geheime sleutel:', secret)
    if matching_counter(secret, getpass.getpass('Voer de 6-cijferige code in: ').strip()) is None:
        raise SystemExit('Code ongeldig; account niet gewijzigd. Controleer de tijd op pc en telefoon.')
    account = {'username': username, 'password_hash': generate_password_hash(password),
               'totp_secret': secret, 'revision': secrets.token_hex(16), 'public_ip': str(address)}
    destination = directory/'account.pending.json'
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(account, stream)
        stream.write('\n')
    print('Account voorbereid. HTTPS wordt nu ingesteld.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
