#!/usr/bin/env python3
"""
5GDash HTTP server — serves dashboard on port 2222
Requires: Python 3.6+ (standard library only)
"""

import os
import re
import sys
import json
import time
import queue
import signal
import threading
import mimetypes
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))
from modem import ModemManager, LTE_BANDS, NR5G_BANDS

# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
    defaults = {
        'port':          2222,
        'host':          '0.0.0.0',
        'modem_port':    'auto',
        'poll_interval': 3,
        'www_dir':       os.path.join(os.path.dirname(__file__), 'www'),
    }
    try:
        with open(cfg_path) as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    return defaults

CONFIG = load_config()
modem  = ModemManager(CONFIG.get('modem_port', 'auto'))

# ── System info ───────────────────────────────────────────────────────────────

def get_sysinfo():
    info = {}
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
        info['load1'] = float(parts[0])
        cores = 1
        with open('/proc/cpuinfo') as f:
            txt = f.read()
        cores = max(1, txt.count('processor'))
        info['cores']   = cores
        info['cpu_pct'] = min(100, round(info['load1'] / cores * 100))
    except Exception:
        info['cpu_pct'] = 0

    try:
        with open('/proc/meminfo') as f:
            mem = {}
            for line in f:
                p = line.split(':')
                if len(p) == 2:
                    mem[p[0].strip()] = int(p[1].strip().split()[0])
        total = mem.get('MemTotal', 1)
        avail = mem.get('MemAvailable', mem.get('MemFree', 0))
        used  = total - avail
        info['ram_total'] = total * 1024
        info['ram_used']  = used  * 1024
        info['ram_pct']   = round(used / max(total, 1) * 100)
    except Exception:
        info['ram_total'] = info['ram_used'] = info['ram_pct'] = 0

    try:
        r = subprocess.run(['df', '/overlay'], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split('\n')
        if len(lines) < 2:
            r = subprocess.run(['df', '/'], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split('\n')
        if len(lines) >= 2:
            p = lines[1].split()
            info['rom_total'] = int(p[1]) * 1024
            info['rom_used']  = int(p[2]) * 1024
            info['rom_pct']   = round(int(p[2]) / max(int(p[1]), 1) * 100)
    except Exception:
        info['rom_total'] = info['rom_used'] = info['rom_pct'] = 0

    try:
        with open('/proc/uptime') as f:
            info['uptime_secs'] = int(float(f.read().split()[0]))
    except Exception:
        info['uptime_secs'] = 0

    try:
        with open('/proc/sys/kernel/hostname') as f:
            info['hostname'] = f.read().strip()
    except Exception:
        info['hostname'] = '5G CPE'

    return info


# ── Connected devices ─────────────────────────────────────────────────────────

def get_connected_devices():
    devices = {}   # mac → dict

    # 1. DHCP leases: "<expire> <mac> <ip> <hostname> <client-id>"
    for lf in ('/tmp/dhcp.leases', '/var/dhcp.leases'):
        try:
            with open(lf) as f:
                for line in f:
                    p = line.strip().split()
                    if len(p) >= 4:
                        mac  = p[1].upper()
                        name = p[3] if p[3] != '*' else 'Unknown'
                        devices[mac] = {
                            'mac':      mac,
                            'ip':       p[2],
                            'hostname': name,
                            'type':     'lan',
                            'band':     'LAN',
                            'signal':   None,
                            'tx_bytes': 0,
                            'rx_bytes': 0,
                            'connected_secs': None,
                        }
            break
        except Exception:
            pass

    # 2. WiFi station dump
    wifi_ifaces = []
    try:
        r = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5)
        wifi_ifaces = re.findall(r'Interface\s+(\S+)', r.stdout)
    except Exception:
        wifi_ifaces = ['wlan0', 'wlan1']

    for iface in wifi_ifaces:
        # Determine band from channel frequency
        band = '?'
        try:
            r = subprocess.run(['iw', 'dev', iface, 'info'],
                               capture_output=True, text=True, timeout=3)
            m = re.search(r'channel \d+ \((\d+) MHz\)', r.stdout)
            if m:
                freq = int(m.group(1))
                band = '2.4G' if freq < 3000 else ('6G' if freq > 5900 else '5G')
        except Exception:
            pass

        try:
            r = subprocess.run(['iw', 'dev', iface, 'station', 'dump'],
                               capture_output=True, text=True, timeout=5)
            cur_mac  = None
            cur_data = {}

            def _flush(mac, data):
                mac = mac.upper()
                if mac not in devices:
                    devices[mac] = {'mac': mac, 'hostname': 'Unknown',
                                    'ip': '--', 'type': 'wifi',
                                    'band': band, 'signal': None,
                                    'tx_bytes': 0, 'rx_bytes': 0,
                                    'connected_secs': None}
                devices[mac].update(data)
                devices[mac]['type'] = 'wifi'
                devices[mac]['band'] = band

            for line in r.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Station '):
                    if cur_mac:
                        _flush(cur_mac, cur_data)
                    cur_mac  = line.split()[1]
                    cur_data = {}
                elif cur_mac:
                    if 'signal:' in line:
                        m2 = re.search(r'(-?\d+) dBm', line)
                        if m2:
                            cur_data['signal'] = int(m2.group(1))
                    elif 'tx bytes:' in line:
                        m2 = re.search(r'(\d+)', line)
                        if m2:
                            cur_data['tx_bytes'] = int(m2.group(1))
                    elif 'rx bytes:' in line:
                        m2 = re.search(r'(\d+)', line)
                        if m2:
                            cur_data['rx_bytes'] = int(m2.group(1))
                    elif 'connected time:' in line:
                        m2 = re.search(r'(\d+)', line)
                        if m2:
                            cur_data['connected_secs'] = int(m2.group(1))

            if cur_mac:
                _flush(cur_mac, cur_data)

        except Exception:
            pass

    # 3. ARP for missing IPs
    try:
        with open('/proc/net/arp') as f:
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    mac = p[3].upper()
                    if mac in devices and devices[mac].get('ip') in (None, '--'):
                        devices[mac]['ip'] = p[0]
    except Exception:
        pass

    return sorted(devices.values(),
                  key=lambda d: (d['type'] != 'wifi', d.get('hostname', '')))


# ── Poller ────────────────────────────────────────────────────────────────────

_latest      = {}
_latest_lock = threading.Lock()
_sse_clients = []
_sse_lock    = threading.Lock()

_polling_enabled = False  # OFF by default — user must explicitly enable
_polling_lock    = threading.Lock()


def _poll_loop():
    interval = CONFIG.get('poll_interval', 3)
    port_released = False
    prev_rx = prev_tx = 0
    prev_ts = time.time()

    while True:
        with _polling_lock:
            enabled = _polling_enabled
        if not enabled:
            if not port_released:
                modem.close()
                port_released = True
            time.sleep(1)
            continue
        port_released = False

        try:
            data    = modem.get_full_status()
            sysinfo = get_sysinfo()

            now = time.time()
            dt  = max(now - prev_ts, 0.1)
            rx  = data['traffic'].get('rx_bytes', 0)
            tx  = data['traffic'].get('tx_bytes', 0)
            data['speed'] = {
                'rx_bps': max(0, (rx - prev_rx) / dt),
                'tx_bps': max(0, (tx - prev_tx) / dt),
            }
            prev_rx, prev_tx, prev_ts = rx, tx, now

            data['sysinfo'] = sysinfo

            with _latest_lock:
                _latest.update(data)

            payload = 'data: ' + json.dumps(data) + '\n\n'
            with _sse_lock:
                dead = []
                for q in _sse_clients:
                    try:
                        q.put_nowait(payload)
                    except Exception:
                        dead.append(q)
                for q in dead:
                    _sse_clients.remove(q)

        except Exception as e:
            print(f'[poller] {e}', file=sys.stderr)

        time.sleep(interval)


# ── Handler ───────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            mime, _ = mimetypes.guess_type(path)
            self.send_response(200)
            self.send_header('Content-Type', mime or 'application/octet-stream')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')

        if path == '/api/status':
            with _latest_lock:
                data = _latest.copy()
            if not data:
                with _polling_lock:
                    if _polling_enabled:
                        data = modem.get_full_status()
            self._json(data)

        elif path == '/api/sysinfo':
            self._json(get_sysinfo())

        elif path == '/api/devices':
            self._json(get_connected_devices())

        elif path == '/api/bands':
            with _polling_lock:
                enabled = _polling_enabled
            self._json({
                'lte_bands':  sorted(LTE_BANDS.keys()),
                'nr5g_bands': sorted(NR5G_BANDS.keys()),
                'current':    modem.get_band_config() if enabled else {},
            })

        elif path == '/api/device':
            with _polling_lock:
                enabled = _polling_enabled
            self._json(modem.get_device_info() if enabled else {})

        elif path == '/api/polling':
            with _polling_lock:
                self._json({'enabled': _polling_enabled})

        elif path == '/api/stream':
            q = queue.Queue(maxsize=20)
            with _sse_lock:
                _sse_clients.append(q)

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()

            with _latest_lock:
                if _latest:
                    snap = 'data: ' + json.dumps(_latest) + '\n\n'
                    try:
                        self.wfile.write(snap.encode())
                        self.wfile.flush()
                    except Exception:
                        pass

            try:
                while True:
                    try:
                        msg = q.get(timeout=30)
                        self.wfile.write(msg.encode())
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b': ping\n\n')
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with _sse_lock:
                    try:
                        _sse_clients.remove(q)
                    except ValueError:
                        pass

        else:
            www = CONFIG['www_dir']
            rel = (path.lstrip('/') or 'index.html')
            safe = os.path.realpath(os.path.join(www, rel))
            if not safe.startswith(os.path.realpath(www)):
                self.send_response(403)
                self.end_headers()
                return
            self._serve_file(safe)

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')

        length = int(self.headers.get('Content-Length', 0))
        raw    = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        with _polling_lock:
            _poll_ok = _polling_enabled

        if path == '/api/band-lock':
            ok = modem.set_band_lock(body.get('lte'), body.get('nr5g')) if _poll_ok else False
            self._json({'ok': ok, 'polling_off': not _poll_ok})

        elif path == '/api/network-mode':
            ok = modem.set_network_mode(body.get('mode', 'auto')) if _poll_ok else False
            self._json({'ok': ok, 'polling_off': not _poll_ok})

        elif path == '/api/traffic-reset':
            ok = modem.reset_traffic() if _poll_ok else False
            self._json({'ok': ok, 'polling_off': not _poll_ok})

        elif path == '/api/reconnect':
            ok = modem.reconnect() if _poll_ok else False
            self._json({'ok': ok, 'polling_off': not _poll_ok})

        elif path == '/api/polling':
            global _polling_enabled
            with _polling_lock:
                _polling_enabled = bool(body.get('enabled', True))
                enabled = _polling_enabled
            self._json({'ok': True, 'enabled': enabled})

        else:
            self._json({'error': 'not found'}, 404)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    host = CONFIG.get('host', '0.0.0.0')
    port = CONFIG.get('port', 2222)

    threading.Thread(target=_poll_loop, daemon=True).start()
    server = ThreadingHTTPServer((host, port), Handler)

    def _stop(sig, frame):
        print('\n[5GDash] Stopping...')
        server.shutdown()

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(f'[5GDash] http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    main()
