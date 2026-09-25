#!/usr/bin/env bash
# Выкат стенда на ВМ: образы собираются здесь, на ВМ едут через docker save/load (реестр не
# нужен), там поднимается compose. Запуск из Git Bash / Linux / macOS из корня репозитория:
#
#   deploy/deploy.sh                # хост testvm (из ~/.ssh/config), каталог ~/domeo/spec, порт 8090
#   DEPLOY_HOST=user@1.2.3.4 EDGE_PORT=8090 deploy/deploy.sh
#
# Стенд открыт без пароля (по решению заказчика); доступ ограничивается только security group.
set -euo pipefail

HOST="${DEPLOY_HOST:-testvm}"
DIR="${DEPLOY_DIR:-domeo/spec}"
PORT="${EDGE_PORT:-8090}"
cd "$(dirname "$0")/.."
TAG="${TAG:-$(git rev-parse --short HEAD)}"

echo "== сборка образов ($TAG)"
docker build -t "domeo-spec-core:$TAG" core
docker build -t "domeo-spec-api:$TAG" -f api/Dockerfile .

echo "== файлы стенда → $HOST:~/$DIR"
ssh "$HOST" "mkdir -p ~/$DIR"
scp -q deploy/docker-compose.yml deploy/nginx.conf "$HOST:~/$DIR/"

echo "== образы → $HOST (docker save | ssh docker load)"
docker save "domeo-spec-core:$TAG" "domeo-spec-api:$TAG" | gzip -1 | ssh "$HOST" "gunzip | docker load"

echo "== запуск"
ssh "$HOST" bash -s -- "$DIR" "$TAG" "$PORT" <<'REMOTE'
set -euo pipefail
DIR="$1"; TAG="$2"; PORT="$3"
cd ~/"$DIR"
printf 'TAG=%s\nEDGE_PORT=%s\n' "$TAG" "$PORT" > .env
docker compose up -d --remove-orphans
sleep 5
docker compose ps
# Старые образы прошлых выкатов — подчистить, чтобы диск не рос.
docker image prune -f >/dev/null
echo "проба: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/edge-health) /edge-health, $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/api/health) /api/health"
REMOTE

echo "== готово: http://$(ssh "$HOST" 'curl -s -4 ifconfig.me 2>/dev/null || hostname -I | cut -d" " -f1'):$PORT"
