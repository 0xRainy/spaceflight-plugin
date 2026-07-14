#!/usr/bin/env bash
# Install spaceflight CLI symlink, systemd user service, and optional waybar snippet.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
SYSTEMD_USER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
WAYBAR_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
WAYBAR_SCRIPTS="$WAYBAR_DIR/scripts"

mkdir -p "$BIN_DIR" "$SYSTEMD_USER" "$WAYBAR_SCRIPTS"
chmod +x "$ROOT/scripts/spaceflight" "$ROOT/scripts/spaceflight-waybar" "$ROOT/scripts/install.sh"

ln -sfn "$ROOT/scripts/spaceflight" "$BIN_DIR/spaceflight"
ln -sfn "$ROOT/scripts/spaceflight-waybar" "$WAYBAR_SCRIPTS/spaceflight-waybar"

# systemd unit (expand home path)
sed "s|%h|$HOME|g" "$ROOT/systemd/spaceflight.service" > "$SYSTEMD_USER/spaceflight.service"

systemctl --user daemon-reload
systemctl --user enable --now spaceflight.service

# Seed cache so waybar has data immediately
"$BIN_DIR/spaceflight" refresh || true

echo ""
echo "Installed:"
echo "  CLI:     $BIN_DIR/spaceflight"
echo "  Waybar:  $WAYBAR_SCRIPTS/spaceflight-waybar"
echo "  Service: spaceflight.service (enabled)"
echo ""
echo "Add this block to $WAYBAR_DIR/config.jsonc (e.g. modules-center or modules-right):"
echo ""
cat <<'EOF'
  "custom/spaceflight": {
    "return-type": "json",
    "exec": "~/.config/waybar/scripts/spaceflight-waybar",
    "interval": 30,
    "tooltip": true,
    "on-click": "xdg-terminal-exec -e spaceflight",
    "on-click-right": "spaceflight refresh",
    "format": "{}"
  },
EOF
echo ""
echo "And add \"custom/spaceflight\" to a modules-* array."
echo "Then: omarchy restart waybar"
echo ""
echo "Optional CSS (~/.config/waybar/style.css):"
cat <<'EOF'
#custom-spaceflight {
  padding: 0 8px;
  color: #7dcfff;
}
#custom-spaceflight.live { color: #f7768e; }
#custom-spaceflight.hold { color: #e0af68; }
#custom-spaceflight.go { color: #9ece6a; }
EOF
