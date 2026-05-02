# Zupt Web — Post-Quantum Backup in Your Browser

**Encrypt, compress, and protect files with quantum-resistant cryptography — from any browser.**

One-command deploy. No accounts. No cloud. Your keys, your data, your server.

```bash
docker compose up -d
# → http://localhost:8181
```

This release bundles **Zupt CLI 2.2.3** (with **VaptVupt 2.48.2** codec and **libzuptsdk 2.0.0**). See [CHANGELOG of bundled zupt](zupt-2.2.3/CHANGELOG.md) for the full list of changes.

---

## What's new in 2.2.3

- **Bundled CLI upgraded** — Zupt 2.1.7 → **Zupt 2.2.3** (VaptVupt 2.48.2 codec, libzuptsdk 2.0).
- **`--pq-sdk` exposed in the UI** — separate "SDK v2 Keypair" button, separate file upload field for SDK public/private keys in the compress/extract forms. SDK v2 = HKDF-SHA3-256 combiner + key commitment + HPKE binding + Argon2id. Recommended for new archives.
- **`--dedup` exposed in the UI** — checkbox in the compress form (block-level deduplication via XXH64 fingerprint index).
- **Upload-size mismatch fixed** — `app.py` capped uploads at 34 MB while the previous nginx layer allowed 2 GB. Now defaults to **2 GiB** and is configurable via `ZUPT_MAX_UPLOAD_MB`.
- **`/healthz` endpoint** — separate from `/version`. No CLI fork on each call, no rate limit, used by the Docker `HEALTHCHECK`.
- **Single-process container** — dropped the nginx tier. Gunicorn binds 8080 directly; Flask serves `/static/` and sets all security headers (CSP, X-Frame-Options, COOP, CORP, Permissions-Policy, X-Content-Type-Options) in `@app.after_request`. One process tree under `tini`, no `su`, no shell-fork chain — much easier to debug, far fewer failure modes.
- **Container hardening** — runs the Python app as `zuptweb` (uid 1001) via `USER zuptweb` in the Dockerfile. `no-new-privileges`, `tini` as PID 1. Workdir is a tmpfs mount (uid-mapped to 1001).
- **Performance tuning** — gunicorn `--max-requests 1000 --max-requests-jitter 100` (recycles workers periodically to bound RSS), `--keep-alive 5`, `--graceful-timeout 30`.
- **Password scrubbing** — passwords are stripped out of error messages before being rendered, so a stray CLI error that quotes back the password can't leak it.
- **Repo move reflected** — github.com/cristiancmoises/* → git.securityops.co/cristiancmoises/*.

---

## Features

| Feature | Description |
|---|---|
| **SDK v2 key generation** | HKDF + key commitment + HPKE binding + Argon2id. `--pq-sdk` workflow |
| **Legacy key generation** | ML-KEM-768 + X25519 hybrid. `--pq` workflow (compatible with Zupt 2.0–2.1 archives) |
| **Compress & encrypt** | Upload files → `.zupt` archive. Password, `--pq`, or `--pq-sdk` (mutually exclusive) |
| **Extract & decrypt** | Upload `.zupt` + key/password → original files returned |
| **Verify integrity** | Validate every block's XXH64 + HMAC-SHA256 without extracting |
| **Codec selection** | AUTO (hardware-adaptive) · VaptVupt 2.48.2 (AVX2/NEON) · LZHP (universal) · Store |
| **Block dedup** | XXH64 fingerprint index, eliminates duplicate blocks before compression |
| **Solid mode** | Cross-file dictionary sharing for higher ratios on similar files |
| **Levels 1–9** | Fastest to maximum compression ratio |

## Security posture

- **Runs as non-root** in the container (`zuptweb`, uid 1001) via `USER zuptweb` in the Dockerfile. There is no `root`-owned process at runtime.
- **`no-new-privileges`** enabled in `docker-compose.yml` — no path to capability-based or setuid escalation.
- **CSRF tokens** on every form (double-submit cookie, `hmac.compare_digest` constant-time check).
- **Rate limiting** — 10 keygen/min, 30 compress·extract·test/min per IP.
- **Tight Content-Security-Policy** set by Flask in `@app.after_request`: `default-src 'none'; script-src 'self' 'unsafe-inline'; …; frame-ancestors 'none'` (the `unsafe-inline` is required because templates are deliberately single-file with inline `<style>` and minimal `<script>`; no separate `.js`/`.css` files are served).
- **Full security header set** applied by Flask: CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy, Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy, Permissions-Policy (camera/mic/geo/payment/USB/interest-cohort revoked).
- **No `shell=True`** — every subprocess call uses explicit argv.
- **Path traversal protection** — filenames sanitised, paths verified with `Path.resolve().relative_to(WORKDIR)`.
- **Password scrubbing** — passwords are stripped from error output before being rendered to the browser.
- **Keys auto-expire** from the server after 4 h (`ZUPT_KEY_TTL_SEC` env override).
- **Workdir is a tmpfs** (`/tmp/zupt-work`, uid-mapped to 1001) — compress jobs never touch the container's writable layer.
- **Container resource limits** — `memory: 4G` in `docker-compose.yml` (defence against runaway compress jobs). CPU is uncapped by default; uncomment the `cpus:` line if your host is shared.
- **HEALTHCHECK** uses dedicated `/healthz` endpoint — no CLI fork on each probe, no rate-limit consumption, no auth roundtrip.

## Screenshots

<p align="center">
  <img src="screenshots/1.png" width="660" alt="Screenshot 1"><br><br>
  <img src="screenshots/2.png" width="660" alt="Screenshot 2"><br><br>
  <img src="screenshots/3.png" width="660" alt="Screenshot 3"><br><br>
  <img src="screenshots/about.png" width="660" alt="About"><br><br>
  <img src="screenshots/test.png" width="660" alt="Test">
</p>

## Comparison

| | **Zupt Web** | age + gzip | GPG + tar | Duplicati | BorgBackup |
|---|---|---|---|---|---|
| Post-quantum encryption | ML-KEM-768 + X25519 | — | — | — | — |
| SDK v2 (key commitment + HPKE binding) | ✓ via `--pq-sdk` | — | — | — | — |
| Block-level dedup | XXH64 fingerprint index | — | — | — | HMAC |
| Web interface | Self-hosted Docker | CLI | CLI | Web | CLI |
| Zero deps in codec | Pure C11 (zupt + VaptVupt) | Go | GnuPG | .NET | Python |
| Hardware-adaptive codec | AVX2/NEON auto | — | — | — | — |
| Per-block integrity | XXH64 + HMAC-SHA256 per block | — | Whole-file | — | HMAC |
| Docker one-command | `docker compose up -d` | — | — | Yes | — |

## Cryptographic stack

| Algorithm | Standard | Purpose |
|---|---|---|
| ML-KEM-768 | FIPS 203 | Post-quantum key encapsulation |
| X25519 | RFC 7748 | Elliptic curve Diffie–Hellman |
| AES-256-CTR | FIPS 197 | Symmetric encryption (legacy `--pq`, `-p`) |
| XChaCha20-Poly1305 | RFC 8439 / draft-irtf-cfrg-xchacha | SDK v2 AEAD (`--pq-sdk` default) |
| AES-256-SIV | RFC 5297 | SDK v2 nonce-misuse-resistant alternative |
| HMAC-SHA256 | RFC 2104 | Per-block authentication (legacy mode) |
| HKDF-SHA3-256 | RFC 5869 / FIPS 202 | SDK v2 hybrid combiner |
| PBKDF2-SHA256 | RFC 8018 | Password key derivation (600 K iter) |
| Argon2id | RFC 9106 | SDK v2 password key derivation |
| SHA3 / SHAKE | FIPS 202 | Hybrid key derivation, Keccak |

## Deploy

### Prerequisites

- Docker and Docker Compose

### Quick start

```bash
git clone https://git.securityops.co/cristiancmoises/zupt-web && cd zupt-web
docker compose up -d
```

Open **http://localhost:8181**.

### Tuning

```bash
# Cap upload size. Default: 2 GiB.
# Edit app.py — value in MEGABYTES:
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024   # 50 MB

# Or override at runtime via env (no rebuild needed):
docker run -e ZUPT_MAX_UPLOAD_MB=50 -p 8181:8080 zupt-web:2.2.3
```

```bash
# Tighten/relax key TTL on the server (defaults to 4 hours):
docker run -e ZUPT_KEY_TTL_SEC=900 -p 8181:8080 zupt-web:2.2.3
```

### Docker DNS fix

If the build fails with `Temporary failure resolving 'archive.ubuntu.com'`:

```bash
echo '{"dns":["9.9.9.9","1.1.1.1"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

Or run `./setup.sh` — it detects this case automatically.

### Verify

```bash
curl localhost:8181/healthz   # {"ok": true, "service": "zupt-web", "version": "2.2.3"}
curl localhost:8181/version   # {"version": "zupt 2.2.3 ...", "ok": true}
docker exec -t zupt-web zupt --version
```

## Architecture

```
┌────────────────────────────────────────────────────┐
│  Browser  ──HTTP──▶  gunicorn  (port 8080, 2 wk) ──┐
│                                                    │
│                                              Flask app
│                                              (sets all
│                                               security
│                                               headers,
│                                               serves
│                                               /static/)
│                                                    │
│                                                    ▼
│                                  /usr/local/bin/zupt
│                                              │     │
│                                              ▼     │
│                                  /usr/lib/zupt/    │
│                                  libzuptsdk.so.2   │
└────────────────────────────────────────────────────┘
```

- **gunicorn** binds 8080 directly as `zuptweb` (uid 1001), 2 workers, 600 s timeout for long compress jobs, recycles workers every 1000 ± 100 requests. PID 1 is `tini` for proper signal forwarding and zombie reaping.
- **Flask app** (`app.py`) serves the UI, accepts uploads, sets all security headers in `@app.after_request`, serves static files from `static/`, and calls the `zupt` CLI via explicit argv (no shell). Streams the result back to the browser.
- **zupt CLI** (built from the bundled `zupt-2.2.3/` source tree) does the actual compress/encrypt/extract work. Links to **libzuptsdk** via `RUNPATH=/usr/lib/zupt`.

## Project family

All maintained by Cristian Cezar Moisés on git.securityops.co:

- [zupt](https://git.securityops.co/cristiancmoises/zupt) — CLI (this repo bundles a copy of its source)
- [zupt-android](https://git.securityops.co/cristiancmoises/zupt-android) — Android port
- [zupt-web](https://git.securityops.co/cristiancmoises/zupt-web) — this repo
- [libzuptsdk](https://git.securityops.co/cristiancmoises/libzuptsdk) — C SDK powering `--pq-sdk`
- [vaptvupt](https://git.securityops.co/cristiancmoises/vaptvupt) — standalone LZ + tANS codec, embedded in zupt

## License

**Zupt-Web is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later).**

The full license text is in [LICENSE](LICENSE), preceded by a formal preamble explaining the rationale.

- **You can run Zupt-Web freely** — for personal use, internal company use, homelab self-hosting, research, or as a tool in your sysadmin workflow. The AGPL imposes essentially no obligations on simple use.
- **If you operate a modified Zupt-Web as a hosted/SaaS service** (a backup-management portal, a cloud archive viewer, a backup-as-a-service frontend, etc.), you MUST make the source code of your modifications available to the users of that service. This is the AGPL's "SaaS clause" and is the entire reason Zupt-Web is AGPL rather than GPL or MIT — Zupt-Web is by design a network-facing application, the exact deployment shape the AGPL exists to address.
- **If you redistribute Zupt-Web** (modified or not), the AGPL travels with it.

The bundled `zupt-2.2.3/` subdirectory contains the Zupt CLI source tree, also licensed under AGPL-3.0-or-later. The integrated VaptVupt 2.48.2 compression codec inside the bundled zupt is licensed under GPL-3.0-or-later (kept in sync with [git.securityops.co/cristiancmoises/vaptvupt](https://git.securityops.co/cristiancmoises/vaptvupt)). The vendored `libzuptsdk.so.2.0.0` shared object is also AGPL-3.0-or-later. GPL-3.0-or-later is two-way compatible with AGPL-3.0-or-later via section 13 of both licenses.

### Commercial licensing

If your intended use is incompatible with the AGPL — for example:

- Operating Zupt-Web as a hosted backup-as-a-service product without releasing your modifications
- Embedding Zupt-Web into a closed-source commercial portal or appliance
- Redistributing Zupt-Web as part of a proprietary product
- Requiring warranty, indemnification, or written terms

**A commercial license is available.** Contact: **sac@securityops.co**
