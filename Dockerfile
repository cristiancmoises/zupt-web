# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Two-stage build:
#   1) "builder" — gcc + make, builds vaptvupt-5.2.1 WITH_SDK=1 with the
#      vendored libvuptsdk (under vendor/vuptsdk/), strips, and patches
#      the RUNPATH so the runtime image can find the SDK at
#      /usr/lib/vaptvupt.
#   2) Runtime — minimal ubuntu:24.04 with python3 + gunicorn only.
#      No nginx (gunicorn binds 8080 directly, security headers and
#      static-file serving are handled by Flask). One process tree =
#      easier to debug, harder to break, no fs-permission gymnastics.
#      Runs as a dedicated non-root user (vaptvupt, uid 1001).

# ───────────────────────────────────────────────────────────────────
# Stage 1: builder
# ───────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

# Builder needs gcc/make to compile vaptvupt. A WITH_SDK=1 build links
# -lvuptsdk -lcrypto -largon2 (Argon2id + OpenSSL primitives powering
# --pq-sdk and the Argon2id password KDF), so the linker needs the
# libssl-dev / libargon2-dev .so symlinks, not just the runtime libs.
# patchelf retargets the binary's RUNPATH.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc make libc6-dev binutils patchelf \
      libargon2-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY vaptvupt-5.2.1/ .
COPY build-vaptvupt.sh /build/build-vaptvupt.sh

# All the build steps live in build-vaptvupt.sh — much easier to edit,
# and much harder for an editor or paste tool to mangle than a long
# inline RUN.
RUN chmod +x /build/build-vaptvupt.sh && /build/build-vaptvupt.sh

# ───────────────────────────────────────────────────────────────────
# Stage 2: runtime
# ───────────────────────────────────────────────────────────────────
FROM ubuntu:24.04

LABEL maintainer="Cristian Cezar Moisés <sac@securityops.co>"
LABEL description="VaptVupt Web — Post-Quantum Backup Utility (browser frontend)"
LABEL version="5.2.1"
LABEL org.opencontainers.image.title="vaptvupt-web"
LABEL org.opencontainers.image.version="5.2.1"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
LABEL org.opencontainers.image.source="https://git.securityops.co/cristiancmoises/vaptvupt-web"
LABEL org.opencontainers.image.documentation="https://git.securityops.co/cristiancmoises/vaptvupt-web/src/branch/main/README.md"
LABEL org.opencontainers.image.vendor="securityops.co"
LABEL org.opencontainers.image.commercial="sac@securityops.co"

# Runtime deps: python3 + tar + curl + tini, plus libargon2-1 + libssl3t64
# for libvuptsdk's runtime crypto. NO nginx — gunicorn binds 8080 directly.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip tar curl ca-certificates \
      libargon2-1 libssl3t64 tini && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install --break-system-packages --no-cache-dir \
        flask==3.0.3 gunicorn==23.0.0

# ─── Install vaptvupt binary + bundled libvuptsdk ───
# A legacy `zupt` symlink is kept for one major version cycle, matching
# the upstream CLI's own install rule (v3.0.0 INPI Brasil rename).
COPY --from=builder /build/vaptvupt /usr/local/bin/vaptvupt
COPY --from=builder /build/vendor/vuptsdk/libvuptsdk.so.2.0.0 /usr/lib/vaptvupt/libvuptsdk.so.2.0.0
RUN chmod 755 /usr/local/bin/vaptvupt && \
    ln -sf vaptvupt /usr/local/bin/zupt && \
    ln -sf libvuptsdk.so.2.0.0 /usr/lib/vaptvupt/libvuptsdk.so.2 && \
    ln -sf libvuptsdk.so.2.0.0 /usr/lib/vaptvupt/libvuptsdk.so && \
    /usr/local/bin/vaptvupt version

# ─── Application code ───
COPY app.py /opt/vaptvupt/app.py
COPY templates/ /opt/vaptvupt/templates/
COPY static/ /opt/vaptvupt/static/

# ─── Dedicated non-root user (defence-in-depth) ───
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 vaptvupt && \
    mkdir -p /tmp/vaptvupt-work && \
    chown vaptvupt:vaptvupt /tmp/vaptvupt-work /opt/vaptvupt && \
    chmod 700 /tmp/vaptvupt-work && \
    python3 -c "import secrets; print(secrets.token_hex(32))" > /opt/vaptvupt/.secret && \
    chown vaptvupt:vaptvupt /opt/vaptvupt/.secret && \
    chmod 400 /opt/vaptvupt/.secret

# Switch to the non-root user. tini will be PID 1, gunicorn its child,
# both running as vaptvupt. No su, no nginx, no shell-fork chain.
USER vaptvupt
WORKDIR /opt/vaptvupt
ENV VAPTVUPT_BIN=/usr/local/bin/vaptvupt \
    VAPTVUPT_WORKDIR=/tmp/vaptvupt-work \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -sf http://127.0.0.1:8080/healthz >/dev/null || exit 1

# tini reaps zombies and forwards signals cleanly.
ENTRYPOINT ["/usr/bin/tini", "--"]
# Gunicorn binds 8080 directly. Two workers, 660s worker timeout —
# deliberately ABOVE the app's 600s CLI subprocess timeout so the
# worker survives long enough to render the timeout error page instead
# of being SIGKILLed at the same moment. Recycle every 1000±100
# requests to bound RSS, log access + error to stdout/stderr.
CMD ["sh", "-c", "\
    export VAPTVUPT_SECRET_KEY=$(cat /opt/vaptvupt/.secret) && \
    exec gunicorn \
      --bind 0.0.0.0:8080 \
      --workers 2 \
      --timeout 660 \
      --graceful-timeout 30 \
      --keep-alive 5 \
      --max-requests 1000 \
      --max-requests-jitter 100 \
      --access-logfile - \
      --error-logfile - \
      app:app"]
