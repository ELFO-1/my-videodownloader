#!/usr/bin/env bash
# Entfernt den lokalen Autostart-Dienst, den Befehl und den Klick-Starter.
set -euo pipefail

systemctl --user disable --now videodownloader.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/videodownloader.service"
rm -f "$HOME/.local/bin/videodownloader"
rm -f "$HOME/.local/share/applications/videodownloader.desktop"

systemctl --user daemon-reload
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

echo "✓ Lokaler Autostart/Starter entfernt."
echo "  (Heruntergeladene Dateien in ~/Downloads bleiben erhalten.)"
