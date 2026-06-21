# Video Downloader

Eigener Video-Downloader auf Basis von **yt-dlp**, mit Unterstützung für
**waipu.tv-Aufnahmen** (eigene, DRM-freie Aufnahmen).

Zwei Varianten:

## `webgui/` — Web-Oberfläche (aktuell genutzt)

Selbst gebaute Web-GUI (reiner Python-Stdlib-Server), läuft als Docker-Container
und schreibt direkt in die Medienordner (z. B. für Jellyfin).

- **Tab Download:** URL(s) einfügen, Qualität wählen, Ziel-Ordner, Optionen
  (nur Audio/MP3, ganze Playlist, Untertitel), Live-Fortschritt
- **Tab waipu:** Browser-Login (OAuth Device Flow), Aufnahmen-Liste, Download.
  DRM-geschützte (Widevine) Aufnahmen werden erkannt und übersprungen.
- **Playlists:** fehlende/nicht verfügbare Videos werden übersprungen statt
  abzubrechen; der Status meldet z. B. „Fertig – 98 geladen, 1 übersprungen".

Aufbau: `server.py` (HTTP + API), `downloader.py` (yt-dlp Job-Manager mit
Fortschritts-Parsing), `waipu.py` (waipu-Client), `static/` (Frontend).
Deploy via `webgui/deploy.sh`, Container per `webgui/docker-compose.yml`.

## Terminal-Version (Original)

`myvideodownloader2.py` — interaktives Terminal-Menü (yt-dlp + waipu), Vorlage
für die Web-GUI.

---

> Hinweis: Es wird **kein Kopierschutz umgangen**. Die waipu-Funktion lädt nur
> eigene, DRM-freie Aufnahmen aus einem bezahlten Account.
