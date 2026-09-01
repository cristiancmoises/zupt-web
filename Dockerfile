# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Cristian Cezar Moisés
# Commercial licensing: sac@securityops.co

# Stage 1: verify and build the immutable ZUPT 5.2.8 source release.
FROM ubuntu:24.04 AS cli-builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash binutils build-essential file gawk git gzip python3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY zupt-5.2.8/ /build/zupt-5.2.8/
COPY build-zupt.sh /build/build-zupt.sh
COPY zupt-5.2.8.SHA256SUMS /build/zupt-5.2.8.SHA256SUMS
RUN chmod 0755 /build/build-zupt.sh && /build/build-zupt.sh

# Stage 2: resolve the hash-locked Python environment. Build tools and pip do
# not cross into the final image.
FROM ubuntu:24.04 AS python-builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates gcc python3-dev python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.txt && \
    /opt/venv/bin/pip uninstall --yes pip setuptools wheel

# Stage 3: minimal non-root runtime. No compiler, Python packaging tools,
# OpenSSL SDK integration, or opaque prebuilt library.
FROM ubuntu:24.04

LABEL maintainer="Cristian Cezar Moisés <sac@securityops.co>"
LABEL description="ZUPT Web — post-quantum backup utility browser frontend"
LABEL version="5.2.8"
LABEL org.opencontainers.image.title="zupt-web"
LABEL org.opencontainers.image.version="5.2.8"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"
LABEL org.opencontainers.image.source="https://git.securityops.co/cristiancmoises/zupt-web"
LABEL org.opencontainers.image.documentation="https://git.securityops.co/cristiancmoises/zupt-web/src/branch/main/README.md"
LABEL org.opencontainers.image.vendor="securityops.co"
LABEL org.opencontainers.image.commercial="sac@securityops.co"

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 tini && \
    rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /opt/venv /opt/venv
COPY --from=cli-builder /build/zupt-5.2.8/zupt /usr/local/bin/zupt
COPY --from=cli-builder /build/zupt-5.2.8/LICENSE* /usr/share/licenses/zupt/
COPY --from=cli-builder /build/zupt-5.2.8/NOTICE /build/zupt-5.2.8/THIRD-PARTY-NOTICES.md /usr/share/licenses/zupt/
COPY LICENSE /usr/share/licenses/zupt-web/LICENSE

# Keep the renamed-era command as a compatibility alias; ZUPT is canonical.
RUN chmod 0755 /usr/local/bin/zupt && \
    ln -s zupt /usr/local/bin/vaptvupt && \
    /usr/local/bin/zupt version

COPY app.py /opt/zupt/app.py
COPY templates/ /opt/zupt/templates/
COPY static/ /opt/zupt/static/

RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 1001 zupt && \
    mkdir -p /tmp/zupt-work && \
    chown zupt:zupt /tmp/zupt-work /opt/zupt && \
    chmod 0700 /tmp/zupt-work

USER zupt
WORKDIR /opt/zupt
ENV PATH="/opt/venv/bin:${PATH}" \
    ZUPT_BIN=/usr/local/bin/zupt \
    ZUPT_WORKDIR=/tmp/zupt-work \
    TMPDIR=/tmp/zupt-work \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "if [ -z \"${ZUPT_SECRET_KEY:-}\" ] && [ -z \"${VAPTVUPT_SECRET_KEY:-}\" ]; then export ZUPT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))'); fi; exec gunicorn --bind 0.0.0.0:8080 --workers 2 --worker-tmp-dir /tmp/zupt-work --timeout 660 --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile - app:app"]
