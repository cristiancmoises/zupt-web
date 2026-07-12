# VaptVupt Web — Post-Quantum Backup in Your Browser

**Encrypt, compress, and protect files with quantum-resistant cryptography — from any browser.**

One-command deploy. No accounts. No cloud. Your keys, your data, your server.

```bash
docker compose up -d
# → http://localhost:8181
```

This release bundles **VaptVupt CLI 5.2.1** (with **VaptVupt 2.65.3** codec and **libvuptsdk 2.0.0**). See [CHANGELOG of bundled vaptvupt](vaptvupt-5.2.1/CHANGELOG.md) for the full list of changes.

> **Renamed from "Zupt-Web"** together with the CLI's v3.0.0 rename, because of
> a prior INPI Brasil trademark registration on the name "Zupt" for unrelated
> software. The `.zupt` archive extension and container format (v1.6) are
> **unchanged**. One documented exception to cross-version compatibility:
> CLI v5.0.0 switched `--pq`/`--pq-only` to genuine FIPS 203 ML-KEM-768
> (a breaking change), so **hybrid/full-PQ encrypted archives and keys made
> by ≤ 4.2.1 — including all Zupt 2.x — cannot be decrypted by this release**
> (and vice versa). Password-mode, `--pq-sdk`, and unencrypted archives are
> unaffected. The `zupt` command remains available inside the container as a
> symlink to `vaptvupt`, and the legacy `ZUPT_*` environment variables are
> still honored.

---

## What's new in 5.2.1

- **Bundled CLI upgraded** — Zupt 2.2.3 → **VaptVupt 5.2.1**: genuine FIPS 203
  ML-KEM-768 (5.0.0), full post-quantum mode (4.2.0), source-only native build
  with vendored SDK (4.1.0), codec 2.48.2 → **2.65.3** with large ratio gains
  (5.1.0: level-9 text 3.77× → 5.98×, JSON 8.25× → 9.38×) and ~1.6–2× faster
  extreme-mode encode (5.2.0).
- **Full post-quantum mode in the UI** — new "Full-PQ Keypair" button and
  `--pq-only` public/private key fields in the compress/extract forms.
  ML-KEM-768 only, no classical X25519 layer.
- **Archive header inspection** — new **Inspect** card on the Verify tab
  (`vaptvupt info`): reports codec, encryption mode (password / hybrid PQ /
  full PQ / SDK v2), and block count without any credential. The same header
  detection the 5.2.1 GUI uses to auto-pick the right decrypt mode.
- **Argon2id password KDF** — the container builds the CLI `WITH_SDK=1`, so
  password-mode archives use Argon2id (RFC 9106) instead of PBKDF2.
- **Renamed environment variables** — `VAPTVUPT_MAX_UPLOAD_MB`,
  `VAPTVUPT_KEY_TTL_SEC`, `VAPTVUPT_BIN`, `VAPTVUPT_WORKDIR`,
  `VAPTVUPT_SECRET_KEY`, `VAPTVUPT_COMPRESS_TIMEOUT`,
  `VAPTVUPT_EXTRACT_TIMEOUT`. The legacy `ZUPT_*` names still work as
  fallbacks.
- **Repo renamed** — git.securityops.co/cristiancmoises/zupt-web →
  [vaptvupt-web](https://git.securityops.co/cristiancmoises/vaptvupt-web)
  (mirrors on [GitHub](https://github.com/cristiancmoises/vaptvupt-web) and
  [Codeberg](https://codeberg.org/berkeley/vaptvupt-web)).

---

## Features

| Feature | Description |
|---|---|
| **SDK v2 key generation** | HKDF + key commitment + HPKE binding + Argon2id. `--pq-sdk` workflow |
| **Hybrid key generation** | ML-KEM-768 + X25519. `--pq` workflow (FIPS 203 since v5.0.0 — keys/archives from ≤ 4.2.1 are incompatible) |
| **Full-PQ key generation** | ML-KEM-768 only, no classical layer. `--pq-only` workflow |
| **Compress & encrypt** | Upload files → `.zupt` archive. Password, `--pq`, `--pq-only`, or `--pq-sdk` (mutually exclusive) |
| **Extract & decrypt** | Upload `.zupt` + key/password → original files returned |
| **Verify integrity** | Validate every block's XXH64 + HMAC-SHA256 without extracting |
| **Inspect header** | Codec, encryption mode, block count — no credential required |
| **Codec selection** | AUTO (hardware-adaptive) · VaptVupt 2.65.3 (AVX2/NEON) · LZHP (universal) · Store |
| **Block dedup** | XXH64 fingerprint index, eliminates duplicate blocks before compression |
| **Solid mode** | Cross-file dictionary sharing for higher ratios on similar files |
| **Levels 1–9** | Fastest to maximum compression ratio |

## Security posture

- **Runs as non-root** in the container (`vaptvupt`, uid 1001) via `USER vaptvupt` in the Dockerfile. There is no `root`-owned process at runtime.
- **`no-new-privileges`** enabled in `docker-compose.yml` — no path to capability-based or setuid escalation.
- **CSRF tokens** on every form (double-submit cookie, `hmac.compare_digest` constant-time check).
- **Rate limiting** — 10 keygen/min, 30 compress·extract·test·info/min per IP.
- **Tight Content-Security-Policy** set by Flask in `@app.after_request`: `default-src 'none'; script-src 'self' 'unsafe-inline'; …; frame-ancestors 'none'` (the `unsafe-inline` is required because templates are deliberately single-file with inline `<style>` and minimal `<script>`; no separate `.js`/`.css` files are served).
- **Full security header set** applied by Flask: CSP, X-Frame-Options DENY, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy, Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy, Permissions-Policy (camera/mic/geo/payment/USB/interest-cohort revoked).
- **No `shell=True`** — every subprocess call uses explicit argv.
- **Path traversal protection** — filenames sanitised, paths verified with `Path.resolve().relative_to(WORKDIR)`.
- **Password scrubbing** — passwords are stripped from error output before being rendered to the browser.
- **Keys auto-expire** from the server after 4 h (`VAPTVUPT_KEY_TTL_SEC` env override).
- **Workdir is a tmpfs** (`/tmp/vaptvupt-work`, uid-mapped to 1001) — compress jobs never touch the container's writable layer.
- **Container resource limits** — `memory: 4G` in `docker-compose.yml` (defence against runaway compress jobs). CPU is uncapped by default; uncomment the `cpus:` line if your host is shared.
- **HEALTHCHECK** uses dedicated `/healthz` endpoint — no CLI fork on each probe, no rate-limit consumption, no auth roundtrip.
- **Audited bundled CLI** — VaptVupt 5.2.1 ships with `make check` 16/16, NIST/RFC KAT 16/16, ML-KEM-768 FIPS 203 conformance 3/3, plus the full security regression matrix (path traversal, block swap, dedup nonce, arg order, decode slack). See [AUDIT.md](vaptvupt-5.2.1/AUDIT.md).

## Screenshots

<p align="center">
  <img src="screenshots/1.png" width="660" alt="Screenshot 1"><br><br>
  <img src="screenshots/2.png" width="660" alt="Screenshot 2"><br><br>
  <img src="screenshots/3.png" width="660" alt="Screenshot 3"><br><br>
  <img src="screenshots/about.png" width="660" alt="About"><br><br>
  <img src="screenshots/test.png" width="660" alt="Test">
</p>

## Comparison

| | **VaptVupt Web** | age + gzip | GPG + tar | Duplicati | BorgBackup |
|---|---|---|---|---|---|
| Post-quantum encryption | ML-KEM-768 hybrid **and** full PQ | — | — | — | — |
| SDK v2 (key commitment + HPKE binding) | ✓ via `--pq-sdk` | — | — | — | — |
| Block-level dedup | XXH64 fingerprint index | — | — | — | HMAC |
| Web interface | Self-hosted Docker | CLI | CLI | Web | CLI |
| Zero deps in codec | Pure C11 (vaptvupt + VV codec) | Go | GnuPG | .NET | Python |
| Hardware-adaptive codec | AVX2/NEON auto | — | — | — | — |
| Per-block integrity | XXH64 + HMAC-SHA256 per block | — | Whole-file | — | HMAC |
| Docker one-command | `docker compose up -d` | — | — | Yes | — |

## Cryptographic stack

| Algorithm | Standard | Purpose |
|---|---|---|
| ML-KEM-768 | FIPS 203 | Post-quantum key encapsulation (`--pq` hybrid, `--pq-only` pure) |
| X25519 | RFC 7748 | Elliptic curve Diffie–Hellman (hybrid layer) |
| AES-256-CTR | FIPS 197 / NIST SP 800-38A | Symmetric encryption (`--pq`, `-p`) |
| XChaCha20-Poly1305 | RFC 8439 / draft-irtf-cfrg-xchacha | SDK v2 AEAD (`--pq-sdk` default) |
| AES-256-SIV | RFC 5297 | SDK v2 nonce-misuse-resistant alternative |
| HMAC-SHA256 | RFC 2104 | Per-block authentication |
| HKDF-SHA3-256 | RFC 5869 / FIPS 202 | SDK v2 hybrid combiner |
| Argon2id | RFC 9106 | Password key derivation (WITH_SDK build — this container) |
| PBKDF2-SHA256 | RFC 8018 | Password key derivation (source-only builds, 600 K iter) |
| SHA3 / SHAKE | FIPS 202 | Hybrid key derivation, Keccak |

## Deploy

### Prerequisites

- Docker and Docker Compose

### Quick start

```bash
git clone https://git.securityops.co/cristiancmoises/vaptvupt-web && cd vaptvupt-web
docker compose up -d
```

Open **http://localhost:8181**.

Or grab the packaged release tarball (`vaptvupt-web-5.2.1.tar.gz` from the
[release page](https://git.securityops.co/cristiancmoises/vaptvupt-web/releases)),
verify it against `SHA256SUMS`, unpack, and run `./setup.sh` — it checks
Docker DNS, builds, starts, and verifies the stack in one go.

### Tuning

```bash
# Cap upload size. Default: 2 GiB.
# Edit app.py — value in MEGABYTES:
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024   # 50 MB

# Or override at runtime via env (no rebuild needed):
docker run -e VAPTVUPT_MAX_UPLOAD_MB=50 -p 8181:8080 vaptvupt-web:5.2.1
```

```bash
# Tighten/relax key TTL on the server (defaults to 4 hours):
docker run -e VAPTVUPT_KEY_TTL_SEC=900 -p 8181:8080 vaptvupt-web:5.2.1
```

(The legacy `ZUPT_*` env names still work.)

### Docker DNS fix

If the build fails with `Temporary failure resolving 'archive.ubuntu.com'`:

```bash
echo '{"dns":["9.9.9.9","1.1.1.1"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

Or run `./setup.sh` — it detects this case automatically.

### Verify

```bash
curl localhost:8181/healthz   # {"ok": true, "service": "vaptvupt-web", "version": "5.2.1"}
curl localhost:8181/version   # {"version": "vaptvupt 5.2.1 ...", "ok": true}
docker exec -t vaptvupt-web vaptvupt version
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
│                              /usr/local/bin/vaptvupt
│                                              │     │
│                                              ▼     │
│                              /usr/lib/vaptvupt/    │
│                              libvuptsdk.so.2       │
└────────────────────────────────────────────────────┘
```

- **gunicorn** binds 8080 directly as `vaptvupt` (uid 1001), 2 workers, 660 s worker timeout (deliberately above the app's 600 s CLI timeout so timeout errors render as pages), recycles workers every 1000 ± 100 requests. PID 1 is `tini` for proper signal forwarding and zombie reaping.
- **Flask app** (`app.py`) serves the UI, accepts uploads, sets all security headers in `@app.after_request`, serves static files from `static/`, and calls the `vaptvupt` CLI via explicit argv (no shell). Streams the result back to the browser.
- **vaptvupt CLI** (built from the bundled `vaptvupt-5.2.1/` source tree, `WITH_SDK=1`) does the actual compress/encrypt/extract work. Links to **libvuptsdk** via `RUNPATH=/usr/lib/vaptvupt`. A legacy `zupt` symlink is kept for one major version cycle.

## Project family

All maintained by Cristian Cezar Moisés on git.securityops.co:

- [vaptvupt](https://git.securityops.co/cristiancmoises/vaptvupt) — CLI + GUI (this repo bundles a copy of its source)
- [vaptvupt-web](https://git.securityops.co/cristiancmoises/vaptvupt-web) — this repo
- [vaptvupt-codec](https://git.securityops.co/cristiancmoises/vaptvupt-codec) — standalone LZ + tANS codec, embedded in vaptvupt
- [libvuptsdk](https://git.securityops.co/cristiancmoises/libvuptsdk) — C SDK powering `--pq-sdk` + Argon2id password KDF

Mirrors: [GitHub](https://github.com/cristiancmoises/vaptvupt-web) · [Codeberg](https://codeberg.org/berkeley/vaptvupt-web)

## License

**VaptVupt-Web is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later).**

The full license text is in [LICENSE](LICENSE), preceded by a formal preamble explaining the rationale.

- **You can run VaptVupt-Web freely** — for personal use, internal company use, homelab self-hosting, research, or as a tool in your sysadmin workflow. The AGPL imposes essentially no obligations on simple use.
- **If you operate a modified VaptVupt-Web as a hosted/SaaS service** (a backup-management portal, a cloud archive viewer, a backup-as-a-service frontend, etc.), you MUST make the source code of your modifications available to the users of that service. This is the AGPL's "SaaS clause" and is the entire reason VaptVupt-Web is AGPL rather than GPL or MIT — VaptVupt-Web is by design a network-facing application, the exact deployment shape the AGPL exists to address.
- **If you redistribute VaptVupt-Web** (modified or not), the AGPL travels with it.

The bundled `vaptvupt-5.2.1/` subdirectory contains the VaptVupt CLI source tree, also licensed under AGPL-3.0-or-later. The integrated VaptVupt 2.65.3 compression codec inside the bundled CLI is licensed under GPL-3.0-or-later (kept in sync with [git.securityops.co/cristiancmoises/vaptvupt-codec](https://git.securityops.co/cristiancmoises/vaptvupt-codec)). The vendored `libvuptsdk.so.2.0.0` shared object is also AGPL-3.0-or-later. GPL-3.0-or-later is two-way compatible with AGPL-3.0-or-later via section 13 of both licenses.

### Commercial licensing

If your intended use is incompatible with the AGPL — for example:

- Operating VaptVupt-Web as a hosted backup-as-a-service product without releasing your modifications
- Embedding VaptVupt-Web into a closed-source commercial portal or appliance
- Redistributing VaptVupt-Web as part of a proprietary product
- Requiring warranty, indemnification, or written terms

**A commercial license is available.** Contact: **sac@securityops.co**
