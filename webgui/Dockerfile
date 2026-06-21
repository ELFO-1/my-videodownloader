FROM python:3.12-slim

# ffmpeg fuer Merge (Video+Audio) und MP3-Extraktion
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp requests

WORKDIR /app
EXPOSE 8088

# Der App-Code wird per Volume nach /app gemountet (siehe compose).
CMD ["python3", "/app/server.py", "8088"]
