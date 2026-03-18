#!/bin/sh
# 5GDash installer for OpenWrt 23
# Usage: sh install.sh
set -e

INSTALL_DIR="/opt/5gdash"
INIT_SCRIPT="/etc/init.d/5gdash"
PORT=2222

echo "═══════════════════════════════════════"
echo "  5GDash Installer — OpenWrt 23"
echo "═══════════════════════════════════════"

if [ "$(id -u)" -ne 0 ]; then
  echo "✗ Cần chạy với quyền root"
  exit 1
fi

# ── Python3 ──────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "→ Cài Python3..."
  opkg update && opkg install python3
fi
echo "✓ Python3: $(python3 --version 2>&1)"

# ── Detect modem ──────────────────────────────────────────────────────────────
MODEM_PORT="auto"
for p in /dev/ttyUSB2 /dev/ttyUSB3 /dev/ttyUSB1; do
  [ -e "$p" ] && MODEM_PORT="$p" && break
done
echo "✓ Modem port: $MODEM_PORT"

# ── Copy files ────────────────────────────────────────────────────────────────
SRC="$(cd "$(dirname "$0")/src" && pwd)"
mkdir -p "$INSTALL_DIR/www/css" "$INSTALL_DIR/www/js"

cp "$SRC/server.py"         "$INSTALL_DIR/"
cp "$SRC/modem.py"          "$INSTALL_DIR/"
cp "$SRC/www/index.html"    "$INSTALL_DIR/www/"
cp "$SRC/www/css/style.css" "$INSTALL_DIR/www/css/"
cp "$SRC/www/js/app.js"     "$INSTALL_DIR/www/js/"

cat > "$INSTALL_DIR/config.json" << EOF
{
  "port":          $PORT,
  "host":          "0.0.0.0",
  "modem_port":    "$MODEM_PORT",
  "poll_interval": 3,
  "www_dir":       "$INSTALL_DIR/www"
}
EOF
echo "✓ Files installed to $INSTALL_DIR"

# ── Init script (procd) ───────────────────────────────────────────────────────
cat > "$INIT_SCRIPT" << 'INITEOF'
#!/bin/sh /etc/rc.common
USE_PROCD=1
START=99
STOP=01

start_service() {
  procd_open_instance
  procd_set_param command /usr/bin/python3 /opt/5gdash/server.py
  procd_set_param respawn 3600 5 5
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
INITEOF

chmod +x "$INIT_SCRIPT"
echo "✓ Init script created"

# ── Firewall ──────────────────────────────────────────────────────────────────
if command -v uci >/dev/null 2>&1; then
  if ! uci show firewall 2>/dev/null | grep -q "5gdash"; then
    uci add firewall rule > /dev/null
    uci set firewall.@rule[-1].name="5gdash"
    uci set firewall.@rule[-1].src="lan"
    uci set firewall.@rule[-1].dest_port="$PORT"
    uci set firewall.@rule[-1].proto="tcp"
    uci set firewall.@rule[-1].target="ACCEPT"
    uci commit firewall
    /etc/init.d/firewall reload 2>/dev/null || true
    echo "✓ Firewall port $PORT opened"
  else
    echo "✓ Firewall rule already exists"
  fi
fi

# ── Start ─────────────────────────────────────────────────────────────────────
"$INIT_SCRIPT" enable
"$INIT_SCRIPT" start

ROUTER_IP=$(uci get network.lan.ipaddr 2>/dev/null || echo "192.168.1.1")
echo ""
echo "═══════════════════════════════════════"
echo "  ✓ 5GDash đã cài đặt thành công!"
echo ""
echo "  → Truy cập: http://$ROUTER_IP:$PORT"
echo "═══════════════════════════════════════"
echo ""
echo "  Lệnh quản lý:"
echo "  $INIT_SCRIPT status|restart|stop"
echo "  logread | grep 5GDash"
