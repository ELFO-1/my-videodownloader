#!/usr/bin/env bash
# Deploy der Video-Downloader Web-GUI auf die docker-vm.
#   - App-Code  -> /DATA/AppData/videodownloader/app
#   - Stack     -> ~/stacks/videodownloader (Dockerfile + compose)
#   - baut Image (falls noetig) und startet den Container neu
#
# Nutzung:  ./deploy.sh
set -euo pipefail

REMOTE=docker-vm
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_DIR=/DATA/AppData/videodownloader/app
STACK_DIR=/home/smoky/stacks/videodownloader

echo ">> Lege Zielverzeichnisse an ..."
ssh "$REMOTE" "mkdir -p $APP_DIR /DATA/AppData/videodownloader/data $STACK_DIR"

echo ">> Kopiere App-Code (server.py, waipu.py, downloader.py, static/) ..."
rsync -az --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$HERE/server.py" "$HERE/waipu.py" "$HERE/downloader.py" \
  "$REMOTE:$APP_DIR/"
rsync -az --delete --exclude '__pycache__' \
  "$HERE/static/" "$REMOTE:$APP_DIR/static/"

echo ">> Kopiere Stack-Dateien (Dockerfile + compose) ..."
rsync -az "$HERE/Dockerfile" "$HERE/docker-compose.yml" "$REMOTE:$STACK_DIR/"

echo ">> Baue Image und starte Container ..."
ssh "$REMOTE" "cd $STACK_DIR && docker compose up -d --build"

echo ">> Fertig. UI: http://192.168.0.10:8088"
