#!/usr/bin/env python3
"""Real local HTTP upstream tests; no station services or internet required."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from flask import Flask, g
from core import web_views


class ViewerBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.seen.append((self.path,dict(self.headers)))
                if self.path == '/escape':
                    self.send_response(302); self.send_header('Location','http://example.invalid/'); self.end_headers();return
                if self.path == '/move':
                    self.send_response(302); self.send_header('Location','/api/ships.json?receiver=1'); self.end_headers();return
                if self.path.startswith('/api/ships.json'):
                    data=b'{"ships":[123]}' ; content_type='application/json'
                elif self.path.endswith('.bin'):
                    data=b'\x00\xff\x01\x02';content_type='application/octet-stream'
                elif self.path == '/api/sse':
                    data=b'data: one\n\n';content_type='text/event-stream'
                else:
                    data=b'<html><head><link href="/favicon.ico"><script src="app.js"></script></head><body>Map</body></html>'
                    content_type='text/html; charset=utf-8'
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Set-Cookie','upstream=must-not-escape')
                self.end_headers();self.wfile.write(data)
            def do_POST(self):
                self.do_GET()
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def setUp(self):
        self.patch=patch.dict(web_views.TARGETS,ais=self.base+'/',adsb=self.base+'/tar1090/')
        self.patch.start();self.addCleanup(self.patch.stop)
        app=Flask('test')
        @app.before_request
        def token():g.csrf='local-test-token'
        web_views.register(app)
        self.client=app.test_client()

    def test_html_and_same_origin_resources(self):
        r=self.client.get('/web/ais/?mmsi=123456789&zoom=14')
        self.assertEqual(r.status_code,200)
        self.assertIn(b'href="/web/ais/favicon.ico"',r.data)
        self.assertIn(b'src="app.js"',r.data)
        self.assertIn(b'/static/js/web_view_bridge.js',r.data)
        self.assertIn(b'local-test-token',r.data)
        self.assertEqual(self.seen[-1][0],'/?mmsi=123456789&zoom=14')
        self.assertIsNone(r.headers.get('Set-Cookie'))

    def test_json_and_binary_are_unchanged(self):
        r=self.client.get('/web/ais/api/ships.json?receiver=2')
        self.assertEqual(r.json,{'ships':[123]})
        self.assertEqual(self.seen[-1][0],'/api/ships.json?receiver=2')
        self.assertEqual(self.client.get('/web/adsb/data/file.bin').data,b'\x00\xff\x01\x02')
        self.assertEqual(self.seen[-1][0],'/tar1090/data/file.bin')

    def test_credentials_not_forwarded(self):
        self.client.set_cookie('__Host-sdrcc','private')
        self.client.get('/web/ais/',headers={'Authorization':'Bearer private','X-CSRF-Token':'private'})
        headers=self.seen[-1][1]
        for name in ('Cookie','Authorization','X-CSRF-Token'):
            self.assertNotIn(name,headers)

    def test_redirect_stays_in_fixed_service(self):
        r=self.client.get('/web/ais/move')
        self.assertEqual(r.location,'/web/ais/api/ships.json?receiver=1')
        self.assertEqual(self.client.get('/web/ais/escape').status_code,502)

    def test_traversal_and_unknown_service_blocked(self):
        for path in ('../secret','a/../secret','%2e%2e/secret','/evil','a\\b'):
            with self.assertRaises(ValueError):web_views.upstream_url('ais',path)
        self.assertEqual(self.client.get('/web/unknown/').status_code,404)
        self.assertEqual(self.client.post('/web/ais/api/admin').status_code,405)

    def test_event_stream(self):
        r=self.client.get('/web/ais/api/sse')
        self.assertEqual(r.data,b'data: one\n\n')
        self.assertIn('text/event-stream',r.content_type)

    def test_offline_service(self):
        with patch('core.web_views.requests.Session.request',side_effect=web_views.requests.ConnectionError):
            r=self.client.get('/web/ais/')
        self.assertEqual(r.status_code,502)
        self.assertIn(b'AIS-catcher',r.data)

    def test_tar1090_root_paths_keep_prefix_once(self):
        html=web_views.rewrite_html('<head><script src="/tar1090/app.js"></script><a href="//tiles.example/a">x</a>', 'adsb','')
        self.assertIn('/web/adsb/app.js',html)
        self.assertNotIn('/web/adsb/tar1090',html)
        self.assertIn('//tiles.example/a',html)


if __name__=='__main__':unittest.main(verbosity=2)
