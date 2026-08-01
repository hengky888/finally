#!/usr/bin/env bash
# Stop and remove the FinAlly container. The data volume is left intact.
set -euo pipefail

CONTAINER=finally

if [ -z "$(docker ps -aq -f name="^${CONTAINER}$")" ]; then
  echo "Not running."
  exit 0
fi

docker stop "$CONTAINER" >/dev/null 2>&1 || true
docker rm "$CONTAINER" >/dev/null 2>&1 || true

echo "Stopped. Data volume 'finally-data' kept."
