#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# vaptvupt-web setup helper. Idempotent — safe to re-run.
set -e

PORT_HOST="${PORT_HOST:-8181}"

cat <<'BANNER'
══════════════════════════════════════════════
  vaptvupt-web 5.2.1 — setup & deploy
══════════════════════════════════════════════
BANNER
echo ""

# ─── Step 1: Docker DNS sanity ───
echo "[1/4] Checking Docker DNS..."
if ! docker run --rm ubuntu:24.04 sh -c "apt-get update >/dev/null 2>&1" 2>/dev/null; then
    echo "  Docker can't resolve DNS during builds. Fixing..."

    DAEMON_JSON="/etc/docker/daemon.json"
    if [ -f "$DAEMON_JSON" ]; then
        sudo cp "$DAEMON_JSON" "${DAEMON_JSON}.bak"
        if ! grep -q '"dns"' "$DAEMON_JSON"; then
            sudo python3 - <<EOF
import json, pathlib
p = pathlib.Path("$DAEMON_JSON")
cfg = json.loads(p.read_text() or "{}")
cfg.setdefault("dns", ["9.9.9.9", "1.1.1.1"])
p.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"  Updated {p}")
EOF
        fi
    else
        echo '{ "dns": ["9.9.9.9", "1.1.1.1"] }' | sudo tee "$DAEMON_JSON" >/dev/null
        echo "  Created $DAEMON_JSON"
    fi

    sudo systemctl restart docker
    sleep 3

    if docker run --rm ubuntu:24.04 sh -c "apt-get update >/dev/null 2>&1"; then
        echo "  ✓ Docker DNS fixed"
    else
        echo "  ⚠ DNS still failing — falling back to host network for build"
    fi
else
    echo "  ✓ Docker DNS works"
fi
echo ""

# ─── Step 2: Build ───
echo "[2/4] Building vaptvupt-web (this builds the bundled vaptvupt-5.2.1 from source)..."
if ! docker compose build 2>/dev/null; then
    echo "  Compose build failed — retrying with --network=host..."
    docker build --network=host -t vaptvupt-web:5.2.1 .
fi
echo ""

# ─── Step 3: Run ───
echo "[3/4] Starting container..."
docker compose up -d
echo ""

# ─── Step 4: Verify ───
echo "[4/4] Verifying..."
# Poll up to 20s for the container to come healthy.
ok=0
for i in $(seq 1 20); do
    if curl -sf "http://localhost:${PORT_HOST}/healthz" >/dev/null 2>&1; then
        ok=1
        break
    fi
    sleep 1
done

if [ "$ok" -eq 1 ]; then
    echo "  ✓ vaptvupt-web is up — /healthz returns 200"
    echo ""
    cat <<EOF
══════════════════════════════════════════════
  Open: http://localhost:${PORT_HOST}
  CLI version inside container:
EOF
    docker exec -t vaptvupt-web /usr/local/bin/vaptvupt version 2>/dev/null | head -3 | sed 's/^/    /'
    cat <<EOF
══════════════════════════════════════════════
EOF
else
    echo "  ⚠ /healthz did not respond within 20s — check logs:"
    echo "     docker compose logs --tail=50 vaptvupt"
fi
echo ""
