#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web-GUI fuer den Video-Downloader (yt-dlp + waipu.tv).

Reiner Python-Stdlib-Server (wie mediadash). Liefert das Frontend aus und
stellt eine JSON-API fuer Downloads, Job-Status und den waipu-Login bereit.

Aufruf:  python3 server.py [PORT]
Env:     MEDIA_ROOT (Default /media), DATA_DIR (Default /data),
         DEST_FOLDERS (kommagetrennt), WORKERS (Default 2),
         BIND (Default 0.0.0.0),
         AUTH_USER (Default admin), AUTH_PASSWORD (setzen = Basic-Auth aktiv)
"""

import base64
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import waipu
import downloader
from downloader import JobManager

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DEST_FOLDERS = [d.strip() for d in os.environ.get(
    "DEST_FOLDERS", "downloads,filme,serien,musik,Aufnahmen").split(",") if d.strip()]
QUALITIES = ["best", "1080", "720", "480"]
BIND = os.environ.get("BIND", "0.0.0.0")
try:
    WORKERS = max(1, int(os.environ.get("WORKERS", "2")))
except ValueError:
    WORKERS = 2

AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
ALLOWED_SCHEMES = ("http", "https")

# globale Singletons
STORE = waipu.Store(os.path.join(DATA_DIR, "waipu.json"))
try:
    WAIPU = waipu.WaipuClient(STORE)
except waipu.WaipuError:
    WAIPU = None
JOBS = JobManager(MEDIA_ROOT, waipu_client=WAIPU, workers=WORKERS, data_dir=DATA_DIR)

# zuletzt geladene waipu-Aufnahmen (id -> rec), damit ein Download die vollen
# Metadaten hat. Wird bei Bedarf automatisch neu geholt.
_WAIPU_RECS = {}
_WAIPU_LOCK = threading.Lock()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def valid_dest(dest):
    """Nur konfigurierte Zielordner zulassen (kein Ausbrechen aus MEDIA_ROOT)."""
    return dest if dest in DEST_FOLDERS else None


def valid_url(url):
    """Akzeptiert nur http(s)-URLs - schuetzt vor file:// & Optionsinjektion."""
    if url.startswith("-"):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoDownloader/1.1"
    # Keep-Alive spart bei der Fortschritts-Abfrage jede Menge Verbindungsaufbau.
    protocol_version = "HTTP/1.1"
    timeout = 60  # untaetige Verbindungen nicht ewig einen Thread belegen lassen

    def log_message(self, fmt, *args):  # ruhiger
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- Helfer -------------------------------------------------------------

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length or length > 1_000_000:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    # --- Authentifizierung --------------------------------------------------

    def _authorized(self):
        """Basic-Auth, sobald AUTH_PASSWORD gesetzt ist."""
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:].strip()).decode("utf-8")
            user, _, password = raw.partition(":")
        except Exception:
            return False
        ok_user = hmac.compare_digest(user, AUTH_USER)
        ok_pass = hmac.compare_digest(password, AUTH_PASSWORD)
        return ok_user and ok_pass

    def _require_auth(self):
        time.sleep(0.5)  # bremst Rateversuche
        body = b"Anmeldung erforderlich."
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Video Downloader"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC, rel)
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ext = os.path.splitext(full)[1]
        ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- Routing ------------------------------------------------------------

    def do_GET(self):
        if not self._authorized():
            return self._require_auth()
        path = urlparse(self.path).path
        if path == "/api/config":
            return self._json({
                "dest_folders": DEST_FOLDERS,
                "qualities": QUALITIES,
                "waipu_available": WAIPU is not None,
                "ytdlp_version": downloader.ytdlp_version(),
                "ytdlp_updatable": bool(downloader.ytdlp_update_cmd()),
            })
        if path == "/api/jobs":
            return self._json({"jobs": JOBS.list_jobs()})
        if path == "/api/waipu/status":
            return self._json({
                "available": WAIPU is not None,
                "logged_in": bool(WAIPU and WAIPU.is_logged_in()),
            })
        if path == "/api/waipu/login/poll":
            if not WAIPU:
                return self._json({"state": "error", "message": "waipu nicht verfuegbar"}, 400)
            return self._json(WAIPU.poll_device_login())
        if path == "/api/waipu/recordings":
            return self._waipu_recordings()
        return self._serve_static(path)

    def do_POST(self):
        if not self._authorized():
            return self._require_auth()
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/download":
            return self._add_download(body)
        if path == "/api/jobs/cancel":
            ok = JOBS.cancel(str(body.get("id", "")))
            return self._json({"ok": ok})
        if path == "/api/jobs/clear":
            return self._json({"cleared": JOBS.clear_finished()})
        if path == "/api/ytdlp/update":
            ok, message, version = downloader.ytdlp_update()
            return self._json({"ok": ok, "message": message, "version": version},
                              200 if ok else 500)
        if path == "/api/waipu/login/start":
            return self._waipu_login_start()
        if path == "/api/waipu/logout":
            if WAIPU:
                WAIPU.logout()
            return self._json({"ok": True})
        if path == "/api/waipu/download":
            return self._waipu_download(body)
        self.send_error(404, "Not found")

    # --- API-Implementierung ------------------------------------------------

    def _add_download(self, body):
        raw = (body.get("url") or "").strip()
        if not raw:
            return self._json({"error": "Keine URL angegeben."}, 400)
        dest = valid_dest(body.get("dest", "downloads"))
        if not dest:
            return self._json({"error": "Unbekannter Zielordner."}, 400)
        quality = body.get("quality", "best")
        audio_only = bool(body.get("audio_only"))
        playlist = bool(body.get("playlist"))
        subtitles = bool(body.get("subtitles"))
        archive = bool(body.get("archive"))

        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        bad = [u for u in urls if not valid_url(u)]
        if bad:
            return self._json(
                {"error": f"Ungueltige URL (nur http/https): {bad[0][:80]}"}, 400)
        ids = [JOBS.add_url(u, quality, audio_only, dest, playlist, subtitles, archive)
               for u in urls]
        return self._json({"ids": ids})

    def _load_waipu_recs(self):
        """Holt die Aufnahmen und aktualisiert den Cache."""
        recs = WAIPU.get_recordings()
        with _WAIPU_LOCK:
            _WAIPU_RECS.clear()
            for r in recs:
                _WAIPU_RECS[str(r.get("id") or r.get("recordingId"))] = r
        return recs

    def _waipu_recordings(self):
        if not WAIPU:
            return self._json({"error": "waipu nicht verfuegbar."}, 400)
        if not WAIPU.is_logged_in():
            return self._json({"error": "Nicht bei waipu angemeldet.", "logged_in": False}, 401)
        try:
            recs = self._load_waipu_recs()
        except waipu.WaipuError as e:
            return self._json({"error": str(e)}, 502)
        out = []
        for r in recs:
            out.append({
                "id": str(r.get("id") or r.get("recordingId")),
                "label": waipu.recording_label(r),
                "channel": waipu.recording_channel(r),
                "duration": waipu.format_duration(r.get("durationSeconds")),
                "start": (r.get("recordingStartTime") or r.get("startTime") or "")[:16].replace("T", " "),
                "status": r.get("status", ""),
            })
        return self._json({"recordings": out, "logged_in": True})

    def _waipu_login_start(self):
        if not WAIPU:
            return self._json({"error": "waipu nicht verfuegbar."}, 400)
        try:
            info = WAIPU.start_device_login()
        except waipu.WaipuError as e:
            return self._json({"error": str(e)}, 502)
        return self._json(info)

    def _waipu_download(self, body):
        if not WAIPU:
            return self._json({"error": "waipu nicht verfuegbar."}, 400)
        dest = valid_dest(body.get("dest", "Aufnahmen"))
        if not dest:
            return self._json({"error": "Unbekannter Zielordner."}, 400)
        ids = [str(i) for i in (body.get("ids") or ([body["id"]] if body.get("id") else []))]
        if not ids:
            return self._json({"error": "Keine Aufnahme ausgewaehlt."}, 400)
        quality = body.get("quality", "best")

        with _WAIPU_LOCK:
            known = set(_WAIPU_RECS)
        # Cache leer oder veraltet (z. B. nach Serverneustart)? Neu laden.
        if not known.issuperset(ids):
            try:
                self._load_waipu_recs()
            except waipu.WaipuError as e:
                return self._json({"error": str(e)}, 502)

        with _WAIPU_LOCK:
            recs = [_WAIPU_RECS[i] for i in ids if i in _WAIPU_RECS]
        if not recs:
            return self._json({"error": "Aufnahme nicht mehr vorhanden."}, 404)
        job_ids = [JOBS.add_waipu(rec, quality, dest) for rec in recs]
        return self._json({"ids": job_ids})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    os.makedirs(DATA_DIR, exist_ok=True)
    # Standard-Zielordner anlegen (downloads existiert evtl. noch nicht)
    for folder in DEST_FOLDERS:
        try:
            os.makedirs(os.path.join(MEDIA_ROOT, os.path.basename(folder)), exist_ok=True)
        except Exception:
            pass
    httpd = ThreadingHTTPServer((BIND, port), Handler)
    print(f"VideoDownloader laeuft auf {BIND}:{port}  (media={MEDIA_ROOT}, data={DATA_DIR})", flush=True)
    print(f"waipu verfuegbar: {WAIPU is not None} | yt-dlp: {downloader.ytdlp_version() or 'NICHT GEFUNDEN'}", flush=True)
    if AUTH_PASSWORD:
        print(f"Basic-Auth aktiv (Benutzer: {AUTH_USER})", flush=True)
    elif BIND not in ("127.0.0.1", "localhost", "::1"):
        print("WARNUNG: kein AUTH_PASSWORD gesetzt und im Netzwerk erreichbar.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeende laufende Downloads ...")
        JOBS.cancel_all()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
