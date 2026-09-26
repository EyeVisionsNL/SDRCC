#!/usr/bin/env python3
"""Root provisioning for nginx + short-lived public-IP certificates.

Prepare exposes only ACME challenges. Activate refuses to proxy until the backend
confirms authentication is enabled. Existing nginx sites remain untouched.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

CONFIG = Path('/etc/nginx/conf.d/sdrcc-https.conf')
MARKER = '# Managed by SDRCC HTTPS setup\n'
CERTBOT = '/opt/sdrcc-certbot/bin/certbot'


def nginx_config(ip, active=False):
    result = MARKER + '''server {
    listen 80;
    server_name IP_ADDRESS;
    location ^~ /.well-known/acme-challenge/ {
        root /var/lib/sdrcc/acme;
        default_type text/plain;
        limit_except GET { deny all; }
    }
    location / { return 404; }
}
'''.replace('IP_ADDRESS', ip)
    if active:
        result += '''server {
    listen 443 ssl;
    server_name IP_ADDRESS;
    ssl_certificate /etc/letsencrypt/live/sdrcc-ip/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sdrcc-ip/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    client_max_body_size 16m;
    if ($host != "IP_ADDRESS") { return 444; }
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-SDRCC-Proxy 1;
        proxy_set_header Forwarded "";
        proxy_set_header X-Forwarded-Host "";
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_request_buffering on;
        proxy_read_timeout 3600s;
    }
}
'''.replace('IP_ADDRESS', ip)
    return result


def run(*args):
    subprocess.run(list(args), check=True)


def install_nginx_config(ip, active):
    previous = CONFIG.read_text() if CONFIG.exists() else None
    if previous is not None and not previous.startswith(MARKER):
        raise RuntimeError(f'Refusing to overwrite unmanaged {CONFIG}')
    CONFIG.write_text(nginx_config(ip, active))
    try:
        run('/usr/sbin/nginx', '-t')
        run('systemctl', 'enable', '--now', 'nginx.service')
        run('systemctl', 'reload', 'nginx.service')
    except Exception:
        if previous is None:
            CONFIG.unlink(missing_ok=True)
        else:
            CONFIG.write_text(previous)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'activate'])
    parser.add_argument('public_ip')
    parser.add_argument('--email')
    args = parser.parse_args()
    address = ipaddress.ip_address(args.public_ip)
    if address.version != 4 or not address.is_global:
        parser.error('A public IPv4 address is required')
    if os.geteuid() != 0:
        parser.error('Root rights required')
    ip = str(address)
    if args.phase == 'prepare':
        if not args.email or '\n' in args.email or '@' not in args.email:
            parser.error('An email address for the certificate is required')
        Path('/var/lib/sdrcc/acme').mkdir(parents=True, exist_ok=True)
        # Never expose the current unauthenticated backend while setting up TLS.
        install_nginx_config(ip, active=False)
        run(CERTBOT, 'certonly', '--non-interactive', '--agree-tos', '--email', args.email,
            '--cert-name', 'sdrcc-ip', '--preferred-profile', 'shortlived',
            '--webroot', '--webroot-path', '/var/lib/sdrcc/acme', '--ip-address', ip)
        Path('/etc/systemd/system/sdrcc-cert-renew.service').write_text('''[Unit]
Description=Renew SDRCC IP certificate
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/opt/sdrcc-certbot/bin/certbot renew --quiet --cert-name sdrcc-ip --deploy-hook "/usr/sbin/nginx -s reload"
''')
        Path('/etc/systemd/system/sdrcc-cert-renew.timer').write_text('''[Unit]
Description=Check SDRCC certificate twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
''')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', '--now', 'sdrcc-cert-renew.timer')
    else:
        directory = Path('/etc/systemd/system/sdrcc.service.d')
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'https.conf').write_text('[Service]\nEnvironment=SDRCC_REQUIRE_AUTH=1\nUMask=0077\n')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'sdrcc.service')
        for _ in range(60):
            try:
                with urlopen('http://127.0.0.1:8080/api/status', timeout=2) as response:
                    data = json.load(response)
                if data.get('secure_dashboard') is True:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Secure dashboard did not start; HTTPS remains unavailable. Check journalctl -u sdrcc.service')
        install_nginx_config(ip, active=True)
        print(f'SDRCC: https://{ip} — wachtwoord en authenticator vereist.')


if __name__ == '__main__':
    main()
