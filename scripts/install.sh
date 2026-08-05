#!/usr/bin/env bash
# Install Spaceflight CLI symlink, systemd user service, optional waybar snippet,
# then run first-time phone (ntfy) onboarding when interactive.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
SYSTEMD_USER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
WAYBAR_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
WAYBAR_SCRIPTS="$WAYBAR_DIR/scripts"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/spaceflight"

mkdir -p "$BIN_DIR" "$SYSTEMD_USER" "$WAYBAR_SCRIPTS" "$CFG_DIR"
chmod +x "$ROOT/scripts/spaceflight" "$ROOT/scripts/spaceflight-waybar" "$ROOT/scripts/install.sh"

ln -sfn "$ROOT/scripts/spaceflight" "$BIN_DIR/spaceflight"
ln -sfn "$ROOT/scripts/spaceflight-waybar" "$WAYBAR_SCRIPTS/spaceflight-waybar"

# Drop dual-product symlinks if a previous install left them
rm -f "$BIN_DIR/spaceflight-next" "$BIN_DIR/spaceflight-classic" 2>/dev/null || true

# Safe example only — never overwrite a live config.toml (may hold ntfy secrets)
if [[ -f "$ROOT/config.example.toml" && ! -f "$CFG_DIR/config.example.toml" ]]; then
  cp "$ROOT/config.example.toml" "$CFG_DIR/config.example.toml"
fi
if [[ ! -f "$CFG_DIR/config.toml" && -f "$ROOT/config.example.toml" ]]; then
  cp "$ROOT/config.example.toml" "$CFG_DIR/config.toml"
  chmod 600 "$CFG_DIR/config.toml" 2>/dev/null || true
fi

# systemd unit (expand home path)
sed "s|%h|$HOME|g" "$ROOT/systemd/spaceflight.service" > "$SYSTEMD_USER/spaceflight.service"

systemctl --user daemon-reload
systemctl --user enable --now spaceflight.service
systemctl --user restart spaceflight.service 2>/dev/null || true

# Seed cache so waybar has data immediately
"$BIN_DIR/spaceflight" refresh || true

echo ""
echo "Installed:"
echo "  CLI:     $BIN_DIR/spaceflight"
echo "  Waybar:  $WAYBAR_SCRIPTS/spaceflight-waybar"
echo "  Service: spaceflight.service (enabled)"
echo "  Config:  $CFG_DIR/config.toml   (local secrets — never commit)"
echo ""
echo "Add this block to $WAYBAR_DIR/config.jsonc (e.g. modules-center or modules-right):"
echo ""
cat <<'EOF'
  "custom/spaceflight": {
    "return-type": "json",
    "exec": "~/.config/waybar/scripts/spaceflight-waybar",
    "interval": 1,
    "tooltip": true,
    "on-click": "omarchy-launch-or-focus-tui ~/.local/bin/spaceflight",
    "on-click-right": "~/.local/bin/spaceflight refresh",
    "format": "{}"
  },
EOF
echo ""
echo "And add \"custom/spaceflight\" to a modules-* array."
echo "Then: omarchy restart waybar   (or restart waybar)"
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
echo ""

# ── First-install phone (ntfy) onboarding ──────────────────────────────────
# Interactive only. Never prints or commits secrets.
if [[ -t 0 && -t 1 ]]; then
  echo "────────────────────────────────────────────────────────"
  echo "  Optional: phone launch alerts via ntfy"
  echo "────────────────────────────────────────────────────────"
  "$BIN_DIR/spaceflight" setup --first-install || true
else
  echo "Non-interactive install — skip phone wizard."
  echo "  Later:  spaceflight setup"
  echo "  Status: spaceflight setup --status"
fi

echo ""
echo "Quick commands:"
echo "  spaceflight              # mission-control TUI"
echo "  spaceflight setup        # phone (ntfy) wizard anytime"
echo "  spaceflight notify-test  # desktop test"
echo "  spaceflight status"
echo ""
