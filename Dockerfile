# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Two-stage build:
#   1) "builder" — gcc + make, builds zupt-2.2.3 with the vendored
#      libzuptsdk (under vendor/zuptsdk/), strips, and patches the
#      RUNPATH so the runtime image can find the SDK at /usr/lib/zupt.
#   2) Runtime — minimal ubuntu:24.04 with python3, nginx, gunicorn.
#      Runs the Python app as a dedicated non-root user (zuptweb, uid 1001).

# ───────────────────────────────────────────────────────────────────
# Stage 1: builder
# ───────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc make libc6-dev binutils patchelf \
      libargon2-1 libssl3t64 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY zupt-2.2.3/ .
COPY build-zupt.sh /build/build-zupt.sh

# All the build steps live in build-zupt.sh — much easier to edit, and
# much harder for an editor or paste tool to mangle than a long inline RUN.
RUN chmod +x /build/build-zupt.sh && /build/build-zupt.sh

# ───────────────────────────────────────────────────────────────────
# Stage 2: runtime
# ───────────────────────────────────────────────────────────────────
FROM ubuntu:24.04

LABEL maintainer="Cristian Cezar Moisés <sac@securityops.co>"
LABEL description="Zupt Web — Post-Quantum Backup Utility (browser frontend)"
LABEL version="2.2.3"
LABEL org.opencontainers.image.title="zupt-web"
LABEL org.opencontainers.image.version="2.2.3"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
LABEL org.opencontainers.image.source="https://git.securityops.co/cristiancmoises/zupt-web"
LABEL org.opencontainers.image.documentation="https://git.securityops.co/cristiancmoises/zupt-web/src/branch/main/README.md"
LABEL org.opencontainers.image.vendor="securityops.co"
LABEL org.opencontainers.image.commercial="sac@securityops.co"

# Runtime deps: python3 + nginx for the web tier; libargon2-1 + libssl3
# for the bundled libzuptsdk's hybrid-PQ crypto.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip nginx tar curl ca-certificates \
      libargon2-1 libssl3t64 tini && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install --break-system-packages --no-cache-dir \
        flask==3.0.3 gunicorn==23.0.0

# ─── Install zupt binary + bundled libzuptsdk ───
COPY --from=builder /build/zupt /usr/local/bin/zupt
COPY --from=builder /build/vendor/zuptsdk/libzuptsdk.so.2.0.0 /usr/lib/zupt/libzuptsdk.so.2.0.0
RUN chmod 755 /usr/local/bin/zupt && \
    ln -sf libzuptsdk.so.2.0.0 /usr/lib/zupt/libzuptsdk.so.2 && \
    ln -sf libzuptsdk.so.2.0.0 /usr/lib/zupt/libzuptsdk.so && \
    /usr/local/bin/zupt --version | head -3

# ─── Application code ───
COPY app.py /opt/zupt/app.py
COPY templates/ /opt/zupt/templates/
COPY static/ /opt/zupt/static/
COPY nginx.conf /etc/nginx/sites-enabled/default

# ─── Dedicated non-root user (defence-in-depth) ───
# Flask + gunicorn run as 'zuptweb' (uid 1001). Nginx still binds to
# port 8080 as root via the master process, then drops to 'www-data'
# for workers (default Ubuntu nginx behaviour).
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 zuptweb && \
    mkdir -p /tmp/zupt-work && \
    chown zuptweb:zuptweb /tmp/zupt-work /opt/zupt && \
    chmod 700 /tmp/zupt-work && \
    python3 -c "import secrets; print(secrets.token_hex(32))" > /opt/zupt/.secret && \
    chown zuptweb:zuptweb /opt/zupt/.secret && \
    chmod 600 /opt/zupt/.secret

# ─── Entrypoint ───
RUN printf '%s\n' \
    '#!/bin/bash' \
    'set -e' \
    'export ZUPT_SECRET_KEY=$(cat /opt/zupt/.secret)' \
    'export ZUPT_BIN=/usr/local/bin/zupt' \
    'export ZUPT_WORKDIR=/tmp/zupt-work' \
    'cd /opt/zupt' \
    '# Start gunicorn as zuptweb (non-root)' \
    'su -s /bin/bash -c "gunicorn -b 127.0.0.1:5000 -w 2 \' \
    '    --timeout 600 --graceful-timeout 30 --keep-alive 5 \' \
    '    --max-requests 1000 --max-requests-jitter 100 \' \
    '    --access-logfile - --error-logfile - app:app &" zuptweb' \
    '# Run nginx in foreground (master as root, workers drop to www-data)' \
    'exec nginx -g "daemon off;"' \
    > /opt/zupt/start.sh && chmod 755 /opt/zupt/start.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -sf http://localhost:8080/healthz >/dev/null || exit 1

# tini: PID 1, reaps zombies, forwards signals
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "/opt/zupt/start.sh"]
