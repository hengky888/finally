#!/usr/bin/env bash
# Build (if needed) and start the FinAlly container. Safe to run repeatedly.
set -euo pipefail

IMAGE=finally:latest
CONTAINER=finally
VOLUME=finally-data
PORT=8000

cd "$(dirname "$0")/.."

BUILD=false
[ "${1:-}" = "--build" ] && BUILD=true

if [ "$BUILD" = true ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build -t "$IMAGE" .
fi

if [ -n "$(docker ps -q -f name="^${CONTAINER}$")" ]; then
  echo "Already running at http://localhost:${PORT}"
  exit 0
fi

# Remove a stopped container of the same name so the run below is idempotent.
docker rm "$CONTAINER" >/dev/null 2>&1 || true

ENV_ARGS=()
if [ -f .env ]; then
  ENV_ARGS=(--env-file .env)
else
  echo "No .env found; starting with defaults (simulator prices, chat needs a key)."
fi

docker run -d \
  --name "$CONTAINER" \
  -v "${VOLUME}:/app/db" \
  -p "${PORT}:8000" \
  "${ENV_ARGS[@]}" \
  "$IMAGE" >/dev/null

echo "FinAlly is starting at http://localhost:${PORT}"
command -v open >/dev/null 2>&1 && open "http://localhost:${PORT}" || true
