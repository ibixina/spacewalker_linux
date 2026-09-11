"""Local, authenticated pose stream for a browser-owned panoramic video player.

The browser renders directly on the glasses output. No desktop capture, video
re-encoding, or second head rotation is applied to that already-projected view.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import queue
import secrets
import socket
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

from .geometry import IDENTITY, matrix


def spherical_angles(q):
    """GL camera -> YouTube's left-positive yaw, up-positive pitch and view roll."""
    m = matrix(q)
    pitch = math.asin(max(-1.,min(1.,-float(m[1,2]))))
    if abs(math.cos(pitch)) > 1e-5:
        yaw = math.atan2(float(m[0,2]),float(m[2,2]))
        roll = math.atan2(float(m[1,0]),float(m[1,1]))
    else:
        yaw = math.atan2(-float(m[2,0]),float(m[0,0]))
        roll = 0.
    return dict(yaw=math.degrees(yaw)%360,pitch=math.degrees(pitch),roll=math.degrees(roll))


class BrowserVideo:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.title = 'Spacewalker 360 — '+secrets.token_hex(4)
        self.condition = threading.Condition()
        self.commands = queue.Queue(maxsize=16)
        self.closed = False
        self.clients = 0
        self.sequence = 0
        self.packet = b''
        self.assets = Path(__file__).with_name('web')
        self.http = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.daemon_threads = True
        self.http.bridge = self
        self.origin = f'http://127.0.0.1:{self.http.server_port}'
        self.publish(IDENTITY, None, 26., False)
        self.thread = threading.Thread(target=self.http.serve_forever,
                                       kwargs={'poll_interval':.1},daemon=True,name='browser-video')
        self.thread.start()

    def url(self,video=''):
        # Fragments are never sent as an HTTP referrer to YouTube or media hosts.
        return self.origin+'/#'+urlencode({'token':self.token,'video':video,'title':self.title})

    def publish(self,q,age,fov_y,stereo=False,simulated=False):
        with self.condition:
            self.sequence += 1
            payload = dict(sequence=self.sequence,quaternion=list(map(float,q)),
                           tracking=age is not None and age<.5,
                           age_ms=round(age*1000,2) if age is not None and math.isfinite(age) else None,
                           fov_y=fov_y,stereo=bool(stereo),simulated=simulated,**spherical_angles(q))
            self.packet = ('data: '+json.dumps(payload,separators=(',',':'),allow_nan=False)+'\n\n').encode()
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=1)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.connection.settimeout(2)

    def log_message(self,*args):
        pass  # In particular, never log URL credentials or media links.

    def allowed(self,authenticated=False):
        bridge = self.server.bridge
        # Reject cross-origin requests and DNS rebinding; no CORS wildcard.
        if self.headers.get('Host') != urlsplit(bridge.origin).netloc or self.headers.get('Origin',bridge.origin)!=bridge.origin:
            self.reply(403,b'Local player only.')
            return False
        if authenticated:
            token = parse_qs(urlsplit(self.path).query).get('token',[''])[0]
            if not secrets.compare_digest(token.encode(),bridge.token.encode()):
                self.reply(403,b'Open the player from Spacewalker again.')
                return False
        return True

    def common_headers(self,status,content_type):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')

    def reply(self,status,data,content_type='text/plain; charset=utf-8'):
        # Rejected requests may have unread bodies. Never reinterpret those
        # bytes as another request on a persistent connection.
        if status >= 400:
            self.close_connection = True
        self.common_headers(status,content_type)
        if self.close_connection:
            self.send_header('Connection','close')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.allowed(path=='/events'):
            return
        assets = {'/':('index.html','text/html; charset=utf-8'),
                  '/player.js':('player.js','text/javascript; charset=utf-8'),
                  '/player.css':('player.css','text/css; charset=utf-8'),
                  '/view.js':('view.js','text/javascript; charset=utf-8'),
                  '/panorama.js':('panorama.js','text/javascript; charset=utf-8')}
        if path in assets:
            name,mime = assets[path]
            return self.reply(200,(self.server.bridge.assets/name).read_bytes(),mime)
        if path != '/events':
            return self.reply(404,b'Not found.')
        bridge = self.server.bridge
        with bridge.condition:
            if bridge.clients>=4:
                return self.reply(429,b'Close an unused Spacewalker player tab.')
            bridge.clients += 1
        try:
            self.common_headers(200,'text/event-stream')
            self.send_header('Connection','close')
            self.end_headers()
            self.close_connection = True
            sequence = -1
            while True:
                with bridge.condition:
                    bridge.condition.wait_for(lambda:bridge.closed or bridge.sequence!=sequence,timeout=1)
                    if bridge.closed:
                        break
                    # Keep only the newest pose if the browser/connection stalls.
                    packet = bridge.packet if sequence!=bridge.sequence else b': alive\n\n'
                    sequence = bridge.sequence
                self.wfile.write(packet)
                self.wfile.flush()
        except (OSError,ConnectionError):
            pass
        finally:
            with bridge.condition:
                bridge.clients -= 1

    def do_POST(self):
        if not self.allowed(True):
            return
        path = urlsplit(self.path).path
        action = path.removeprefix('/action/')
        if not path.startswith('/action/') or action not in ('recenter','glasses','controls'):
            return self.reply(404,b'Unknown action.')
        if self.headers.get('Content-Length','0')!='0' or self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            return self.reply(400,b'No body expected.')
        try:
            self.server.bridge.commands.put_nowait(action)
        except queue.Full:
            return self.reply(429,b'Try again.')
        self.reply(204,b'')
