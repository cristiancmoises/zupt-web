FROM ubuntu:24.04 AS builder
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc make libc6-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY zupt-2.1.5/ .
RUN make clean && make && strip zupt

FROM ubuntu:24.04
LABEL maintainer="Cristian Cezar Moises"
LABEL description="Zupt Web — Post-Quantum Backup Utility"
LABEL version="2.1.5"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip nginx tar curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install --break-system-packages --no-cache-dir flask gunicorn

COPY --from=builder /build/zupt /usr/local/bin/zupt
RUN chmod 755 /usr/local/bin/zupt

COPY app.py /opt/zupt/app.py
COPY templates/ /opt/zupt/templates/
COPY static/ /opt/zupt/static/
COPY nginx.conf /etc/nginx/sites-enabled/default

RUN mkdir -p /tmp/zupt-work && chmod 777 /tmp/zupt-work && \
    python3 -c "import secrets; print(secrets.token_hex(32))" > /opt/zupt/.secret

RUN printf '#!/bin/bash\nexport ZUPT_SECRET_KEY=$(cat /opt/zupt/.secret)\ncd /opt/zupt\ngunicorn -b 127.0.0.1:5000 -w 2 --timeout 600 app:app &\nnginx -g "daemon off;"\n' > /opt/zupt/start.sh && chmod +x /opt/zupt/start.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:8080/version || exit 1

CMD ["/bin/bash", "/opt/zupt/start.sh"]
