#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co

set -Eeuo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
cd "$SCRIPT_DIR"

PORT_HOST=${PORT_HOST:-8181}

cat <<'BANNER'
══════════════════════════════════════════════
  zupt-web 5.2.8 — build, audit, and deploy
══════════════════════════════════════════════
BANNER

echo "[1/4] Checking Docker and Compose..."
docker info >/dev/null
docker compose config --quiet

echo "[2/4] Building the audited source-only image..."
docker compose build

echo "[3/4] Starting zupt-web..."
docker compose up -d

echo "[4/4] Waiting for health checks..."
healthy=0
for attempt in $(seq 1 60); do
    status=$(docker inspect --format '{{.State.Health.Status}}' zupt-web \
        2>/dev/null || true)
    if [[ $status == healthy ]]; then
        healthy=1
        break
    fi
    if (( attempt == 60 )); then
        break
    fi
    sleep 1
done

if (( healthy == 0 )); then
    echo "Error: zupt-web did not become healthy within 60 seconds" >&2
    docker compose logs --tail=100 zupt >&2
    exit 1
fi

docker exec zupt-web python3 -c "import json, urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)); raise SystemExit(payload != {'ok': True, 'service': 'zupt-web', 'version': '5.2.8'})"

docker exec zupt-web /usr/local/bin/zupt version
echo "Ready: http://localhost:${PORT_HOST}"
