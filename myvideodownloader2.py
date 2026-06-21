#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author :  ELFO

import os
import subprocess
import shutil
import glob
import configparser
import sys
import re
import json
import time
import base64
import uuid
from pathlib import Path
from tqdm import tqdm

try:
    import requests
except ImportError:
    requests = None


def load_config():
    """Lädt die Konfiguration oder erstellt eine neue"""
    config = configparser.ConfigParser()
    config_file = Path.home() / ".config" / "ytdownloader" / "config.ini"

    config_file.parent.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        config.read(config_file)
    else:
        config["DEFAULT"] = {
            "cookies_file": "",
            "download_path": str(Path.home() / "Downloads" / "YTDownloader"),
        }
        with open(config_file, "w") as f:
            config.write(f)

    # waipu.tv-Abschnitt sicherstellen (auch bei bestehender Config)
    dirty = False
    if not config.has_section("waipu"):
        config.add_section("waipu")
        dirty = True
    if not config["waipu"].get("device_id"):
        config["waipu"]["device_id"] = str(uuid.uuid4())
        dirty = True

    # Optionen-Abschnitt (Qualitaet, Untertitel, Serien-Ordner) sicherstellen
    if not config.has_section("options"):
        config.add_section("options")
        dirty = True
    option_defaults = {
        "video_quality": "best",
        "download_subtitles": "false",
        "embed_subtitles": "false",
        "subtitle_langs": "de",
        "organize_series": "false",
    }
    for key, value in option_defaults.items():
        if key not in config["options"]:
            config["options"][key] = value
            dirty = True

    if dirty:
        with open(config_file, "w") as f:
            config.write(f)

    return config, config_file


def _quality_format(quality):
    """Uebersetzt eine Qualitaets-Einstellung in einen yt-dlp Format-String."""
    q = (quality or "best").strip().lower()
    if q.isdigit():
        return f"bv*[height<={q}]+ba/b[height<={q}]/b"
    return "bv*+ba/b"  # 'best'


def _ytdlp_quality_args(config):
    return ["-f", _quality_format(config["options"].get("video_quality", "best"))]


def _ytdlp_subtitle_args(config):
    """Liefert yt-dlp Untertitel-Argumente gemaess Konfiguration."""
    opts = config["options"]
    want = opts.get("download_subtitles", "false") == "true"
    embed = opts.get("embed_subtitles", "false") == "true"
    if not (want or embed):
        return []
    langs = opts.get("subtitle_langs", "de") or "de"
    args = ["--write-subs", "--write-auto-subs", "--sub-langs", langs]
    if embed:
        args.append("--embed-subs")
    return args


def _format_duration(seconds):
    """Formatiert Sekunden als '1h 23m' / '45m' / '' (unbekannt)."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _recording_channel(rec):
    """Versucht den Sendernamen aus verschiedenen moeglichen Feldern zu lesen."""
    for key in ("channelName", "channelDisplay", "stationDisplay", "channel", "station"):
        value = rec.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def setup_cookies():
    """Konfiguriert den Pfad zur Cookies-Datei"""
    config, config_file = load_config()

    current_cookies = config["DEFAULT"].get("cookies_file", "")
    print(f"\nAktuelle Cookies-Datei: {current_cookies or 'Nicht konfiguriert'}")

    change = input("Möchtest du den Pfad zur Cookies-Datei ändern? (j/n): ")
    if change.lower() == "j":
        new_path = input("Gib den vollständigen Pfad zur cookies.txt ein: ")
        if os.path.exists(new_path):
            config["DEFAULT"]["cookies_file"] = new_path
            with open(config_file, "w") as f:
                config.write(f)
            print("Cookies-Pfad erfolgreich aktualisiert!")
        else:
            print("Fehler: Die angegebene Datei existiert nicht!")

    return config["DEFAULT"].get("cookies_file", "")


def setup_download_path():
    """Konfiguriert den Download-Pfad"""
    config, config_file = load_config()
    current_path = config["DEFAULT"].get("download_path", "")

    print(f"\nAktueller Download-Pfad: {current_path or 'Standard'}")
    change = input("Möchtest du den Download-Pfad ändern? (j/n): ")

    if change.lower() == "j":
        new_path = input("Gib den gewünschten Download-Pfad ein: ")
        path = Path(new_path).expanduser()
        path.mkdir(parents=True, exist_ok=True)

        config["DEFAULT"]["download_path"] = str(path)
        with open(config_file, "w") as f:
            config.write(f)
        print(f"Download-Pfad erfolgreich auf {path} gesetzt!")

    return Path(config["DEFAULT"]["download_path"])


def convert_to_wav(video_file):
    """Konvertiert Video in WAV-Format für Audio-CD"""
    try:
        output_file = os.path.splitext(video_file)[0] + ".wav"
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_file,
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                output_file,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Erfolgreich konvertiert zu: {output_file}")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Fehler bei der Konvertierung: {e.stderr}")
        return None


def convert_to_mp3(video_file):
    """Konvertiert Video in MP3-Format"""
    try:
        output_file = os.path.splitext(video_file)[0] + ".mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_file,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ab",
                "320k",
                "-ar",
                "44100",
                "-ac",
                "2",
                output_file,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Erfolgreich konvertiert zu: {output_file}")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Fehler bei der Konvertierung: {e.stderr}")
        return None


def convert_audio(video_file, format_type):
    """Konvertiert Video in das gewählte Audioformat"""
    if format_type == "mp3":
        return convert_to_mp3(video_file)
    else:
        return convert_to_wav(video_file)


def rename_video(video_path):
    """Funktion zum Umbenennen der Videodatei"""
    try:
        directory = os.path.dirname(video_path)
        old_filename = os.path.basename(video_path)
        extension = os.path.splitext(old_filename)[1]

        print(f"\nAktueller Dateiname: {old_filename}")
        new_name = input(
            "Gib den neuen Namen ein (ohne Dateiendung) oder drücke Enter zum Überspringen: "
        ).strip()

        if new_name:
            new_filename = f"{new_name}{extension}"
            new_path = os.path.join(directory, new_filename)

            if os.path.exists(new_path):
                overwrite = input(
                    "Eine Datei mit diesem Namen existiert bereits. Überschreiben? (j/n): "
                )
                if overwrite.lower() != "j":
                    print("Umbenennen abgebrochen.")
                    return video_path

            os.rename(video_path, new_path)
            print(f"Datei erfolgreich umbenannt zu: {new_filename}")
            return new_path
        return video_path
    except Exception as e:
        print(f"Fehler beim Umbenennen: {e}")
        return video_path


def download_video(url, cookies_file, extra_args=None):
    """Lädt ein Video herunter und zeigt den Fortschritt an"""
    # --newline: Fortschritt zeilenweise (gut parsebar); --no-playlist: nur das
    # eine Video, auch wenn die URL einen &list=...-Parameter enthaelt.
    download_cmd = ["yt-dlp", "--newline", "--no-playlist", "--progress", "--no-warnings"]
    download_cmd += extra_args if extra_args else ["-f", "b"]
    download_cmd.append(url)
    if cookies_file:
        download_cmd.extend(["--cookies", cookies_file])

    print(f"Ausgeführter yt-dlp Befehl: {' '.join(download_cmd)}")

    progress_bar = None
    total_size = None
    last_downloaded = 0

    # stderr -> stdout zusammenfuehren, damit der Puffer nicht volllaeuft
    # (sonst Deadlock, wenn yt-dlp viel auf stderr schreibt, z.B. beim Mergen).
    process = subprocess.Popen(
        download_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        bufsize=1,
    )

    def _close_bar():
        nonlocal progress_bar
        if progress_bar:
            progress_bar.close()
            progress_bar = None

    # Finalen Dateinamen direkt aus der yt-dlp-Ausgabe ermitteln (statt zu raten)
    merged_path = None
    last_destination = None
    already_path = None

    while True:
        output = process.stdout.readline()
        if not output and process.poll() is not None:
            break
        if not output:
            continue

        if "[download]" in output:
            # Neuer Stream (z.B. erst Video, dann Audio) -> Balken zuruecksetzen
            if "Destination:" in output:
                last_destination = output.split("Destination:", 1)[1].strip()
                _close_bar()
                total_size = None
                last_downloaded = 0
                continue

            already = re.search(r"\[download\]\s+(.+?) has already been downloaded", output)
            if already:
                already_path = already.group(1).strip()

            size_match = re.search(r"of\s+~?\s*([\d.]+)([GMK]?i?B)", output)
            if size_match and total_size is None:
                size_val = float(size_match.group(1))
                multiplier = {
                    "GiB": 1024**3,
                    "MiB": 1024**2,
                    "KiB": 1024,
                    "GB": 1024**3,
                    "MB": 1024**2,
                    "KB": 1024,
                    "B": 1,
                }.get(size_match.group(2), 1024**2)
                total_size = int(size_val * multiplier)
                progress_bar = tqdm(
                    total=total_size, unit="B", unit_scale=True, desc="Downloading"
                )

            progress_match = re.search(r"([\d.]+)%", output)
            if progress_match and total_size and progress_bar:
                current_downloaded = int(total_size * (float(progress_match.group(1)) / 100))
                if current_downloaded > last_downloaded:
                    progress_bar.update(current_downloaded - last_downloaded)
                    last_downloaded = current_downloaded
        elif "[Merger]" in output or "[ExtractAudio]" in output:
            _close_bar()
            print(output.strip())
            merge_match = re.search(r'into "(.+)"', output)
            if merge_match:
                merged_path = merge_match.group(1).strip()

    _close_bar()

    # Beim Merge ist der gemergte Pfad der finale; sonst die (einzelne)
    # Destination bzw. eine bereits vorhandene Datei.
    final_path = merged_path or last_destination or already_path
    return process.poll() == 0, final_path


# ---------------------------------------------------------------------------
# waipu.tv Integration
#
# Nutzt die inoffizielle (reverse-engineerte) waipu.tv-API, wie sie auch das
# Kodi-Plugin flubshi/pvr.waipu verwendet. Funktioniert nur fuer EIGENE
# Aufnahmen aus deinem bezahlten Account.
#
# WICHTIG: Viele Aufnahmen (v.a. Privatsender) sind mit Widevine-DRM
# verschluesselt. Solche Streams werden ERKANNT und UEBERSPRUNGEN - es wird
# kein Kopierschutz umgangen. Nur DRM-freie Aufnahmen werden heruntergeladen.
# ---------------------------------------------------------------------------

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


class WaipuClient:
    """Schlanker Client fuer Login und Aufnahmen-Abruf bei waipu.tv."""

    def __init__(self, username, password, device_id, config=None, config_file=None):
        if requests is None:
            raise WaipuError(
                "Das Python-Paket 'requests' fehlt. Installiere es mit: pip install requests"
            )
        self.username = username
        self.password = password
        self.device_id = device_id or str(uuid.uuid4())
        self._config = config
        self._config_file = config_file
        self._access_token = ""
        self._refresh_token = ""
        if config is not None and config.has_section("waipu"):
            self._access_token = config["waipu"].get("access_token", "")
            self._refresh_token = config["waipu"].get("refresh_token", "")

    # --- Token-Handling -----------------------------------------------------

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

    def _persist_tokens(self):
        if self._config is None or self._config_file is None:
            return
        if not self._config.has_section("waipu"):
            self._config.add_section("waipu")
        self._config["waipu"]["access_token"] = self._access_token
        self._config["waipu"]["refresh_token"] = self._refresh_token
        with open(self._config_file, "w") as f:
            self._config.write(f)

    def _fetch_token(self):
        if self._jwt_valid(self._refresh_token):
            payload = {
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
                "waipu_device_id": self.device_id,
            }
        else:
            if not self.username or not self.password:
                raise WaipuError(
                    "Nicht angemeldet. Bitte zuerst ueber Menuepunkt 7 einloggen "
                    "(Browser-Login empfohlen, funktioniert auch mit Amazon-Konto)."
                )
            payload = {
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
                "waipu_device_id": self.device_id,
            }

        headers = {
            "User-Agent": WAIPU_USER_AGENT,
            "Authorization": WAIPU_BASIC_AUTH,
        }
        try:
            r = requests.post(
                WAIPU_TOKEN_URL, data=payload, headers=headers, timeout=30
            )
        except requests.exceptions.RequestException as e:
            raise WaipuError(f"Verbindungsfehler beim Login: {e}")

        if r.status_code != 200:
            raise WaipuError(
                f"Login fehlgeschlagen (HTTP {r.status_code}). "
                "Bei einem ueber Amazon verwalteten Konto nutze den Browser-Login "
                "(Menuepunkt 7)."
            )
        data = r.json()
        self._access_token = data.get("access_token", "")
        if data.get("refresh_token"):
            self._refresh_token = data["refresh_token"]
        if not self._access_token:
            raise WaipuError("Kein gueltiges Access-Token erhalten.")
        self._persist_tokens()
        return self._access_token

    def device_login(self, tenant="waipu"):
        """Browser-basierter Geraete-Login (OAuth Device Flow).

        Funktioniert auch fuer ueber Amazon verwaltete Konten, da die
        Anmeldung im Browser erfolgt (dort steht der Amazon-Button bereit).
        """
        headers = {
            "Authorization": WAIPU_BASIC_AUTH,
            "Content-Type": "application/json",
            "User-Agent": WAIPU_USER_AGENT,
        }
        body = json.dumps({"client_id": tenant, "waipu_device_id": self.device_id})
        try:
            r = requests.post(
                WAIPU_DEVICE_AUTH_URL, data=body, headers=headers, timeout=30
            )
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

        print("\n=== waipu.tv Browser-Login ===")
        print(f"1. Oeffne im Browser:   {verification}")
        print(f"2. Gib diesen Code ein: {user_code}")
        print(f"   (oder direkt diesen Link: {verification_full})")
        print("   Dort kannst du dich auch ueber den Amazon-Button anmelden.")
        print(f"\nWarte auf Bestaetigung (max. {expires_in // 60} Min., Strg+C zum Abbrechen)...")

        poll_headers = {
            "Authorization": WAIPU_BASIC_AUTH,
            "User-Agent": WAIPU_USER_AGENT,
        }
        payload = {
            "device_code": device_code,
            "grant_type": WAIPU_DEVICE_GRANT,
            "waipu_device_id": self.device_id,
        }
        deadline = time.time() + expires_in
        while time.time() < deadline:
            time.sleep(interval)
            try:
                rr = requests.post(
                    WAIPU_TOKEN_URL, data=payload, headers=poll_headers, timeout=30
                )
            except requests.exceptions.RequestException:
                continue

            if rr.status_code == 200:
                jwt = rr.json()
                if jwt.get("access_token"):
                    self._access_token = jwt["access_token"]
                    if jwt.get("refresh_token"):
                        self._refresh_token = jwt["refresh_token"]
                    self._persist_tokens()
                    print("Login erfolgreich!")
                    return self._access_token

            # waipu/OAuth-Fehlerbehandlung waehrend des Pollings
            try:
                err = rr.json().get("error", "")
            except Exception:
                err = ""
            if err == "slow_down":
                interval += 5
            elif err in ("access_denied", "expired_token"):
                raise WaipuError(f"Login abgebrochen/abgelaufen ({err}).")
            # sonst: authorization_pending -> weiter warten

        raise WaipuError("Login-Zeitfenster abgelaufen. Bitte erneut versuchen.")

    def _token(self):
        if not self._jwt_valid(self._access_token):
            return self._fetch_token()
        return self._access_token

    def _headers(self, extra=None):
        headers = {
            "User-Agent": WAIPU_USER_AGENT,
            "Authorization": "Bearer " + self._token(),
        }
        if extra:
            headers.update(extra)
        return headers

    # --- API-Aufrufe --------------------------------------------------------

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
            # v4: Eintrag ist entweder eine Gruppe (Serie) oder eine Einzelaufnahme
            if isinstance(entry.get("recordingGroup"), int):
                group_ids.add(entry["recordingGroup"])
            elif entry.get("status") in ("FINISHED", "RECORDING") and not entry.get("locked"):
                recordings.append(entry)

        # Gruppen (Serien) aufloesen
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
            "https://recording.waipu.tv/api/recordings/"
            + str(recording_id)
            + "/streamingdetails",
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code != 200:
            raise WaipuError(f"Stream-Daten nicht abrufbar (HTTP {r.status_code}).")
        return r.json()

    def fetch_manifest(self, url):
        r = requests.get(
            url, headers={"User-Agent": WAIPU_USER_AGENT}, timeout=30
        )
        r.raise_for_status()
        return r.text


def _is_drm_protected(manifest_text):
    """Erkennt Widevine-/CENC-DRM im DASH-Manifest."""
    text = manifest_text.lower()
    return (
        WIDEVINE_UUID in text
        or "contentprotection" in text
        or "cenc:default_kid" in text
        or "urn:mpeg:dash:mp4protection" in text
    )


def _safe_filename(name):
    """Macht einen String dateinamen-tauglich."""
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    return name or "waipu_aufnahme"


def _waipu_device_login(config, config_file):
    """Fuehrt den Browser-Login durch und speichert die Tokens."""
    device_id = config["waipu"].get("device_id", "")
    try:
        client = WaipuClient("", "", device_id, config, config_file)
        client.device_login()
    except WaipuError as e:
        print(f"Fehler: {e}")
        return
    # bei Token-Login etwaiges altes Passwort entfernen (nicht mehr noetig)
    config["waipu"]["username"] = ""
    config["waipu"]["password"] = ""
    with open(config_file, "w") as f:
        config.write(f)


def _waipu_password_login(config, config_file):
    """Speichert E-Mail + Passwort fuer den klassischen Login."""
    username = input("waipu.tv E-Mail/Benutzername: ").strip()
    password = input("waipu.tv Passwort: ").strip()
    if not username or not password:
        print("Abgebrochen: Benutzername und Passwort duerfen nicht leer sein.")
        return
    config["waipu"]["username"] = username
    config["waipu"]["password"] = password
    config["waipu"]["access_token"] = ""
    config["waipu"]["refresh_token"] = ""
    with open(config_file, "w") as f:
        config.write(f)
    print("waipu.tv-Zugangsdaten gespeichert.")
    print(
        "Hinweis: Das Passwort wird im Klartext in der config.ini gespeichert "
        f"({config_file})."
    )


def setup_waipu_credentials():
    """Login bei waipu.tv einrichten (Browser- oder Passwort-Login)."""
    if requests is None:
        print(
            "Fehler: Das Python-Paket 'requests' wird benoetigt. "
            "Installiere es mit: pip install requests"
        )
        return

    config, config_file = load_config()
    print("\n=== waipu.tv Login ===")
    print("1. Browser-Login (empfohlen, funktioniert auch mit Amazon-Konto)")
    print("2. E-Mail + Passwort (nur direkte waipu-Konten)")
    method = input("Methode waehlen (1/2, Enter = abbrechen): ").strip()

    if method == "1":
        _waipu_device_login(config, config_file)
    elif method == "2":
        _waipu_password_login(config, config_file)
    else:
        print("Abgebrochen.")


def _waipu_is_logged_in(config):
    """Prueft, ob ein nutzbares Token oder Zugangsdaten vorliegen."""
    waipu = config["waipu"]
    if waipu.get("refresh_token") or waipu.get("access_token"):
        return True
    return bool(waipu.get("username") and waipu.get("password"))


def download_waipu_recording():
    """Listet waipu.tv-Aufnahmen auf und laedt eine DRM-freie herunter."""
    if requests is None:
        print(
            "Fehler: Das Python-Paket 'requests' wird benoetigt. "
            "Installiere es mit: pip install requests"
        )
        return

    config, config_file = load_config()

    if not _waipu_is_logged_in(config):
        print("\nNoch nicht bei waipu.tv angemeldet.")
        setup_waipu_credentials()
        config, config_file = load_config()
        if not _waipu_is_logged_in(config):
            return

    username = config["waipu"].get("username", "")
    password = config["waipu"].get("password", "")
    device_id = config["waipu"].get("device_id", "")

    try:
        client = WaipuClient(username, password, device_id, config, config_file)
        print("\nMelde bei waipu.tv an und lade Aufnahmen...")
        recordings = client.get_recordings()
    except WaipuError as e:
        print(f"Fehler: {e}")
        return

    if not recordings:
        print("Keine (fertigen) Aufnahmen gefunden.")
        return

    # Optionaler Suchfilter nach Titel/Episode
    print(f"\n{len(recordings)} Aufnahme(n) gefunden.")
    term = input("Suchbegriff (Enter = alle anzeigen): ").strip().lower()
    if term:
        recordings = [
            rec
            for rec in recordings
            if term in (rec.get("title") or "").lower()
            or term in (rec.get("episodeTitle") or "").lower()
        ]
        if not recordings:
            print(f"Keine Aufnahme passt zu '{term}'.")
            return

    print(f"\n=== Deine waipu.tv-Aufnahmen ({len(recordings)}) ===")
    for idx, rec in enumerate(recordings, start=1):
        title = rec.get("title") or "Ohne Titel"
        episode = rec.get("episodeTitle") or ""
        start = (rec.get("recordingStartTime") or rec.get("startTime") or "")[:16].replace("T", " ")
        status = rec.get("status", "")
        label = title + (f" - {episode}" if episode else "")
        # Sender + Dauer als Zusatzinfo, sofern vorhanden
        extras = [x for x in (_recording_channel(rec), _format_duration(rec.get("durationSeconds"))) if x]
        suffix = ("  " + " | ".join(extras)) if extras else ""
        print(f"{idx:>3}. {label}  [{start}]{suffix}  ({status})")

    print("\nAuswahl: einzelne Nummer (z.B. 3), mehrere (z.B. 1,3,5) oder 'alle'.")
    choice = input("Welche Aufnahme(n)? (Enter zum Abbrechen): ").strip().lower()
    if not choice:
        print("Abgebrochen.")
        return

    selected = _parse_selection(choice, len(recordings))
    if not selected:
        print("Ungueltige Auswahl.")
        return

    results = {"ok": 0, "drm": 0, "skip": 0, "error": 0}
    for pos in selected:
        rec = recordings[pos - 1]
        status, msg = _download_one_recording(client, rec, config)
        results[status] = results.get(status, 0) + 1
        print(f"  -> {msg}")

    if len(selected) > 1:
        print(
            f"\nFertig: {results['ok']} geladen, {results['drm']} DRM-geschuetzt, "
            f"{results['skip']} uebersprungen, {results['error']} Fehler."
        )


def _parse_selection(choice, count):
    """Parst 'alle' / '1,3,5' / '3' zu einer Liste gueltiger 1-basierter Indizes."""
    if choice in ("alle", "all", "*"):
        return list(range(1, count + 1))
    selected = []
    for part in choice.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= count and int(part) not in selected:
            selected.append(int(part))
    return selected


def _download_one_recording(client, rec, config=None):
    """Laedt eine einzelne Aufnahme. Gibt (status, meldung) zurueck.

    status ist eines von: 'ok', 'drm', 'skip', 'error'.
    """
    base_title = rec.get("title") or "waipu_aufnahme"
    episode = rec.get("episodeTitle") or ""
    label = base_title + (f" - {episode}" if episode else "")

    rec_id = rec.get("id") or rec.get("recordingId")
    try:
        streaming_data = client.get_recording_streams(rec_id)
    except WaipuError as e:
        return "error", f"{label}: Fehler beim Stream-Abruf ({e})"

    # v4: streams liegen top-level. DASH bevorzugen, sonst erste vorhandene href.
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
        return "error", f"{label}: Keine Stream-URL gefunden"

    # DRM-Pruefung anhand des Manifests
    try:
        manifest = client.fetch_manifest(stream_url)
    except Exception as e:
        manifest = ""
        print(f"  Warnung: Manifest fuer '{label}' nicht ladbar ({e}).")

    if manifest and _is_drm_protected(manifest):
        return "drm", f"{label}: DRM-geschuetzt (Widevine) - uebersprungen"

    # Ausgabename: optional mit Datum, Serien optional in Unterordner
    opts = config["options"] if config and config.has_section("options") else {}
    is_series = bool(rec.get("episodeTitle") or rec.get("episode") or rec.get("season"))
    date_str = (rec.get("recordingStartTime") or rec.get("startTime") or "")[:10]

    file_base = _safe_filename(label)
    if date_str:
        file_base = f"{file_base} ({date_str})"

    out_path = file_base
    if opts.get("organize_series", "false") == "true" and is_series:
        out_path = os.path.join(_safe_filename(base_title), file_base)

    # Schutz vor Doppel-Download (auch im Serien-Unterordner)
    if glob.glob(out_path + ".*"):
        return "skip", f"{label}: Datei existiert bereits - uebersprungen"

    print(f"\nLade DRM-freie Aufnahme herunter: {out_path}")
    download_cmd = ["yt-dlp", "--no-warnings", "--no-overwrites"]
    if config:
        download_cmd += _ytdlp_quality_args(config) + _ytdlp_subtitle_args(config)
    download_cmd += [
        "--add-header",
        f"User-Agent: {WAIPU_USER_AGENT}",
        "-o",
        out_path + ".%(ext)s",
        stream_url,
    ]
    try:
        subprocess.run(download_cmd, check=True)
        return "ok", f"{label}: erfolgreich heruntergeladen"
    except subprocess.CalledProcessError as e:
        return "error", f"{label}: Download fehlgeschlagen ({e})"


def setup_options():
    """Einstellungen: Qualitaet, Untertitel, Serien-Ordner."""
    config, config_file = load_config()
    opts = config["options"]

    def _onoff(key):
        return "an" if opts.get(key, "false") == "true" else "aus"

    while True:
        print("\n=== Einstellungen ===")
        print(f"1. Video-Qualitaet:        {opts.get('video_quality', 'best')}")
        print(f"2. Untertitel laden:       {_onoff('download_subtitles')}")
        print(f"3. Untertitel einbetten:   {_onoff('embed_subtitles')}")
        print(f"4. Untertitel-Sprachen:    {opts.get('subtitle_langs', 'de')}")
        print(f"5. Serien in Unterordner:  {_onoff('organize_series')}")
        print("6. Zurueck")
        sel = input("Auswahl (1-6): ").strip()

        if sel == "1":
            print("Qualitaet: 'best', oder max. Hoehe wie 1080 / 720 / 480")
            val = input("Neue Qualitaet: ").strip().lower()
            if val:
                opts["video_quality"] = val
        elif sel == "2":
            opts["download_subtitles"] = (
                "false" if opts.get("download_subtitles") == "true" else "true"
            )
        elif sel == "3":
            opts["embed_subtitles"] = (
                "false" if opts.get("embed_subtitles") == "true" else "true"
            )
        elif sel == "4":
            val = input("Sprachen (z.B. de,en oder 'all'): ").strip()
            if val:
                opts["subtitle_langs"] = val
        elif sel == "5":
            opts["organize_series"] = (
                "false" if opts.get("organize_series") == "true" else "true"
            )
        elif sel == "6":
            break
        else:
            print("Ungueltige Auswahl.")
            continue

        with open(config_file, "w") as f:
            config.write(f)
        print("Gespeichert.")


def display_banner():
    """Zeigt ein Startbanner an"""
    print("=" * 50)
    print("        Willkommen zum Video-Downloader")
    print("        by ELFO")
    print("=" * 50)
    print()


def display_menu(current_cookie_path, current_download_path):
    """Zeigt das Hauptmenü an"""
    print("\n=== Menü ===")
    print("1. Video herunterladen")
    print("2. Playlist herunterladen")
    print(
        f"3. Cookie Pfad ändern (aktueller Pfad: {current_cookie_path or 'Nicht konfiguriert'})"
    )
    print(
        f"4. Downloadpfad ändern (aktueller Pfad: {current_download_path or 'Standard'})"
    )
    print("5. Video umwandeln (Mp3 oder Wav)")
    print("6. waipu.tv Aufnahme herunterladen")
    print("7. waipu.tv Login (Browser/Amazon oder Passwort)")
    print("8. Einstellungen (Qualität/Untertitel/Serien-Ordner)")
    print("9. Beenden")
    print("=" * 20)


def main():
    display_banner()
    config, _ = load_config()
    cookies_file = config["DEFAULT"].get("cookies_file", "")
    download_path = Path(config["DEFAULT"].get("download_path", "")).expanduser()
    download_path.mkdir(parents=True, exist_ok=True)
    os.chdir(download_path)
    latest_video = None

    if not shutil.which("yt-dlp"):
        print(
            "\nFehler: yt-dlp ist nicht installiert. Bitte installiere yt-dlp und stelle sicher, dass es im Pfad verfügbar ist."
        )
        return

    while True:
        display_menu(cookies_file, str(download_path))
        choice = input("Wähle eine Option (1-9): ")

        if choice == "1":
            url = input("\nVideo-URL eingeben: ")
            if not url:
                print("Ungültige Eingabe. Bitte eine Video-URL eingeben.")
                continue

            config, _ = load_config()
            extra = _ytdlp_quality_args(config) + _ytdlp_subtitle_args(config)
            ok, final_path = download_video(url, cookies_file, extra)
            if ok:
                print("Video erfolgreich heruntergeladen.")
                if final_path and os.path.exists(final_path):
                    latest_video = final_path
                else:
                    # Fallback: neueste Videodatei im Ordner
                    video_files = (
                        glob.glob("*.mp4") + glob.glob("*.webm") + glob.glob("*.mkv")
                    )
                    latest_video = (
                        max(video_files, key=os.path.getctime) if video_files else None
                    )

                if latest_video:
                    print(f"Gefundenes Video: {latest_video}")
                    if (
                        input("\nMöchtest du die Datei umbenennen? (j/n): ").lower()
                        == "j"
                    ):
                        latest_video = rename_video(latest_video)
                else:
                    print("Keine Video-Datei gefunden.")
            else:
                print("Fehler beim Herunterladen des Videos.")

        elif choice == "2":
            playlist_url = input("\nPlaylist-URL eingeben: ")
            if not playlist_url:
                print("Ungültige Eingabe. Bitte eine Playlist-URL eingeben.")
                continue

            config, _ = load_config()
            download_cmd = ["yt-dlp", "-v", "--progress", "--no-warnings"]
            download_cmd += _ytdlp_quality_args(config) + _ytdlp_subtitle_args(config)
            download_cmd.append(playlist_url)
            if cookies_file:
                download_cmd.extend(["--cookies", cookies_file])

            try:
                subprocess.run(download_cmd, check=True)
                print("Playlist erfolgreich heruntergeladen.")
                latest_video = None
                print(
                    "Hinweis: Video-Umwandlungsoption (5) ist nach Playlist-Downloads nicht direkt verfügbar."
                )
            except subprocess.CalledProcessError as e:
                print(f"Fehler beim Herunterladen der Playlist: {e}")

        elif choice == "3":
            cookies_file = setup_cookies()
            config, _ = load_config()
            cookies_file = config["DEFAULT"].get("cookies_file", "")

        elif choice == "4":
            download_path = setup_download_path()
            config, _ = load_config()
            download_path = Path(config["DEFAULT"].get("download_path", ""))
            os.chdir(download_path)

        elif choice == "5":
            if latest_video:
                print("\nIn welches Format möchtest du konvertieren?")
                print("1. MP3")
                print("2. WAV (Audio-CD Format)")
                format_choice = input("Wähle 1 oder 2: ")

                audio_file = None
                if format_choice == "1":
                    audio_file = convert_audio(latest_video, "mp3")
                elif format_choice == "2":
                    audio_file = convert_audio(latest_video, "wav")
                else:
                    print("Ungültige Auswahl für Format.")

                if audio_file:
                    print("\nKonvertierung abgeschlossen!")
                    print(f"Die Audiodatei wurde erstellt: {audio_file}")
                    if (
                        input(
                            "\nMöchtest du die Audiodatei umbenennen? (j/n): "
                        ).lower()
                        == "j"
                    ):
                        audio_file = rename_video(audio_file)
                    if format_choice == "2":
                        print(
                            "Du kannst diese Datei nun mit deinem bevorzugten CD-Brennprogramm brennen."
                        )
            else:
                print(
                    "Kein Video zum Konvertieren vorhanden. Lade zuerst ein Video herunter."
                )

        elif choice == "6":
            download_waipu_recording()
            os.chdir(download_path)

        elif choice == "7":
            setup_waipu_credentials()

        elif choice == "8":
            setup_options()

        elif choice == "9":
            print("Programm wird beendet...")
            break

        else:
            print("Ungültige Option. Bitte wähle eine Zahl von 1 bis 9.")


if __name__ == "__main__":
    main()
