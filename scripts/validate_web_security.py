#!/usr/bin/env python3
"""Exercise real Flask login, persistent sessions and generated proxy policy."""
import base64
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask import Flask, Response
from werkzeug.security import generate_password_hash
from core.web_security import Security, COOKIE, totp, matching_counter

spec = importlib.util.spec_from_file_location('provision', ROOT/'scripts/install/provision_https.py')
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)
SECRET = base64.b32encode(b'12345678901234567890').decode()
PASSWORD = 'a long test password'


class Authentication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash(PASSWORD)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        directory = self.root/'data/security'
        directory.mkdir(parents=True)
        (directory/'account.json').write_text(json.dumps(dict(
            username='admin', password_hash=self.password_hash, totp_secret=SECRET,
            revision='test-revision', public_ip='8.8.8.8')))
        self.app, self.security = self.make_app()
        self.client = self.app.test_client()

    def make_app(self):
        app = Flask(__name__, template_folder=str(ROOT/'dashboard/templates'))
        app.config['TESTING'] = True
        security = Security(app, self.root, required=True)
        app.add_url_rule('/', 'home', lambda: 'station data')
        app.add_url_rule('/api/action', 'action', lambda: 'acted', methods=['POST'])
        app.add_url_rule('/api/audio', 'audio', lambda: Response(iter([b'one', b'two'])))
        return app, security

    def request(self, method, path, **kwargs):
        return self.client.open(path, method=method, base_url='https://8.8.8.8', **kwargs)

    def token(self, response):
        return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()

    def password_step(self):
        response = self.request('GET', '/login')
        token = self.token(response)
        response = self.request('POST', '/login', data=dict(username='admin', password=PASSWORD, csrf_token=token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/login/code')
        return self.token(self.request('GET', '/login/code'))

    def authenticate(self):
        token = self.password_step()
        response = self.request('POST', '/login/code', data={'csrf_token': token, 'code':totp(SECRET, int(time.time())//30)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/')
        cookie = self.client.get_cookie(COOKIE, domain='8.8.8.8').value
        import hashlib
        sid = hashlib.sha256(cookie.encode()).hexdigest()
        return self.security.session(sid)['csrf'], sid

    def test_totp_rfc6238_vectors(self):
        for stamp, code in [(59,'287082'), (1111111109,'081804'), (1111111111,'050471'), (1234567890,'005924'), (2000000000,'279037'), (20000000000,'353130')]:
            self.assertEqual(totp(SECRET, stamp//30), code)
            self.assertEqual(matching_counter(SECRET,code,stamp), stamp//30)
        self.assertIsNone(matching_counter(SECRET, '１２３４５６', 59))

    def test_anonymous_all_routes_protected_and_http_denied(self):
        for path in ('/', '/api/audio', '/static/css/base.css', '/capture/private', '/api/events'):
            self.assertIn(self.request('GET',path).status_code, (302,401))
        self.assertEqual(self.request('POST','/api/action').status_code,401)
        self.assertEqual(self.client.get('/', base_url='http://8.8.8.8').status_code,403)

    def test_local_health_only_no_proxy_bypass(self):
        response=self.client.get('/api/status')
        self.assertEqual(response.json, {'ok':True,'secure_dashboard':True})
        self.assertEqual(self.client.get('/api/status',headers={'X-SDRCC-Proxy':'1'}).status_code,403)
        self.assertEqual(self.client.get('/api/status',environ_overrides={'REMOTE_ADDR':'192.168.1.2'}).status_code,403)
        self.assertEqual(self.request('GET','/api/status').status_code,401)

    def test_password_is_only_first_factor_and_cookie_rotates(self):
        self.password_step()
        pending=self.client.get_cookie(COOKIE,domain='8.8.8.8').value
        self.assertEqual(self.request('GET','/api/audio').status_code,401)
        csrf=self.token(self.request('GET','/login/code'))
        response=self.request('POST','/login/code',data={'csrf_token':csrf,'code':totp(SECRET,int(time.time())//30)})
        self.assertEqual(response.status_code,302)
        cookie=self.client.get_cookie(COOKIE,domain='8.8.8.8')
        self.assertNotEqual(cookie.value,pending)
        self.assertTrue(cookie.secure and cookie.http_only)
        self.assertEqual(cookie.same_site,'Strict')
        self.assertEqual(self.request('GET','/').data,b'station data')
        self.client.set_cookie(COOKIE,pending,domain='8.8.8.8')
        self.assertEqual(self.request('GET','/api/audio').status_code,401)

    def test_csrf_and_cross_origin(self):
        token,sid=self.authenticate()
        self.assertEqual(self.request('POST','/api/action').status_code,403)
        self.assertEqual(self.request('POST','/api/action',headers={'X-CSRF-Token':token,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.request('POST','/api/action',headers={'X-CSRF-Token':token,'Origin':'https://8.8.8.8'}).status_code,200)
        self.assertEqual(self.request('GET','/logout').status_code,405)
        self.assertEqual(self.request('POST','/logout',data={'csrf_token':token}).status_code,302)
        self.assertIsNone(self.security.session(sid))
        self.assertEqual(self.request('GET','/api/audio').status_code,401)

    def test_favicon_does_not_replace_login_session(self):
        token = self.token(self.request('GET', '/login'))
        original = self.client.get_cookie(COOKIE, domain='8.8.8.8').value
        for path in ('/favicon.ico', '/static/assets/sdrcc-favicon.png', '/missing-image.png'):
            response = self.request('GET', path, headers={'Sec-Fetch-Dest':'image'}, follow_redirects=True)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(self.client.get_cookie(COOKIE, domain='8.8.8.8').value, original)
        # Even an unrelated redirect or another tab cannot rotate the password session.
        second = self.request('GET', '/login')
        self.assertEqual(self.token(second), token)
        response = self.request('POST', '/login', data={'username':'admin', 'password':PASSWORD, 'csrf_token':token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/login/code')
        pending = self.client.get_cookie(COOKIE, domain='8.8.8.8').value
        self.request('GET', '/favicon.ico', follow_redirects=True)
        self.assertEqual(self.client.get_cookie(COOKIE, domain='8.8.8.8').value, pending)
        self.assertEqual(self.request('GET', '/login/code').status_code, 200)

    def test_login_csrf_and_wrong_password(self):
        token=self.token(self.request('GET','/login'))
        self.assertEqual(self.request('POST','/login',data={'username':'admin','password':PASSWORD}).status_code,403)
        self.assertEqual(self.request('POST','/login',data={'username':'admin','password':'wrong','csrf_token':token}).status_code,401)

    def test_otp_replay_survives_restart(self):
        token,sid=self.authenticate()
        self.request('POST','/logout',data={'csrf_token':token})
        self.app,self.security=self.make_app()
        self.client=self.app.test_client()
        token=self.password_step()
        response=self.request('POST','/login/code',data={'csrf_token':token,'code':totp(SECRET,int(time.time())//30)})
        self.assertEqual(response.status_code,401)

    def test_rate_limit_persists(self):
        token=self.token(self.request('GET','/login'))
        for _ in range(10):
            self.assertEqual(self.request('POST','/login',data={'username':'admin','password':'wrong','csrf_token':token}).status_code,401)
        self.assertEqual(self.request('POST','/login',data={'username':'admin','password':PASSWORD,'csrf_token':token}).status_code,429)
        self.app,self.security=self.make_app()
        self.client=self.app.test_client()
        token=self.token(self.request('GET','/login'))
        self.assertEqual(self.request('POST','/login',data={'username':'admin','password':PASSWORD,'csrf_token':token}).status_code,429)

    def test_expired_session_and_changed_account(self):
        token,sid=self.authenticate()
        with self.security.db() as db:
            db.execute('UPDATE sessions SET expires=0 WHERE id=?',(sid,))
        self.assertEqual(self.request('GET','/api/audio').status_code,401)
        self.security.account['revision']='new-account'
        self.assertIsNone(self.security.session(sid))

    def test_missing_required_config_fails_closed_and_opt_in(self):
        self.security.account_file.unlink()
        with self.assertRaises(FileNotFoundError):
            self.make_app()
        app=Flask('local')
        security=Security(app,self.root)
        self.assertFalse(security.enabled)

    def test_actual_dashboard_routes_are_guarded(self):
        with patch('core.web_security.Security', side_effect=lambda app, root, required=False: Security(app, self.root, required=True)):
            from dashboard.app import app
        client = app.test_client()
        for rule in app.url_map.iter_rules():
            if rule.endpoint in ('security_login', 'security_code'):
                continue
            path = str(rule)
            path = re.sub(r'<(?:[^:>]+:)?[^>]+>', 'test', path)
            method = 'GET' if 'GET' in rule.methods else 'POST'
            response = client.open(path, method=method, base_url='https://8.8.8.8')
            self.assertIn(response.status_code, (302, 401), path)
        self.app, self.security, self.client = app, app.extensions['sdrcc_security'], client
        self.authenticate()
        response = self.request('GET', '/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'meta name="csrf-token"', response.data)
        self.assertIn(b'action="/logout"', response.data)

    def test_stream_stops_after_session_revocation(self):
        token, sid = self.authenticate()
        response = self.request('GET', '/api/audio', buffered=False)
        iterator = iter(response.response)
        self.assertEqual(next(iterator), b'one')
        with self.security.db() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))
        with patch('core.web_security.time.monotonic', return_value=time.monotonic()+2):
            with self.assertRaises(StopIteration):
                next(iterator)
        response.close()

    def test_nginx_bootstrap_never_exposes_backend(self):
        initial=provision.nginx_config('8.8.8.8')
        final=provision.nginx_config('8.8.8.8',True)
        self.assertNotIn('proxy_pass',initial)
        self.assertIn('location / { return 404; }',initial)
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;',final)
        self.assertNotIn('$proxy_add_x_forwarded_for',final)
        self.assertIn('proxy_set_header X-SDRCC-Proxy 1;',final)
        self.assertIn('ssl_protocols TLSv1.2 TLSv1.3;',final)
        self.assertIn('proxy_buffering off;',final)


if __name__=='__main__':
    unittest.main(verbosity=2)
