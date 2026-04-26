#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
set -e

echo "══════════════════════════════════════════════"
echo "  Zupt Web — Setup & Deploy"
echo "══════════════════════════════════════════════"
echo ""

# ─── Step 1: Fix Docker DNS (the root cause of build failures) ───
echo "[1/4] Checking Docker DNS..."

# Test if Docker can resolve DNS during builds
if ! docker run --rm ubuntu:24.04 sh -c "apt-get update > /dev/null 2>&1" 2>/dev/null; then
    echo "  Docker DNS is broken. Fixing..."

    # Create or update daemon.json with DNS servers
    DAEMON_JSON="/etc/docker/daemon.json"
    if [ -f "$DAEMON_JSON" ]; then
        # Backup existing config
        sudo cp "$DAEMON_JSON" "${DAEMON_JSON}.bak"
        # Add DNS if not present (merge with existing config)
        if ! grep -q '"dns"' "$DAEMON_JSON"; then
            # Insert dns before the last closing brace
            sudo python3 -c "
import json
with open('$DAEMON_JSON') as f:
    cfg = json.load(f)
cfg['dns'] = ['8.8.8.8', '1.1.1.1']
with open('$DAEMON_JSON', 'w') as f:
    json.dump(cfg, f, indent=2)
print('  Updated $DAEMON_JSON')
"
        fi
    else
        echo '{ "dns": ["8.8.8.8", "1.1.1.1"] }' | sudo tee "$DAEMON_JSON" > /dev/null
        echo "  Created $DAEMON_JSON"
    fi

    sudo systemctl restart docker
    echo "  Docker restarted. Waiting 3s..."
    sleep 3

    # Verify fix
    if docker run --rm ubuntu:24.04 sh -c "apt-get update > /dev/null 2>&1"; then
        echo "  ✓ Docker DNS fixed!"
    else
        echo "  ✗ DNS still failing. Trying build with --network=host..."
        echo "  Run: docker build --network=host ."
    fi
else
    echo "  ✓ Docker DNS works"
fi

echo ""

# ─── Step 2: Build ───
echo "[2/4] Building Zupt Web..."
# Try normal build first, fall back to --network=host
if ! docker compose build 2>/dev/null; then
    echo "  Normal build failed, trying with host network..."
    docker build --network=host -t zupt-web .
fi

echo ""

# ─── Step 3: Run ───
echo "[3/4] Starting container..."
docker compose up -d

echo ""

# ─── Step 4: Verify ───
echo "[4/4] Verifying..."
sleep 2

if curl -sf http://localhost:8080/version > /dev/null 2>&1; then
    echo "  ✓ Zupt Web is running!"
    echo ""
    echo "══════════════════════════════════════════════"
    echo "  Open: http://localhost:8080"
    echo "══════════════════════════════════════════════"
else
    echo "  Container starting... check in a few seconds:"
    echo "  curl http://localhost:8080/version"
    echo ""
    echo "  Logs: docker compose logs -f"
fi

echo ""
