#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yt-dlp Job-Manager mit Live-Fortschritt fuer die Web-GUI.

Jeder Download laeuft als Job in einem Worker-Thread. yt-dlp wird mit
--newline aufgerufen, sodass jede Fortschrittszeile einzeln geparst werden
kann (Prozent / Tempo / ETA / Zieldatei).
"""

import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from collections import OrderedDict


# [download]  23.4% of  100.00MiB at    1.20MiB/s ETA 00:30
_PROG = re.compile(
    r"\[download\]\s+([\d.]+)%"
    r"(?:\s+of\s+~?\s*\S+)?"
    r"(?:\s+at\s+(\S+))?"
    r"(?:\s+ETA\s+(\S+))?"
)
_DEST = re.compile(r"\[download\]\s+Destination:\s+(.+)")
_ALREADY = re.compile(r"\[download\]\s+(.+?) has already been downloaded")
_MERGE = re.compile(r'\[Merger\] Merging formats into "(.+)"')
_EXTRACT = re.compile(r'\[ExtractAudio\] Destination:\s+(.+)')
_ITEM = re.compile(r"Downloading item (\d+) of (\d+)")


def quality_format(quality):
    """Uebersetzt 'best' / '1080' / '720' ... in einen yt-dlp Format-String."""
    q = (quality or "best").strip().lower()
    if q.isdigit():
        return f"bv*[height<={q}]+ba/b[height<={q}]/b"
    return "bv*+ba/b"


class Job:
    def __init__(self, title, kind, dest):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.kind = kind          # 'url' | 'playlist' | 'waipu'
        self.dest = dest
        self.status = "queued"    # queued|running|done|error|skipped|canceled
        self.percent = 0.0
        self.speed = ""
        self.eta = ""
        self.message = ""
        self.filename = ""
        self.failed = 0           # uebersprungene/fehlgeschlagene Videos (Playlist)
        self.total = 0            # Gesamtzahl Videos laut Playlist
        self.last_error = ""      # letzte ERROR-Zeile von yt-dlp
        self.created = time.time()
        self.finished = None
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
            "speed": self.speed,
            "eta": self.eta,
            "message": self.message,
            "filename": os.path.basename(self.filename) if self.filename else "",
            "created": self.created,
            "finished": self.finished,
        }


class JobManager:
    def __init__(self, media_root, waipu_client=None, workers=2, max_jobs=100):
        self.media_root = media_root
        self.waipu = waipu_client
        self.jobs = OrderedDict()      # id -> Job
        self.max_jobs = max_jobs
        self._queue = []               # list of (job, runnable)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        for _ in range(workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()

    # --- oeffentliche API ---------------------------------------------------

    def list_jobs(self):
        with self._lock:
            return [j.to_dict() for j in self.jobs.values()]

    def clear_finished(self):
        with self._lock:
            done = [jid for jid, j in self.jobs.items()
                    if j.status in ("done", "error", "skipped", "canceled")]
            for jid in done:
                del self.jobs[jid]
        return len(done)

    def cancel(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job._cancel = True
            proc = job._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        return True

    def add_url(self, url, quality="best", audio_only=False, dest="downloads",
                playlist=False, subtitles=False):
        kind = "playlist" if playlist else "url"
        job = Job(title=url, kind=kind, dest=dest)
        self._register(job, lambda: self._run_url(
            job, url, quality, audio_only, dest, playlist, subtitles))
        return job.id

    def add_waipu(self, rec, quality="best", dest="Aufnahmen"):
        from waipu import recording_label
        job = Job(title=recording_label(rec), kind="waipu", dest=dest)
        self._register(job, lambda: self._run_waipu(job, rec, quality, dest))
        return job.id

    # --- intern -------------------------------------------------------------

    def _register(self, job, runnable):
        with self._cv:
            # alte fertige Jobs begrenzen
            if len(self.jobs) >= self.max_jobs:
                for jid, j in list(self.jobs.items()):
                    if j.status in ("done", "error", "skipped", "canceled"):
                        del self.jobs[jid]
                        break
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
                job.status = "canceled"
                job.message = "Abgebrochen."
                job.finished = time.time()
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

    def _dest_path(self, dest):
        # nur erlaubte Unterordner unterhalb media_root
        safe = os.path.basename(dest or "downloads")
        path = os.path.join(self.media_root, safe)
        os.makedirs(path, exist_ok=True)
        return path

    def _run_proc(self, job, cmd):
        """Startet yt-dlp und parst den Fortschritt zeilenweise."""
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        job._proc = proc
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            m = _DEST.search(line)
            if m:
                job.filename = m.group(1).strip()
                continue
            m = _MERGE.search(line) or _EXTRACT.search(line)
            if m:
                job.filename = m.group(1).strip()
                job.message = "Verarbeite ..."
                continue
            m = _ALREADY.search(line)
            if m:
                job.filename = m.group(1).strip()
                job.percent = 100.0
                continue
            m = _PROG.search(line)
            if m:
                job.percent = float(m.group(1))
                job.speed = (m.group(2) or "").strip()
                job.eta = (m.group(3) or "").strip()
                continue
            m = _ITEM.search(line)
            if m:
                job.total = int(m.group(2))
                continue
            if line.startswith("ERROR"):
                job.failed += 1
                job.last_error = line.strip()[:300]
        proc.wait()
        job._proc = None
        return proc.returncode

    def _run_url(self, job, url, quality, audio_only, dest, playlist, subtitles):
        out_dir = self._dest_path(dest)
        cmd = ["yt-dlp", "--newline", "--no-warnings", "--ignore-config",
               "--no-overwrites", "-P", out_dir]
        if audio_only:
            cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0",
                    "-o", "%(title)s.%(ext)s"]
        else:
            cmd += ["-f", quality_format(quality)]
            if playlist:
                # fehlende/nicht verfuegbare Videos ueberspringen statt abbrechen
                cmd += ["--ignore-errors",
                        "-o", "%(playlist_title|)s/%(title)s.%(ext)s"]
            else:
                cmd += ["--no-playlist", "-o", "%(title)s.%(ext)s"]
        if subtitles:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "de",
                    "--embed-subs", "--convert-subs", "srt"]
        cmd.append(url)
        rc = self._run_proc(job, cmd)
        if job._cancel:
            job.status = "canceled"
            job.message = "Abgebrochen."
        elif playlist:
            # Playlist gilt als erfolgreich, solange nicht ALLE Videos fehlschlugen.
            got = (job.total - job.failed) if job.total else None
            if job.failed and got == 0:
                job.status = "error"
                job.message = job.last_error or "Alle Videos fehlgeschlagen."
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
            job.message = job.last_error or f"yt-dlp Fehler (Code {rc})."

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
        out_template = os.path.join(out_dir, base + ".%(ext)s")
        # bereits vorhanden?
        existing = [f for f in os.listdir(out_dir) if f.startswith(base + ".")]
        if existing:
            job.status = "skipped"
            job.message = "Datei existiert bereits - uebersprungen."
            job.filename = existing[0]
            return

        cmd = ["yt-dlp", "--newline", "--no-warnings", "--ignore-config",
               "--no-overwrites", "-f", quality_format(quality),
               "--add-header", f"User-Agent: {WAIPU_USER_AGENT}",
               "-o", out_template, stream_url]
        rc = self._run_proc(job, cmd)
        if job._cancel:
            job.status = "canceled"
            job.message = "Abgebrochen."
        elif rc == 0:
            job.status = "done"
            job.percent = 100.0
            job.message = "Fertig."
        else:
            job.status = "error"
            job.message = job.last_error or f"yt-dlp Fehler (Code {rc})."
