#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author :  ELFO

import os
import subprocess
import glob
import configparser
import sys
from pathlib import Path


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

    return config, config_file


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
        )
        print(f"Erfolgreich konvertiert zu: {output_file}")
        return output_file
    except subprocess.CalledProcessError:
        print("Fehler bei der Konvertierung.")
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
        )
        print(f"Erfolgreich konvertiert zu: {output_file}")
        return output_file
    except subprocess.CalledProcessError:
        print("Fehler bei der Konvertierung.")
        return None


def convert_audio(video_file, format_type):
    """Konvertiert Video in das gewählte Audioformat"""
    if format_type == "mp3":
        return convert_to_mp3(video_file)
    else:  # wav für Audio-CD
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

            # Prüfe ob die Datei bereits existiert
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


def main():
    print("\n=== Videodownloader and converter by Elfo ===")

    # Cookies-Setup
    print("\n=== Für YouTube mit Cookies-Unterstützung ===")
    cookies_file = setup_cookies()

    # Download-Pfad Setup
    download_path = setup_download_path()
    os.chdir(download_path)

    while True:
        url = input("\nVideo-URL eingeben (oder 'q' zum Beenden): ")

        if url.lower() == "q":
            break

        # Download-Kommando vorbereiten
        download_cmd = ["yt-dlp", "-f", "b"]
        if cookies_file:
            download_cmd.extend(["--cookies", cookies_file])
        download_cmd.append(url)

        try:
            subprocess.run(download_cmd, check=True)
            print("Video erfolgreich heruntergeladen.")

            video_files = glob.glob("*.mp4") + glob.glob("*.webm") + glob.glob("*.mkv")
            if video_files:
                latest_video = max(video_files, key=os.path.getctime)
                print(f"Gefundenes Video: {latest_video}")

                # Neue Abfrage zum Umbenennen
                rename_choice = input("\nMöchtest du die Datei umbenennen? (j/n): ")
                if rename_choice.lower() == "j":
                    latest_video = rename_video(latest_video)

                print("\nWas möchtest du tun?")
                print("1: In MP3 konvertieren")
                print("2: In Audio-CD Format (WAV) konvertieren")
                print("3: Nicht konvertieren und neues Video herunterladen")
                print("4: Nicht konvertieren und beenden")

                choice = input("Wähle 1-4: ")

                if choice == "1":
                    audio_file = convert_audio(latest_video, "mp3")
                elif choice == "2":
                    audio_file = convert_audio(latest_video, "wav")
                elif choice == "3":
                    continue
                elif choice == "4":
                    break
                else:
                    print("Ungültige Auswahl.")
                    continue

                if audio_file and choice in ["1", "2"]:
                    print("\nKonvertierung abgeschlossen!")
                    print(f"Die Audiodatei wurde erstellt: {audio_file}")

                    # Optional: Auch die Audiodatei umbenennen
                    rename_audio = input(
                        "\nMöchtest du die Audiodatei umbenennen? (j/n): "
                    )
                    if rename_audio.lower() == "j":
                        audio_file = rename_video(audio_file)

                    if choice == "2":
                        print(
                            "Du kannst diese Datei nun mit deinem bevorzugten CD-Brennprogramm brennen."
                        )

            else:
                print("Keine Video-Datei gefunden.")

        except subprocess.CalledProcessError:
            print("Fehler beim Herunterladen des Videos.")

        if choice != "3":
            another = input("\nMöchtest du ein weiteres Video herunterladen? (j/n): ")
            if another.lower() != "j":
                break


if __name__ == "__main__":
    main()
