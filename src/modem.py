#!/usr/bin/env python3
"""
Modem communication module for Quectel RM520N-GL on OpenWrt
No external dependencies — Python standard library only
"""

import os
import re
import time
import select
import termios
import threading
import subprocess
from datetime import datetime

# ── Band bitmask tables ───────────────────────────────────────────────────────

LTE_BANDS = {
    'B1':0x1,'B2':0x2,'B3':0x4,'B4':0x8,'B5':0x10,'B7':0x40,'B8':0x80,
    'B12':0x800,'B13':0x1000,'B17':0x10000,'B18':0x20000,'B19':0x40000,
    'B20':0x80000,'B25':0x1000000,'B26':0x2000000,'B28':0x8000000,
    'B32':0x80000000,'B38':0x2000000000,'B39':0x4000000000,
    'B40':0x8000000000,'B41':0x10000000000,'B42':0x20000000000,
}

NR5G_BANDS = {
    'N1':0x1,'N2':0x2,'N3':0x4,'N5':0x10,'N7':0x40,'N8':0x80,
    'N12':0x800,'N20':0x80000,'N25':0x1000000,'N28':0x8000000,
    'N38':0x2000000000,'N40':0x8000000000,'N41':0x10000000000,
    'N48':0x800000000000,'N77':0x1000000000000,'N78':0x2000000000000,
    'N79':0x4000000000000,
}

NETWORK_MODE_MAP = {
    'auto':'0','2g':'1','3g':'2','4g':'3','5g':'4','4g5g':'5',
}

# ── PLMN → operator name lookup (add more as needed) ─────────────────────────

PLMN_NAMES = {
    # Vietnam
    '45201': 'Mobifone',  '45202': 'Vinaphone', '45203': 'Viettel',
    '45204': 'Gmobile',   '45205': 'Reddi',      '45207': 'Mobicast',
    '45208': 'Indochina Telecom',
    # Common global
    '20404': 'Vodafone NL', '23420': 'Three UK',  '31026': 'T-Mobile US',
    '52000': 'AIS TH',      '52001': 'DTAC TH',   '52015': 'TOT TH',
    '52020': 'DTAC TH',
}


# ── Serial port ───────────────────────────────────────────────────────────────

class ModemSerial:
    """Raw serial port — no pyserial required"""

    def __init__(self, port, baudrate=115200, timeout=6):
        self.port    = port
        self.timeout = timeout
        self._fd     = None
        self._lock   = threading.Lock()

    def open(self):
        self._fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self._fd)
        attrs[0] = 0                                               # iflag
        attrs[1] = 0                                               # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL   # cflag
        attrs[3] = 0                                               # lflag
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        attrs[6][termios.VMIN]  = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
        termios.tcflush(self._fd, termios.TCIOFLUSH)

    def close(self):
        if self._fd is not None:
            try: os.close(self._fd)
            except Exception: pass
            self._fd = None

    def is_open(self):
        return self._fd is not None

    def send(self, cmd, timeout=None):
        timeout = timeout or self.timeout
        with self._lock:
            if self._fd is None:
                self.open()
            termios.tcflush(self._fd, termios.TCIFLUSH)
            os.write(self._fd, (cmd.strip() + '\r\n').encode())

            buf = b''
            deadline = time.time() + timeout
            while time.time() < deadline:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if r:
                    chunk = os.read(self._fd, 4096)
                    if chunk:
                        buf += chunk
                        txt = buf.decode('utf-8', errors='ignore')
                        if ('OK\r\n' in txt or '\nOK' in txt
                                or 'ERROR' in txt or '+CME ERROR' in txt):
                            break
            return buf.decode('utf-8', errors='ignore')


def detect_port():
    """Find Quectel AT command port"""
    for port in ['/dev/ttyUSB2', '/dev/ttyUSB3', '/dev/ttyUSB1',
                 '/dev/ttyUSB0', '/dev/ttyUSB4', '/dev/ttyACM0']:
        if not os.path.exists(port):
            continue
        try:
            s = ModemSerial(port)
            s.open()
            resp = s.send('ATI', timeout=3)
            s.close()
            if any(k in resp for k in ('Quectel', 'RM520', 'RM500', 'OK')):
                return port
        except Exception:
            pass
    return '/dev/ttyUSB2'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _num(s):
    """Safe numeric parse"""
    try:
        s = str(s).strip()
        return float(s) if '.' in s else int(s)
    except (ValueError, TypeError):
        return None


def _smart_signal(raw_val):
    """
    RM520N-GL AT+QRSRP/QRSRQ/QSINR return values in dBm on some firmware
    and in 0.1 dBm on others.  Detect by magnitude:
      |val| > 200  → 0.1 dBm units → divide by 10
      |val| ≤ 200  → already dBm   → use directly
    """
    if raw_val is None:
        return None
    return raw_val / 10.0 if abs(raw_val) > 200 else float(raw_val)


def _plmn_name(plmn_str):
    """Return operator name for numeric PLMN code, or the code itself"""
    p = plmn_str.strip().replace(' ', '')
    return PLMN_NAMES.get(p, plmn_str)


def _parse_band_str(band_str):
    """'NR5G BAND 41' → 'N41', 'LTE BAND 28' → 'B28' """
    m = re.search(r'(NR5G|LTE|WCDMA|GSM)\s+BAND\s*(\d+)', band_str, re.I)
    if not m:
        return band_str
    prefix = 'N' if 'NR5G' in m.group(1).upper() else 'B'
    return f"{prefix}{m.group(2)}"


def _mode_from_str(s):
    """'NR5G-NSA' → '5G NSA', 'LTE' → '4G LTE', etc."""
    s = s.upper()
    if 'NR5G-SA' in s  or '5G-SA'  in s: return '5G SA'
    if 'NR5G-NSA' in s or '5G-NSA' in s: return '5G NSA'
    if 'NR5G' in s or 'NR' in s:          return '5G'
    if 'LTE' in s:                         return '4G LTE'
    if 'WCDMA' in s or 'HSPA' in s or 'UMTS' in s: return '3G'
    if 'GSM' in s or 'GPRS' in s or 'EDGE' in s:   return '2G'
    return s


# ── Modem Manager ─────────────────────────────────────────────────────────────

class ModemManager:
    """High-level API for Quectel RM520N-GL"""

    def __init__(self, port='auto'):
        self._port   = port
        self._serial = None
        self._lock   = threading.Lock()

    def _ser(self):
        if self._serial is None or not self._serial.is_open():
            port = detect_port() if self._port == 'auto' else self._port
            self._serial = ModemSerial(port)
            self._serial.open()
        return self._serial

    def _at(self, cmd, timeout=6):
        try:
            return self._ser().send(cmd, timeout)
        except Exception:
            self._serial = None
            try:
                return self._ser().send(cmd, timeout)
            except Exception:
                return ''

    # ── Network info (primary source) ─────────────────────────────────────────

    def get_nwinfo(self):
        """AT+QNWINFO — most reliable source for mode/band/operator"""
        raw = self._at('AT+QNWINFO')
        # +QNWINFO: "NR5G-NSA","45204","NR5G BAND 41",627264
        m = re.search(
            r'\+QNWINFO:\s*"([^"]*)","([^"]*)","([^"]*)",(\d+)', raw
        )
        if not m:
            return {}

        type_str = m.group(1)   # NR5G-NSA
        plmn     = m.group(2)   # 45204
        band_str = m.group(3)   # NR5G BAND 41
        arfcn    = m.group(4)   # 627264

        # Extract MCC/MNC from PLMN
        mcc = plmn[:3] if len(plmn) >= 5 else ''
        mnc = plmn[3:] if len(plmn) >= 5 else ''

        return {
            'mode':      _mode_from_str(type_str),
            'type_raw':  type_str,
            'band':      _parse_band_str(band_str),
            'dl_arfcn':  arfcn,
            'plmn':      plmn,
            'operator':  _plmn_name(plmn),
            'mcc':       mcc,
            'mnc':       mnc,
        }

    # ── Serving cell (supplementary detail) ───────────────────────────────────

    def get_serving_cell(self):
        """AT+QENG="servingcell" — cell-level details (PCI, Cell ID, RSRP…)"""
        raw = self._at('AT+QENG="servingcell"', 8)
        base = {
            'state':    'unknown',
            'mode':     'unknown',
            'band':     '--',
            'pci':      None,
            'cell_id':  None,
            'dl_arfcn': None,
            'mcc':      None,
            'mnc':      None,
            'rsrp':     None,
            'rsrq':     None,
            'sinr':     None,
            'rssi':     None,
        }

        m = re.search(r'\+QENG:\s*"servingcell",(.*)', raw)
        if not m:
            return base

        # Strip quotes and split
        parts = m.group(1).replace('"', '').split(',')
        parts = [p.strip() for p in parts]

        # Pad to avoid IndexError
        while len(parts) < 20:
            parts.append('')

        try:
            base['state'] = parts[0]
            net = parts[1]
            base['mode'] = _mode_from_str(net) if net else 'unknown'

            # ── Determine offset: some firmware adds FDD/TDD field ─────────
            # Possible positions for MCC:
            #   [2]=FDD/TDD → MCC at [3]   (most common)
            #   [2]=MCC directly            (less common)

            # Detect FDD/TDD presence
            has_duplex = parts[2] in ('FDD', 'TDD', 'IDD-NR5G-NSA',
                                       'IDD-NR5G-SA', 'SA', 'NSA')
            off = 3 if has_duplex else 2   # offset to MCC

            base['mcc']      = parts[off]     if parts[off]     else None
            base['mnc']      = parts[off+1]   if parts[off+1]   else None
            base['cell_id']  = parts[off+2]   if parts[off+2]   else None
            base['pci']      = parts[off+3]   if parts[off+3]   else None
            base['dl_arfcn'] = parts[off+4]   if parts[off+4]   else None
            base['band']     = f"B{parts[off+5]}" if parts[off+5].isdigit() else (
                               f"N{parts[off+5]}" if parts[off+5] else '--')

            # Signal: positions vary with bandwidth fields (usually 2-3 fields after band)
            # Try to find RSRP by scanning: first negative value < -20 after band
            sig_start = off + 8   # typical start of signal params
            raw_vals = []
            for i in range(sig_start, min(sig_start + 6, len(parts))):
                v = _num(parts[i])
                if v is not None:
                    raw_vals.append((i, v))

            if len(raw_vals) >= 3:
                base['rsrp'] = _smart_signal(raw_vals[0][1])
                base['rsrq'] = _smart_signal(raw_vals[1][1])
                # RSSI usually 3rd for LTE, SINR 4th
                if len(raw_vals) >= 4:
                    base['rssi'] = _num(parts[raw_vals[2][0]])
                    base['sinr'] = _smart_signal(raw_vals[3][1])
                else:
                    base['sinr'] = _smart_signal(raw_vals[2][1])

        except Exception:
            pass

        return base

    # ── NR5G secondary cell (NSA) ─────────────────────────────────────────────

    def get_nr5g_cell(self):
        raw = self._at('AT+QENG="neighbourcell"', 8)
        # +QENG: "neighbourcell nr5g-nsa","NR5G-NSA",...
        m = re.search(r'\+QENG:\s*"neighbourcell nr5g-nsa","[^"]*",(.+)', raw)
        if not m:
            return {}
        parts = [p.strip() for p in m.group(1).split(',')]
        while len(parts) < 8:
            parts.append('')
        try:
            band_num = parts[0]
            return {
                'band':      f"N{band_num}" if band_num.isdigit() else '--',
                'dl_arfcn':  parts[1],
                'pci':       parts[2],
                'rsrp':      _smart_signal(_num(parts[3])),
                'sinr':      _smart_signal(_num(parts[4])),
            }
        except Exception:
            return {}

    # ── Operator ──────────────────────────────────────────────────────────────

    def get_operator(self):
        raw = self._at('AT+COPS?')
        m = re.search(r'\+COPS:\s*(\d+),(\d+),"([^"]+)",(\d+)', raw)
        if not m:
            return {'operator': '--', 'access_type': '--'}

        fmt  = int(m.group(2))
        name = m.group(3)
        act  = int(m.group(4))

        act_map = {0:'2G',2:'3G',7:'4G LTE',11:'5G NSA',12:'5G SA'}

        # Format 2 = numeric PLMN → look up name
        if fmt == 2:
            name = _plmn_name(name)

        return {
            'operator':    name,
            'access_type': act_map.get(act, f'Act{act}'),
        }

    def get_network_mode(self):
        raw = self._at('AT+QNWPREFMDE?')
        m = re.search(r'\+QNWPREFMDE:\s*(\d+)', raw)
        names = {'0':'Tự động','1':'2G only','2':'3G only',
                 '3':'4G only','4':'5G only','5':'4G + 5G'}
        code = m.group(1) if m else '0'
        return {'code': code, 'name': names.get(code, 'Auto')}

    # ── Signal quality (separate commands) ────────────────────────────────────

    def get_signal(self):
        sig = {}
        for cmd, key in [('AT+QRSRP','rsrp'), ('AT+QRSRQ','rsrq'), ('AT+QSINR','sinr')]:
            raw = self._at(cmd)
            # Response: +QRSRP: val1,val2,...  (take first valid, non-32767)
            vals = re.findall(r'(-?\d+)', raw.split(':')[-1]) if ':' in raw else []
            for v in vals:
                n = int(v)
                if abs(n) != 32767 and abs(n) != 32768:
                    sig[key] = _smart_signal(n)
                    break

        # Fallback CSQ
        raw = self._at('AT+CSQ')
        m = re.search(r'\+CSQ:\s*(\d+),', raw)
        if m:
            csq = int(m.group(1))
            if csq != 99:
                sig.setdefault('rssi', -113 + csq * 2)
                sig['csq'] = csq
        return sig

    # ── CA info ───────────────────────────────────────────────────────────────

    def get_ca_info(self):
        raw = self._at('AT+QCAINFO', 8)
        cas = []
        for m in re.finditer(
            r'\+QCAINFO:\s*"(\w+)",(\d+),(\d+),"([^"]+)",(\d+)', raw
        ):
            cas.append({
                'role':  m.group(1),
                'earfcn': m.group(2),
                'bw':    m.group(3),
                'band':  m.group(4),
                'pci':   m.group(5),
            })
        return cas

    # ── Traffic ───────────────────────────────────────────────────────────────

    def get_traffic(self):
        raw = self._at('AT+QGDCNT?')
        m = re.search(r'\+QGDCNT:\s*(\d+),(\d+)', raw)
        if m:
            return {'tx_bytes': int(m.group(1)), 'rx_bytes': int(m.group(2)),
                    'source': 'modem'}
        # Fallback /proc/net/dev
        try:
            with open('/proc/net/dev') as f:
                content = f.read()
            for iface in ('wwan0','usb0','rmnet_data0','eth1'):
                m2 = re.search(
                    rf'^\s*{iface}:\s*(\d+)(?:\s+\d+){{7}}\s+(\d+)',
                    content, re.M
                )
                if m2:
                    return {'rx_bytes': int(m2.group(1)),
                            'tx_bytes': int(m2.group(2)),
                            'source': iface}
        except Exception:
            pass
        return {'tx_bytes': 0, 'rx_bytes': 0, 'source': 'none'}

    def reset_traffic(self):
        return 'OK' in self._at('AT+QGDCNT=0')

    # ── Temperature ───────────────────────────────────────────────────────────

    def get_temperature(self):
        """
        RM520N-GL may return temps in various formats:
          +QTEMP: "mdm-q6","43","51"
          +QTEMP: "XO_therm",35,0
          +QTEMP: 0,"pa-therm","42"
        """
        raw = self._at('AT+QTEMP')
        temps = {}

        # Pattern 1: +QTEMP: "key","value" or +QTEMP: "key",value
        for m in re.finditer(r'\+QTEMP:\s*"([^"]+)","?(-?\d+)', raw):
            temps[m.group(1)] = int(m.group(2))

        # Pattern 2: +QTEMP: index,"key","value"
        if not temps:
            for m in re.finditer(r'\+QTEMP:\s*\d+,"([^"]+)","?(-?\d+)', raw):
                temps[m.group(1)] = int(m.group(2))

        # Pattern 3: plain numbers after colon (e.g. some compact formats)
        if not temps:
            m = re.search(r'\+QTEMP[^:]*:\s*(-?\d{2,3})', raw)
            if m:
                temps['temp'] = int(m.group(1))

        # Fallback: try thermal zones in Linux
        if not temps:
            try:
                import glob as _glob
                for path in _glob.glob('/sys/class/thermal/thermal_zone*/temp'):
                    try:
                        with open(path) as f:
                            val = int(f.read().strip())
                        name = path.split('/')[-2]
                        temps[name] = val // 1000  # millidegree → degree
                    except Exception:
                        pass
            except Exception:
                pass

        return temps

    # ── Device info ───────────────────────────────────────────────────────────

    def get_device_info(self):
        info = {}
        raw = self._at('ATI')
        m = re.search(r'Model:\s*(.+)', raw)
        info['model'] = m.group(1).strip() if m else 'RM520N-GL'

        raw = self._at('AT+CGSN=1')
        m = re.search(r'\+CGSN:\s*(\d{15})', raw)
        if not m:
            m = re.search(r'(\d{15})', self._at('AT+CGSN'))
        info['imei'] = m.group(1) if m else '--'

        raw = self._at('AT+QCCID')
        m = re.search(r'\+QCCID:\s*(\S+)', raw)
        info['iccid'] = m.group(1) if m else '--'

        raw = self._at('AT+QGMR')
        lines = [l.strip() for l in raw.split('\n')
                 if l.strip() and 'OK' not in l and 'AT+' not in l]
        info['firmware'] = lines[0] if lines else '--'

        return info

    # ── Band config ───────────────────────────────────────────────────────────

    def get_band_config(self):
        raw = self._at('AT+QCFG="band"', 8)
        m = re.search(
            r'\+QCFG:\s*"band",0x([0-9a-fA-F]+),0x([0-9a-fA-F]+),0x([0-9a-fA-F]+)',
            raw, re.I
        )
        if not m:
            return {'lte_mask': 0, 'nr5g_mask': 0,
                    'lte_locked': [], 'nr5g_locked': []}
        lte_mask  = int(m.group(2), 16)
        nr5g_mask = int(m.group(3), 16)
        return {
            'lte_mask':    lte_mask,
            'nr5g_mask':   nr5g_mask,
            'lte_locked':  [b for b, v in LTE_BANDS.items()  if lte_mask  & v],
            'nr5g_locked': [b for b, v in NR5G_BANDS.items() if nr5g_mask & v],
        }

    def set_band_lock(self, lte_bands=None, nr5g_bands=None):
        lte_mask = 0
        if lte_bands:
            for b in lte_bands:
                lte_mask |= LTE_BANDS.get(b.upper(), 0)
        else:
            lte_mask = sum(LTE_BANDS.values())

        nr5g_mask = 0
        if nr5g_bands:
            for b in nr5g_bands:
                nr5g_mask |= NR5G_BANDS.get(b.upper(), 0)
        else:
            nr5g_mask = sum(NR5G_BANDS.values())

        resp = self._at(f'AT+QCFG="band",0xf,0x{lte_mask:x},0x{nr5g_mask:x}', 10)
        return 'OK' in resp

    def set_network_mode(self, mode):
        code = NETWORK_MODE_MAP.get(mode.lower(), '0')
        return 'OK' in self._at(f'AT+QNWPREFMDE={code}', 10)

    def reconnect(self):
        self._at('AT+CFUN=0', 10)
        time.sleep(2)
        return 'OK' in self._at('AT+CFUN=1', 10)

    # ── Full status ───────────────────────────────────────────────────────────

    def get_full_status(self):
        """
        Strategy:
        1. AT+QNWINFO  → reliable: mode, band, operator, arfcn, MCC/MNC
        2. AT+QENG     → supplementary: cell_id, PCI, per-cell signal
        3. AT+QRSRP/Q  → best signal quality numbers
        4. Merge: QNWINFO fills gaps left by QENG parsing failure
        """
        nwinfo = self.get_nwinfo()
        cell   = self.get_serving_cell()
        ca     = self.get_ca_info()

        # ── Patch mode ─────────────────────────────────────────────────────
        if cell.get('mode') in ('unknown', None, '--'):
            cell['mode'] = nwinfo.get('mode', 'unknown')

        # ── Patch band ─────────────────────────────────────────────────────
        if cell.get('band') in ('--', None, ''):
            mode_str = cell.get('mode', '')
            if 'NSA' in mode_str:
                # NSA → cell.band = LTE anchor (PCC in CA)
                for ca_item in ca:
                    if ca_item.get('role', '').upper() == 'PCC':
                        cell['band'] = _parse_band_str(ca_item['band'])
                        break
            if cell.get('band') in ('--', None, ''):
                # For non-NSA or PCC not found: use QNWINFO band
                cell['band'] = nwinfo.get('band', '--')

        # ── Patch arfcn / mcc / mnc ────────────────────────────────────────
        if not cell.get('dl_arfcn'):
            cell['dl_arfcn'] = nwinfo.get('dl_arfcn')
        if not cell.get('mcc'):
            cell['mcc'] = nwinfo.get('mcc')
            cell['mnc'] = nwinfo.get('mnc')

        # ── NR5G secondary cell (NSA) ──────────────────────────────────────
        nr5g = {}
        if 'NSA' in cell.get('mode', ''):
            nr5g = self.get_nr5g_cell()
            # SCC band from CA
            if not nr5g.get('band') or nr5g.get('band') == '--':
                for ca_item in ca:
                    if ca_item.get('role', '').upper() == 'SCC':
                        nr5g['band'] = _parse_band_str(ca_item['band'])
                        break
            # Fallback: QNWINFO band (for NSA it usually reports NR5G band)
            if not nr5g.get('band') or nr5g.get('band') == '--':
                nw_band = nwinfo.get('band', '')
                if nw_band.startswith('N'):
                    nr5g['band'] = nw_band

        # ── Operator ───────────────────────────────────────────────────────
        operator = self.get_operator()
        if operator.get('operator') in ('--', None):
            operator['operator'] = nwinfo.get('operator', '--')

        # ── Signal ────────────────────────────────────────────────────────
        sig = self.get_signal()
        # Fill signal from cell if not from dedicated AT+QRSRP commands
        for k in ('rsrp', 'rsrq', 'sinr', 'rssi'):
            if sig.get(k) is None and cell.get(k) is not None:
                sig[k] = cell[k]

        # ── Net mode ───────────────────────────────────────────────────────
        net_mode = self.get_network_mode()

        return {
            'timestamp': datetime.now().isoformat(),
            'cell':      cell,
            'nr5g':      nr5g,
            'operator':  operator,
            'net_mode':  net_mode,
            'signal':    sig,
            'traffic':   self.get_traffic(),
            'temps':     self.get_temperature(),
            'bands':     self.get_band_config(),
            'ca':        ca,
        }
