#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""waipu.tv-Anbindung fuer die Web-GUI.

Wiederverwendung der reverse-engineerten waipu.tv-API aus dem urspruenglichen
Terminal-Downloader (Author: ELFO). Funktioniert nur fuer EIGENE Aufnahmen aus
einem bezahlten Account. DRM-geschuetzte (Widevine) Aufnahmen werden ERKANNT
und UEBERSPRUNGEN - es wird kein Kopierschutz umgangen.

Gegenueber dem CLI-Original ist der Device-Login fuer eine Web-Oberflaeche
aufgeteilt: start_device_login() liefert Code + Link, poll_device_login()
fragt einmal den Status ab. So kann das Frontend den Fortschritt anzeigen.
"""

import base64
import json
import os
import re
import threading
import time
import uuid

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


WAIPU_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) myvideodownloader/1.0"
# Oeffentlich bekannte Basic-Auth des waipu Android-Clients (androidClient:superSecret)
WAIPU_BASIC_AUTH = "Basic YW5kcm9pZENsaWVudDpzdXBlclNlY3JldA=="
WAIPU_TOKEN_URL = "https://auth.waipu.tv/oauth/token"
WAIPU_DEVICE_AUTH_URL = "https://auth.waipu.tv/oauth/device_authorization"
WAIPU_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# Widevine-Protection-System-UUID laut MPEG-CENC
WIDEVINE_UUID = "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"


class WaipuError(Exception):
    pass


# ---------------------------------------------------------------------------
# Persistenter Store (JSON) fuer device_id und Tokens
# ---------------------------------------------------------------------------

class Store:
    """Schlanker JSON-Store. Schreibzugriffe sind durch ein Lock serialisiert,
    da mehrere Worker-Threads gleichzeitig Tokens erneuern koennen."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        self._lock = threading.RLock()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self.data[key] = value
            self.save()

    def update(self, **kwargs):
        with self._lock:
            self.data.update(kwargs)
            self.save()

    def save(self):
        with self._lock:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def is_drm_protected(manifest_text):
    """Erkennt Widevine-/CENC-DRM im DASH-Manifest."""
    text = (manifest_text or "").lower()
    return (
        WIDEVINE_UUID in text
        or "contentprotection" in text
        or "cenc:default_kid" in text
        or "urn:mpeg:dash:mp4protection" in text
    )


def safe_filename(name):
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name or "").strip()
    return name or "waipu_aufnahme"


def format_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def recording_channel(rec):
    for key in ("channelName", "channelDisplay", "stationDisplay", "channel", "station"):
        value = rec.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def recording_label(rec):
    title = rec.get("title") or "Ohne Titel"
    episode = rec.get("episodeTitle") or ""
    return title + (f" - {episode}" if episode else "")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class WaipuClient:
    """waipu.tv-Client mit web-tauglichem Device-Login (OAuth Device Flow)."""

    def __init__(self, store):
        if requests is None:
            raise WaipuError(
                "Das Python-Paket 'requests' fehlt im Container."
            )
        self.store = store
        if not store.get("device_id"):
            store.set("device_id", str(uuid.uuid4()))
        self.device_id = store.get("device_id")
        # laufender Device-Login-Zustand (im Speicher)
        self._login = None  # dict: device_code, deadline, interval, state, msg, code, url
        # waipu rotiert den Refresh-Token: zwei parallele Refreshes wuerden sich
        # gegenseitig invalidieren -> Erneuerung serialisieren.
        self._token_lock = threading.Lock()

    # --- Tokens -------------------------------------------------------------

    @staticmethod
    def _decode_jwt(token):
        try:
            payload = token.split(".")[1]
            payload = payload.replace("_", "/").replace("-", "+")
            decoded = base64.b64decode(payload + "=" * (-len(payload) % 4))
            return json.loads(decoded)
        except Exception:
            return {}

    def _jwt_valid(self, token, threshold=30):
        if not token:
            return False
        data = self._decode_jwt(token)
        exp = data.get("exp")
        return bool(exp) and time.time() < (int(exp) - threshold)

    def is_logged_in(self):
        return bool(
            self._jwt_valid(self.store.get("access_token", ""))
            or self._jwt_valid(self.store.get("refresh_token", ""))
        )

    def logout(self):
        self.store.update(access_token="", refresh_token="")

    def _persist_tokens(self, access, refresh):
        upd = {"access_token": access or ""}
        if refresh:
            upd["refresh_token"] = refresh
        self.store.update(**upd)

    def _refresh_access(self):
        with self._token_lock:
            # Ein anderer Thread war evtl. schneller.
            access = self.store.get("access_token", "")
            if self._jwt_valid(access):
                return access
            return self._do_refresh()

    def _do_refresh(self):
        refresh = self.store.get("refresh_token", "")
        if not self._jwt_valid(refresh):
            raise WaipuError("Nicht angemeldet. Bitte ueber den waipu-Login einloggen.")
        payload = {
            "refresh_token": refresh,
            "grant_type": "refresh_token",
            "waipu_device_id": self.device_id,
        }
        headers = {"User-Agent": WAIPU_USER_AGENT, "Authorization": WAIPU_BASIC_AUTH}
        try:
            r = requests.post(WAIPU_TOKEN_URL, data=payload, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            raise WaipuError(f"Verbindungsfehler beim Token-Refresh: {e}")
        if r.status_code != 200:
            raise WaipuError(f"Token-Refresh fehlgeschlagen (HTTP {r.status_code}). Bitte neu einloggen.")
        data = r.json()
        access = data.get("access_token", "")
        if not access:
            raise WaipuError("Kein gueltiges Access-Token erhalten.")
        self._persist_tokens(access, data.get("refresh_token"))
        return access

    def _token(self):
        access = self.store.get("access_token", "")
        if self._jwt_valid(access):
            return access
        return self._refresh_access()

    def _headers(self, extra=None):
        headers = {
            "User-Agent": WAIPU_USER_AGENT,
            "Authorization": "Bearer " + self._token(),
        }
        if extra:
            headers.update(extra)
        return headers

    # --- Device-Login (Web) -------------------------------------------------

    def start_device_login(self, tenant="waipu"):
        """Startet den Browser-Login und liefert Code + Link fuers Frontend."""
        headers = {
            "Authorization": WAIPU_BASIC_AUTH,
            "Content-Type": "application/json",
            "User-Agent": WAIPU_USER_AGENT,
        }
        body = json.dumps({"client_id": tenant, "waipu_device_id": self.device_id})
        try:
            r = requests.post(WAIPU_DEVICE_AUTH_URL, data=body, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            raise WaipuError(f"Verbindungsfehler: {e}")
        if r.status_code != 200:
            raise WaipuError(f"Geraete-Login konnte nicht gestartet werden (HTTP {r.status_code}).")

        data = r.json()
        user_code = data.get("user_code", "")
        verification = data.get("verification_uri", "https://www.waipu.tv/anmelden")
        verification_full = data.get("verification_uri_complete") or verification
        device_code = data.get("device_code", "")
        interval = int(data.get("interval", 5)) or 5
        expires_in = int(data.get("expires_in", 600)) or 600
        if not device_code or not user_code:
            raise WaipuError("Unvollstaendige Antwort vom Geraete-Login.")

        self._login = {
            "device_code": device_code,
            "interval": interval,
            "deadline": time.time() + expires_in,
            "next_poll": time.time() + interval,
            "state": "pending",
            "message": "Warte auf Bestaetigung im Browser ...",
            "user_code": user_code,
            "verification_uri": verification,
            "verification_uri_complete": verification_full,
        }
        return {
            "user_code": user_code,
            "verification_uri": verification,
            "verification_uri_complete": verification_full,
            "expires_in": expires_in,
        }

    def poll_device_login(self):
        """Fragt einmal den Login-Status ab. Liefert state: pending/ok/error."""
        login = self._login
        if not login:
            return {"state": "idle", "message": "Kein Login aktiv."}
        if login["state"] in ("ok", "error"):
            return {"state": login["state"], "message": login["message"]}
        now = time.time()
        if now > login["deadline"]:
            login["state"] = "error"
            login["message"] = "Login-Zeitfenster abgelaufen. Bitte erneut versuchen."
            return {"state": "error", "message": login["message"]}
        if now < login["next_poll"]:
            return {"state": "pending", "message": login["message"]}

        login["next_poll"] = now + login["interval"]
        payload = {
            "device_code": login["device_code"],
            "grant_type": WAIPU_DEVICE_GRANT,
            "waipu_device_id": self.device_id,
        }
        headers = {"Authorization": WAIPU_BASIC_AUTH, "User-Agent": WAIPU_USER_AGENT}
        try:
            rr = requests.post(WAIPU_TOKEN_URL, data=payload, headers=headers, timeout=30)
        except requests.exceptions.RequestException:
            return {"state": "pending", "message": login["message"]}

        if rr.status_code == 200:
            jwt = rr.json()
            if jwt.get("access_token"):
                self._persist_tokens(jwt["access_token"], jwt.get("refresh_token"))
                login["state"] = "ok"
                login["message"] = "Login erfolgreich!"
                return {"state": "ok", "message": login["message"]}

        try:
            err = rr.json().get("error", "")
        except Exception:
            err = ""
        if err == "slow_down":
            login["interval"] += 5
        elif err in ("access_denied", "expired_token"):
            login["state"] = "error"
            login["message"] = f"Login abgebrochen/abgelaufen ({err})."
            return {"state": "error", "message": login["message"]}
        return {"state": "pending", "message": login["message"]}

    # --- API ----------------------------------------------------------------

    def get_recordings(self):
        accept = {"Accept": "application/vnd.waipu.recordings-v4+json"}
        r = requests.get(
            "https://recording.waipu.tv/api/recordings",
            headers=self._headers(accept),
            timeout=30,
        )
        if r.status_code != 200:
            raise WaipuError(f"Aufnahmen konnten nicht geladen werden (HTTP {r.status_code}).")

        recordings = []
        group_ids = set()
        for entry in r.json():
            if isinstance(entry.get("recordingGroup"), int):
                group_ids.add(entry["recordingGroup"])
            elif entry.get("status") in ("FINISHED", "RECORDING") and not entry.get("locked"):
                recordings.append(entry)

        for gid in sorted(group_ids):
            gr = requests.get(
                "https://recording.waipu.tv/api/recordings?recordingGroup=" + str(gid),
                headers=self._headers(accept),
                timeout=30,
            )
            if gr.status_code != 200:
                continue
            for entry in gr.json():
                if entry.get("status") in ("FINISHED", "RECORDING") and not entry.get("locked"):
                    recordings.append(entry)
        return recordings

    def get_recording_streams(self, recording_id):
        r = requests.get(
            "https://recording.waipu.tv/api/recordings/" + str(recording_id) + "/streamingdetails",
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code != 200:
            raise WaipuError(f"Stream-Daten nicht abrufbar (HTTP {r.status_code}).")
        return r.json()

    def fetch_manifest(self, url):
        r = requests.get(url, headers={"User-Agent": WAIPU_USER_AGENT}, timeout=30)
        r.raise_for_status()
        return r.text

    def resolve_recording(self, rec):
        """Liefert (stream_url, basisname, drm_bool) fuer eine Aufnahme.

        Wirft WaipuError, wenn keine Stream-URL gefunden wird.
        """
        rec_id = rec.get("id") or rec.get("recordingId")
        streaming_data = self.get_recording_streams(rec_id)
        streams = streaming_data.get("streams") or []
        stream_url = None
        for stream in streams:
            if stream.get("protocol") in ("MPEG_DASH", "DASH", "mpeg-dash") and stream.get("href"):
                stream_url = stream["href"]
                break
        if not stream_url:
            for stream in streams:
                if stream.get("href"):
                    stream_url = stream["href"]
                    break
        if not stream_url:
            raise WaipuError("Keine Stream-URL gefunden.")

        try:
            manifest = self.fetch_manifest(stream_url)
        except Exception:
            manifest = ""
        drm = bool(manifest and is_drm_protected(manifest))

        label = recording_label(rec)
        date_str = (rec.get("recordingStartTime") or rec.get("startTime") or "")[:10]
        base = safe_filename(label)
        if date_str:
            base = f"{base} ({date_str})"
        return stream_url, base, drm
