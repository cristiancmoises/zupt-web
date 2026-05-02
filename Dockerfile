# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co
#
# Two-stage build:
#   1) "builder" — gcc + make, builds zupt-2.2.3 with the vendored
#      libzuptsdk (under vendor/zuptsdk/), strips, and patches the
#      RUNPATH so the runtime image can find the SDK at /usr/lib/zupt.
#   2) Runtime — minimal ubuntu:24.04 with python3 + gunicorn only.
#      No nginx (gunicorn binds 8080 directly, security headers and
#      static-file serving are handled by Flask). One process tree =
#      easier to debug, harder to break, no fs-permission gymnastics.
#      Runs as a dedicated non-root user (zuptweb, uid 1001).

# ───────────────────────────────────────────────────────────────────
# Stage 1: builder
# ───────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

# Builder needs gcc/make to compile zupt, plus libargon2-1 + libssl3t64
# at link time because the vendored libzuptsdk.so has DT_NEEDED entries
# for libargon2.so.1 and libcrypto.so.3 (Argon2id + OpenSSL primitives
# powering --pq-sdk). patchelf retargets the binary's RUNPATH.
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

# Runtime deps: python3 + tar + curl + tini, plus libargon2-1 + libssl3t64
# for libzuptsdk's runtime crypto. NO nginx — gunicorn binds 8080 directly.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip tar curl ca-certificates \
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

# ─── Dedicated non-root user (defence-in-depth) ───
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 zuptweb && \
    mkdir -p /tmp/zupt-work && \
    chown zuptweb:zuptweb /tmp/zupt-work /opt/zupt && \
    chmod 700 /tmp/zupt-work && \
    python3 -c "import secrets; print(secrets.token_hex(32))" > /opt/zupt/.secret && \
    chown zuptweb:zuptweb /opt/zupt/.secret && \
    chmod 400 /opt/zupt/.secret

# Switch to the non-root user. tini will be PID 1, gunicorn its child,
# both running as zuptweb. No su, no nginx, no shell-fork chain.
USER zuptweb
WORKDIR /opt/zupt
ENV ZUPT_BIN=/usr/local/bin/zupt \
    ZUPT_WORKDIR=/tmp/zupt-work \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -sf http://127.0.0.1:8080/healthz >/dev/null || exit 1

# tini reaps zombies and forwards signals cleanly.
ENTRYPOINT ["/usr/bin/tini", "--"]
# Gunicorn binds 8080 directly. Two workers, 600s timeout for long
# compress jobs, recycle every 1000±100 requests to bound RSS, log
# access + error to stdout/stderr (Docker captures both).
CMD ["sh", "-c", "\
    export ZUPT_SECRET_KEY=$(cat /opt/zupt/.secret) && \
    exec gunicorn \
      --bind 0.0.0.0:8080 \
      --workers 2 \
      --timeout 600 \
      --graceful-timeout 30 \
      --keep-alive 5 \
      --max-requests 1000 \
      --max-requests-jitter 100 \
      --access-logfile - \
      --error-logfile - \
      app:app"]
