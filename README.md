# Video Downloader

Eigener Video-Downloader auf Basis von **yt-dlp**, mit Unterstützung für
**waipu.tv-Aufnahmen** (eigene, DRM-freie Aufnahmen).

Zwei Varianten:

## `webgui/` — Web-Oberfläche (aktuell genutzt)

Selbst gebaute Web-GUI (reiner Python-Stdlib-Server), läuft als Docker-Container
und schreibt direkt in die Medienordner (z. B. für Jellyfin).

- **Tab Download:** URL(s) einfügen, Qualität wählen, Ziel-Ordner, Optionen
  (nur Audio/MP3, ganze Playlist, Untertitel, Archiv), Live-Fortschritt
- **Tab waipu:** Browser-Login (OAuth Device Flow), Aufnahmen-Liste, Download.
  DRM-geschützte (Widevine) Aufnahmen werden erkannt und übersprungen.
- **Playlists:** fehlende/nicht verfügbare Videos werden übersprungen statt
  abzubrechen; der Status meldet z. B. „Fertig – 98 geladen, 1 übersprungen".
  Der Fortschritt zählt über alle Videos („Video 3/12 · 47 %").
- **Archiv:** mit „Schon Geladenes überspringen" merkt sich die App pro
  Ziel-Ordner, was bereits geladen wurde — erneutes Laden derselben Playlist
  überspringt diese Videos sofort (`DATA_DIR/archive/<ordner>.txt`).
- **Job-Historie** überlebt einen Neustart (`DATA_DIR/jobs.json`).
- **yt-dlp aktualisieren** direkt aus der Fußzeile der GUI (im Container).

Aufbau: `server.py` (HTTP + API), `downloader.py` (yt-dlp Job-Manager mit
Fortschritts-Parsing), `waipu.py` (waipu-Client), `static/` (Frontend).
Deploy via `webgui/deploy.sh`, Container per `webgui/docker-compose.yml`.

### Konfiguration (Umgebungsvariablen)

| Variable | Default | Bedeutung |
|---|---|---|
| `MEDIA_ROOT` | `/media` | Wurzel der Zielordner |
| `DATA_DIR` | `/data` | Tokens, Job-Historie, Archiv, `cookies.txt` |
| `DEST_FOLDERS` | `downloads,filme,…` | Auswahl im UI (nur diese sind erlaubt) |
| `WORKERS` | `2` | gleichzeitige Downloads |
| `BIND` | `0.0.0.0` | Netzwerk-Interface |
| `AUTH_USER` / `AUTH_PASSWORD` | `admin` / *(leer)* | Basic-Auth; **leer = kein Schutz** |
| `YTDLP_BIN`, `YTDLP_UPDATE_CMD` | | abweichender yt-dlp-Pfad / Update-Befehl |

> ⚠️ Ohne `AUTH_PASSWORD` kann jeder, der den Port erreicht, Downloads auslösen.
> Die lokalen Starter (`run-local.sh`, systemd-Service) binden deshalb nur an
> `127.0.0.1`. Für LAN-Zugriff `BIND=0.0.0.0` **und** `AUTH_PASSWORD` setzen.

Cookies für Login-pflichtige Seiten: `cookies.txt` (Netscape-Format) nach
`DATA_DIR` legen — sie wird automatisch an yt-dlp übergeben.

## Terminal-Version (Original)

`myvideodownloader2.py` — interaktives Terminal-Menü (yt-dlp + waipu), Vorlage
für die Web-GUI. Ältere Entwicklungsstände liegen in `legacy/`.

---

> Hinweis: Es wird **kein Kopierschutz umgangen**. Die waipu-Funktion lädt nur
> eigene, DRM-freie Aufnahmen aus einem bezahlten Account.
