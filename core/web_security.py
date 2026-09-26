"""Single-operator password + TOTP login for the optional HTTPS listener.

Secrets and sessions stay in data/security, outside the update manifest.
No proxy-supplied identity, password-only session or LAN authentication bypass.
"""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import struct
import time

from flask import abort, g, jsonify, redirect, render_template, request
from werkzeug.security import check_password_hash

COOKIE = '__Host-sdrcc'
SESSION_SECONDS = 12 * 3600


def totp(secret, counter):
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return f'{value % 1000000:06d}'


def matching_counter(secret, code, now=None):
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    counter = int(time.time() if now is None else now) // 30
    for candidate in (counter, counter - 1, counter + 1):
        if candidate >= 0 and hmac.compare_digest(totp(secret, candidate), code):
            return candidate
    return None


class Security:
    def __init__(self, app, root, required=False):
        self.directory = Path(root) / 'data/security'
        self.account_file = self.directory / 'account.json'
        self.enabled = required or self.account_file.exists()
        app.extensions['sdrcc_security'] = self
        app.context_processor(lambda: {'security_enabled': self.enabled,
                                      'csrf_token': getattr(g, 'csrf', '')})
        if not self.enabled:
            return
        # Missing/malformed configuration must stop startup, never disable auth.
        self.account = json.loads(self.account_file.read_text())
        for key in ('username', 'password_hash', 'totp_secret', 'revision', 'public_ip'):
            if not isinstance(self.account.get(key), str) or not self.account[key]:
                raise RuntimeError('Incomplete HTTPS account; rerun local security setup')
        base64.b32decode(self.account['totp_secret'])
        self.database = self.directory / 'sessions.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, csrf TEXT NOT NULL, phase TEXT NOT NULL,
                    expires REAL NOT NULL, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (bucket TEXT PRIMARY KEY, start REAL, attempts INTEGER);
                CREATE TABLE IF NOT EXISTS otp (revision TEXT PRIMARY KEY, counter INTEGER);
            ''')
        os.chmod(self.database, 0o600)
        app.before_request(self.guard)
        app.after_request(self.headers)
        app.add_url_rule('/login', 'security_login', self.login, methods=['GET', 'POST'])
        app.add_url_rule('/login/code', 'security_code', self.code, methods=['GET', 'POST'])
        app.add_url_rule('/logout', 'security_logout', self.logout, methods=['POST'])

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def session(self, session_id):
        if not session_id:
            return None
        with self.db() as db:
            return db.execute('SELECT * FROM sessions WHERE id=? AND expires>? AND revision=?',
                              (session_id, time.time(), self.account['revision'])).fetchone()

    def new_session(self, phase):
        token = secrets.token_urlsafe(32)
        session_id = hashlib.sha256(token.encode()).hexdigest()
        csrf = secrets.token_urlsafe(32)
        duration = SESSION_SECONDS if phase == 'authenticated' else 300
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<? OR id=?',
                       (time.time(), getattr(g, 'session_id', '')))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                       (session_id, csrf, phase, time.time() + duration, self.account['revision']))
        g.new_cookie = token
        g.session_id = session_id
        g.csrf = csrf
        g.auth_session = self.session(session_id)

    def guard(self):
        # Existing root updater health probe: return only a constant, no station data.
        if (request.path == '/api/status' and request.method in ('GET', 'HEAD')
                and request.remote_addr == '127.0.0.1' and not request.is_secure
                and not request.headers.get('X-SDRCC-Proxy')):
            return jsonify(ok=True, secure_dashboard=True)
        if not request.is_secure:
            return 'HTTPS is required.', 403
        cookie = request.cookies.get(COOKIE, '')
        g.session_id = hashlib.sha256(cookie.encode()).hexdigest() if cookie else ''
        g.auth_session = self.session(g.session_id)
        g.csrf = g.auth_session['csrf'] if g.auth_session else ''
        public = request.endpoint in ('security_login', 'security_code')
        if public:
            request.max_content_length = 8192
        if not public and (not g.auth_session or g.auth_session['phase'] != 'authenticated'):
            if request.path.startswith('/api/') or request.method not in ('GET', 'HEAD'):
                return jsonify(ok=False, message='Login required'), 401
            return redirect('/login')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not g.csrf or not hmac.compare_digest(g.csrf.encode(), token.encode()):
                abort(403)

    def rate_allowed(self):
        # Persist limits across process restarts; never trust forwarded client headers here.
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM limits WHERE start<?', (now - 300,))
            for bucket, maximum in (('ip:' + str(request.remote_addr), 10), ('account', 50)):
                row = db.execute('SELECT attempts FROM limits WHERE bucket=?', (bucket,)).fetchone()
                if row and row['attempts'] >= maximum:
                    return False
            for bucket in ('ip:' + str(request.remote_addr), 'account'):
                db.execute('INSERT INTO limits VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1',
                           (bucket, now))
        return True

    def page(self, stage, error=None, status=200):
        return render_template('login.html', stage=stage, error=error), status

    def login(self):
        if g.auth_session and g.auth_session['phase'] == 'authenticated':
            return redirect('/')
        if request.method == 'GET':
            self.new_session('anonymous')
            return self.page('password')
        if not self.rate_allowed():
            return self.page('password', 'Te veel pogingen. Probeer over vijf minuten opnieuw.', 429)
        password = request.form.get('password', '')
        valid = len(password) <= 1024 and check_password_hash(self.account['password_hash'], password)
        valid = valid and hmac.compare_digest(request.form.get('username', '').encode(), self.account['username'].encode())
        if not valid:
            return self.page('password', 'Gebruikersnaam of wachtwoord klopt niet.', 401)
        self.new_session('pending')
        return redirect('/login/code')

    def code(self):
        if not g.auth_session or g.auth_session['phase'] != 'pending':
            return redirect('/login')
        if request.method == 'GET':
            return self.page('code')
        if not self.rate_allowed():
            return self.page('code', 'Te veel pogingen. Probeer over vijf minuten opnieuw.', 429)
        counter = matching_counter(self.account['totp_secret'], request.form.get('code', '').strip())
        if counter is not None:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT counter FROM otp WHERE revision=?', (self.account['revision'],)).fetchone()
                if row and counter <= row['counter']:
                    counter = None
                else:
                    db.execute('INSERT INTO otp VALUES (?,?) ON CONFLICT(revision) DO UPDATE SET counter=excluded.counter',
                               (self.account['revision'], counter))
        if counter is None:
            return self.page('code', 'Code ongeldig of al gebruikt. Wacht op de volgende code.', 401)
        self.new_session('authenticated')
        return redirect('/')

    def logout(self):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (g.session_id,))
        g.delete_cookie = True
        return redirect('/login')

    def headers(self, response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'same-origin'
        if getattr(g, 'new_cookie', None):
            response.set_cookie(COOKIE, g.new_cookie, secure=True, httponly=True, samesite='Strict', path='/')
        if getattr(g, 'delete_cookie', False):
            response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='Strict', path='/')
        # Stop long-running audio/SSE streams after logout or session expiration.
        if response.is_streamed and getattr(g, 'auth_session', None):
            iterator = response.response
            session_id = g.session_id
            def authenticated_stream():
                checked = 0
                try:
                    for chunk in iterator:
                        if time.monotonic() - checked >= 1:
                            if not self.session(session_id):
                                break
                            checked = time.monotonic()
                        yield chunk
                finally:
                    if hasattr(iterator, 'close'):
                        iterator.close()
            response.response = authenticated_stream()
        return response
