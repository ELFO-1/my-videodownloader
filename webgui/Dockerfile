FROM python:3.12-slim

# ffmpeg fuer Merge (Video+Audio) und MP3-Extraktion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno als JavaScript-Laufzeit. YouTube verlangt inzwischen das Loesen einer
# JS-Challenge ("n challenge"); ohne Laufzeit liefert yt-dlp nur einen
# Rumpf-Formatsatz, dessen URLs mit HTTP 403 abgewiesen werden.
RUN curl -fsSL -o /tmp/deno.zip \
      https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod 755 /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && deno --version

# yt-dlp in ein eigenes venv, das dem Laufzeit-User (1000) gehoert. Nur so
# kann die GUI yt-dlp spaeter selbst aktualisieren, ohne Neubau des Images.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir yt-dlp requests \
    && chown -R 1000:1000 /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    YTDLP_UPDATE_CMD="/opt/venv/bin/python -m pip install --no-cache-dir --upgrade yt-dlp" \
    DENO_DIR=/data/deno

WORKDIR /app
EXPOSE 8088

# Der App-Code wird per Volume nach /app gemountet (siehe compose).
CMD ["python3", "/app/server.py", "8088"]
