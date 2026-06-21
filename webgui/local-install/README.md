# Lokale Installation (ohne Server / ohne Docker)

Installiert die Web-GUI als dauerhaften Dienst auf dem eigenen Rechner.

```bash
cd webgui/local-install
./install.sh
```

Das richtet ein:

- **systemd-User-Service** `videodownloader.service` – startet automatisch beim
  Login, lauscht auf `http://localhost:8088`, Neustart bei Absturz
- **Befehl** `videodownloader` – stellt den Dienst sicher und öffnet die GUI im
  Browser
- **Klick-Starter** „Video Downloader" im App-Menü (XDG/KDE)

Downloads landen in `~/Downloads/videos` bzw. `~/Downloads/musik`, waipu-Tokens
in `~/.config/videodownloader/`.

Anderer Port: `PORT=9000 ./install.sh`

## Verwalten

```bash
systemctl --user restart videodownloader    # neu starten
systemctl --user stop videodownloader        # anhalten
systemctl --user disable videodownloader     # Autostart aus
```

## Deinstallieren

```bash
./uninstall.sh
```

> Voraussetzungen: `python3`, `yt-dlp`, `ffmpeg`, `python-requests`.
> Schnell ohne Installation testen: stattdessen `../run-local.sh` ausführen.
