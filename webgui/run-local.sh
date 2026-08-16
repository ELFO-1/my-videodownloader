#!/usr/bin/env bash
# ============================================================================
# Videodownloader Web-GUI LOKAL starten (ohne Server / ohne Docker).
# Braucht nur: python3, yt-dlp, ffmpeg, python-requests.
#
# Nutzung:   ./run-local.sh [PORT]      (Standard-Port 8088)
# Danach im Browser:  http://localhost:8088
#
# Anpassen per Umgebungsvariablen, z. B.:
#   MEDIA_ROOT=~/Videos DEST_FOLDERS="filme,musik" ./run-local.sh
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Wohin geladen wird (Unterordner werden automatisch angelegt)
export MEDIA_ROOT="${MEDIA_ROOT:-$HOME/Downloads}"
# Wo waipu-Login/Tokens gespeichert werden
export DATA_DIR="${DATA_DIR:-$HOME/.config/videodownloader}"
# Auswahl der Ziel-Ordner im UI
export DEST_FOLDERS="${DEST_FOLDERS:-videos,musik}"
# Nur lokal erreichbar. Fuer Zugriff aus dem LAN: BIND=0.0.0.0 *und*
# AUTH_PASSWORD setzen - sonst kann jeder im Netz Downloads ausloesen.
export BIND="${BIND:-127.0.0.1}"
# Gleichzeitige Downloads
export WORKERS="${WORKERS:-2}"

PORT="${1:-8088}"
mkdir -p "$MEDIA_ROOT" "$DATA_DIR"

# kurze Abhängigkeits-Prüfung
for c in python3 yt-dlp ffmpeg; do
  command -v "$c" >/dev/null || { echo "FEHLT: $c (bitte installieren)"; exit 1; }
done

echo "──────────────────────────────────────────────"
echo " Video Downloader (lokal)"
echo "   URL:        http://localhost:$PORT"
echo "   Downloads:  $MEDIA_ROOT/<Ordner>"
echo "   Beenden:    Strg+C"
echo "──────────────────────────────────────────────"
exec python3 "$HERE/server.py" "$PORT"
