#!/bin/sh
# 5GDash uninstaller for OpenWrt
set -e

INSTALL_DIR="/opt/5gdash"
INIT_SCRIPT="/etc/init.d/5gdash"

echo "→ Gỡ cài đặt 5GDash..."

# Stop and disable service
if [ -x "$INIT_SCRIPT" ]; then
  "$INIT_SCRIPT" stop  2>/dev/null || true
  "$INIT_SCRIPT" disable 2>/dev/null || true
fi
rm -f "$INIT_SCRIPT"
rm -rf "$INSTALL_DIR"

# Remove firewall rule safely (iterate, match by name)
if command -v uci >/dev/null 2>&1; then
  i=0
  while uci -q get firewall.@rule[$i] >/dev/null 2>&1; do
    name=$(uci -q get firewall.@rule[$i].name 2>/dev/null || echo "")
    if [ "$name" = "5gdash" ]; then
      uci delete firewall.@rule[$i]
      uci commit firewall
      /etc/init.d/firewall reload 2>/dev/null || true
      echo "✓ Đã xóa firewall rule"
      break
    fi
    i=$((i + 1))
  done
fi

echo "✓ Đã gỡ 5GDash hoàn toàn."
