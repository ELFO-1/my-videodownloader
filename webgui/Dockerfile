FROM python:3.12-slim

# ffmpeg fuer Merge (Video+Audio) und MP3-Extraktion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp in ein eigenes venv, das dem Laufzeit-User (1000) gehoert. Nur so
# kann die GUI yt-dlp spaeter selbst aktualisieren, ohne Neubau des Images.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir yt-dlp requests \
    && chown -R 1000:1000 /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    YTDLP_UPDATE_CMD="/opt/venv/bin/python -m pip install --no-cache-dir --upgrade yt-dlp"

WORKDIR /app
EXPOSE 8088

# Der App-Code wird per Volume nach /app gemountet (siehe compose).
CMD ["python3", "/app/server.py", "8088"]
