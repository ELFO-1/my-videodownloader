#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yt-dlp Job-Manager mit Live-Fortschritt fuer die Web-GUI.

Jeder Download laeuft als Job in einem Worker-Thread. yt-dlp wird mit
--newline aufgerufen, sodass jede Fortschrittszeile einzeln geparst werden
kann (Prozent / Tempo / ETA / Zieldatei).

Die Job-Historie wird nach DATA_DIR/jobs.json geschrieben und beim Start
wieder eingelesen, damit ein Neustart die Liste nicht verliert.
"""

import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import uuid
from collections import OrderedDict


# [download]  23.4% of  100.00MiB at    1.20MiB/s ETA 00:30
_PROG = re.compile(
    r"\[download\]\s+([\d.]+)%"
    r"(?:\s+of\s+~?\s*(\S+))?"
    r"(?:\s+at\s+(\S+))?"
    r"(?:\s+ETA\s+(\S+))?"
)
_DEST = re.compile(r"\[download\]\s+Destination:\s+(.+)")
_ALREADY = re.compile(r"\[download\]\s+(.+?) has already been downloaded")
_MERGE = re.compile(r'\[Merger\] Merging formats into "(.+)"')
_EXTRACT = re.compile(r'\[ExtractAudio\] Destination:\s+(.+)')
# yt-dlp schreibt je nach Version "item" oder "video"
_ITEM = re.compile(r"Downloading (?:item|video) (\d+) of (\d+)")
_PLAYLIST_N = re.compile(r"Playlist .*?: Downloading (\d+) items")

FINAL_STATES = ("done", "error", "skipped", "canceled")

YTDLP_BIN = os.environ.get("YTDLP_BIN", "yt-dlp")
# Challenge-Solver-Skripte, die yt-dlp bei Bedarf nachlaedt. YouTube verlangt
# das Loesen einer JS-Challenge; ohne Solver (und ohne JS-Laufzeit wie Deno)
# bleiben nur Formate uebrig, deren URLs mit HTTP 403 abgewiesen werden.
# Auf "" setzen, um das Nachladen zu unterbinden.
YTDLP_REMOTE_COMPONENTS = os.environ.get("YTDLP_REMOTE_COMPONENTS", "ejs:github")
# YouTube drosselt schnelle Serien von Anfragen: das erste Video laedt, danach
# kommt fuer den Rest HTTP 403. Eine kurze zufaellige Pause zwischen den Videos
# einer Playlist vermeidet das weitgehend. 0 schaltet die Pausen ab.
def _float_env(name, default):
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return default


# Formatwahl fuer Jellyfin: zuerst die hoechste Aufloesung, und bei gleicher
# Aufloesung H.264 + AAC bevorzugen - das spielt Jellyfin auf jedem Client
# direkt ab. Oberhalb 1080p bietet YouTube kein H.264 an, dort greift
# automatisch VP9/AV1.
FORMAT_SORT = os.environ.get("YTDLP_FORMAT_SORT",
                             "res,vcodec:h264,acodec:aac,ext:mp4:m4a")
# Einheitlicher Container, damit nicht mal .webm und mal .mp4 herauskommt.
MERGE_FORMAT = os.environ.get("YTDLP_MERGE_FORMAT", "mp4")

SLEEP_REQUESTS = _float_env("YTDLP_SLEEP_REQUESTS", 1.0)
SLEEP_INTERVAL = _float_env("YTDLP_SLEEP_INTERVAL", 5.0)
MAX_SLEEP_INTERVAL = _float_env("YTDLP_MAX_SLEEP_INTERVAL", 30.0)

_remote_components_ok = None


def supports_remote_components():
    """Prueft einmalig, ob das installierte yt-dlp --remote-components kennt."""
    global _remote_components_ok
    if _remote_components_ok is None:
        try:
            out = subprocess.run([YTDLP_BIN, "--help"], capture_output=True,
                                 text=True, timeout=30)
            _remote_components_ok = "--remote-components" in out.stdout
        except (OSError, subprocess.SubprocessError):
            _remote_components_ok = False
    return _remote_components_ok


def ytdlp_update_cmd():
    """Wie yt-dlp aktualisiert wird - oder "" wenn es keinen sicheren Weg gibt.

    Per YTDLP_UPDATE_CMD ueberschreibbar (der Container setzt das auf sein
    venv-pip). Sonst wird nur aktualisiert, wenn yt-dlp im selben venv liegt
    wie dieser Python. Bei einem Distributions-Paket (pacman/apt) wuerde pip
    das System zerschiessen bzw. an PEP 668 scheitern - dann lieber nichts tun.
    """
    env = os.environ.get("YTDLP_UPDATE_CMD", "").strip()
    if env:
        return env
    path = shutil.which(YTDLP_BIN)
    in_venv = sys.prefix != sys.base_prefix
    if path and in_venv and os.path.dirname(path) == os.path.dirname(sys.executable):
        return f"{shlex.quote(sys.executable)} -m pip install --no-cache-dir --upgrade yt-dlp"
    return ""


def shorten_error(line):
    """Macht aus einer yt-dlp-ERROR-Zeile eine lesbare Meldung.

    yt-dlp haengt den Ursprungsfehler oft noch einmal in "(caused by ...)" an -
    das verdoppelt den Text ohne Mehrwert.
    """
    text = line.strip()
    text = re.sub(r"^(?:ERROR|WARNING):\s*", "", text)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)      # Extractor-Praefix
    text = text.split(" (caused by")[0]
    return text[:200].strip()


def quality_format(quality):
    """Uebersetzt 'best' / '1080' / '720' ... in einen yt-dlp Format-String.

    Erste Wahl ist immer 'bv' (reiner Video-Stream) + 'ba', also getrennte
    DASH-Streams. Das progressive Kombiformat (bei YouTube Format 18) kommt
    erst ganz am Ende zum Zug, aus zwei Gruenden:

      * YouTube weist dessen URLs derzeit mit HTTP 403 ab, waehrend dieselben
        Inhalte als getrennte Streams anstandslos laden.
      * Es ist ohnehin auf 360p begrenzt. Sobald ein Video nicht hoeher
        aufloest, gewinnt es die Sortierung nach 'res' gegen den gleich
        grossen Video-Stream - und zieht die Qualitaet unbemerkt nach unten.
    """
    q = (quality or "best").strip().lower()
    if q.isdigit():
        return (f"bv[height<={q}]+ba/bv*[height<={q}]+ba"
                f"/b[height<={q}]/b")
    return "bv+ba/bv*+ba/b"


def ytdlp_version():
    """Liefert die installierte yt-dlp-Version (oder '' wenn nicht gefunden)."""
    try:
        out = subprocess.run([YTDLP_BIN, "--version"], capture_output=True,
                             text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def ytdlp_update():
    """Aktualisiert yt-dlp. Liefert (ok, meldung, neue_version)."""
    before = ytdlp_version()
    update_cmd = ytdlp_update_cmd()
    if not update_cmd:
        return False, ("yt-dlp wird vom System verwaltet (z. B. pacman/apt). "
                       "Bitte darueber aktualisieren."), before
    try:
        cmd = shlex.split(update_cmd)
    except ValueError as e:
        return False, f"Ungueltiges YTDLP_UPDATE_CMD: {e}", before
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"Update fehlgeschlagen: {e}", before
    after = ytdlp_version()
    if out.returncode != 0:
        tail = (out.stderr or out.stdout or "").strip().splitlines()
        detail = tail[-1][:200] if tail else f"Exit-Code {out.returncode}"
        return False, f"Update fehlgeschlagen: {detail}", after or before
    if after and before and after == before:
        return True, f"Bereits aktuell ({after}).", after
    return True, f"Aktualisiert: {before or '?'} → {after or '?'}", after


class Job:
    def __init__(self, title, kind, dest):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.kind = kind          # 'url' | 'playlist' | 'waipu'
        self.dest = dest
        self.status = "queued"    # queued|running|done|error|skipped|canceled
        self.percent = 0.0        # Gesamtfortschritt (bei Playlists ueber alle Videos)
        self.item_percent = 0.0   # Fortschritt des aktuellen Videos
        self.speed = ""
        self.eta = ""
        self.size = ""            # Groesse laut yt-dlp, z. B. "104.20MiB"
        self.message = ""
        self.filename = ""        # absoluter Pfad der Zieldatei
        self.relpath = ""         # Pfad relativ zum Medien-Root (fuer die Anzeige)
        self.item = 0             # aktuelles Video einer Playlist
        self.failed = 0           # uebersprungene/fehlgeschlagene Videos (Playlist)
        self.total = 0            # Gesamtzahl Videos laut Playlist
        self.last_error = ""      # letzte ERROR-Zeile von yt-dlp
        self.last_warning = ""    # letzte WARNING-Zeile (hilft bei der Ursache)
        self.created = time.time()
        self.finished = None
        self.out_dir = ""
        self._proc = None
        self._cancel = False

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "dest": self.dest,
            "status": self.status,
            "percent": round(self.percent, 1),
            "item_percent": round(self.item_percent, 1),
            "speed": self.speed,
            "eta": self.eta,
            "size": self.size,
            "message": self.message,
            "filename": os.path.basename(self.filename) if self.filename else "",
            "relpath": self.relpath,
            "item": self.item,
            "total": self.total,
            "failed": self.failed,
            "created": self.created,
            "finished": self.finished,
        }

    @classmethod
    def from_dict(cls, data):
        """Stellt einen Job aus der gespeicherten Historie wieder her."""
        job = cls(data.get("title", ""), data.get("kind", "url"), data.get("dest", ""))
        job.id = data.get("id") or job.id
        job.status = data.get("status", "done")
        job.percent = float(data.get("percent") or 0)
        job.item_percent = float(data.get("item_percent") or 0)
        job.size = data.get("size", "")
        job.message = data.get("message", "")
        job.filename = data.get("filename", "")
        job.relpath = data.get("relpath", "")
        job.item = int(data.get("item") or 0)
        job.total = int(data.get("total") or 0)
        job.failed = int(data.get("failed") or 0)
        job.created = float(data.get("created") or time.time())
        job.finished = data.get("finished")
        return job


class JobManager:
    def __init__(self, media_root, waipu_client=None, workers=2, max_jobs=100,
                 data_dir=None):
        self.media_root = media_root
        self.waipu = waipu_client
        self.data_dir = data_dir
        self.jobs = OrderedDict()      # id -> Job
        self.max_jobs = max_jobs
        self._queue = []               # list of (job, runnable)
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._state_path = os.path.join(data_dir, "jobs.json") if data_dir else None
        self._load_state()
        for _ in range(workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()

    # --- oeffentliche API ---------------------------------------------------

    def list_jobs(self):
        with self._lock:
            return [j.to_dict() for j in self.jobs.values()]

    def clear_finished(self):
        with self._lock:
            done = [jid for jid, j in self.jobs.items() if j.status in FINAL_STATES]
            for jid in done:
                del self.jobs[jid]
        self._save_state()
        return len(done)

    def cancel(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job._cancel = True
            proc = job._proc
            queued = job.status == "queued"
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        elif queued:
            # noch nicht gestartet: sofort als abgebrochen markieren
            with self._lock:
                if job.status == "queued":
                    job.status = "canceled"
                    job.message = "Abgebrochen."
                    job.finished = time.time()
            self._save_state()
        return True

    def cancel_all(self):
        """Beendet laufende yt-dlp-Prozesse (fuer sauberes Herunterfahren)."""
        with self._lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            if job.status in ("running", "queued"):
                self.cancel(job.id)

    def add_url(self, url, quality="best", audio_only=False, dest="downloads",
                playlist=False, subtitles=False, archive=False, cookies=False):
        kind = "playlist" if playlist else "url"
        job = Job(title=url, kind=kind, dest=dest)
        self._register(job, lambda: self._run_url(
            job, url, quality, audio_only, dest, playlist, subtitles, archive,
            cookies))
        return job.id

    def add_waipu(self, rec, quality="best", dest="Aufnahmen"):
        from waipu import recording_label
        job = Job(title=recording_label(rec), kind="waipu", dest=dest)
        self._register(job, lambda: self._run_waipu(job, rec, quality, dest))
        return job.id

    # --- Persistenz ---------------------------------------------------------

    def _load_state(self):
        if not self._state_path or not os.path.isfile(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        for entry in data.get("jobs", [])[-self.max_jobs:]:
            try:
                job = Job.from_dict(entry)
            except Exception:
                continue
            if job.status not in FINAL_STATES:
                # lief beim letzten Beenden noch -> kann nicht fortgesetzt werden
                job.status = "error"
                job.message = "Durch Neustart des Servers unterbrochen."
                job.finished = job.finished or time.time()
            self.jobs[job.id] = job

    def _save_state(self):
        if not self._state_path:
            return
        with self._lock:
            payload = {"jobs": [j.to_dict() for j in self.jobs.values()]}
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, self._state_path)
        except OSError:
            pass  # Historie ist nice-to-have, kein Grund den Job zu kippen

    # --- intern -------------------------------------------------------------

    def _register(self, job, runnable):
        with self._cv:
            # alte fertige Jobs begrenzen
            while len(self.jobs) >= self.max_jobs:
                oldest = next((jid for jid, j in self.jobs.items()
                               if j.status in FINAL_STATES), None)
                if oldest is None:
                    break
                del self.jobs[oldest]
            self.jobs[job.id] = job
            self._queue.append((job, runnable))
            self._cv.notify()

    def _worker(self):
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                job, runnable = self._queue.pop(0)
            if job._cancel:
                if job.status not in FINAL_STATES:
                    job.status = "canceled"
                    job.message = "Abgebrochen."
                    job.finished = time.time()
                self._save_state()
                continue
            job.status = "running"
            try:
                runnable()
            except Exception as e:  # pragma: no cover
                job.status = "error"
                job.message = str(e)
            if job.status == "running":
                job.status = "done"
            job.finished = time.time()
            job.speed = ""
            job.eta = ""
            self._save_state()

    def _dest_path(self, dest):
        # nur erlaubte Unterordner unterhalb media_root
        safe = os.path.basename(dest or "downloads")
        path = os.path.join(self.media_root, safe)
        os.makedirs(path, exist_ok=True)
        return path

    def _base_args(self):
        """Argumente, die jeder yt-dlp-Aufruf bekommt."""
        args = ["--newline", "--ignore-config", "--no-overwrites"]
        if self.data_dir:
            # Der Container-User hat kein beschreibbares HOME - ohne eigenen
            # Cache laedt yt-dlp das Solver-Skript bei jedem Aufruf neu.
            args += ["--cache-dir", os.path.join(self.data_dir, "cache")]
        if YTDLP_REMOTE_COMPONENTS and supports_remote_components():
            args += ["--remote-components", YTDLP_REMOTE_COMPONENTS]
        if SLEEP_REQUESTS:
            args += ["--sleep-requests", str(SLEEP_REQUESTS)]
        args += ["--extractor-retries", "5"]
        return args

    def _format_args(self):
        """Sortierung und Zielcontainer (siehe FORMAT_SORT)."""
        args = []
        if FORMAT_SORT:
            args += ["-S", FORMAT_SORT]
        if MERGE_FORMAT:
            args += ["--merge-output-format", MERGE_FORMAT]
        return args

    def _throttle_args(self):
        """Zufaellige Pause zwischen den Videos einer Playlist."""
        if not SLEEP_INTERVAL:
            return []
        return ["--sleep-interval", str(SLEEP_INTERVAL),
                "--max-sleep-interval", str(max(SLEEP_INTERVAL, MAX_SLEEP_INTERVAL))]

    def cookies_path(self):
        """Pfad der optionalen cookies.txt - oder "" wenn keine hinterlegt ist."""
        if not self.data_dir:
            return ""
        path = os.path.join(self.data_dir, "cookies.txt")
        return path if os.path.isfile(path) else ""

    def _cookie_copy(self, use_cookies):
        """Wegwerf-Kopie der cookies.txt fuer genau einen yt-dlp-Lauf.

        yt-dlp schreibt die Cookie-Datei nach jedem Lauf zurueck. YouTube
        beantwortet Anfragen dabei regelmaessig mit einem Logout - danach
        fehlen SID, SAPISID, __Secure-1PSID & Co. in der Datei und jeder
        weitere Download scheitert mit HTTP 403. yt-dlp bekommt deshalb nur
        eine Kopie zu sehen; das Original bleibt unangetastet.

        Ausserdem ist --cookies eine bewusste Entscheidung pro Download:
        eine kaputte Session laesst Videos scheitern, die ohne Cookies
        problemlos laden.
        """
        src = self.cookies_path() if use_cookies else ""
        if not src:
            return ""
        fd, tmp = tempfile.mkstemp(prefix=".cookies-", suffix=".txt",
                                   dir=self.data_dir or None)
        os.close(fd)
        try:
            shutil.copyfile(src, tmp)
            os.chmod(tmp, 0o600)
        except OSError:
            self._drop_cookie_copy(tmp)
            return ""
        return tmp

    @staticmethod
    def _drop_cookie_copy(path):
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def _archive_args(self, dest):
        """Fuehrt pro Zielordner eine Liste bereits geladener Videos."""
        if not self.data_dir:
            return []
        archive_dir = os.path.join(self.data_dir, "archive")
        try:
            os.makedirs(archive_dir, exist_ok=True)
        except OSError:
            return []
        safe = os.path.basename(dest or "downloads")
        return ["--download-archive", os.path.join(archive_dir, safe + ".txt")]

    def _set_file(self, job, path):
        job.filename = path
        try:
            rel = os.path.relpath(path, self.media_root)
        except ValueError:
            rel = ""
        job.relpath = "" if rel.startswith("..") else rel

    def _set_percent(self, job, pct):
        """Rechnet den Video-Fortschritt auf den Gesamtfortschritt hoch."""
        job.item_percent = pct
        if job.total > 1 and job.item:
            done_items = min(job.item - 1, job.total)
            job.percent = min(100.0, (done_items + pct / 100.0) / job.total * 100.0)
        else:
            job.percent = pct

    def _cleanup_partials(self, job):
        """Entfernt .part/.ytdl-Reste eines abgebrochenen Downloads."""
        if not job.filename:
            return
        base = glob.escape(job.filename)
        for pattern in (base + ".part*", base + ".ytdl"):
            for leftover in glob.glob(pattern):
                try:
                    os.remove(leftover)
                except OSError:
                    pass

    def _run_proc(self, job, cmd):
        """Startet yt-dlp und parst den Fortschritt zeilenweise."""
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except OSError as e:
            job.last_error = f"{cmd[0]} konnte nicht gestartet werden: {e}"
            return 127
        job._proc = proc
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                m = _DEST.search(line)
                if m:
                    self._set_file(job, m.group(1).strip())
                    continue
                m = _MERGE.search(line) or _EXTRACT.search(line)
                if m:
                    self._set_file(job, m.group(1).strip())
                    job.message = "Verarbeite ..."
                    continue
                m = _ALREADY.search(line)
                if m:
                    self._set_file(job, m.group(1).strip())
                    self._set_percent(job, 100.0)
                    continue
                m = _PROG.search(line)
                if m:
                    self._set_percent(job, float(m.group(1)))
                    if m.group(2):
                        job.size = m.group(2).strip()
                    job.speed = (m.group(3) or "").strip()
                    job.eta = (m.group(4) or "").strip()
                    continue
                m = _ITEM.search(line)
                if m:
                    job.item = int(m.group(1))
                    job.total = int(m.group(2))
                    job.message = f"Video {job.item}/{job.total}"
                    continue
                m = _PLAYLIST_N.search(line)
                if m:
                    job.total = int(m.group(1))
                    continue
                if line.startswith("ERROR"):
                    job.failed += 1
                    job.last_error = shorten_error(line)
                elif line.startswith("WARNING"):
                    job.last_warning = shorten_error(line)
        finally:
            proc.wait()
            job._proc = None
        return proc.returncode

    def _error_message(self, job, rc, fallback=""):
        """Fehlertext plus letzte Warnung - die nennt oft die eigentliche Ursache
        (z. B. fehlende JS-Laufzeit, weswegen YouTube nur 403 liefert)."""
        text = job.last_error or fallback or f"yt-dlp Fehler (Code {rc})."
        if job.last_warning and job.last_warning[:40] not in text:
            text += f" — Hinweis: {job.last_warning}"
        return text

    def _run_url(self, job, url, quality, audio_only, dest, playlist, subtitles,
                 archive=False, use_cookies=False):
        out_dir = self._dest_path(dest)
        job.out_dir = out_dir
        cmd = [YTDLP_BIN] + self._base_args() + ["-P", out_dir]
        # Cookies optional: nur anhaengen, wenn DATA_DIR/cookies.txt vorhanden ist.
        cookie_file = self._cookie_copy(use_cookies)
        if cookie_file:
            cmd += ["--cookies", cookie_file]
        if audio_only:
            cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0",
                    "-o", "%(title)s.%(ext)s"]
        else:
            cmd += ["-f", quality_format(quality)] + self._format_args()
            if playlist:
                # fehlende/nicht verfuegbare Videos ueberspringen statt abbrechen
                # Der "/" muss AUSSERHALB der Klammer stehen, sonst gilt er als
                # Teil des Feldwerts und yt-dlp ersetzt ihn durch "\u29f8" - dann
                # entsteht ein flacher Dateiname statt eines Unterordners.
                # Die Fallback-Kette verhindert einen leeren Wert (fuehrender "/"
                # waere ein absoluter Pfad, bei dem -P ignoriert wird).
                cmd += ["--ignore-errors"] + self._throttle_args() + [
                    "-o", "%(playlist_title,playlist_id|Playlist)s/%(title)s.%(ext)s"]
            else:
                cmd += ["--no-playlist", "-o", "%(title)s.%(ext)s"]
        if archive:
            cmd += self._archive_args(dest)
        if subtitles:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "de",
                    "--embed-subs", "--convert-subs", "srt"]
        # "--" trennt Optionen von der URL: sonst wuerde yt-dlp eine mit "-"
        # beginnende Eingabe als Option interpretieren (z. B. --exec).
        cmd += ["--", url]
        try:
            rc = self._run_proc(job, cmd)
        finally:
            self._drop_cookie_copy(cookie_file)
        if job._cancel:
            job.status = "canceled"
            job.message = "Abgebrochen."
            self._cleanup_partials(job)
        elif playlist:
            # Playlist gilt als erfolgreich, solange nicht ALLE Videos fehlschlugen.
            got = (job.total - job.failed) if job.total else None
            if job.failed and got == 0:
                job.status = "error"
                job.message = self._error_message(job, rc, "Alle Videos fehlgeschlagen.")
            else:
                job.status = "done"
                job.percent = 100.0
                if job.failed:
                    cnt = f"{got} geladen, " if got is not None else ""
                    job.message = f"Fertig – {cnt}{job.failed} übersprungen."
                else:
                    job.message = "Fertig."
        elif rc == 0:
            job.status = "done"
            job.percent = 100.0
            job.message = "Fertig."
        else:
            job.status = "error"
            job.message = self._error_message(job, rc)

    def _run_waipu(self, job, rec, quality, dest):
        if self.waipu is None:
            job.status = "error"
            job.message = "waipu nicht verfuegbar."
            return
        from waipu import WAIPU_USER_AGENT, WaipuError
        try:
            stream_url, base, drm = self.waipu.resolve_recording(rec)
        except WaipuError as e:
            job.status = "error"
            job.message = str(e)
            return
        if drm:
            job.status = "skipped"
            job.message = "DRM-geschuetzt (Widevine) - uebersprungen."
            return

        out_dir = self._dest_path(dest)
        job.out_dir = out_dir
        out_template = os.path.join(out_dir, base + ".%(ext)s")
        # bereits vorhanden?
        existing = [f for f in os.listdir(out_dir)
                    if f.startswith(base + ".") and not f.endswith((".part", ".ytdl"))]
        if existing:
            job.status = "skipped"
            job.message = "Datei existiert bereits - uebersprungen."
            self._set_file(job, os.path.join(out_dir, existing[0]))
            return

        cmd = [YTDLP_BIN] + self._base_args() + [
            "-f", quality_format(quality)] + self._format_args() + [
            "--add-header", f"User-Agent: {WAIPU_USER_AGENT}",
            "-o", out_template, "--", stream_url]
        rc = self._run_proc(job, cmd)
        if job._cancel:
            job.status = "canceled"
            job.message = "Abgebrochen."
            self._cleanup_partials(job)
        elif rc == 0:
            job.status = "done"
            job.percent = 100.0
            job.message = "Fertig."
        else:
            job.status = "error"
            job.message = self._error_message(job, rc)
