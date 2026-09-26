"""Authenticated, fixed-target HTTP bridges for local radio map viewers.

Every request passes the normal SDRCC guard. No arbitrary target, credential
forwarding, upstream redirects or unauthenticated nginx exception is allowed.
"""
import re
from urllib.parse import quote, urljoin, urlsplit

import requests
from flask import Response, abort, g, redirect, request

TARGETS = {
    'ais': 'http://127.0.0.1:8119/',
    'adsb': 'http://127.0.0.1/tar1090/',
}
MAX_BODY = 32 * 1024 * 1024


def upstream_url(viewer, path, query=b''):
    if viewer not in TARGETS:
        raise ValueError('Unknown viewer')
    # Flask already percent-decodes the route once. Reject remaining escapes
    # rather than letting another HTTP server interpret an ambiguous path.
    if (path.startswith('/') or any(c in path for c in ('\\', '%', '\x00', '?', '#'))
            or any(part in ('.', '..') for part in path.split('/'))):
        raise ValueError('Invalid viewer path')
    url = TARGETS[viewer] + quote(path, safe='/@-._~')
    if query:
        url += '?' + query.decode('ascii')
    return url


def rewrite_html(html, viewer, csrf):
    prefix = '/web/' + viewer + '/'
    upstream_path = urlsplit(TARGETS[viewer]).path
    def rooted(match):
        path = match.group(3)
        if upstream_path != '/' and path.startswith(upstream_path):
            path = path[len(upstream_path):]
        else:
            path = path.lstrip('/')
        return match.group(1) + match.group(2) + prefix + path
    # Handle root-relative scripts, styles, icons, forms and links. Ordinary
    # relative URLs and external https:// or // tile sources remain untouched.
    html = re.sub(r'((?:src|href|action)\s*=\s*)([\"\'])(/(?!/)[^\"\']*)', rooted, html, flags=re.I)
    from markupsafe import escape
    bridge = ('<meta name="sdrcc-view-prefix" content="' + prefix + '">'
              '<meta name="sdrcc-view-upstream-path" content="' + upstream_path + '">'
              '<meta name="csrf-token" content="' + str(escape(csrf)) + '">'
              '<script src="/static/js/web_view_bridge.js?v=0.60.0-r3"></script>')
    # Install before the viewer's own scripts run.
    if re.search(r'<head\b[^>]*>', html, re.I):
        return re.sub(r'(<head\b[^>]*>)', lambda m: m.group(1) + bridge, html, count=1, flags=re.I)
    return bridge + html


def register(app):
    @app.route('/web/<viewer>/', defaults={'path': ''}, methods=['GET', 'HEAD', 'POST'])
    @app.route('/web/<viewer>/<path:path>', methods=['GET', 'HEAD', 'POST'])
    def radio_web_view(viewer, path):
        try:
            target = upstream_url(viewer, path, request.query_string)
        except (ValueError, UnicodeError):
            abort(404)
        # The embedded AIS decoder posts text to this read-only decoding API.
        # This bridge never exposes upstream administrative write endpoints.
        if request.method == 'POST' and not (viewer == 'ais' and path == 'api/decode'):
            abort(405)
        request.max_content_length = 65536
        headers = {'Accept-Encoding': 'identity'}
        for name in ('Accept', 'Range', 'If-None-Match', 'If-Modified-Since', 'Last-Event-ID', 'Content-Type'):
            if name in request.headers:
                headers[name] = request.headers[name]
        transport = requests.Session()
        transport.trust_env = False
        try:
            upstream = transport.request(request.method, target, headers=headers,
                                         data=request.get_data() if request.method == 'POST' else None,
                                         timeout=(3, 30), stream=True, allow_redirects=False)
        except requests.RequestException:
            transport.close()
            return Response('De kaartdienst is niet bereikbaar. Start ' +
                            ('AIS-catcher.' if viewer == 'ais' else 'ADS-B/tar1090.'),
                            status=502, content_type='text/plain; charset=utf-8')
        def close():
            upstream.close()
            transport.close()
        if upstream.is_redirect:
            location = urljoin(target, upstream.headers.get('Location', ''))
            parsed, base = urlsplit(location), urlsplit(TARGETS[viewer])
            close()
            if parsed.netloc != base.netloc or parsed.scheme != base.scheme or not parsed.path.startswith(base.path):
                abort(502)
            suffix = parsed.path[len(base.path):]
            return redirect('/web/' + viewer + '/' + suffix + ('?' + parsed.query if parsed.query else ''), code=upstream.status_code)
        content_type = upstream.headers.get('Content-Type', 'application/octet-stream')
        response_headers = {'Content-Type': content_type}
        for name in ('Content-Range', 'Accept-Ranges', 'Last-Modified'):
            if name in upstream.headers:
                response_headers[name] = upstream.headers[name]
        if request.method == 'HEAD' or upstream.status_code in (204, 304):
            close()
            return Response(status=upstream.status_code, headers=response_headers)
        if 'text/html' in content_type.lower():
            try:
                data = bytearray()
                for chunk in upstream.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > MAX_BODY:
                        abort(502)
                html = data.decode(upstream.encoding or 'utf-8', errors='replace')
                html = rewrite_html(html, viewer, getattr(g, 'csrf', ''))
                return Response(html, status=upstream.status_code, content_type='text/html; charset=utf-8')
            except requests.RequestException:
                abort(502)
            finally:
                close()
        is_events = 'text/event-stream' in content_type.lower()
        def stream():
            size = 0
            try:
                for chunk in upstream.iter_content(1 if is_events else 65536):
                    size += len(chunk)
                    if not is_events and size > MAX_BODY:
                        break
                    yield chunk
            except requests.RequestException:
                return
            finally:
                close()
        response = Response(stream(), status=upstream.status_code, headers=response_headers)
        response.call_on_close(close)
        return response
