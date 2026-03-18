# 5GDash

A lightweight, mobile-friendly web dashboard for 5G CPE devices running **OpenWrt 23**, designed for the **Quectel RM520N-GL** modem module.

Access your router's full 5G status, signal quality, traffic, and band locking — all from a clean, flat UI at `http://192.168.1.1:2222`.

---

## Features

| Category | Details |
|---|---|
| **Signal** | RSRP / RSRQ / SINR with quality labels (Excellent / Good / Fair / Poor), visual progress bars, animated signal-strength indicator |
| **Network** | Network type (5G NSA / 5G SA / 4G LTE), band (e.g. B28 + N41), operator name, Cell ID, PCI, ARFCN, MCC/MNC |
| **Carrier Aggregation** | Shows PCC + SCC bands when CA is active |
| **Traffic** | Real-time download/upload speed with 60-second rolling chart, cumulative TX/RX counter, one-click reset |
| **Band Lock** | Lock LTE and/or NR5G to specific bands (e.g. N78 only), unlock all, 4G/5G/Auto mode switching |
| **Connected Devices** | WiFi clients (2.4G / 5G / 6G) and LAN devices with IP, signal dBm, data usage, connection time |
| **System** | CPU load, RAM, ROM usage bars, uptime, modem temperature |
| **Device** | Module model, firmware version, IMEI, ICCID |
| **Mobile-first** | Responsive layout, works great on phones |
| **Real-time** | Server-Sent Events (SSE) push every 3 seconds, auto-reconnect |

---

## Requirements

| Component | Requirement |
|---|---|
| Router OS | OpenWrt 23.x (or later) |
| Modem | Quectel RM520N-GL (other RM5xx/RM500 series may work) |
| Python | Python 3.6+ (`opkg install python3`) |
| Storage | ~200 KB |
| RAM | ~15 MB runtime |

> **Note:** No pip packages, no npm, no build tools. Pure Python standard library + vanilla HTML/CSS/JS.

---

## Quick Install (One Command)

SSH into your router, then:

```bash
# Download and install
cd /tmp
wget https://github.com/quyendang/5GDash/archive/refs/heads/main.tar.gz -O 5gdash.tar.gz
tar xzf 5gdash.tar.gz
cd 5GDash-main
sh install.sh
```

Then open **`http://<router-ip>:2222`** in your browser.

---

## Manual Install (Step by Step)

### 1. Install Python3 on your router

```bash
opkg update
opkg install python3
```

### 2. Transfer files to router

**From your computer:**
```bash
# Via SCP
scp -r 5GDash root@192.168.1.1:/tmp/

# Or via SSH + wget if you have internet on router
```

### 3. Run the installer

```bash
ssh root@192.168.1.1
cd /tmp/5GDash
sh install.sh
```

The installer will:
- Detect your modem AT command port automatically
- Copy files to `/opt/5gdash/`
- Create a `procd` init script at `/etc/init.d/5gdash`
- Open firewall port `2222` on the LAN interface
- Start the service and enable auto-start on boot

### 4. Open the dashboard

```
http://192.168.1.1:2222
```

---

## Configuration

Edit `/opt/5gdash/config.json` on the router:

```json
{
  "port":          2222,
  "host":          "0.0.0.0",
  "modem_port":    "auto",
  "poll_interval": 3,
  "www_dir":       "/opt/5gdash/www"
}
```

| Key | Default | Description |
|---|---|---|
| `port` | `2222` | HTTP port for the dashboard |
| `host` | `0.0.0.0` | Bind address (`0.0.0.0` = all interfaces) |
| `modem_port` | `auto` | AT command port. `auto` detects automatically, or set explicitly e.g. `/dev/ttyUSB2` |
| `poll_interval` | `3` | Seconds between modem polls |
| `www_dir` | `/opt/5gdash/www` | Path to static frontend files |

After editing, restart the service:
```bash
/etc/init.d/5gdash restart
```

---

## Service Management

```bash
/etc/init.d/5gdash start      # Start
/etc/init.d/5gdash stop       # Stop
/etc/init.d/5gdash restart    # Restart
/etc/init.d/5gdash status     # Check status

logread | grep 5GDash          # View logs
```

---

## Uninstall

```bash
sh /tmp/5GDash/uninstall.sh
```

This removes all files, the init script, and the firewall rule.

---

## Band Locking

The dashboard supports locking the modem to specific LTE and/or NR5G bands.

**How to use:**
1. Go to the **Band Lock** card
2. Select the bands you want (highlighted = selected)
3. Click **Áp dụng** (Apply)
4. Green-glowing chips = bands the modem is currently camping on

**Common Vietnam bands:**

| Operator | LTE | NR5G |
|---|---|---|
| Viettel | B3, B8 | N78 |
| Vinaphone | B1, B3 | N78 |
| Mobifone | B3, B8 | N78 |
| Gmobile | B28 | N41 |

**To unlock all bands (auto):** Click **Bỏ khóa tất cả**.

---

## API Reference

The server exposes a simple REST + SSE API on the same port:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stream` | SSE stream — pushes full status every `poll_interval` seconds |
| `GET` | `/api/status` | One-shot JSON status snapshot |
| `GET` | `/api/bands` | Available LTE + NR5G bands and current lock config |
| `GET` | `/api/device` | Modem info (IMEI, ICCID, firmware, model) |
| `GET` | `/api/devices` | Connected WiFi + LAN clients |
| `GET` | `/api/sysinfo` | System info (CPU, RAM, ROM, uptime, hostname) |
| `POST` | `/api/band-lock` | `{"lte":["B3","B8"],"nr5g":["N78"]}` — lock bands |
| `POST` | `/api/network-mode` | `{"mode":"auto\|4g\|5g\|4g5g"}` |
| `POST` | `/api/traffic-reset` | Reset modem data counter (`AT+QGDCNT=0`) |
| `POST` | `/api/reconnect` | Force modem reconnect (`AT+CFUN=0/1`) |

---

## Architecture

```
Quectel RM520N-GL
      │ AT commands
      ▼ /dev/ttyUSB2 (auto-detected)
 modem.py  ← ModemManager
      │ Python dict (JSON-serializable)
      ▼
 server.py  ← HTTPServer port 2222
      ├── GET /api/stream   → SSE push every 3s
      ├── GET /api/*        → REST endpoints
      └── GET /             → static www/
            ▼
       Browser Dashboard
       (HTML + CSS + vanilla JS)
```

**Key design decisions:**
- No external Python packages (stdlib only: `http.server`, `termios`, `select`, `threading`)
- No JS frameworks or bundlers — pure HTML/CSS/JS, works offline on the router
- SSE for real-time updates with automatic fallback to polling

---

## Modem Compatibility

Primarily built and tested for **Quectel RM520N-GL**. Other modules with similar AT command sets may work:

| Module | Status |
|---|---|
| RM520N-GL | ✅ Tested |
| RM500Q-GL | 🟡 Should work |
| RM500U-CN | 🟡 Should work |
| RM502Q-AE | 🟡 Should work |
| Other Quectel RM5xx | 🟡 Likely works |
| Sierra Wireless / other | ❌ Not supported |

---

## Troubleshooting

**Dashboard not loading:**
```bash
/etc/init.d/5gdash status
logread | grep 5GDash
```

**Modem port not found:**
```bash
ls /dev/ttyUSB*
# Then set modem_port manually in /opt/5gdash/config.json
```

**All values show `--`:**
- Check Python3 is installed: `python3 --version`
- Check modem is recognized: `ls /dev/ttyUSB*`
- Try AT commands manually:
  ```bash
  echo -e 'ATI\r\n' > /dev/ttyUSB2 && sleep 1 && cat /dev/ttyUSB2
  ```

**Port 2222 blocked:**
```bash
uci show firewall | grep 5gdash
# If empty, add manually:
uci add firewall rule
uci set firewall.@rule[-1].name="5gdash"
uci set firewall.@rule[-1].src="lan"
uci set firewall.@rule[-1].dest_port="2222"
uci set firewall.@rule[-1].proto="tcp"
uci set firewall.@rule[-1].target="ACCEPT"
uci commit firewall && /etc/init.d/firewall reload
```

---

## Project Structure

```
5GDash/
├── install.sh          # One-command installer for OpenWrt
├── uninstall.sh        # Clean uninstaller
├── src/
│   ├── server.py       # HTTP server + SSE broadcaster + system info + device list
│   ├── modem.py        # Modem AT command layer (ModemManager, band tables, PLMN lookup)
│   ├── config.json     # Default configuration
│   └── www/
│       ├── index.html  # Single-page dashboard
│       ├── css/
│       │   └── style.css   # Light flat design, mobile-first
│       └── js/
│           └── app.js      # Dashboard logic, SSE client, charts, band UI
```

---

## Contributing

Pull requests welcome! Particularly interested in:
- Modem compatibility reports and fixes for other RM5xx variants
- Additional operator PLMN mappings (`modem.py` → `PLMN_NAMES`)
- Translation support
- Feature suggestions

---

## License

MIT
