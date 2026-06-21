#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web-GUI fuer den Video-Downloader (yt-dlp + waipu.tv).

Reiner Python-Stdlib-Server (wie mediadash). Liefert das Frontend aus und
stellt eine JSON-API fuer Downloads, Job-Status und den waipu-Login bereit.

Aufruf:  python3 server.py [PORT]
Env:     MEDIA_ROOT (Default /media), DATA_DIR (Default /data),
         DEST_FOLDERS (kommagetrennt), AUTH_PASSWORD (optional)
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import waipu
from downloader import JobManager

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DEST_FOLDERS = [d.strip() for d in os.environ.get(
    "DEST_FOLDERS", "downloads,filme,serien,musik,Aufnahmen").split(",") if d.strip()]
QUALITIES = ["best", "1080", "720", "480"]

# globale Singletons
STORE = waipu.Store(os.path.join(DATA_DIR, "waipu.json"))
try:
    WAIPU = waipu.WaipuClient(STORE)
except waipu.WaipuError:
    WAIPU = None
JOBS = JobManager(MEDIA_ROOT, waipu_client=WAIPU)

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoDownloader/1.0"

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
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC, rel)
        if not full.startswith(STATIC) or not os.path.isfile(full):
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
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/config":
            return self._json({
                "dest_folders": DEST_FOLDERS,
                "qualities": QUALITIES,
                "waipu_available": WAIPU is not None,
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
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/download":
            return self._add_download(body)
        if path == "/api/jobs/cancel":
            ok = JOBS.cancel(body.get("id", ""))
            return self._json({"ok": ok})
        if path == "/api/jobs/clear":
            n = JOBS.clear_finished()
            return self._json({"cleared": n})
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
        url = (body.get("url") or "").strip()
        if not url:
            return self._json({"error": "Keine URL angegeben."}, 400)
        quality = body.get("quality", "best")
        dest = body.get("dest", "downloads")
        audio_only = bool(body.get("audio_only"))
        playlist = bool(body.get("playlist"))
        subtitles = bool(body.get("subtitles"))
        # mehrere URLs (zeilenweise) erlauben
        ids = []
        for one in [u.strip() for u in url.splitlines() if u.strip()]:
            ids.append(JOBS.add_url(one, quality, audio_only, dest, playlist, subtitles))
        return self._json({"ids": ids})

    def _ensure_waipu_recordings_cache(self):
        # einfacher In-Memory-Cache der letzten Liste, fuer den Download per Index
        return getattr(self.server, "_waipu_recs", None)

    def _waipu_recordings(self):
        if not WAIPU:
            return self._json({"error": "waipu nicht verfuegbar."}, 400)
        if not WAIPU.is_logged_in():
            return self._json({"error": "Nicht bei waipu angemeldet.", "logged_in": False}, 401)
        try:
            recs = WAIPU.get_recordings()
        except waipu.WaipuError as e:
            return self._json({"error": str(e)}, 502)
        # Cache fuer spaeteren Download per id
        self.server._waipu_recs = {  # type: ignore[attr-defined]
            str(r.get("id") or r.get("recordingId")): r for r in recs
        }
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
        ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
        quality = body.get("quality", "best")
        dest = body.get("dest", "Aufnahmen")
        cache = getattr(self.server, "_waipu_recs", None) or {}
        if not cache:
            return self._json({"error": "Bitte zuerst Aufnahmen laden."}, 400)
        job_ids = []
        for rid in ids:
            rec = cache.get(str(rid))
            if rec:
                job_ids.append(JOBS.add_waipu(rec, quality, dest))
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
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"VideoDownloader laeuft auf :{port}  (media={MEDIA_ROOT}, data={DATA_DIR})")
    print(f"waipu verfuegbar: {WAIPU is not None}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
