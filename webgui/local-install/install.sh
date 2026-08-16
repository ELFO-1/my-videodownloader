#!/usr/bin/env bash
# ============================================================================
# Installiert die lokale Video-Downloader-GUI als:
#   - systemd-User-Service (Autostart beim Login, Port 8088)
#   - Befehl `videodownloader` (~/.local/bin)
#   - Klick-Starter im App-Menue (XDG/KDE)
# Pfade werden automatisch aus dem Repo-Ort ermittelt -> laeuft auf jedem System.
#
# Nutzung:   ./install.sh           (Port 8088)
#            PORT=9000 ./install.sh
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"            # .../my_videodownloader
SERVER="$REPO/webgui/server.py"
PORT="${PORT:-8088}"

[ -f "$SERVER" ] || { echo "FEHLER: server.py nicht gefunden unter $SERVER"; exit 1; }
for c in python3 yt-dlp ffmpeg; do
    command -v "$c" >/dev/null || { echo "FEHLT: $c (bitte installieren)"; exit 1; }
done

BIN="$HOME/.local/bin"
SVC_DIR="$HOME/.config/systemd/user"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$BIN" "$SVC_DIR" "$APP_DIR"

# 1) Befehl
install -m 0755 "$HERE/videodownloader" "$BIN/videodownloader"

# 2) systemd-User-Service ( %h = Home, vom systemd selbst aufgeloest )
cat > "$SVC_DIR/videodownloader.service" <<EOF
[Unit]
Description=Video Downloader (lokale Web-GUI, yt-dlp + waipu)
Documentation=https://github.com/ELFO-1/my-videodownloader

[Service]
Type=simple
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=MEDIA_ROOT=%h/Downloads
Environment=DATA_DIR=%h/.config/videodownloader
Environment=DEST_FOLDERS=videos,musik
# nur lokal erreichbar (fuer LAN-Zugriff zusaetzlich AUTH_PASSWORD setzen)
Environment=BIND=127.0.0.1
ExecStartPre=/usr/bin/mkdir -p %h/Downloads %h/.config/videodownloader
ExecStart=/usr/bin/python3 $SERVER $PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# 3) Klick-Starter
cat > "$APP_DIR/videodownloader.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Video Downloader
GenericName=Video & waipu Downloader
Comment=Videos & waipu-Aufnahmen herunterladen (lokal, yt-dlp)
Exec=$BIN/videodownloader
Icon=folder-download
Terminal=false
Categories=AudioVideo;
Keywords=youtube;yt-dlp;download;waipu;video;musik;
EOF

systemctl --user daemon-reload
systemctl --user enable --now videodownloader.service
update-desktop-database "$APP_DIR" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

echo "✓ Installiert."
echo "  GUI:    http://localhost:$PORT"
echo "  Befehl: videodownloader   (oder App-Menue: 'Video Downloader')"
