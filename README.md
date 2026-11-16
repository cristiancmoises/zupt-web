# ZUPT Web 5.2.13

[English](README.md) | [Português do Brasil](README.pt-BR.md)

ZUPT Web is a self-hosted browser frontend for the ZUPT backup archiver. It
compresses, encrypts, verifies, inspects, and extracts `.zupt` archives without
accounts or cloud storage. It builds the official **ZUPT 5.2.10** source with
**VaptVupt 2.65.13**; the desktop archive format remains **v1.6**.
The Web release number, 5.2.13, is independent of the bundled CLI version, 5.2.10.

## Run

Requirements: Docker Engine and Docker Compose.

```sh
git clone https://git.securityops.co/cristiancmoises/zupt-web.git
cd zupt-web
./setup.sh
# http://localhost:8181
```

A Web `.zupt` source package extracts files with mode 0600. Verify the GPG
signature on that Web release's `SHA256SUMS` and the package checksum first;
[UPSTREAM.md](UPSTREAM.md) records the signing fingerprint and core provenance.
From the extracted project root, restore only these entry points before
running setup or the source gate:

```sh
chmod u+x setup.sh build-zupt.sh \
  zupt-5.2.10/scripts/check-source-only.sh
```

`setup.sh` validates Compose, builds and tests the bundled CLI, starts the
container, and checks its version. Use `PORT_HOST=8282 ./setup.sh` to change
the local port. To manage it directly:

```sh
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

The default bind is `127.0.0.1:8181`. Remote access requires an HTTPS reverse
proxy and access control appropriate to the audience: this service receives
passwords and private keys. When TLS terminates at the proxy, set
`ZUPT_COOKIE_SECURE=1`. Set `BIND_HOST=0.0.0.0` only when the network boundary
is already in place.

## Features

| Feature | Implementation |
|---|---|
| Hybrid encryption | ML-KEM-768 + X25519, `--pq` |
| Full post-quantum encryption | ML-KEM-768, `--pq-only` |
| Password encryption | AES-256-CTR + HMAC-SHA256; PBKDF2-SHA256 |
| Compression | AUTO, VaptVupt 2.65.13, LZHP, Store; levels 1–9 |
| Backup options | Solid mode or block deduplication, mutually exclusive |
| Inspection | Format/trailer, UUID, flags, encryption metadata, sizes, block count |
| Deployment | Three-stage Docker image, non-root runtime, read-only root filesystem |

Android uses its independent `zupt-android/v1.3` STORE/raw-DEFLATE format.
Desktop and Android archives are not interchangeable.

## Configuration

`ZUPT_*` settings take precedence over the corresponding `VAPTVUPT_*`
compatibility names used by releases 3.0.0–5.2.1.

| Variable | Default | Purpose |
|---|---:|---|
| `ZUPT_MAX_UPLOAD_MB` | `512` | Maximum request size in MiB |
| `ZUPT_KEY_TTL_SEC` | `14400` | Job/key retention in seconds |
| `ZUPT_SECRET_KEY` | generated at startup | Flask secret |
| `ZUPT_COMPRESS_TIMEOUT` | `600` | Compression timeout, 1–600 seconds |
| `ZUPT_EXTRACT_TIMEOUT` | `600` | Extraction/verification timeout, 1–600 seconds |
| `ZUPT_COOKIE_SECURE` | `0` | Use `1` for browser access exclusively through HTTPS |

The supported container fixes `ZUPT_BIN=/usr/local/bin/zupt` and
`ZUPT_WORKDIR=/tmp/zupt-work`, backed by a mode-0700 2 GiB tmpfs. It uses uid
1001, drops all capabilities, enables `no-new-privileges`, and caps memory at
4 GiB and processes at 256. The application timeout is at most 600 seconds;
Gunicorn waits 660 seconds. Custom launchers can set `ZUPT_BIN` and
`ZUPT_WORKDIR` directly.

Passwords reach the CLI through inherited standard input (`--pass-fd 0`),
not process arguments. Forms use CSRF checks. Jobs use isolated directories
and expiring key downloads. These controls reduce risk; uploads remain
untrusted input. Save required keys before stopping the container: tmpfs
contents disappear with it.

## Verify

```sh
curl -fsS http://127.0.0.1:8181/healthz
# {"ok":true,"service":"zupt-web","version":"5.2.13"}
curl -fsS http://127.0.0.1:8181/version
docker exec zupt-web zupt version
```

`/healthz` reports process liveness. `/version` reports CLI readiness and returns
503 when the binary is unavailable. `/usr/local/bin/vaptvupt` remains an alias
for older scripts.

## Upgrade compatibility

This source-only build excludes the opaque `libvuptsdk` used by ZUPT Web
5.2.1. Native password, `--pq`, and `--pq-only` modes remain available.
Argon2id password archives and `--pq-sdk` archives from 5.2.1 need that
release's compatibility reader. Keep the recovery environment and original
archives until you have restored, verified, and re-encrypted them. See
[MIGRATION.md](MIGRATION.md).

## Development and CI

```sh
./build-zupt.sh --verify-only
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
shellcheck setup.sh build-zupt.sh
docker compose config --quiet
```

The vendor verifier permits exact LF or its deterministic pure CRLF form only
for the two Windows batch paths declared by upstream. Other transformations,
mixed endings, traversal, duplicates, and symlinks fail. Historical tests use
each tag's own manifest; a source export without Git history cannot run those
two Git integration checks.

`./build-zupt.sh` verifies and builds the CLI, runs `make check`, strips it,
and rejects RPATH/RUNPATH. See [AUDIT.md](AUDIT.md) for the full gate matrix
and [UPSTREAM.md](UPSTREAM.md) for signed-source verification and all 294
manifest entries. Upstream results do not validate this web service.

CI runs on `main`, `5.2.13`, pull requests, and manual dispatch. The image job
depends on the web and bundled-CLI jobs. Only after image inventory and live
HTTP/crypto-mode tests pass does it export a Docker image artifact with
`SHA256SUMS`, the web `COMMIT`, and image metadata. The artifact is not a
production deployment. Compose accepts `VCS_REF` for the image revision label;
CI binds it to the tested commit.

## Project and license

- [ZUPT CLI/GUI](https://github.com/cristiancmoises/zupt)
- [GitHub mirror](https://github.com/cristiancmoises/zupt-web)
- [Codeberg mirror](https://codeberg.org/berkeley/zupt-web)
- [VaptVupt codec](https://git.securityops.co/cristiancmoises/vaptvupt-codec)

ZUPT Web uses [AGPL-3.0-or-later](LICENSE). The bundled source has separately
identified AGPL-3.0-or-later, GPL-3.0-or-later, BSD-2-Clause, BSD-3-Clause, and
CC0-1.0 scopes. Preserve `LICENSE*`, `NOTICE`, and
[THIRD-PARTY-NOTICES.md](zupt-5.2.10/THIRD-PARTY-NOTICES.md). Operators of a
modified network service must meet the AGPL source-availability requirements.
Commercial licensing contact: `sac@securityops.co`.
